from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest

from skeinminder.ravelry.client import RavelryClient
from skeinminder.ravelry.fixture_transport import FixtureTransport
from skeinminder.ravelry.models import RawStashListResponse
from skeinminder.ravelry.normalizer import StashItem, normalize_stash

FIXTURES_DIR = Path(__file__).parent / "fixtures"


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


@pytest.fixture
def normalized_stash() -> list[StashItem]:
    data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
    raw = RawStashListResponse.model_validate(data)
    return normalize_stash(raw.stash)
