from app.graph.nodes import (
    BlogEvaluation,
    accept_section,
    evaluator_node,
    orchestrator_node,
    prepare_retry,
    reducer_node,
    route_after_evaluation,
    worker_node,
    write_markdown_node,
)


def test_blog_evaluation_normalizes_percentage_score():
    evaluation = BlogEvaluation(score=100, passed=True, feedback="ready")
    assert evaluation.score == 1.0
from app.graph.state import BlogState, SectionDraft, SectionEvaluation, SectionPlan, SectionWorkState


def test_orchestrator_plans_sections(fake_llm):
    state = BlogState(topic="Testing LangGraph agents")
    result = orchestrator_node(state)
    assert result["blog_title"] == "Fake Blog Title"
    assert len(result["sections"]) == 2
    assert all(isinstance(s, SectionPlan) for s in result["sections"])


def test_worker_produces_draft(fake_llm):
    section = SectionPlan(id="s1", title="Section 1", brief="brief", key_points=["a"])
    state = SectionWorkState(topic="topic", section=section)
    result = worker_node(state)
    draft = result["drafts"]["s1"]
    assert draft.content == "Fake generated content."
    assert draft.attempt == 1


def test_evaluator_scores_draft(fake_llm):
    section = SectionPlan(id="s1", title="Section 1", brief="brief", key_points=["a"])
    draft = SectionDraft(id="s1", title="Section 1", content="some content")
    state = SectionWorkState(topic="topic", section=section, drafts={"s1": draft})
    result = evaluator_node(state)
    evaluation = result["evaluations"]["s1"]
    assert evaluation.passed is True
    assert evaluation.score == 0.9


def test_route_accepts_on_pass():
    section = SectionPlan(id="s1", title="T", brief="b")
    state = SectionWorkState(
        topic="t",
        section=section,
        evaluations={"s1": SectionEvaluation(score=0.9, passed=True, feedback="ok")},
    )
    assert route_after_evaluation(state) == "accept"


def test_route_retries_on_fail_under_max_attempts():
    section = SectionPlan(id="s1", title="T", brief="b")
    state = SectionWorkState(
        topic="t",
        section=section,
        attempt=1,
        evaluations={"s1": SectionEvaluation(score=0.2, passed=False, feedback="fix it")},
    )
    assert route_after_evaluation(state) == "retry"


def test_route_accepts_on_fail_at_max_attempts():
    section = SectionPlan(id="s1", title="T", brief="b")
    state = SectionWorkState(
        topic="t",
        section=section,
        attempt=2,  # equals default max_worker_retries
        evaluations={"s1": SectionEvaluation(score=0.2, passed=False, feedback="fix it")},
    )
    assert route_after_evaluation(state) == "accept"


def test_prepare_retry_carries_feedback_forward():
    section = SectionPlan(id="s1", title="T", brief="b")
    draft = SectionDraft(id="s1", title="T", content="draft v1")
    evaluation = SectionEvaluation(score=0.3, passed=False, feedback="needs examples")
    state = SectionWorkState(
        topic="t", section=section, attempt=1, drafts={"s1": draft}, evaluations={"s1": evaluation}
    )
    result = prepare_retry(state)
    assert result["attempt"] == 2
    assert result["previous_draft"] == "draft v1"
    assert result["previous_feedback"] == "needs examples"


def test_accept_section_records_id():
    section = SectionPlan(id="s1", title="T", brief="b")
    state = SectionWorkState(topic="t", section=section)
    result = accept_section(state)
    assert result["accepted_ids"] == ["s1"]


def test_reducer_combines_accepted_drafts(fake_llm):
    sections = [SectionPlan(id="s1", title="One", brief="b"), SectionPlan(id="s2", title="Two", brief="b")]
    drafts = {
        "s1": SectionDraft(id="s1", title="One", content="content one"),
        "s2": SectionDraft(id="s2", title="Two", content="content two"),
    }
    state = BlogState(topic="t", blog_title="My Blog", sections=sections, drafts=drafts)
    result = reducer_node(state)
    assert result["final_markdown"] == "Fake generated content."


def test_write_markdown_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr("app.graph.nodes.settings.output_dir", str(tmp_path))
    state = BlogState(topic="t", blog_title="My Great Blog", final_markdown="body text")
    result = write_markdown_node(state)
    assert result["output_path"].endswith(".md")
    with open(result["output_path"], encoding="utf-8") as f:
        content = f.read()
    assert "My Great Blog" in content
    assert "body text" in content
