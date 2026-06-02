"""LangGraph → SSE bridge for the SkeinMinder web UI."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from langfuse.decorators import langfuse_context, observe
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

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


@observe(name="skeinminder-recommend")
async def _invoke_graph(
    graph: Any,
    initial_state: GraphState,
    *,
    config: dict[str, Any],
    goal: str,
    event_queue: asyncio.Queue[tuple[str, Any]],
    resume_future: asyncio.Future[bool] | None,
) -> None:
    """Run the complete LangGraph lifecycle under a single Langfuse trace.

    Handles initial run, optional interrupt pause, and optional resume in one call.
    Awaiting resume_future here (not in stream_graph_events) keeps the full session
    under one trace and eliminates the need for a second _invoke_graph call on resume.

    Signals put on event_queue:
      ("event", event)       — raw LangGraph event to forward to SSE
      ("interrupted", dict)  — graph paused; dict is the interrupt() payload
      ("cancelled", None)    — user declined or client disconnected (future -> False)
      ("done", None)         — graph completed (normal completion or after resume)
      ("error", exc)         — unhandled exception
    """
    langfuse_context.update_current_trace(
        input={"user_goal": goal},
        tags=["web"],
    )
    try:
        async for event in graph.astream_events(
            initial_state, config=config, version="v2"
        ):
            await event_queue.put(("event", event))

        state = graph.get_state(config)
        if not state.next:
            await event_queue.put(("done", None))
            return

        interrupt_payload: dict[str, Any] = {}
        for task in state.tasks:
            for interrupt_val in task.interrupts:
                interrupt_payload = interrupt_val.value
                break
        await event_queue.put(("interrupted", interrupt_payload))

        decision = False
        if resume_future is not None:
            decision = await resume_future

        if not decision:
            await event_queue.put(("cancelled", None))
            return

        async for event in graph.astream_events(
            Command(resume=True), config=config, version="v2"
        ):
            await event_queue.put(("event", event))

        await event_queue.put(("done", None))

    except Exception as exc:
        await event_queue.put(("error", exc))


async def stream_graph_events(
    goal: str,
    stash: list[StashItem],
    ravelry_username: str,
    use_fixture: bool,
    *,
    thread_id: str,
    resume_future: asyncio.Future[bool] | None = None,
) -> AsyncGenerator[str, None]:
    """Run the LangGraph pipeline and yield SSE-formatted event strings.

    The SSE connection stays open if the graph pauses at interrupt — _invoke_graph
    blocks on resume_future while this generator continues to await queue.get().
    Emits node_start/node_complete for known nodes, 'pause' on interrupt, 'cancelled'
    on decline or disconnect, and a final 'result' event on success.
    Saves the result payload to last_run.json for /replay.
    """
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)

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

    event_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    recommendations: list[Recommendation] = []
    pattern_candidates: list[PatternSummary] = []
    formatted_output = ""

    graph_task = asyncio.create_task(
        _invoke_graph(
            graph,
            initial_state,
            config=config,
            goal=goal,
            event_queue=event_queue,
            resume_future=resume_future,
        )
    )

    while True:
        kind, payload = await event_queue.get()

        if kind == "done":
            break
        if kind == "cancelled":
            yield _sse({"type": "cancelled", "message": "Run cancelled."})
            await graph_task
            return
        if kind == "error":
            yield _sse({"type": "error", "message": str(payload)})
            await graph_task
            return
        if kind == "interrupted":
            yield _sse({"type": "pause", **payload})
            continue

        # kind == "event": raw LangGraph event
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
