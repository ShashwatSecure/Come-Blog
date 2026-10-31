"""Domain models shared by the pipeline, the store, the renderer and the API."""

from __future__ import annotations

import datetime as dt
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, computed_field

Length = Literal["short", "medium", "long"]
Tone = Literal["conversational", "professional", "playful", "authoritative"]

# sections, words per section (min, max)
LENGTH_PRESETS: dict[str, tuple[int, tuple[int, int]]] = {
    "short": (3, (70, 120)),
    "medium": (4, (110, 170)),
    "long": (6, (130, 200)),
}


class Source(BaseModel):
    id: int
    title: str
    url: str
    snippet: str = ""
    provider: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def domain(self) -> str:
        return (urlparse(self.url).hostname or "").removeprefix("www.")


class ImageAsset(BaseModel):
    url: str
    alt: str
    credit: str = ""
    credit_url: str = ""
    filename: str = ""  # set once downloaded into the post folder
    width: int | None = None
    height: int | None = None


class ResearchBundle(BaseModel):
    topic: str
    summary: str = ""
    sources: list[Source] = Field(default_factory=list)
    images: list[ImageAsset] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.sources or self.summary)

    def as_prompt(self, snippet_chars: int = 420) -> str:
        parts: list[str] = []
        if self.summary:
            parts.append(f"Overview:\n{self.summary}")
        for s in self.sources:
            parts.append(f"[{s.id}] {s.title} ({s.domain})\n{s.snippet[:snippet_chars]}")
        return "\n\n".join(parts)


class SectionPlan(BaseModel):
    heading: str
    brief: str = ""
    key_points: list[str] = Field(default_factory=list)


class ArticlePlan(BaseModel):
    title: str
    subtitle: str = ""
    excerpt: str = ""
    tags: list[str] = Field(default_factory=list)
    sections: list[SectionPlan]


class SectionDraft(BaseModel):
    heading: str
    body_md: str
    attempt: int = 1


class QualityCheck(BaseModel):
    name: str
    passed: bool
    detail: str = ""
    blocking: bool = True


class QualityReport(BaseModel):
    checks: list[QualityCheck] = Field(default_factory=list)
    llm_score: float | None = None
    llm_feedback: str = ""
    llm_threshold: float = 0.7
    # Small local reviewers are noisy (see docs/production/06), so by default the score is advisory.
    llm_gate: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        if any(c.blocking and not c.passed for c in self.checks):
            return False
        if not self.llm_gate:
            return True
        return self.llm_score is None or self.llm_score >= self.llm_threshold

    @computed_field  # type: ignore[prop-decorator]
    @property
    def checks_passed(self) -> int:
        return sum(c.passed for c in self.checks)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def checks_total(self) -> int:
        return len(self.checks)


class AttemptRecord(BaseModel):
    attempt: int
    word_count: int
    checks_passed: int
    checks_total: int
    llm_score: float | None = None
    feedback: str = ""
    rewritten_sections: list[str] = Field(default_factory=list)


class Section(BaseModel):
    id: str
    heading: str
    body_md: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def word_count(self) -> int:
        return len(self.body_md.split())


class Article(BaseModel):
    slug: str
    topic: str
    title: str
    subtitle: str = ""
    excerpt: str = ""
    tags: list[str] = Field(default_factory=list)
    sections: list[Section]
    takeaways: list[str] = Field(default_factory=list)
    closing: str = ""
    sources: list[Source] = Field(default_factory=list)
    images: list[ImageAsset] = Field(default_factory=list)
    status: Literal["published", "needs_review"] = "published"
    quality: QualityReport = Field(default_factory=QualityReport)
    attempts: list[AttemptRecord] = Field(default_factory=list)
    audience: str = "general readers"
    tone: str = "conversational"
    length: str = "medium"
    model: str = ""
    hue: int = 210
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    generation_seconds: float | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def word_count(self) -> int:
        body = sum(s.word_count for s in self.sections)
        return body + len(self.closing.split()) + sum(len(t.split()) for t in self.takeaways)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reading_minutes(self) -> int:
        return max(1, round(self.word_count / 220))

    def cited_source_ids(self) -> set[int]:
        import re

        found: set[int] = set()
        text = " ".join([s.body_md for s in self.sections] + [self.closing])
        for match in re.finditer(r"\[(\d{1,2})\](?!\()", text):
            found.add(int(match.group(1)))
        return {i for i in found if any(src.id == i for src in self.sources)}
