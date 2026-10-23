from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.graph.nodes import (
    accept_section,
    evaluator_node,
    orchestrator_node,
    prepare_retry,
    reducer_node,
    route_after_evaluation,
    worker_node,
    write_markdown_node,
)
from app.graph.state import BlogState, SectionWorkState


def _fan_out_to_workers(state: BlogState) -> list[Send]:
    """Dynamic fan-out: one Send per planned section, each carrying its own
    isolated SectionWorkState so parallel branches don't share mutable state
    beyond the reducer-merged keys (drafts/evaluations/accepted_ids)."""
    return [
        Send("worker", SectionWorkState(topic=state.topic, section=section).model_dump())
        for section in state.sections
    ]


def _join_check(state: BlogState) -> str:
    """Fan-in gate: only proceed to reducer once every planned section has
    been accepted. LangGraph re-runs this after each branch merges in."""
    if set(state.accepted_ids) >= {s.id for s in state.sections}:
        return "reducer"
    return END


def build_graph():
    section_graph = StateGraph(SectionWorkState)
    section_graph.add_node("worker", worker_node)
    section_graph.add_node("evaluator", evaluator_node)
    section_graph.add_node("prepare_retry", prepare_retry)
    section_graph.add_node("accept_section", accept_section)

    section_graph.add_edge(START, "worker")
    section_graph.add_edge("worker", "evaluator")
    section_graph.add_conditional_edges(
        "evaluator", route_after_evaluation, {"retry": "prepare_retry", "accept": "accept_section"}
    )
    section_graph.add_edge("prepare_retry", "worker")
    section_graph.add_edge("accept_section", END)
    section_subgraph = section_graph.compile()

    def run_section_subgraph(state: SectionWorkState, config: dict | None = None) -> dict:
        """Invokes the worker/evaluator subgraph and returns only the keys
        that the parent BlogState knows how to merge (drafts, evaluations,
        accepted_ids). The subgraph's own per-branch fields (topic, section,
        attempt, ...) must never leak back into parent state: with dynamic
        Send() fan-out, every parallel branch would then write to the same
        unreduced parent channel (e.g. 'topic') in the same step, which
        LangGraph rejects (InvalidUpdateError - only Annotated/reduced keys
        may receive more than one value per step)."""
        result = section_subgraph.invoke(state, config=config)
        return {
            "drafts": result["drafts"],
            "evaluations": result["evaluations"],
            "accepted_ids": result["accepted_ids"],
        }

    graph = StateGraph(BlogState)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("worker", run_section_subgraph)
    graph.add_node("reducer", reducer_node)
    graph.add_node("write_markdown", write_markdown_node)

    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges("orchestrator", _fan_out_to_workers, ["worker"])
    graph.add_conditional_edges("worker", _join_check, ["reducer", END])
    graph.add_edge("reducer", "write_markdown")
    graph.add_edge("write_markdown", END)

    return graph.compile()
