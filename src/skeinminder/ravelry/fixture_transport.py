"""httpx transport that serves local fixture JSON files instead of network requests.

Lives in src/ so the --fixture CLI mode (Phase 6b+) can import it from
production code as well as from tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

_FIXTURES_DIR = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures"


class FixtureTransport(httpx.BaseTransport):
    """Routes Ravelry API requests to local fixture JSON files."""

    def __init__(self) -> None:
        self._current_user = json.loads(
            (_FIXTURES_DIR / "current_user.json").read_text()
        )
        self._stash_list = json.loads((_FIXTURES_DIR / "stash_list.json").read_text())
        self._stash_detail: list[dict[str, object]] = json.loads(
            (_FIXTURES_DIR / "stash_detail_sample.json").read_text()
        )
        self._library_search_patterns = json.loads(
            (_FIXTURES_DIR / "library_search_patterns.json").read_text()
        )
        self._pattern_search_free = json.loads(
            (_FIXTURES_DIR / "pattern_search_free.json").read_text()
        )
        self._pattern_search_popular = json.loads(
            (_FIXTURES_DIR / "pattern_search_popular.json").read_text()
        )
        self._pattern_detail = json.loads(
            (_FIXTURES_DIR / "pattern_detail.json").read_text()
        )
        self._yarn_details = json.loads(
            (_FIXTURES_DIR / "yarn_details.json").read_text()
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/current_user.json":
            return httpx.Response(200, json=self._current_user)
        if path == "/patterns.json":
            return httpx.Response(200, json=self._pattern_detail)
        if path == "/patterns/search.json":
            params = dict(request.url.params)
            if params.get("availability") == "free":
                return httpx.Response(200, json=self._pattern_search_free)
            return httpx.Response(200, json=self._pattern_search_popular)
        if "/library/search.json" in path:
            return httpx.Response(200, json=self._library_search_patterns)
        if "/list.json" in path:
            return httpx.Response(200, json=self._stash_list)
        if "/stash/" in path and path.endswith(".json"):
            return httpx.Response(200, json={"stash": self._stash_detail[0]})
        if path == "/yarns.json":
            return httpx.Response(200, json=self._yarn_details)
        return httpx.Response(404, json={"error": "fixture not found"})
