import inspect
import logging
import time
from functools import lru_cache

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app import domain
from app.graph.nodes import (
    assemble_node,
    human_plan_node,
    human_review_node,
    plan_node,
    prepare_retry_node,
    publish_node,
    research_node,
    review_node,
    route_after_human,
    route_after_review,
    write_sections_node,
)
from app.graph.state import BlogState
from app.logging_config import log_event, logging_context

# Paused (human-in-the-loop) runs keep their state here, keyed by thread_id = job id.
# Domain models are allow-listed so the checkpoint serializer may restore them.
_CHECKPOINT_TYPES = [
    (domain.__name__, name) for name, cls in vars(domain).items()
    if inspect.isclass(cls) and issubclass(cls, BaseModel) and cls.__module__ == domain.__name__
]
CHECKPOINTER = InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINT_TYPES))


def forget_run(thread_id: str) -> None:
    CHECKPOINTER.delete_thread(thread_id)


def _logged_node(name, node):
    def run(state, config=None):
        configurable = (config or {}).get("configurable", {})
        started = time.perf_counter()
        with logging_context(node=name, run_id=configurable.get("run_id"), request_id=configurable.get("request_id")):
            log_event(logging.INFO, "node_started")
            try:
                result = node(state, config)
            except GraphBubbleUp:
                log_event(logging.INFO, "node_paused_for_human")
                raise
            except Exception:
                log_event(logging.ERROR, "node_failed", duration_ms=round((time.perf_counter() - started) * 1000, 2), exc_info=True)
                raise
            log_event(
                logging.INFO, "node_completed",
                duration_ms=round((time.perf_counter() - started) * 1000, 2), result_fields=list(result),
            )
            return result

    return run


@lru_cache(maxsize=2)
def build_graph(checkpointed: bool = False):
    """research -> plan -> [human] -> write -> assemble(+gates) -> review -> [human] -> publish, with a bounded rewrite loop.

    The human steps are no-ops unless state.interactive is set, which requires checkpointed=True so the run can pause.
    """
    graph = StateGraph(BlogState)
    graph.add_node("research", _logged_node("research", research_node))
    graph.add_node("plan", _logged_node("plan", plan_node))
    graph.add_node("human_plan", _logged_node("human_plan", human_plan_node))
    graph.add_node("write", _logged_node("write", write_sections_node))
    graph.add_node("assemble", _logged_node("assemble", assemble_node))
    graph.add_node("review", _logged_node("review", review_node))
    graph.add_node("human_review", _logged_node("human_review", human_review_node))
    graph.add_node("prepare_retry", _logged_node("prepare_retry", prepare_retry_node))
    graph.add_node("publish", _logged_node("publish", publish_node))

    graph.add_edge(START, "research")
    graph.add_edge("research", "plan")
    graph.add_edge("plan", "human_plan")
    graph.add_edge("human_plan", "write")
    graph.add_edge("write", "assemble")
    graph.add_edge("assemble", "review")
    graph.add_conditional_edges("review", route_after_review, {"retry": "prepare_retry", "publish": "publish", "human": "human_review"})
    graph.add_conditional_edges("human_review", route_after_human, {"retry": "prepare_retry", "publish": "publish"})
    graph.add_edge("prepare_retry", "write")
    graph.add_edge("publish", END)
    return graph.compile(checkpointer=CHECKPOINTER if checkpointed else None)
