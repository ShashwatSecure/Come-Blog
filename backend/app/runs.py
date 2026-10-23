import datetime as dt
import os
import uuid

from pydantic import BaseModel, Field

from langchain_core.messages import HumanMessage, SystemMessage
from slugify import slugify

from app.config import settings
from app.graph.llm import get_llm


class BlogEvaluation(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    feedback: str


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
