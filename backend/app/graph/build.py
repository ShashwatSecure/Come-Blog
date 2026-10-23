import time

from langgraph.graph import END, START, StateGraph
from app.graph.nodes import (
    analyze_topic_node,
    evaluate_blog_node,
    generate_blog_node,
    prepare_blog_retry_node,
    route_after_blog_evaluation,
    write_markdown_node,
)
from app.graph.state import BlogState
from app.logging_config import logger


def _logged_node(name, node):
    def run(state, config=None):
        configurable = (config or {}).get("configurable", {})
        started = time.perf_counter()
        fields = {"event": "node_started", "node": name, "run_id": configurable.get("run_id"), "request_id": configurable.get("request_id")}
        logger.info("node_started", extra=fields)
        try:
            result = node(state, config)
        except Exception:
            logger.exception("node_failed", extra={**fields, "event": "node_failed", "duration_ms": round((time.perf_counter() - started) * 1000, 2)})
            raise
        logger.info("node_completed", extra={**fields, "event": "node_completed", "duration_ms": round((time.perf_counter() - started) * 1000, 2)})
        return result

    return run


def build_graph():
    graph = StateGraph(BlogState)
    graph.add_node("orchestrator", _logged_node("orchestrator", analyze_topic_node))
    graph.add_node("generator", _logged_node("generator", generate_blog_node))
    graph.add_node("evaluator", _logged_node("evaluator", evaluate_blog_node))
    graph.add_node("prepare_retry", _logged_node("prepare_retry", prepare_blog_retry_node))
    graph.add_node("writer", _logged_node("writer", write_markdown_node))

    graph.add_edge(START, "orchestrator")
    graph.add_edge("orchestrator", "generator")
    graph.add_edge("generator", "evaluator")
    graph.add_conditional_edges("evaluator", route_after_blog_evaluation, {"retry": "prepare_retry", "writer": "writer"})
    graph.add_edge("prepare_retry", "generator")
    graph.add_edge("writer", END)

    return graph.compile()
