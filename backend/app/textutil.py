"""Small, dependency-free text helpers used by the pipeline and quality gates."""

import re
from collections.abc import Iterable

from slugify import slugify

_STOPWORDS = frozenset(
    "a an and are as at be by for from has have how in into is it its of on or that the "
    "this to was were what when where which who why will with your you their they them "
    "can do does not more most than then these those about over under up out so if".split()
)

_PREAMBLE = re.compile(
    r"^\s*(sure|certainly|here(?:'s| is| are)|of course|okay|absolutely)\b[^\n]*:?\s*\n+",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


def word_count(text: str) -> int:
    return len(text.split())


def sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text).strip()
    return [s for s in _SENTENCE_SPLIT.split(flat) if s]


def significant_tokens(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9]+", text.lower())
        if len(t) > 2 and t not in _STOPWORDS
    }


def coverage(points: Iterable[str], body: str, threshold: float = 0.5) -> float:
    """Fraction of `points` whose significant words mostly appear in `body`."""
    body_tokens = significant_tokens(body)
    points = [p for p in points if p.strip()]
    if not points:
        return 1.0
    hit = 0
    for point in points:
        tokens = significant_tokens(point)
        if not tokens or len(tokens & body_tokens) / len(tokens) >= threshold:
            hit += 1
    return hit / len(points)


_TAKEAWAY_LABEL = re.compile(r"^\W*(?:key[\s_-]*)?(?:takeaway|point|tip)[\s_-]*\d*\s*[:.)-]\s*", re.IGNORECASE)


def clean_takeaways(items: Iterable[str], limit: int = 5) -> list[str]:
    """Drop JSON/list debris small models leak ('{', 'keytakeaway1: ...') and keep real sentences."""
    cleaned: list[str] = []
    for item in items:
        text = _TAKEAWAY_LABEL.sub("", item.strip().strip("{}[]\",'").strip())
        text = re.sub(r"^[-*•\d.)\s]+", "", text).strip()
        if len(text.split()) >= 3 and text not in cleaned:
            cleaned.append(text)
    return cleaned[:limit]


def topic_relevance(topic: str, text: str) -> float:
    """Fraction of the topic's significant words found in `text` (5-char prefix match, so sleep ~ sleeping)."""
    wanted = {t[:5] for t in significant_tokens(topic)}
    if not wanted:
        return 1.0
    have = {t[:5] for t in significant_tokens(text)}
    return len(wanted & have) / len(wanted)


def clean_llm_markdown(text: str) -> str:
    """Strip chatty preambles, code fences, headings and stray whitespace from model output."""
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text).strip()
    text = _PREAMBLE.sub("", text, count=1)
    lines = [ln for ln in text.splitlines() if not re.match(r"^\s{0,3}#{1,6}\s", ln)]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clamp_text(text: str, limit: int) -> str:
    """Trim to `limit` characters on a word boundary, adding an ellipsis when cut."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:-")
    return cut + "…"


def make_slug(text: str, max_length: int = 60) -> str:
    return slugify(text, max_length=max_length, word_boundary=True) or "post"


def normalize_tag(tag: str) -> str:
    return slugify(tag.strip(), max_length=24, word_boundary=True)


def unique_ratio(items: list[str]) -> float:
    if not items:
        return 1.0
    normalized = [re.sub(r"\W+", " ", i.lower()).strip() for i in items]
    return len(set(normalized)) / len(normalized)
