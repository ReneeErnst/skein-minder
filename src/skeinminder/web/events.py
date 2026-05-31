"""LangGraph → SSE bridge for the SkeinMinder web UI."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from langfuse.decorators import langfuse_context, observe

from skeinminder.graph.graph import build_graph
from skeinminder.graph.state import GraphState, Recommendation
from skeinminder.ravelry.normalizer import StashItem
from skeinminder.ravelry.patterns import PatternSummary

LAST_RUN_PATH = Path("last_run.json")

_KNOWN_NODES = frozenset(
    {
        "supervisor",
        "project_first_filter",
        "stash_first_filter",
        "assess_filter_quality",
        "low_confidence_output",
        "pattern_search",
        "recommend",
        "format_output",
    }
)


def _sse(data: dict[str, Any]) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


def _build_result_payload(
    recommendations: list[Recommendation],
    pattern_candidates: list[PatternSummary],
    formatted_output: str,
) -> dict[str, Any]:
    """Build the result SSE event payload.

    Joins each Recommendation with its matching PatternSummary (keyed by
    pattern_id) to attach photo_url. Returns None for photo_url when the
    pattern has no candidate or the candidate has no photo.
    """
    pattern_by_id = {p.pattern_id: p for p in pattern_candidates}
    enriched: list[dict[str, Any]] = []
    for rec in recommendations:
        photo_url: str | None = None
        if rec.pattern_id is not None:
            candidate = pattern_by_id.get(rec.pattern_id)
            if candidate is not None:
                photo_url = candidate.photo_url
        enriched.append(
            {
                "pattern_id": rec.pattern_id,
                "pattern_name": rec.pattern_name,
                "pattern_url": rec.pattern_url,
                "photo_url": photo_url,
                "stash_ids": rec.yarn_candidate_ids,
                "title": rec.title,
                "rationale": rec.rationale,
                "risks": rec.risks,
            }
        )
    return {
        "type": "result",
        "recommendations": enriched,
        "formatted_output": formatted_output,
    }


@observe(name="skeinminder-recommend")  # type: ignore[untyped-decorator]
async def _invoke_graph(
    graph: Any,
    initial_state: GraphState,
    *,
    goal: str,
    event_queue: "asyncio.Queue[tuple[str, Any]]",
) -> None:
    """Run the LangGraph pipeline inside a Langfuse trace, feeding events to a queue.

    Creates the root 'skeinminder-recommend' trace so all node @observe calls
    nest under it as spans rather than creating separate top-level traces. Signals
    completion with a ("done", None) sentinel, or ("error", exc) on failure.
    """
    langfuse_context.update_current_trace(
        input={"user_goal": goal},
        tags=["web"],
    )
    try:
        async for event in graph.astream_events(initial_state, version="v2"):
            await event_queue.put(("event", event))
    except Exception as exc:
        await event_queue.put(("error", exc))
    finally:
        await event_queue.put(("done", None))


async def stream_graph_events(
    goal: str,
    stash: list[StashItem],
    ravelry_username: str,
    use_fixture: bool,
) -> AsyncGenerator[str, None]:
    """Run the LangGraph pipeline and yield SSE-formatted event strings.

    Emits node_start/node_complete for each known graph node as it executes,
    then a final result event with enriched recommendations. Saves the result
    payload to last_run.json for /replay. Emits an error event on failure.

    Note: if the low_confidence_output node is reached (unusual with fixture
    data), it will block waiting for stdin input — this is a Phase 9 concern.
    """
    initial_state: GraphState = {
        "user_input": goal,
        "normalized_stash": stash,
        "filtered_stash": [],
        "mode": "",
        "user_goal": None,
        "stash_filter": None,
        "recommendations": None,
        "requires_approval": False,
        "formatted_output": None,
        "filter_confidence": "",
        "force_recommend": False,
        "ravelry_username": ravelry_username,
        "use_fixture": use_fixture,
        "pattern_candidates": [],
    }

    graph = build_graph()
    event_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    recommendations: list[Recommendation] = []
    pattern_candidates: list[PatternSummary] = []
    formatted_output = ""

    graph_task = asyncio.create_task(
        _invoke_graph(graph, initial_state, goal=goal, event_queue=event_queue)
    )

    while True:
        kind, payload = await event_queue.get()
        if kind == "done":
            break
        if kind == "error":
            yield _sse({"type": "error", "message": str(payload)})
            await graph_task
            return

        event = payload
        event_type: str = event.get("event", "")
        node: str = event.get("metadata", {}).get("langgraph_node", "")

        if node not in _KNOWN_NODES:
            continue

        if event_type == "on_chain_start":
            yield _sse({"type": "node_start", "node": node})
        elif event_type == "on_chain_end":
            yield _sse({"type": "node_complete", "node": node})
            output: Any = event.get("data", {}).get("output", {})
            if isinstance(output, dict):
                if "recommendations" in output:
                    recommendations = output["recommendations"]
                if "pattern_candidates" in output:
                    pattern_candidates = output["pattern_candidates"]
                if output.get("formatted_output"):
                    formatted_output = output["formatted_output"]

    await graph_task  # ensure Langfuse trace is finalized before yielding result

    result_payload = _build_result_payload(
        recommendations, pattern_candidates, formatted_output
    )
    yield _sse(result_payload)
    try:
        LAST_RUN_PATH.write_text(json.dumps(result_payload))
    except OSError:
        pass
