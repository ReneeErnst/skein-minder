from __future__ import annotations

import base64

import httpx
import pytest

from skeinminder.config import ConfigError
from skeinminder.ravelry.client import RavelryClient
from skeinminder.ravelry.exceptions import (
    RavelryAPIError,
    RavelryAuthError,
    RavelryRateLimitError,
)
from skeinminder.ravelry.models import RawStashItem, RawUser


def test_client_requires_credentials_without_transport() -> None:
    with pytest.raises(ConfigError):
        RavelryClient()


def test_client_accepts_transport_without_credentials(
    fixture_client: RavelryClient,
) -> None:
    assert fixture_client is not None


def test_get_current_user_returns_user(fixture_client: RavelryClient) -> None:
    user = fixture_client.get_current_user()
    assert isinstance(user, RawUser)
    assert isinstance(user.username, str)
    assert isinstance(user.id, int)


def test_client_sends_basic_auth_header() -> None:
    captured: list[httpx.Request] = []

    class CapturingTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200, json={"user": {"id": 1, "username": "u", "small_photo_url": None}}
            )

    client = RavelryClient(
        username="myuser", password="mypass", transport=CapturingTransport()
    )
    client.get_current_user()
    assert len(captured) == 1
    auth_header = captured[0].headers.get("authorization", "")
    assert auth_header.startswith("Basic ")
    decoded = base64.b64decode(auth_header[6:]).decode()
    assert decoded == "myuser:mypass"


def test_get_stash_list_returns_items(fixture_client: RavelryClient) -> None:
    items = fixture_client.get_stash_list("testuser")
    assert len(items) == 39
    assert all(isinstance(item, RawStashItem) for item in items)
    assert items[0].id == 15878461
    assert items[0].colorway_name == "7888 Iris"


def test_get_stash_list_fetches_all_pages() -> None:
    """Verifies the client keeps fetching until pages are exhausted."""

    call_count = 0

    class PaginatedTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            page = int(request.url.params.get("page", 1))
            stash_item = {
                "id": page * 100,
                "permalink": None,
                "colorway_name": None,
                "stash_status": None,
                "skeins": 1.0,
                "notes": None,
                "yarn_name": f"Yarn Page {page}",
                "yarn": None,
                "color_family_name": None,
            }
            return httpx.Response(
                200,
                json={
                    "stash": [stash_item],
                    "paginator": {
                        "page": page,
                        "page_size": 1,
                        "results": 2,
                        "pages": 2,
                        "last_page": 2,
                    },
                },
            )

    client = RavelryClient(transport=PaginatedTransport())
    items = client.get_stash_list("anyuser")
    assert call_count == 2
    assert len(items) == 2
    assert items[0].yarn_name == "Yarn Page 1"
    assert items[1].yarn_name == "Yarn Page 2"


def test_get_stash_detail_returns_item(fixture_client: RavelryClient) -> None:
    item = fixture_client.get_stash_detail("testuser", 15952696)
    assert isinstance(item, RawStashItem)
    assert item.id == 15952696
    assert item.colorway_name == "205 Cotton Candy"


def test_get_stash_detail_requests_correct_url() -> None:
    captured: list[httpx.Request] = []

    class CapturingTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                json={
                    "stash": {
                        "id": 42,
                        "permalink": None,
                        "colorway_name": None,
                        "stash_status": None,
                        "skeins": 1.0,
                        "notes": None,
                        "yarn_name": "Test",
                        "yarn": None,
                        "color_family_name": None,
                    }
                },
            )

    client = RavelryClient(transport=CapturingTransport())
    client.get_stash_detail("myuser", 42)
    assert len(captured) == 1
    assert captured[0].url.path == "/people/myuser/stash/42.json"


def _make_status_transport(status: int) -> httpx.BaseTransport:
    class StatusTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={"error": "test"})

    return StatusTransport()


@pytest.mark.parametrize(
    "status_code,exc_class",
    [
        (401, RavelryAuthError),
        (403, RavelryAuthError),
        (429, RavelryRateLimitError),
        (500, RavelryAPIError),
    ],
)
def test_http_error_raises(status_code: int, exc_class: type[Exception]) -> None:
    client = RavelryClient(transport=_make_status_transport(status_code))
    with pytest.raises(exc_class) as exc_info:
        client.get_current_user()
    if isinstance(exc_info.value, RavelryAPIError):
        assert exc_info.value.status_code == status_code


def test_search_patterns_passes_pc_param_when_set() -> None:
    """When pc is provided, it must appear in the request query params."""
    captured: list[httpx.Request] = []

    class CapturingTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json={"patterns": []})

    client = RavelryClient(username="u", password="p", transport=CapturingTransport())
    client.search_patterns("worsted", pc="cardigan")
    client.close()
    assert len(captured) == 1
    assert captured[0].url.params.get("pc") == "cardigan"


def test_search_patterns_omits_pc_when_not_set() -> None:
    """When pc is omitted, the request must not include a pc param."""
    captured: list[httpx.Request] = []

    class CapturingTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json={"patterns": []})

    client = RavelryClient(username="u", password="p", transport=CapturingTransport())
    client.search_patterns("worsted")
    client.close()
    assert "pc" not in captured[0].url.params
