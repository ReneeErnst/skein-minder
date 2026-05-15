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
from skeinminder.ravelry.models import RawUser


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
    from skeinminder.ravelry.models import RawStashItem

    items = fixture_client.get_stash_list("testuser")
    assert len(items) == 1379
    assert all(isinstance(item, RawStashItem) for item in items)
    assert items[0].id == 15952696
    assert items[0].colorway_name == "205 Cotton Candy"


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
    from skeinminder.ravelry.models import RawStashItem

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


def test_401_raises_auth_error() -> None:
    client = RavelryClient(transport=_make_status_transport(401))
    with pytest.raises(RavelryAuthError):
        client.get_current_user()


def test_403_raises_auth_error() -> None:
    client = RavelryClient(transport=_make_status_transport(403))
    with pytest.raises(RavelryAuthError):
        client.get_current_user()


def test_429_raises_rate_limit_error() -> None:
    client = RavelryClient(transport=_make_status_transport(429))
    with pytest.raises(RavelryRateLimitError):
        client.get_current_user()


def test_500_raises_api_error() -> None:
    client = RavelryClient(transport=_make_status_transport(500))
    with pytest.raises(RavelryAPIError) as exc_info:
        client.get_current_user()
    assert exc_info.value.status_code == 500
