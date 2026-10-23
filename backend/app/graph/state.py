from pydantic import BaseModel, Field, field_validator

class BlogEvaluation(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    feedback: str

    @field_validator("score", mode="before")
    @classmethod
    def normalize_score(cls, value: float) -> float:
        numeric_score = float(value)
        return numeric_score / 100 if numeric_score > 1 else numeric_score


class BlogState(BaseModel):
    """Top-level graph state, shared across all nodes."""

    topic: str
    blog_title: str = ""
    summary: str = ""
    strong_points: list[str] = Field(default_factory=list)
    draft: str = ""
    evaluation: BlogEvaluation | None = None
    attempt: int = 1

    final_markdown: str = ""
    output_path: str = ""
