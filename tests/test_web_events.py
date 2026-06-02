"""Unit tests for SSE event helpers in web/events.py."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock, patch

from skeinminder.graph.state import Recommendation
from skeinminder.ravelry.patterns import PatternSummary
from skeinminder.web.events import _build_result_payload, _sse, stream_graph_events


def test_sse_format() -> None:
    result = _sse({"type": "node_start", "node": "supervisor"})
    assert result == 'data: {"type": "node_start", "node": "supervisor"}\n\n'


def test_sse_preserves_all_keys() -> None:
    result = _sse({"type": "result", "recommendations": [], "formatted_output": "hi"})
    parsed = json.loads(result.removeprefix("data: ").strip())
    assert parsed["type"] == "result"
    assert parsed["recommendations"] == []
    assert parsed["formatted_output"] == "hi"


def _make_summary(pattern_id: int, photo_url: str | None = None) -> PatternSummary:
    return PatternSummary(
        pattern_id=pattern_id,
        name="Test Pattern",
        permalink="test-pattern",
        url="https://www.ravelry.com/patterns/library/test-pattern",
        free=True,
        library_owned=False,
        yardage_min=800,
        yardage_max=1200,
        weight_name="Worsted",
        tier="free",
        photo_url=photo_url,
    )


def test_build_result_payload_attaches_photo_url() -> None:
    rec = Recommendation(
        title="Test Project",
        rationale="Good match",
        risks=["Swatch required"],
        yarn_candidate_ids=[101],
        pattern_id=42,
        pattern_name="Pattern A",
        pattern_url="https://www.ravelry.com/patterns/library/a",
    )
    candidate = _make_summary(42, photo_url="https://example.com/photo.jpg")

    payload = _build_result_payload([rec], [candidate], "formatted output text")

    assert payload["type"] == "result"
    assert payload["formatted_output"] == "formatted output text"
    assert len(payload["recommendations"]) == 1
    r = payload["recommendations"][0]
    assert r["photo_url"] == "https://example.com/photo.jpg"
    assert r["pattern_id"] == 42
    assert r["stash_ids"] == [101]
    assert r["rationale"] == "Good match"
    assert r["risks"] == ["Swatch required"]


def test_build_result_payload_photo_url_none_when_no_pattern() -> None:
    rec = Recommendation(
        title="Abstract Project",
        rationale="Good",
        risks=[],
        yarn_candidate_ids=[1],
        pattern_id=None,
    )
    payload = _build_result_payload([rec], [], "output")
    assert payload["recommendations"][0]["photo_url"] is None
    assert payload["recommendations"][0]["pattern_id"] is None


def test_build_result_payload_photo_url_none_when_candidate_missing() -> None:
    rec = Recommendation(
        title="Test",
        rationale="Rationale",
        risks=[],
        yarn_candidate_ids=[1],
        pattern_id=99,
        pattern_name="Missing Pattern",
        pattern_url="https://www.ravelry.com/patterns/library/missing",
    )
    # No matching candidate in list
    payload = _build_result_payload([rec], [_make_summary(42)], "output")
    assert payload["recommendations"][0]["photo_url"] is None


def test_build_result_payload_empty_recommendations() -> None:
    payload = _build_result_payload([], [], "No recommendations.")
    assert payload["recommendations"] == []
    assert payload["formatted_output"] == "No recommendations."


def _run_stream(
    goal: str, stash: list[Any], username: str, use_fixture: bool
) -> list[dict[str, Any]]:
    """Collect all events from stream_graph_events synchronously."""

    async def _collect() -> list[dict[str, Any]]:
        events = []
        async for ev in stream_graph_events(
            goal, stash, username, use_fixture, thread_id="test-thread"
        ):
            events.append(json.loads(ev.removeprefix("data: ").strip()))
        return events

    return asyncio.run(_collect())


async def _fake_astream(*args: Any, **kwargs: Any) -> Any:
    yield {
        "event": "on_chain_start",
        "name": "supervisor",
        "metadata": {"langgraph_node": "supervisor"},
        "data": {},
    }
    yield {
        "event": "on_chain_end",
        "name": "supervisor",
        "metadata": {"langgraph_node": "supervisor"},
        "data": {"output": {"mode": "project_first"}},
    }
    yield {
        "event": "on_chain_end",
        "name": "recommend",
        "metadata": {"langgraph_node": "recommend"},
        "data": {
            "output": {
                "recommendations": [
                    Recommendation(
                        title="Test Hat",
                        rationale="Great",
                        risks=[],
                        yarn_candidate_ids=[1],
                        pattern_id=None,
                        pattern_name=None,
                        pattern_url=None,
                    )
                ]
            }
        },
    }
    yield {
        "event": "on_chain_end",
        "name": "format_output",
        "metadata": {"langgraph_node": "format_output"},
        "data": {"output": {"formatted_output": "Project recommendations\n"}},
    }


def test_stream_graph_events_emits_node_and_result_events(
    normalized_stash: list[Any],
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    monkeypatch.chdir(tmp_path)
    mock_graph = MagicMock()
    mock_graph.astream_events = _fake_astream
    mock_graph.get_state.return_value.next = ()

    with patch("skeinminder.web.events.build_graph", return_value=mock_graph):
        events = _run_stream("test goal", normalized_stash, "test_user", True)

    types = [e["type"] for e in events]
    assert "node_start" in types
    assert "node_complete" in types
    assert "result" in types

    result_event = next(e for e in events if e["type"] == "result")
    assert result_event["formatted_output"] == "Project recommendations\n"
    assert len(result_event["recommendations"]) == 1


def test_stream_graph_events_saves_last_run_json(
    normalized_stash: list[Any],
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    monkeypatch.chdir(tmp_path)
    mock_graph = MagicMock()
    mock_graph.astream_events = _fake_astream
    mock_graph.get_state.return_value.next = ()

    with patch("skeinminder.web.events.build_graph", return_value=mock_graph):
        _run_stream("test goal", normalized_stash, "test_user", True)

    last_run = json.loads((tmp_path / "last_run.json").read_text())
    assert last_run["type"] == "result"


def test_stream_graph_events_emits_error_on_exception(
    normalized_stash: list[Any],
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    monkeypatch.chdir(tmp_path)

    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("graph exploded")
        yield  # make it an async generator

    mock_graph = MagicMock()
    mock_graph.astream_events = _boom
    mock_graph.get_state.return_value.next = ()

    with patch("skeinminder.web.events.build_graph", return_value=mock_graph):
        events = _run_stream("test goal", normalized_stash, "test_user", True)

    assert any(e["type"] == "error" for e in events)
    error_event = next(e for e in events if e["type"] == "error")
    assert "graph exploded" in error_event["message"]


def test_stream_graph_events_yields_pause_then_cancelled(
    normalized_stash: list[Any],
) -> None:
    """Graph pause + cancel: SSE emits 'pause' then 'cancelled'."""
    loop = asyncio.new_event_loop()
    resume_future: asyncio.Future[bool] = loop.create_future()
    resume_future.set_result(False)  # simulate immediate cancel

    async def run() -> list[dict[str, Any]]:
        async def fake_invoke(
            graph: Any,
            state: Any,
            *,
            config: Any,
            goal: str,
            event_queue: asyncio.Queue[tuple[str, Any]],
            resume_future: asyncio.Future[bool] | None,
        ) -> None:
            await event_queue.put(
                ("interrupted", {"message": "Low confidence.", "candidate_count": 0})
            )
            decision = await resume_future if resume_future is not None else False
            if not decision:
                await event_queue.put(("cancelled", None))
            else:
                await event_queue.put(("done", None))

        with patch("skeinminder.web.events._invoke_graph", side_effect=fake_invoke):
            events: list[dict[str, Any]] = []
            async for ev in stream_graph_events(
                "a cozy hat",
                normalized_stash,
                "testuser",
                True,
                thread_id="test-pause",
                resume_future=resume_future,
            ):
                events.append(json.loads(ev.removeprefix("data: ").strip()))
        return events

    events = loop.run_until_complete(run())
    loop.close()

    event_types = [e.get("type") for e in events]
    assert "pause" in event_types
    assert "cancelled" in event_types
    assert event_types.index("pause") < event_types.index("cancelled")
