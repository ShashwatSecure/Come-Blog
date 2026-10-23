import datetime as dt
import os
import uuid
import time
from typing import cast

from pydantic import BaseModel, Field, field_validator

from langchain_core.messages import HumanMessage, SystemMessage
from slugify import slugify

from app.config import settings
from app.graph.build import build_graph
from app.graph.llm import get_llm
from app.graph.state import BlogState
from app.logging_config import logger


class BlogEvaluation(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    feedback: str

    @field_validator("score", mode="before")
    @classmethod
    def normalize_score(cls, value: float) -> float:
        numeric_score = float(value)
        return numeric_score / 100 if numeric_score > 1 else numeric_score


class DraftAttempt(BaseModel):
    iteration: int
    draft: str
    score: float | None = None
    feedback: str = ""

def check_ollama() -> str:
    response = get_llm().invoke([HumanMessage(content="Reply with exactly: Ollama is up.")])
    return response.content.strip()


def generate_preview(topic: str) -> str:
    response = get_llm().invoke(
        [
            SystemMessage(content="Give a concise, useful preview in 3-4 lines about the topic."),
            HumanMessage(content=f"Topic: {topic}"),
        ]
    )
    return response.content.strip()


def _draft_blog(topic: str, feedback: str = "") -> str:
    instruction = "Generate a simple blog in exactly 10 sentences about the topic. Include different aspects of the topic but keep it simple and useful."
    if feedback:
        instruction += f" Improve the previous draft using this evaluator feedback: {feedback}"
    response = get_llm().invoke(
        [SystemMessage(content=instruction), HumanMessage(content=f"Topic: {topic}")]
    )
    return response.content.strip()


def _evaluate_blog(topic: str, draft: str) -> BlogEvaluation:
    evaluator = get_llm(model=settings.evaluator_model, reasoning=False).with_structured_output(BlogEvaluation)
    response = evaluator.invoke(
        [
            SystemMessage(
                content=(
                    "Evaluate the blog draft against the topic. Score relevance, clarity, usefulness, "
                    "and whether it is approximately 10 simple sentences. Return a score from 0.0 to 1.0 "
                    "and concise, specific feedback for the writer."
                )
            ),
            HumanMessage(content=f"Topic: {topic}\n\nDraft:\n{draft}"),
        ]
    )
    return response


def generate_blog(topic: str) -> tuple[str, str, list[DraftAttempt]]:
    result = run_blog_graph(topic)
    return (
        cast(str, result["markdown"]),
        cast(str, result["output_path"]),
        cast(list[DraftAttempt], result["attempts"]),
    )


def run_blog_graph(topic: str, request_id: str | None = None) -> dict[str, object]:
    run_id = str(uuid.uuid4())
    started = time.perf_counter()
    logger.info("graph_started", extra={"event": "graph_started", "run_id": run_id, "request_id": request_id, "topic_length": len(topic)})
    try:
        result = build_graph().invoke(
            BlogState(topic=topic),
            config={"configurable": {"run_id": run_id, "request_id": request_id}},
        )
    except Exception:
        logger.exception(
            "graph_failed",
            extra={"event": "graph_failed", "run_id": run_id, "request_id": request_id, "duration_ms": round((time.perf_counter() - started) * 1000, 2)},
        )
        raise
    logger.info(
        "graph_completed",
        extra={"event": "graph_completed", "run_id": run_id, "request_id": request_id, "duration_ms": round((time.perf_counter() - started) * 1000, 2), "attempt": result.get("attempt", 1), "strong_points": len(result.get("strong_points", []))},
    )
    evaluation = result.get("evaluation")
    attempts = [
        DraftAttempt(
            iteration=result.get("attempt", 1),
            draft=result.get("draft", ""),
            score=evaluation.score if evaluation else None,
            feedback=evaluation.feedback if evaluation else "",
        )
    ]
    return {
        "topic": topic,
        "summary": result.get("summary", ""),
        "strong_points": result.get("strong_points", []),
        "markdown": result["final_markdown"],
        "output_path": result["output_path"],
        "attempts": attempts,
    }


def generate_blog_legacy(topic: str) -> tuple[str, str, list[DraftAttempt]]:
    attempts: list[DraftAttempt] = []
    feedback = ""
    markdown = ""
    for iteration in range(1, settings.max_draft_iterations + 1):
        markdown = _draft_blog(topic, feedback)
        evaluation = _evaluate_blog(topic, markdown)
        attempts.append(
            DraftAttempt(
                iteration=iteration,
                draft=markdown,
                score=evaluation.score,
                feedback=evaluation.feedback,
            )
        )
        if evaluation.score >= settings.evaluator_pass_threshold:
            break
        feedback = evaluation.feedback

    now = dt.datetime.now(dt.timezone.utc)
    filename = f"{slugify(topic)[:60]}-{now.strftime('%Y%m%d%H%M%S')}.md"
    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", settings.output_dir))
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, filename)
    with open(output_path, "w", encoding="utf-8") as file:
        file.write(f"# {topic}\n\n{markdown}\n")
    return markdown, output_path, attempts
