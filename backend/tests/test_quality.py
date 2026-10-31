from app import quality
from app.domain import Section, SectionPlan
from tests.conftest import make_article

PLANS = [SectionPlan(heading="Keep a schedule", key_points=["consistent sleep schedules", "internal clock"]),
         SectionPlan(heading="Fix your room", key_points=["cool dark rooms"])]


def _padded(sources, words):
    text = "sleep hygiene " + " ".join(f"word{i}" for i in range(words)) + " [1] [2]."
    return make_article(sources, sections=[
        Section(id="a", heading="Keep a schedule", body_md=text),
        Section(id="b", heading="Fix your room", body_md=text.replace("word", "term")),
    ])


def test_good_article_passes(sources):
    article = _padded(sources, 130)
    report = quality.evaluate(article, PLANS, "medium")
    assert report.passed
    assert report.checks_passed >= report.checks_total - 2


def test_too_short_section_blocks_and_is_reported_for_rewrite(sources):
    article = _padded(sources, 10)
    report = quality.evaluate(article, PLANS, "medium")
    assert not report.passed
    assert quality.failing_headings(report) == ["Keep a schedule", "Fix your room"]


def test_unknown_citation_id_is_blocking(sources):
    article = make_article(sources, sections=[
        Section(id="a", heading="Keep a schedule", body_md=" ".join(["x"] * 130) + " [9]."),
        Section(id="b", heading="Fix your room", body_md=" ".join(["y"] * 130)),
    ])
    names = {c.name: c for c in quality.evaluate(article, PLANS).checks}
    assert not names["valid_citations"].passed and names["valid_citations"].blocking


def test_repetition_is_detected(sources):
    repeated = "This exact long sentence repeats across sections without any change at all. " * 20
    article = make_article(sources, sections=[
        Section(id="a", heading="Keep a schedule", body_md=repeated),
        Section(id="b", heading="Fix your room", body_md=repeated),
    ])
    names = {c.name: c for c in quality.evaluate(article, PLANS).checks}
    assert not names["no_repetition"].passed


def test_takeaway_debris_is_a_blocking_failure(sources):
    article = _padded(sources, 130).model_copy(update={"takeaways": ["{", "keytakeaway1: Do the thing well", "Fine point here"]})
    checks = {c.name: c for c in quality.evaluate(article, PLANS).checks}
    assert not checks["clean_takeaways"].passed and checks["clean_takeaways"].blocking


def test_llm_score_is_advisory_by_default(sources):
    report = quality.evaluate(_padded(sources, 130), PLANS)
    assert report.model_copy(update={"llm_score": 0.0}).passed is True


def test_llm_score_blocks_when_gate_enabled(sources):
    report = quality.evaluate(_padded(sources, 130), PLANS).model_copy(update={"llm_gate": True})
    assert report.model_copy(update={"llm_score": 0.2}).passed is False
    assert report.model_copy(update={"llm_score": 0.9}).passed is True


def test_off_topic_section_fails_relevance_and_is_rewritten(sources):
    volcano = " ".join(["Volcanoes erupt when magma rises through the crust today."] * 14) + " [1] [2]"
    article = make_article(sources, topic="how to improve your sleep", sections=[
        Section(id="a", heading="Keep a schedule", body_md=" ".join(["Sleeping at regular times improves your sleep."] * 17) + " [1] [2]"),
        Section(id="b", heading="Volcano Basics", body_md=volcano),
    ])
    plans = [PLANS[0], SectionPlan(heading="Volcano Basics", key_points=["magma"])]
    report = quality.evaluate(article, plans, "medium")
    failed = {c.name for c in report.checks if not c.passed}
    assert "relevance:Volcano Basics" in failed and "relevance:Keep a schedule" not in failed
    assert quality.failing_headings(report) == ["Volcano Basics"]
