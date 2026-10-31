"""Pipeline tests with a scripted fake LLM: no Ollama, no network."""

import pytest

from app.config import settings
from app.domain import ArticlePlan, QualityReport, SectionPlan
from app.graph import nodes
from app.graph.build import build_graph
from app.graph.state import BlogState, LLMReview


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeStructured:
    def __init__(self, llm, schema):
        self.llm, self.schema = llm, schema

    def invoke(self, messages):
        self.llm.calls.append(self.schema.__name__)
        response = self.llm.structured[self.schema.__name__]
        return response() if callable(response) else response


class FakeLLM:
    def __init__(self, section_words=130):
        self.calls: list[str] = []
        self.section_words = section_words
        self.structured = {
            "ArticlePlan": ArticlePlan(
                title="Sleep Better Tonight", subtitle="Small habits.", excerpt="Practical, evidence-based habits that improve how well and how long you sleep.",
                tags=["Sleep", "health"],
                sections=[SectionPlan(heading=h, brief="b", key_points=["sleep schedule"]) for h in ("Keep a schedule", "Fix your room", "Limit screens", "Eat well")]),
            "Wrapup": nodes.Wrapup(takeaways=["One", "Two", "Three"], closing="Start tonight with one small change."),
            "LLMReview": LLMReview(score=0.9, feedback="Good.", weakest_section=""),
        }

    def with_structured_output(self, schema):
        return FakeStructured(self, schema)

    def invoke(self, messages):
        self.calls.append("section")
        n = self.section_words() if callable(self.section_words) else self.section_words
        return FakeMessage("Sleep schedule habits matter [1]. " + " ".join(f"w{len(self.calls)}x{i}" for i in range(n)))


@pytest.fixture
def fake(monkeypatch, bundle):
    llm = FakeLLM()
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: llm)
    monkeypatch.setattr(nodes.research, "research", lambda topic: bundle)
    return llm


def test_plan_node_normalises_tags_and_limits_sections(fake):
    out = nodes.plan_node(BlogState(topic="sleep hygiene", length="medium"))
    assert out["plan"].tags == ["sleep", "health"]
    assert len(out["plan"].sections) <= 5


def test_blank_excerpt_is_replaced_from_research_summary(fake, bundle):
    fake.structured["ArticlePlan"] = fake.structured["ArticlePlan"].model_copy(update={"excerpt": ""})
    out = nodes.plan_node(BlogState(topic="sleep hygiene", research=bundle))
    assert len(out["plan"].excerpt) >= 10 and out["plan"].excerpt.startswith("Sleep matters")


def test_reviewer_is_shown_the_numbered_sources(fake, bundle, article, monkeypatch):
    seen = {}

    class SpyStructured:
        def invoke(self, messages):
            seen["prompt"] = messages[1].content
            return LLMReview(score=0.8, feedback="ok")

    class SpyLLM:
        def with_structured_output(self, schema):
            return SpyStructured()

    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: SpyLLM())
    state = BlogState(topic="sleep hygiene", article=article, quality=QualityReport())
    out = nodes.review_node(state)
    assert "[1] Alpha - Wikipedia" in seen["prompt"] and "they are real" in seen["prompt"]
    assert out["quality"].llm_score == 0.8


def test_plan_node_falls_back_when_model_breaks_schema(monkeypatch):
    class Broken:
        def with_structured_output(self, schema):
            raise ValueError("bad json")

    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: Broken())
    plan = nodes.plan_node(BlogState(topic="deep sea farming", length="short"))["plan"]
    assert plan.title and len(plan.sections) == 3


def test_full_graph_publishes_a_complete_site_page(fake, tmp_path):
    result = build_graph().invoke(BlogState(topic="sleep hygiene"), config={"configurable": {}})
    article = result["article"]
    assert article.status == "published" and article.quality.passed
    assert len(article.sections) == 4 and len(article.sources) == 2
    post = settings.site_path / "posts" / article.slug
    assert (post / "index.html").is_file() and (post / "article.md").is_file() and (post / "article.json").is_file()
    assert (settings.site_path / "index.html").is_file() and (settings.site_path / "feed.xml").is_file()
    assert article.attempts[-1].llm_score == 0.9


def test_failing_quality_triggers_targeted_rewrite_then_publishes(monkeypatch, bundle):
    sizes = iter([5, 5, 5, 5] + [130] * 40)  # first pass too short, rewrites are fine
    llm = FakeLLM(section_words=lambda: next(sizes))
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: llm)
    monkeypatch.setattr(nodes.research, "research", lambda topic: bundle)
    result = build_graph().invoke(BlogState(topic="sleep hygiene"), config={"configurable": {}})
    article = result["article"]
    assert len(article.attempts) == 2 and article.attempts[0].rewritten_sections
    assert article.status == "published"


def test_attempts_are_capped_and_flagged_for_review(monkeypatch, bundle):
    llm = FakeLLM(section_words=3)  # can never satisfy the length gate
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: llm)
    monkeypatch.setattr(nodes.research, "research", lambda topic: bundle)
    result = build_graph().invoke(BlogState(topic="sleep hygiene"), config={"configurable": {}})
    article = result["article"]
    assert len(article.attempts) == settings.max_attempts
    assert article.status == "needs_review"  # never silently published as good


def test_reviewer_outage_does_not_block_publishing(monkeypatch, bundle):
    llm = FakeLLM()
    llm.structured["LLMReview"] = lambda: (_ for _ in ()).throw(TimeoutError("ollama down"))
    monkeypatch.setattr(nodes, "get_llm", lambda *a, **k: llm)
    monkeypatch.setattr(nodes.research, "research", lambda topic: bundle)
    result = build_graph().invoke(BlogState(topic="sleep hygiene"), config={"configurable": {}})
    assert result["article"].quality.llm_score is None and result["article"].status == "published"


def test_events_are_delivered_to_the_sink(fake):
    events = []
    build_graph().invoke(BlogState(topic="sleep hygiene"), config={"configurable": {"event_sink": events.append}})
    stages = [e["stage"] for e in events]
    assert stages[0] == "research" and stages[-1] == "done"
    assert {"plan", "write", "assemble", "review", "publish"} <= set(stages)


def test_percentage_review_scores_are_normalised():
    assert LLMReview(score=85, feedback="x").score == 0.85
