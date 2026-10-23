import uuid
import time

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.graph.build import build_graph
from app.graph.llm import get_llm
from app.graph.state import BlogState
from app.logging_config import logger


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
