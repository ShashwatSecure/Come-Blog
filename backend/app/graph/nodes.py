import hashlib
import time
from concurrent.futures import ThreadPoolExecutor

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app import quality, research, store
from app.config import settings
from app.domain import (
    LENGTH_PRESETS,
    Article,
    ArticlePlan,
    AttemptRecord,
    Section,
    SectionDraft,
    SectionPlan,
)
from app.graph.llm import get_llm
from app.graph.state import BlogState, LLMReview
from app.logging_config import log_event
from app.textutil import clamp_text, clean_llm_markdown, clean_takeaways, make_slug, normalize_tag


class Wrapup(BaseModel):
    takeaways: list[str] = Field(min_length=3, max_length=5)
    closing: str


def _emit(config: dict | None, stage: str, message: str) -> None:
    sink = (config or {}).get("configurable", {}).get("event_sink")
    if sink:
        sink({"stage": stage, "message": message})


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p if isinstance(p, str) else str(p) for p in content)
    return str(content)


def _hue(topic: str) -> int:
    return int(hashlib.sha256(topic.lower().encode()).hexdigest()[:6], 16) % 360


# --------------------------------------------------------------------------- research


def research_node(state: BlogState, config: dict | None = None) -> dict:
    _emit(config, "research", "Researching the topic across Wikipedia, Commons and web search...")
    bundle = research.research(state.topic)
    _emit(config, "research", f"Found {len(bundle.sources)} sources and {len(bundle.images)} candidate images.")
    return {"research": bundle}


# --------------------------------------------------------------------------- plan


def _fallback_plan(state: BlogState) -> ArticlePlan:
    count, _ = LENGTH_PRESETS[state.length]
    headings = ["What it is", "Why it matters", "How it works", "Common mistakes", "Practical steps", "What to do next"]
    return ArticlePlan(
        title=state.topic.strip().rstrip("?.").title(),
        excerpt=f"A practical guide to {state.topic.strip().rstrip('?.').lower()}.",
        tags=[normalize_tag(w) for w in state.topic.split()[:3] if len(w) > 3],
        sections=[SectionPlan(heading=h, brief=f"{h}: {state.topic}") for h in headings[:count]],
    )


def plan_node(state: BlogState, config: dict | None = None) -> dict:
    _emit(config, "plan", "Planning the article structure...")
    count, _ = LENGTH_PRESETS[state.length]
    context = state.research.as_prompt(280) if state.research else ""
    try:
        plan = get_llm(reasoning=False).with_structured_output(ArticlePlan).invoke([
            SystemMessage(content=(
                "You are an experienced editor planning a magazine-quality blog post. "
                f"Return a catchy specific title (max 70 chars), a one-line subtitle, an excerpt of 80-180 characters, "
                f"3-4 lowercase tags, and exactly {count} sections. Each section has a short distinct heading "
                "(2-6 words, no numbering), a one-sentence brief, and 2-3 concrete key points. "
                "Every section must directly help the reader with the stated topic; never add a section about a related but different subject."
            )),
            HumanMessage(content=(
                f"Topic: {state.topic}\nAudience: {state.audience}\nTone: {state.tone}\n\n"
                + (f"Research notes:\n{context}" if context else "No research available; rely on general knowledge.")
            )),
        ])
        plan = ArticlePlan.model_validate(plan)
        if len(plan.sections) < 2:
            raise ValueError("too few sections")
        plan = plan.model_copy(update={"sections": plan.sections[: count + 1]})
    except Exception as exc:  # noqa: BLE001 - weak local models sometimes break the schema
        log_event(30, "plan_fallback", error=type(exc).__name__)
        plan = _fallback_plan(state)
    excerpt = plan.excerpt.strip()
    if len(excerpt) < 40:  # small models sometimes leave this empty; never publish a blank meta description
        seed = state.research.summary if state.research and state.research.summary else plan.subtitle
        excerpt = seed.strip() or f"A practical guide to {state.topic.strip().rstrip('?.').lower()}."
    plan = plan.model_copy(update={
        "title": clamp_text(plan.title, 90),
        "excerpt": clamp_text(excerpt, 200),
        "tags": [t for t in dict.fromkeys(normalize_tag(t) for t in plan.tags) if t][:4],
    })
    log_event(20, "plan_ready", sections=len(plan.sections))
    return {"plan": plan}


# --------------------------------------------------------------------------- write sections


def _write_section(state: BlogState, index: int, previous: SectionDraft | None, feedback: str) -> SectionDraft:
    plan = state.plan
    assert plan is not None
    section = plan.sections[index]
    _, (low, high) = LENGTH_PRESETS[state.length]
    sources = state.research.sources if state.research else []
    context = state.research.as_prompt(520) if state.research else ""
    cite_rule = (
        f"Support claims with the numbered research sources by adding markers like [1] or [2] right after the "
        f"claim. Use only ids 1 to {len(sources)}. Never invent facts, numbers, quotes or names that are not in the research."
        if sources
        else "Be precise and avoid unverifiable statistics."
    )
    system = (
        f"You write one section of a blog post in a {state.tone} tone for {state.audience}. "
        f"Write {low}-{high} words of Markdown prose (paragraphs; a short bullet list is allowed). "
        "Do not write the heading, do not add a preamble such as 'Here is', and do not conclude the whole article. "
        f"{cite_rule}"
    )
    if previous and feedback:
        system += f"\nRevise the previous version. Reviewer feedback: {feedback}"
    other = [s.heading for i, s in enumerate(plan.sections) if i != index]
    user = (
        f"Article title: {plan.title}\nThis section: {section.heading}\nPurpose: {section.brief}\n"
        f"Cover: {'; '.join(section.key_points) or section.brief}\n"
        f"Other sections (avoid repeating them): {', '.join(other)}\n\n"
        + (f"Research:\n{context}\n\n" if context else "")
        + (f"Previous version:\n{previous.body_md}" if previous else "")
    )
    response = get_llm().invoke([SystemMessage(content=system), HumanMessage(content=user)])
    body = clean_llm_markdown(_text(response.content))
    return SectionDraft(heading=section.heading, body_md=body, attempt=(previous.attempt + 1) if previous else 1)


def write_sections_node(state: BlogState, config: dict | None = None) -> dict:
    assert state.plan is not None
    targets = [i for i, s in enumerate(state.plan.sections) if not state.rewrite or s.heading in state.rewrite]
    if not targets:
        targets = list(range(len(state.plan.sections)))
    verb = "Rewriting" if state.rewrite else "Writing"
    _emit(config, "write", f"{verb} {len(targets)} section(s) (attempt {state.attempt})...")
    feedback = state.quality.llm_feedback if state.quality else ""
    drafts = dict(state.drafts)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            i: pool.submit(_write_section, state, i, drafts.get(state.plan.sections[i].heading), feedback)
            for i in targets
        }
        for future in futures.values():
            draft = future.result()
            drafts[draft.heading] = draft
            _emit(config, "write", f"Finished section: {draft.heading}")
    return {"drafts": drafts}


# --------------------------------------------------------------------------- assemble + gate


def _wrapup(state: BlogState) -> tuple[list[str], str]:
    assert state.plan is not None
    body = "\n\n".join(f"{h}: {clamp_text(d.body_md, 380)}" for h, d in state.drafts.items())
    try:
        result = get_llm(reasoning=False).with_structured_output(Wrapup).invoke([
            SystemMessage(content=(
                "From the article below, write 3-5 short key takeaways (each under 22 words, no numbering, no citations) "
                f"and a closing paragraph of 40-70 words in a {state.tone} tone with a clear next step for the reader."
            )),
            HumanMessage(content=f"Title: {state.plan.title}\n\n{body}"),
        ])
        result = Wrapup.model_validate(result)
        takeaways = [clamp_text(t, 160) for t in clean_takeaways(result.takeaways)]
        if len(takeaways) < 3:
            raise ValueError("takeaways unusable after cleaning")
        return takeaways, clean_llm_markdown(result.closing)
    except Exception as exc:  # noqa: BLE001
        log_event(30, "wrapup_fallback", error=type(exc).__name__)
        points = [p for s in state.plan.sections for p in s.key_points][:4] or [s.heading for s in state.plan.sections][:4]
        return [clamp_text(p, 160) for p in points], f"That is the essence of {state.topic.rstrip('?.').lower()}. Pick one idea above and try it today."


def assemble_node(state: BlogState, config: dict | None = None) -> dict:
    assert state.plan is not None and state.research is not None
    _emit(config, "assemble", "Assembling the article and running quality gates...")
    takeaways, closing = (state.takeaways, state.closing) if state.takeaways and state.rewrite == [] else _wrapup(state)
    if state.rewrite:
        takeaways, closing = _wrapup(state)
    sections = [
        Section(id=make_slug(s.heading, 40), heading=s.heading, body_md=state.drafts[s.heading].body_md)
        for s in state.plan.sections if s.heading in state.drafts
    ]
    article = Article(
        slug=make_slug(state.plan.title),
        topic=state.topic, title=state.plan.title, subtitle=state.plan.subtitle, excerpt=state.plan.excerpt,
        tags=state.plan.tags, sections=sections, takeaways=takeaways, closing=closing,
        sources=state.research.sources, images=state.research.images,
        audience=state.audience, tone=state.tone, length=state.length,
        model=f"{settings.ollama_model} + {settings.evaluator_model}" if settings.llm_review else settings.ollama_model,
        hue=_hue(state.topic),
    )
    report = quality.evaluate(article, state.plan.sections, state.length)
    log_event(20, "quality_checked", passed=report.passed, checks=f"{report.checks_passed}/{report.checks_total}")
    return {"article": article, "quality": report, "takeaways": takeaways, "closing": closing}


def review_node(state: BlogState, config: dict | None = None) -> dict:
    assert state.article is not None and state.quality is not None
    if not settings.llm_review:
        return {}
    _emit(config, "review", "Independent reviewer is reading the draft...")
    article = state.article
    body = "\n\n".join(f"## {s.heading}\n{s.body_md}" for s in article.sections)
    try:
        review = get_llm(model=settings.evaluator_model, reasoning=False).with_structured_output(LLMReview).invoke([
            SystemMessage(content=(
                "You are a strict editor. Score the blog post from 0.0 to 1.0 (a decimal, never a percentage) for relevance to the topic, "
                "clarity and concreteness. Give 1-2 sentences of actionable feedback "
                "and name the single weakest section heading exactly as written, or leave it empty. "
                "Scale: 0.9+ excellent, 0.7 solid and publishable, 0.5 mediocre, below 0.3 unusable or off-topic. "
                "Most reasonable posts deserve 0.6-0.8."
            )),
            HumanMessage(content=(
                f"Topic: {article.topic}\nTitle: {article.title}\n\n"
                "Numbered sources the author was given (bracketed numbers in the text refer to these; they are real):\n"
                + "\n".join(f"[{s.id}] {s.title} ({s.domain})" for s in article.sources)
                + f"\n\n{clamp_text(body, 6000)}"
            )),
        ])
        review = LLMReview.model_validate(review)
        report = state.quality.model_copy(update={
            "llm_score": review.score, "llm_feedback": review.feedback, "llm_threshold": settings.pass_threshold,
        })
        log_event(20, "llm_review_done", score=review.score)
        return {"quality": report, "rewrite": [review.weakest_section] if review.weakest_section else []}
    except Exception as exc:  # noqa: BLE001 - reviewer outage must not block publishing
        log_event(30, "llm_review_skipped", error=type(exc).__name__)
        return {}


def route_after_review(state: BlogState) -> str:
    assert state.quality is not None
    if state.quality.passed or state.attempt >= settings.max_attempts:
        route = "publish"
    else:
        route = "retry"
    log_event(20, "route_selected", route=route, attempt=state.attempt, passed=state.quality.passed)
    return route


def prepare_retry_node(state: BlogState, config: dict | None = None) -> dict:
    assert state.quality is not None and state.article is not None and state.plan is not None
    headings = quality.failing_headings(state.quality)
    llm_weak = [h for h in state.rewrite if h in {s.heading for s in state.plan.sections}]
    targets = list(dict.fromkeys(headings + llm_weak))
    if not targets:
        targets = [state.plan.sections[0].heading]
    record = AttemptRecord(
        attempt=state.attempt, word_count=state.article.word_count,
        checks_passed=state.quality.checks_passed, checks_total=state.quality.checks_total,
        llm_score=state.quality.llm_score, feedback=state.quality.llm_feedback, rewritten_sections=targets,
    )
    _emit(config, "retry", f"Quality bar not met; rewriting: {', '.join(targets)}")
    return {"attempt": state.attempt + 1, "rewrite": targets, "history": [*state.history, record]}


# --------------------------------------------------------------------------- publish


def publish_node(state: BlogState, config: dict | None = None) -> dict:
    assert state.article is not None and state.quality is not None
    _emit(config, "publish", "Downloading images and rendering the site...")
    final = AttemptRecord(
        attempt=state.attempt, word_count=state.article.word_count,
        checks_passed=state.quality.checks_passed, checks_total=state.quality.checks_total,
        llm_score=state.quality.llm_score, feedback=state.quality.llm_feedback,
    )
    elapsed = round(time.time() - state.started_at, 1) if state.started_at else None
    article = state.article.model_copy(update={
        "quality": state.quality,
        "attempts": [*state.history, final],
        "status": "published" if state.quality.passed else "needs_review",
        "generation_seconds": elapsed,
    })
    saved = store.save_article(article, state.research.images if state.research else [])
    _emit(config, "done", "Published.")
    return {"article": saved}
