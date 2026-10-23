import pytest

from app.graph.nodes import (
    BlogEvaluation,
    SimpleTopicAnalysis,
    analyze_topic_node,
    evaluate_blog_node,
    generate_blog_node,
    prepare_blog_retry_node,
    route_after_blog_evaluation,
    write_markdown_node,
)
from app.graph.state import BlogState


class FakeStructuredLLM:
    def __init__(self, response):
        self.response = response

    def invoke(self, _messages):
        return self.response


class FakeMessage:
    def __init__(self, content: str):
        self.content = content


class FakeLLM:
    def __init__(self):
        self.responses = {}

    def invoke(self, _messages):
        return FakeMessage("Sentence one. Sentence two.")

    def with_structured_output(self, schema):
        return FakeStructuredLLM(self.responses[schema])


@pytest.fixture
def fake_llm(monkeypatch):
    llm = FakeLLM()
    llm.responses[SimpleTopicAnalysis] = SimpleTopicAnalysis(
        title="Fake Blog Title",
        summary="A concise topic summary.",
        strong_points=["one", "two", "three", "four", "five"],
    )
    llm.responses[BlogEvaluation] = BlogEvaluation(score=0.9, passed=True, feedback="Looks good.")
    monkeypatch.setattr("app.graph.nodes.get_llm", lambda *args, **kwargs: llm)
    return llm


def test_analyze_topic_returns_summary_and_five_points(fake_llm):
    result = analyze_topic_node(BlogState(topic="Testing LangGraph agents"))
    assert result["blog_title"] == "Fake Blog Title"
    assert len(result["strong_points"]) == 5


def test_generate_blog_returns_draft(fake_llm):
    state = BlogState(topic="topic", strong_points=["one", "two", "three", "four", "five"])
    assert generate_blog_node(state)["draft"] == "Sentence one. Sentence two."


def test_evaluator_and_retry_routing(fake_llm):
    state = BlogState(topic="topic", draft="draft", strong_points=["one"] * 5)
    state = state.model_copy(update=evaluate_blog_node(state))
    assert state.evaluation.score == 0.9
    assert route_after_blog_evaluation(state) == "writer"


def test_retry_increments_attempt():
    state = BlogState(topic="topic", attempt=1)
    assert prepare_blog_retry_node(state)["attempt"] == 2


def test_percentage_score_is_normalized():
    assert BlogEvaluation(score=100, passed=True, feedback="ready").score == 1.0


def test_write_markdown_creates_title_and_body_only(tmp_path, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.settings.output_dir", str(tmp_path))
    state = BlogState(topic="t", blog_title="My Great Blog", final_markdown="body text")
    result = write_markdown_node(state)
    with open(result["output_path"], encoding="utf-8") as file:
        content = file.read()
    assert content == "# My Great Blog\n\nbody text\n"
