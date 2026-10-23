import operator
from typing import Annotated

from pydantic import BaseModel, Field


class SectionPlan(BaseModel):
    id: str
    title: str
    brief: str
    key_points: list[str] = Field(default_factory=list)


class OrchestratorOutput(BaseModel):
    """Structured output the orchestrator LLM call must produce."""

    title: str
    sections: list[SectionPlan]


class SectionDraft(BaseModel):
    id: str
    title: str
    content: str
    attempt: int = 1


class SectionEvaluation(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    feedback: str


def _merge_dict(left: dict, right: dict) -> dict:
    merged = dict(left)
    merged.update(right)
    return merged


class BlogState(BaseModel):
    """Top-level graph state, shared across all nodes."""

    topic: str
    blog_title: str = ""
    sections: list[SectionPlan] = Field(default_factory=list)

    # Keyed by section id. Annotated with a merge reducer so parallel
    # worker/evaluator branches can each write their own key without
    # clobbering siblings' writes (LangGraph fan-out requirement).
    drafts: Annotated[dict[str, SectionDraft], _merge_dict] = Field(default_factory=dict)
    evaluations: Annotated[dict[str, SectionEvaluation], _merge_dict] = Field(default_factory=dict)
    accepted_ids: Annotated[list[str], operator.add] = Field(default_factory=list)

    final_markdown: str = ""
    output_path: str = ""


class SectionWorkState(BaseModel):
    """Per-branch state passed via Send() to the worker/evaluator subgraph."""

    topic: str
    section: SectionPlan
    attempt: int = 1
    previous_draft: str = ""
    previous_feedback: str = ""

    drafts: Annotated[dict[str, SectionDraft], _merge_dict] = Field(default_factory=dict)
    evaluations: Annotated[dict[str, SectionEvaluation], _merge_dict] = Field(default_factory=dict)
    accepted_ids: Annotated[list[str], operator.add] = Field(default_factory=list)
