import datetime as dt
import os

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from slugify import slugify

from app.config import settings
from app.graph.llm import get_llm
from app.graph.state import (
    BlogState,
    BlogEvaluation,
    OrchestratorOutput,
    SectionDraft,
    SectionEvaluation,
    SectionWorkState,
)


class SimpleTopicAnalysis(BaseModel):
    title: str
    summary: str
    strong_points: list[str] = Field(min_length=5, max_length=5)


def _emit(config: dict | None, message: str) -> None:
    event_sink = (config or {}).get("configurable", {}).get("event_sink")
    if event_sink:
        event_sink(message)


def analyze_topic_node(state: BlogState, config: dict | None = None) -> dict:
    _emit(config, "Analyzing the topic and identifying the five essential points...")
    result: SimpleTopicAnalysis = get_llm().with_structured_output(SimpleTopicAnalysis).invoke(
        [
            SystemMessage(content="You are a precise topic analyst and blog editor."),
            HumanMessage(content=(
                f"Topic: {state.topic}\n\nReturn a concise 3-4 line summary and exactly five "
                "strong, distinct points that must be present in a useful blog, essay, or paragraph "
                "about this topic. Make each point concrete and relevant."
            )),
        ]
    )
    return {"blog_title": result.title, "summary": result.summary, "strong_points": result.strong_points}


def generate_blog_node(state: BlogState, config: dict | None = None) -> dict:
    _emit(config, f"Generating the blog draft (attempt {state.attempt} of 3)...")
    instruction = "Write a simple blog of exactly 10 sentences about the topic. Cover every strong point. Be clear, useful, and concrete. Return only the blog text."
    if state.evaluation and state.evaluation.feedback:
        instruction += f" Improve the previous draft using this feedback: {state.evaluation.feedback}"
    response = get_llm().invoke([
        SystemMessage(content=instruction),
        HumanMessage(content=f"Topic: {state.topic}\nStrong points:\n- " + "\n- ".join(state.strong_points)),
    ])
    return {"draft": response.content.strip()}


def evaluate_blog_node(state: BlogState, config: dict | None = None) -> dict:
    _emit(config, "Evaluating the draft and checking all five points...")
    evaluator = get_llm(model=settings.evaluator_model, reasoning=False).with_structured_output(BlogEvaluation)
    result: BlogEvaluation = evaluator.invoke([
        SystemMessage(content=(
            "Evaluate this simple 10-sentence blog for relevance, clarity, usefulness, coverage "
            "of all five strong points, and sentence count. Return score as a decimal from 0.0 to "
            "1.0, never as a percentage. Pass only if it is ready."
        )),
        HumanMessage(content=(
            f"Topic: {state.topic}\nStrong points:\n- " + "\n- ".join(state.strong_points)
            + f"\n\nDraft:\n{state.draft}"
        )),
    ])
    return {"evaluation": result}


def route_after_blog_evaluation(state: BlogState) -> str:
    if state.evaluation and (state.evaluation.passed or state.attempt >= 3):
        return "writer"
    return "retry"


def prepare_blog_retry_node(state: BlogState, config: dict | None = None) -> dict:
    _emit(config, "The draft needs improvement; sending evaluator feedback back to the generator...")
    return {"attempt": state.attempt + 1}

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

ORCHESTRATOR_SYSTEM = f"""You are a blog editor planning an article outline.
Break the given topic into {settings.min_sections}-{settings.max_sections} \
distinct, non-overlapping sections that together make a useful, well \
organized blog post. Each section needs a short id (snake_case), a title, \
a one-sentence brief describing what it must cover, and 2-4 key points to \
hit. Do not include an "introduction" or "conclusion" section — those are \
added later automatically."""


def orchestrator_node(state: BlogState, config: dict | None = None) -> dict:
    _emit(config, "Researching the topic and creating an article outline...")
    llm = get_llm().with_structured_output(OrchestratorOutput)
    result: OrchestratorOutput = llm.invoke(
        [
            SystemMessage(content=ORCHESTRATOR_SYSTEM),
            HumanMessage(content=f"Topic: {state.topic}"),
        ]
    )
    sections = result.sections[: settings.max_sections]
    progress_sink = (config or {}).get("configurable", {}).get("progress_sink")
    if progress_sink:
        progress_sink("planned", len(sections))
    _emit(config, f"Breaking the article into {len(sections)} titles...")
    for section in sections:
        _emit(config, f"Planned section: {section.title}")
    return {"blog_title": result.title, "sections": sections}


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

WORKER_SYSTEM = """You are a knowledgeable blog writer. Write ONE section of \
a larger blog post. Be concrete, useful, and to the point - no fluff, no \
restating the brief, no meta commentary about the article itself. Use \
markdown (## not needed, just body text and sub-bullets where useful). \
Aim for 150-300 words unless the brief clearly needs more."""


def worker_node(state: SectionWorkState, config: dict | None = None) -> dict:
    section = state.section
    _emit(config, f"Working on '{section.title}' (attempt {state.attempt})...")
    prompt = (
        f"Blog topic: {state.topic}\n"
        f"Section title: {section.title}\n"
        f"Section brief: {section.brief}\n"
        f"Key points to cover: {', '.join(section.key_points)}\n"
    )
    if state.previous_draft and state.previous_feedback:
        prompt += (
            f"\nYour previous draft was rejected by an editor.\n"
            f"Previous draft:\n{state.previous_draft}\n\n"
            f"Editor feedback to address:\n{state.previous_feedback}\n"
            f"Write an improved draft that fixes this feedback."
        )

    llm = get_llm()
    response = llm.invoke([SystemMessage(content=WORKER_SYSTEM), HumanMessage(content=prompt)])
    draft = SectionDraft(
        id=section.id,
        title=section.title,
        content=response.content.strip(),
        attempt=state.attempt,
    )
    return {"drafts": {section.id: draft}}


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

EVALUATOR_SYSTEM = f"""You are a strict but fair blog editor evaluating a \
single section draft against its brief. Score it from 0.0 to 1.0 on: \
relevance to the brief, coverage of the key points, clarity, and whether it \
is useful/to the point (no filler). passed must be true only if score >= \
{settings.evaluator_pass_threshold}. feedback must be short, specific, and \
actionable - things the writer should literally change, not praise."""


def evaluator_node(state: SectionWorkState, config: dict | None = None) -> dict:
    section = state.section
    _emit(config, f"Evaluating '{section.title}'...")
    draft = state.drafts[section.id]
    prompt = (
        f"Section brief: {section.brief}\n"
        f"Key points required: {', '.join(section.key_points)}\n\n"
        f"Draft to evaluate:\n{draft.content}"
    )
    llm = get_llm().with_structured_output(SectionEvaluation)
    evaluation: SectionEvaluation = llm.invoke(
        [SystemMessage(content=EVALUATOR_SYSTEM), HumanMessage(content=prompt)]
    )
    return {"evaluations": {section.id: evaluation}}


def route_after_evaluation(state: SectionWorkState) -> str:
    section = state.section
    evaluation = state.evaluations[section.id]
    if evaluation.passed or state.attempt >= settings.max_worker_retries:
        return "accept"
    return "retry"


def prepare_retry(state: SectionWorkState, config: dict | None = None) -> dict:
    section = state.section
    draft = state.drafts[section.id]
    evaluation = state.evaluations[section.id]
    _emit(config, f"'{section.title}' needs revision; applying editor feedback...")
    return {
        "attempt": state.attempt + 1,
        "previous_draft": draft.content,
        "previous_feedback": evaluation.feedback,
    }


def accept_section(state: SectionWorkState, config: dict | None = None) -> dict:
    progress_sink = (config or {}).get("configurable", {}).get("progress_sink")
    if progress_sink:
        progress_sink("accepted", state.section.id)
    _emit(config, f"Accepted '{state.section.title}'.")
    return {"accepted_ids": [state.section.id]}


# ---------------------------------------------------------------------------
# Reducer
# ---------------------------------------------------------------------------

REDUCER_SYSTEM = """You are a senior editor assembling a final blog post from \
already-approved section drafts. Write a short, engaging introduction and a \
brief conclusion, then stitch the sections together in the given order with \
proper markdown headings (##). Keep each section's content mostly intact - \
only smooth transitions, fix duplicate points across sections, and keep a \
consistent voice. Output ONLY the final markdown body (no title line, no \
frontmatter, no commentary)."""


def reducer_node(state: BlogState, config: dict | None = None) -> dict:
    _emit(config, "All sections accepted. Assembling the final article...")
    ordered_drafts = [state.drafts[s.id] for s in state.sections if s.id in state.drafts]
    sections_text = "\n\n".join(f"### {d.title}\n{d.content}" for d in ordered_drafts)

    llm = get_llm()
    messages = [
        SystemMessage(content=REDUCER_SYSTEM),
        HumanMessage(content=f"Blog title: {state.blog_title}\n\n{sections_text}"),
    ]
    stream_sink = (config or {}).get("configurable", {}).get("stream_sink")
    if hasattr(llm, "stream"):
        chunks = []
        for chunk in llm.stream(messages):
            text = chunk.content
            chunks.append(text)
            if stream_sink:
                stream_sink(text)
        body = "".join(chunks).strip()
    else:
        body = llm.invoke(messages).content.strip()
    return {"final_markdown": body}


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_markdown_node(state: BlogState, config: dict | None = None) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    slug = slugify(state.blog_title or state.topic)[:60]
    filename = f"{slug}-{now.strftime('%Y%m%d%H%M%S')}.md"

    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", settings.output_dir))
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, filename)

    final_markdown = (state.final_markdown or state.draft).strip()
    if final_markdown.startswith("---"):
        _, _, final_markdown = final_markdown.partition("---")
        _, _, final_markdown = final_markdown.partition("---")
        final_markdown = final_markdown.strip()
    title = state.blog_title or state.topic
    heading = f"# {title}"
    if final_markdown.casefold().startswith(heading.casefold()):
        final_markdown = final_markdown[len(heading):].lstrip()
    full_doc = f"{heading}\n\n{final_markdown}\n"

    with open(path, "w", encoding="utf-8") as f:
        f.write(full_doc)

    _emit(config, "Saved the completed Markdown article.")
    return {"final_markdown": full_doc, "output_path": path}
