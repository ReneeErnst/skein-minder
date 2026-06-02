"""Builds the compiled LangGraph for SkeinMinder project recommendations."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from skeinminder.graph import nodes
from skeinminder.graph.state import GraphState


def build_graph(checkpointer: Any | None = None) -> CompiledStateGraph[GraphState]:
    """Build and compile the recommendation graph.

    Nodes are referenced via the `nodes` module object so that
    patch('skeinminder.graph.nodes.<node>') works correctly in tests.
    Compiles with a MemorySaver checkpointer by default so that interrupt()
    works on the low-confidence path. Pass a custom checkpointer for tests
    that need a shared instance.
    """
    workflow: StateGraph[GraphState] = StateGraph(GraphState)

    workflow.add_node("supervisor", nodes.supervisor)
    workflow.add_node("project_first_filter", nodes.project_first_filter)
    workflow.add_node("stash_first_filter", nodes.stash_first_filter)
    workflow.add_node("assess_filter_quality", nodes.assess_filter_quality)
    workflow.add_node("low_confidence_output", nodes.low_confidence_output)
    workflow.add_node("pattern_search", nodes.pattern_search)
    workflow.add_node("recommend", nodes.recommend)
    workflow.add_node("format_output", nodes.format_output)

    workflow.set_entry_point("supervisor")
    workflow.add_conditional_edges(
        "supervisor",
        lambda state: state["mode"],
        {
            "project_first": "project_first_filter",
            "stash_first": "stash_first_filter",
        },
    )
    workflow.add_edge("project_first_filter", "assess_filter_quality")
    workflow.add_edge("stash_first_filter", "assess_filter_quality")
    workflow.add_conditional_edges(
        "assess_filter_quality",
        lambda state: state["filter_confidence"],
        {"high": "pattern_search", "low": "low_confidence_output"},
    )
    workflow.add_conditional_edges(
        "low_confidence_output",
        lambda state: "pattern_search" if state["force_recommend"] else END,
        {"pattern_search": "pattern_search", END: END},
    )
    workflow.add_edge("pattern_search", "recommend")
    workflow.add_edge("recommend", "format_output")
    workflow.add_edge("format_output", END)

    cp = checkpointer if checkpointer is not None else MemorySaver()
    return workflow.compile(checkpointer=cp)
