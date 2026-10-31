from pydantic import BaseModel, Field

from app.domain import (
    Article,
    ArticlePlan,
    AttemptRecord,
    QualityReport,
    ResearchBundle,
    SectionDraft,
)


class LLMReview(BaseModel):
    """Structured output of the independent reviewer model."""

    score: float = Field(ge=0.0, le=1.0)
    feedback: str = ""
    weakest_section: str = ""

    def __init__(self, **data):
        raw = data.get("score")
        if isinstance(raw, int | float) and raw > 1:
            data["score"] = min(float(raw) / 100, 1.0)
        super().__init__(**data)


class BlogState(BaseModel):
    """Graph state shared across nodes. Node functions return partial updates."""

    topic: str
    length: str = "medium"
    tone: str = "conversational"
    audience: str = "general readers"

    research: ResearchBundle | None = None
    plan: ArticlePlan | None = None
    drafts: dict[str, SectionDraft] = Field(default_factory=dict)
    takeaways: list[str] = Field(default_factory=list)
    closing: str = ""
    article: Article | None = None
    quality: QualityReport | None = None
    attempt: int = 1
    rewrite: list[str] = Field(default_factory=list)
    history: list[AttemptRecord] = Field(default_factory=list)
    started_at: float = 0.0
