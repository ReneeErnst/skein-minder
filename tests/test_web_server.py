"""Endpoint tests for the SkeinMinder web server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from skeinminder.web.server import create_app


def test_recommend_returns_stream_id(normalized_stash: list[Any]) -> None:
    app = create_app(normalized_stash, "test_user", use_fixture=True)
    client = TestClient(app)
    response = client.post("/recommend", json={"goal": "knit a hat"})
    assert response.status_code == 200
    assert "stream_id" in response.json()
    assert isinstance(response.json()["stream_id"], str)


def test_replay_404_when_no_last_run(
    normalized_stash: list[Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(normalized_stash, "test_user", use_fixture=True)
    client = TestClient(app)
    response = client.get("/replay")
    assert response.status_code == 404


def test_replay_returns_saved_payload(
    normalized_stash: list[Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    payload = {"type": "result", "recommendations": [], "formatted_output": "test"}
    (tmp_path / "last_run.json").write_text(json.dumps(payload))
    app = create_app(normalized_stash, "test_user", use_fixture=True)
    client = TestClient(app)
    response = client.get("/replay")
    assert response.status_code == 200
    assert response.json()["formatted_output"] == "test"


def test_approve_returns_404_for_unknown_stream(normalized_stash: list[Any]) -> None:
    """Approve returns 404 when the stream_id is not a live run."""
    app = create_app(normalized_stash, "test_user", use_fixture=True)
    client = TestClient(app)
    response = client.post("/approve/nonexistent-id")
    assert response.status_code == 404


def test_cancel_returns_404_for_unknown_stream(normalized_stash: list[Any]) -> None:
    """Cancel returns 404 when the stream_id is not a live run."""
    app = create_app(normalized_stash, "test_user", use_fixture=True)
    client = TestClient(app)
    response = client.post("/cancel/nonexistent-id")
    assert response.status_code == 404


def test_stream_unknown_id_returns_404(normalized_stash: list[Any]) -> None:
    app = create_app(normalized_stash, "test_user", use_fixture=True)
    client = TestClient(app)
    response = client.get("/stream/nonexistent-id")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"level": "warn", "message": "something off"}, id="warn"),
        pytest.param(
            {
                "level": "error",
                "message": "something broke",
                "timestamp": "2026-01-01T00:00:00Z",
            },
            id="error",
        ),
    ],
)
def test_browser_log_accepted(
    normalized_stash: list[Any], payload: dict[str, str]
) -> None:
    app = create_app(normalized_stash, "test_user", use_fixture=True)
    client = TestClient(app)
    response = client.post("/api/logs", json=payload)
    assert response.status_code == 204
