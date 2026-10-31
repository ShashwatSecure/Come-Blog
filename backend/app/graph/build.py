import time
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    assemble_node,
    plan_node,
    prepare_retry_node,
    publish_node,
    research_node,
    review_node,
    route_after_review,
    write_sections_node,
)
from app.graph.state import BlogState
from app.logging_config import log_event, logging_context


def _logged_node(name, node):
    def run(state, config=None):
        configurable = (config or {}).get("configurable", {})
        started = time.perf_counter()
        with logging_context(node=name, run_id=configurable.get("run_id"), request_id=configurable.get("request_id")):
            log_event(20, "node_started")
            try:
                result = node(state, config)
            except Exception:
                log_event(40, "node_failed", duration_ms=round((time.perf_counter() - started) * 1000, 2), exc_info=True)
                raise
            log_event(20, "node_completed", duration_ms=round((time.perf_counter() - started) * 1000, 2), result_fields=list(result))
            return result

    return run


@lru_cache(maxsize=1)
def build_graph():
    """research -> plan -> write -> assemble(+gates) -> review -> publish, with a bounded rewrite loop."""
    graph = StateGraph(BlogState)
    graph.add_node("research", _logged_node("research", research_node))
    graph.add_node("plan", _logged_node("plan", plan_node))
    graph.add_node("write", _logged_node("write", write_sections_node))
    graph.add_node("assemble", _logged_node("assemble", assemble_node))
    graph.add_node("review", _logged_node("review", review_node))
    graph.add_node("prepare_retry", _logged_node("prepare_retry", prepare_retry_node))
    graph.add_node("publish", _logged_node("publish", publish_node))

    graph.add_edge(START, "research")
    graph.add_edge("research", "plan")
    graph.add_edge("plan", "write")
    graph.add_edge("write", "assemble")
    graph.add_edge("assemble", "review")
    graph.add_conditional_edges("review", route_after_review, {"retry": "prepare_retry", "publish": "publish"})
    graph.add_edge("prepare_retry", "write")
    graph.add_edge("publish", END)
    return graph.compile()
