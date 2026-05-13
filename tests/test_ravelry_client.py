from __future__ import annotations

import base64

import httpx
import pytest

from skeinminder.config import ConfigError
from skeinminder.ravelry.client import RavelryClient
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
    assert user.username == "testuser"
    assert user.id == 99999


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
