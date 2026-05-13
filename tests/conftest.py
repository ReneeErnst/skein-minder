from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest

from skeinminder.ravelry.client import RavelryClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class FixtureTransport(httpx.BaseTransport):
    """Routes requests to local fixture JSON files instead of the network."""

    def __init__(self) -> None:
        self._current_user = json.loads(
            (FIXTURES_DIR / "current_user.json").read_text()
        )
        self._stash_list = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
        self._stash_detail: list[dict[str, object]] = json.loads(
            (FIXTURES_DIR / "stash_detail_sample.json").read_text()
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/current_user.json":
            return httpx.Response(200, json=self._current_user)
        if "/list.json" in path:
            return httpx.Response(200, json=self._stash_list)
        if "/stash/" in path and path.endswith(".json"):
            return httpx.Response(200, json={"stash": self._stash_detail[0]})
        return httpx.Response(404, json={"error": "fixture not found"})


@pytest.fixture
def fixture_transport() -> FixtureTransport:
    return FixtureTransport()


@pytest.fixture
def fixture_client(
    fixture_transport: FixtureTransport,
) -> Generator[RavelryClient, None, None]:
    client = RavelryClient(transport=fixture_transport)
    yield client
    client.close()
