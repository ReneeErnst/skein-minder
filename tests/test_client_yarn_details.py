"""Tests for RavelryClient.get_yarn_details."""

from __future__ import annotations

from skeinminder.ravelry.client import RavelryClient
from skeinminder.ravelry.fixture_transport import FixtureTransport


def test_get_yarn_details_returns_fiber_data() -> None:
    client = RavelryClient(
        username="test",
        password="test",
        transport=FixtureTransport(),
    )
    result = client.get_yarn_details([110466, 66891])

    assert 110466 in result
    assert 66891 in result
    wool_fibers = result[110466].yarn_fibers
    assert len(wool_fibers) == 1
    assert wool_fibers[0].fiber_category is not None
    assert wool_fibers[0].fiber_category.name == "Wool"


def test_get_yarn_details_returns_empty_dict_on_empty_input() -> None:
    client = RavelryClient(
        username="test",
        password="test",
        transport=FixtureTransport(),
    )
    result = client.get_yarn_details([])
    assert result == {}
