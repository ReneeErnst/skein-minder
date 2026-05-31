"""Unit tests for SSE event helpers in web/events.py."""

from __future__ import annotations

import json

from skeinminder.graph.state import Recommendation
from skeinminder.ravelry.patterns import PatternSummary
from skeinminder.web.events import _build_result_payload, _sse


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
