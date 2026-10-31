"""Deterministic quality gates. These run before (and independently of) the LLM reviewer."""

import re

from app.config import settings
from app.domain import LENGTH_PRESETS, Article, QualityCheck, QualityReport, SectionPlan
from app.textutil import coverage, sentences, topic_relevance, unique_ratio

_PREAMBLE_MARKERS = ("here is", "here's", "sure,", "certainly", "as an ai", "in this section")


def _section_checks(article: Article, plans: list[SectionPlan], length: str) -> list[QualityCheck]:
    _, (low, high) = LENGTH_PRESETS[length]
    low_ok, high_ok = int(low * 0.6), int(high * 1.8)
    checks: list[QualityCheck] = []
    for section, plan in zip(article.sections, plans, strict=False):
        words = section.word_count
        checks.append(QualityCheck(
            name=f"length:{section.heading}",
            passed=low_ok <= words <= high_ok,
            detail=f"{words} words (target {low}-{high})",
        ))
        cover = coverage(plan.key_points, section.body_md)
        checks.append(QualityCheck(
            name=f"coverage:{section.heading}", passed=cover >= 0.5,
            detail=f"{round(cover * 100)}% of key points present", blocking=False,
        ))
        relevance = topic_relevance(article.topic, f"{section.heading} {section.body_md}")
        checks.append(QualityCheck(
            name=f"relevance:{section.heading}", passed=relevance >= 0.5,
            detail=f"{round(relevance * 100)}% of the topic's key words appear",
        ))
        lowered = section.body_md.lower()[:120]
        checks.append(QualityCheck(
            name=f"clean:{section.heading}",
            passed=not any(m in lowered for m in _PREAMBLE_MARKERS),
            detail="no chatty preamble",
        ))
    return checks


def evaluate(article: Article, plans: list[SectionPlan], length: str = "medium") -> QualityReport:
    """Return a report whose failing check names carry the heading to rewrite after a colon."""
    checks = _section_checks(article, plans, length)

    headings = [s.heading for s in article.sections]
    checks.append(QualityCheck(name="unique_headings", passed=unique_ratio(headings) == 1.0,
                               detail=f"{len(set(headings))}/{len(headings)} unique"))

    all_sentences = [s for sec in article.sections for s in sentences(sec.body_md)]
    ratio = unique_ratio([s for s in all_sentences if len(s.split()) > 5])
    checks.append(QualityCheck(name="no_repetition", passed=ratio >= 0.9,
                               detail=f"{round(ratio * 100)}% of sentences are unique"))

    if article.sources:
        cited = article.cited_source_ids()
        needed = min(2, len(article.sources))
        checks.append(QualityCheck(name="cites_sources", passed=len(cited) >= needed,
                                   detail=f"{len(cited)} distinct sources cited", blocking=False))
        stray = [m for m in re.findall(r"\[(\d{1,2})\](?!\()", " ".join(s.body_md for s in article.sections))
                 if not any(src.id == int(m) for src in article.sources)]
        checks.append(QualityCheck(name="valid_citations", passed=not stray,
                                   detail=f"unknown citation ids: {sorted(set(stray))}" if stray else "all ids resolve"))

    checks.append(QualityCheck(name="has_excerpt", passed=40 <= len(article.excerpt) <= 220,
                               detail=f"{len(article.excerpt)} chars", blocking=False))
    checks.append(QualityCheck(name="has_takeaways", passed=len(article.takeaways) >= 3,
                               detail=f"{len(article.takeaways)} takeaways", blocking=False))
    debris = [t for t in article.takeaways if re.search(r"[{}\[\]]|^\W*key\s*takeaway", t, re.IGNORECASE)]
    checks.append(QualityCheck(name="clean_takeaways", passed=not debris,
                               detail=f"{len(debris)} takeaway(s) contain JSON/list debris"))
    return QualityReport(checks=checks, llm_threshold=settings.pass_threshold, llm_gate=settings.llm_gate)


def failing_headings(report: QualityReport) -> list[str]:
    """Headings of sections whose blocking per-section checks failed."""
    out: list[str] = []
    for check in report.checks:
        if check.blocking and not check.passed and ":" in check.name:
            heading = check.name.split(":", 1)[1]
            if heading not in out:
                out.append(heading)
    return out
