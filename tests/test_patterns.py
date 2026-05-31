# tests/test_patterns.py
"""Tests for ravelry.patterns models and normalization."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from skeinminder.ravelry.client import RavelryClient
from skeinminder.ravelry.exceptions import RavelryAPIError
from skeinminder.ravelry.patterns import (
    RawPattern,
    RawPatternFull,
    RawPatternYarnWeight,
    normalize_pattern,
)


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(
            {"library_owned": True, "free": True, "expected_tier": "library"},
            id="library-beats-free",
        ),
        pytest.param(
            {"library_owned": False, "free": True, "expected_tier": "free"},
            id="free-beats-popular",
        ),
        pytest.param(
            {"library_owned": False, "free": False, "expected_tier": "popular"},
            id="non-free-non-owned-is-popular",
        ),
    ],
)
def test_normalize_pattern_tier(scenario: dict[str, object]) -> None:
    raw = RawPatternFull(
        id=1, name="Test", permalink="test-pattern", free=bool(scenario["free"])
    )
    library_ids = {1} if scenario["library_owned"] else set()
    result = normalize_pattern(raw, library_ids=library_ids)
    assert result.tier == scenario["expected_tier"]


def test_normalize_pattern_url() -> None:
    raw = RawPatternFull(
        id=42, name="Hat Pattern", permalink="my-hat-pattern", free=True
    )
    result = normalize_pattern(raw, library_ids=set())
    assert result.url == "https://www.ravelry.com/patterns/library/my-hat-pattern"


def test_normalize_pattern_fields() -> None:
    raw = RawPatternFull(
        id=100,
        name="Mossy Cardigan",
        permalink="mossy-cardigan",
        free=False,
        yardage=1200,
        yardage_max=1800,
        yarn_weight=RawPatternYarnWeight(id=10, name="DK"),
    )
    result = normalize_pattern(raw, library_ids={100})
    assert result.pattern_id == 100
    assert result.name == "Mossy Cardigan"
    assert result.free is False
    assert result.library_owned is True
    assert result.yardage_min == 1200
    assert result.yardage_max == 1800
    assert result.weight_name == "DK"


def test_get_library_pattern_ids_happy_path(fixture_client: RavelryClient) -> None:
    # Fixture has pattern_ids 1001, 1002, and one null entry — null must be excluded
    result = fixture_client.get_library_pattern_ids("[REDACTED]")
    assert result == {1001, 1002}


def test_get_library_pattern_ids_empty_volumes(fixture_client: RavelryClient) -> None:
    empty_response: dict[str, object] = {
        "paginator": {"page": 1, "page_size": 100, "results": 0, "pages": 1},
        "volumes": [],
    }
    with patch.object(fixture_client, "_get", return_value=empty_response):
        result = fixture_client.get_library_pattern_ids("testuser")
    assert result == set()


def test_get_library_pattern_ids_api_failure(fixture_client: RavelryClient) -> None:
    err = RavelryAPIError(500, "/test")
    with patch.object(fixture_client, "_get", side_effect=err):
        result = fixture_client.get_library_pattern_ids("testuser")
    assert result == set()


def test_search_patterns_returns_popular_by_default(
    fixture_client: RavelryClient,
) -> None:
    result = fixture_client.search_patterns(weight="worsted")
    assert len(result) == 5
    assert all(isinstance(p, RawPattern) for p in result)
    assert result[0].id == 2001


def test_search_patterns_free_filter(fixture_client: RavelryClient) -> None:
    result = fixture_client.search_patterns(weight="fingering", availability="free")
    assert len(result) == 4
    assert all(p.free for p in result)


def test_search_patterns_api_failure(fixture_client: RavelryClient) -> None:
    err = RavelryAPIError(500, "/test")
    with patch.object(fixture_client, "_get", side_effect=err):
        result = fixture_client.search_patterns(weight="worsted")
    assert result == []


def test_get_pattern_details_happy_path(fixture_client: RavelryClient) -> None:
    result = fixture_client.get_pattern_details([1001, 1002, 2001])
    assert set(result.keys()) == {1001, 1002, 2001}
    assert result[1001].name == "Simple Stockinette Hat"
    assert result[1001].yardage == 100
    assert result[1001].yarn_weight is not None
    assert result[1001].yarn_weight.name == "DK"


def test_get_pattern_details_partial_response(fixture_client: RavelryClient) -> None:
    # 9999 is not in the fixture; should be absent from result, not raise
    result = fixture_client.get_pattern_details([1001, 9999])
    assert 1001 in result
    assert 9999 not in result


def test_get_pattern_details_empty_input(fixture_client: RavelryClient) -> None:
    result = fixture_client.get_pattern_details([])
    assert result == {}


def test_get_pattern_details_api_failure(fixture_client: RavelryClient) -> None:
    err = RavelryAPIError(500, "/test")
    with patch.object(fixture_client, "_get", side_effect=err):
        result = fixture_client.get_pattern_details([1001, 1002])
    assert result == {}


def test_get_pattern_details_skips_invalid_entry(fixture_client: RavelryClient) -> None:
    bad_response: dict[str, object] = {
        "patterns": {
            "1001": {
                "id": 1001,
                "name": "Good Pattern",
                "permalink": "good",
                "free": True,
            },
            "bad": "not-a-dict",
        }
    }
    with patch.object(fixture_client, "_get", return_value=bad_response):
        result = fixture_client.get_pattern_details([1001])
    assert 1001 in result
    assert result[1001].name == "Good Pattern"


def test_search_patterns_skips_invalid_entry(fixture_client: RavelryClient) -> None:
    bad_response: dict[str, object] = {
        "patterns": [
            {
                "id": 2001,
                "name": "Good Pattern",
                "permalink": "good-pattern",
                "free": False,
            },
            "not-a-dict",
        ],
        "paginator": {"page": 1, "page_size": 20, "results": 2, "page_count": 1},
    }
    with patch.object(fixture_client, "_get", return_value=bad_response):
        result = fixture_client.search_patterns(weight="worsted")
    assert len(result) == 1
    assert result[0].id == 2001
