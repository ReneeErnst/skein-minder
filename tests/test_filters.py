from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest

from skeinminder.graph.nodes import project_first_filter, stash_first_filter
from skeinminder.graph.state import GraphState, StashFilter
from skeinminder.ravelry.normalizer import (
    MatchScore,
    ProjectQuantity,
    StashItem,
    WeightCategory,
)


def _make_item(
    *,
    stash_id: int = 1,
    yarn_id: int = 100,
    colorway: str | None = None,
    weight: WeightCategory = WeightCategory.WORSTED,
    yards_total: float = 1000.0,
    color_family: str | None = None,
    project_quantity: ProjectQuantity = ProjectQuantity.SWEATER,
    fiber: list[str] | None = None,
    is_weaving_yarn: bool = False,
    added_date: datetime | None = None,
) -> StashItem:
    return StashItem(
        stash_id=stash_id,
        yarn_id=yarn_id,
        brand="Test Brand",
        yarn_name="Test Yarn",
        colorway=colorway,
        weight_category=weight,
        fiber=fiber if fiber is not None else ["Wool"],
        color_family=color_family,
        skeins=5.0,
        yards_per_skein=yards_total / 5.0,
        yards_total=yards_total,
        grams_total=None,
        notes=None,
        project_quantity=project_quantity,
        is_weaving_yarn=is_weaving_yarn,
        added_date=added_date,
    )


def _make_state(
    *,
    stash: list[StashItem],
    user_goal: str | None = None,
    stash_filter: StashFilter | None = None,
) -> GraphState:
    return GraphState(
        user_input="",
        mode="project_first" if user_goal is not None else "stash_first",
        user_goal=user_goal,
        stash_filter=stash_filter,
        normalized_stash=stash,
        filtered_stash=[],
        recommendations=None,
        requires_approval=False,
        formatted_output=None,
        filter_confidence="",
        force_recommend=False,
        ravelry_username="",
        use_fixture=False,
        pattern_candidates=[],
    )


# --- project_first_filter ---


def test_project_first_filter_excludes_low_yardage_for_sweater_goals() -> None:
    # Distinct yarn_ids — group total equals per-item total.
    # DK threshold is 900 yds; items with < 900 yds are excluded.
    items = [
        _make_item(stash_id=1, yarn_id=1, weight=WeightCategory.DK, yards_total=1000.0),
        _make_item(stash_id=2, yarn_id=2, weight=WeightCategory.DK, yards_total=400.0),
        _make_item(stash_id=3, yarn_id=3, weight=WeightCategory.DK, yards_total=100.0),
    ]
    result = project_first_filter(
        _make_state(stash=items, user_goal="I want a cardigan")
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert 1 in ids
    assert 2 not in ids
    assert 3 not in ids


def test_project_first_filter_groups_same_yarn_colorway_for_sweater_check() -> None:
    # 6 × 200 yd DK, same yarn_id and colorway → group total 1200 yds ≥ 900 → all pass
    items = [
        _make_item(stash_id=i, yarn_id=5, weight=WeightCategory.DK, yards_total=200.0)
        for i in range(1, 7)
    ]
    result = project_first_filter(
        _make_state(stash=items, user_goal="I want a cardigan")
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert set(ids) == {1, 2, 3, 4, 5, 6}


def test_project_first_filter_treats_different_colorways_as_independent_groups() -> (
    None
):
    # 3 × 200 yd DK colorway A + 3 × 200 yd DK colorway B
    # Each group = 600 yds < 900 (DK threshold) → all 6 excluded
    items = [
        _make_item(
            stash_id=i,
            yarn_id=5,
            weight=WeightCategory.DK,
            yards_total=200.0,
            colorway="Colorway A",
        )
        for i in range(1, 4)
    ] + [
        _make_item(
            stash_id=i,
            yarn_id=5,
            weight=WeightCategory.DK,
            yards_total=200.0,
            colorway="Colorway B",
        )
        for i in range(4, 7)
    ]
    result = project_first_filter(
        _make_state(stash=items, user_goal="I want a cardigan")
    )
    assert result["filtered_stash"] == []


def test_project_first_filter_weight_excludes_mismatches() -> None:
    items = [
        _make_item(stash_id=1, weight=WeightCategory.WORSTED),
        _make_item(stash_id=2, weight=WeightCategory.LACE),  # mismatch vs worsted
    ]
    result = project_first_filter(
        _make_state(stash=items, user_goal="I want a worsted cardigan")
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert 1 in ids
    assert 2 not in ids


def test_project_first_filter_includes_adjacent_weight() -> None:
    items = [
        _make_item(stash_id=1, weight=WeightCategory.WORSTED),
        _make_item(stash_id=2, weight=WeightCategory.ARAN),  # adjacent to worsted
    ]
    result = project_first_filter(
        _make_state(stash=items, user_goal="I want a worsted sweater")
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert 1 in ids
    assert 2 in ids


def test_project_first_filter_non_sweater_goal_passes_accessory() -> None:
    items = [
        _make_item(stash_id=1, project_quantity=ProjectQuantity.SWEATER),
        _make_item(stash_id=2, project_quantity=ProjectQuantity.ACCESSORY),
    ]
    result = project_first_filter(_make_state(stash=items, user_goal="I want a hat"))
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert 1 in ids
    assert 2 in ids  # accessory passes for non-sweater goals


@pytest.mark.parametrize(
    "user_goal",
    [
        "I want a cardigan",
        "I want a scarf",  # excluded unconditionally, not just for sweaters
    ],
)
def test_project_first_filter_excludes_weaving_yarn(user_goal: str) -> None:
    items = [
        _make_item(stash_id=1, is_weaving_yarn=False),
        _make_item(stash_id=2, is_weaving_yarn=True),
    ]
    result = project_first_filter(_make_state(stash=items, user_goal=user_goal))
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert 1 in ids
    assert 2 not in ids


def test_project_first_filter_excludes_fiber_mismatch_for_garment_goal() -> None:
    items = [
        _make_item(stash_id=1, fiber=["Wool"]),
        _make_item(stash_id=2, fiber=["Silk"]),
    ]
    with patch("skeinminder.graph.nodes.fiber_suitability") as mock_fs:
        mock_fs.side_effect = lambda item, garment: (
            MatchScore.EXACT if "Wool" in item.fiber else MatchScore.MISMATCH
        )
        result = project_first_filter(
            _make_state(stash=items, user_goal="I want a cardigan")
        )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert 1 in ids
    assert 2 not in ids


def test_project_first_filter_passes_fiber_adjacent_for_garment_goal() -> None:
    # Silk is ADJACENT (not MISMATCH) for cardigan in the real fiber rules
    items = [
        _make_item(stash_id=1, fiber=["Silk"]),
    ]
    result = project_first_filter(
        _make_state(stash=items, user_goal="I want a cardigan")
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert 1 in ids


def test_project_first_filter_caps_at_20_items() -> None:
    items = [_make_item(stash_id=i) for i in range(30)]
    result = project_first_filter(_make_state(stash=items, user_goal="I want a hat"))
    assert len(result["filtered_stash"]) == 20


def test_project_first_filter_sorts_by_yardage_descending() -> None:
    items = [
        _make_item(stash_id=1, yards_total=500.0),
        _make_item(stash_id=2, yards_total=1500.0),
        _make_item(stash_id=3, yards_total=900.0),
    ]
    result = project_first_filter(_make_state(stash=items, user_goal="I want a hat"))
    yards = [i.yards_total for i in result["filtered_stash"]]
    assert yards == sorted(yards, reverse=True)


def test_project_first_filter_sorts_oldest_first_ascending() -> None:
    old = datetime(2016, 3, 1, tzinfo=timezone.utc)
    mid = datetime(2020, 6, 15, tzinfo=timezone.utc)
    recent = datetime(2024, 1, 10, tzinfo=timezone.utc)
    items = [
        _make_item(stash_id=1, yards_total=900.0, added_date=recent),
        _make_item(stash_id=2, yards_total=600.0, added_date=old),
        _make_item(stash_id=3, yards_total=750.0, added_date=mid),
    ]
    result = project_first_filter(
        _make_state(
            stash=items,
            user_goal="",
            stash_filter=StashFilter(oldest_first=True),
        )
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert ids == [2, 3, 1]  # old → mid → recent


# --- stash_first_filter ---


def test_stash_first_filter_no_filter_returns_up_to_20() -> None:
    items = [_make_item(stash_id=i) for i in range(30)]
    result = stash_first_filter(_make_state(stash=items, stash_filter=StashFilter()))
    assert len(result["filtered_stash"]) == 20


STASH_FIRST_FILTER_SCENARIOS: list[dict[str, Any]] = [
    {
        "items": [
            _make_item(stash_id=1, weight=WeightCategory.SPORT),
            _make_item(stash_id=2, weight=WeightCategory.BULKY),
        ],
        "stash_filter": StashFilter(weight=WeightCategory.SPORT),
        "expected_in": [1],
        "expected_out": [2],
    },
    {
        # Each item is a distinct yarn; individual totals govern the group check.
        "items": [
            _make_item(stash_id=1, yarn_id=1, yards_total=400.0),
            _make_item(stash_id=2, yarn_id=2, yards_total=1000.0),
        ],
        "stash_filter": StashFilter(min_yards=600.0),
        "expected_in": [2],
        "expected_out": [1],
    },
    {
        "items": [
            _make_item(stash_id=1, yards_total=400.0),
            _make_item(stash_id=2, yards_total=1000.0),
        ],
        "stash_filter": StashFilter(max_yards=600.0),
        "expected_in": [1],
        "expected_out": [2],
    },
    {
        "items": [
            _make_item(stash_id=1, color_family="Greens"),
            _make_item(stash_id=2, color_family="Blues"),
        ],
        "stash_filter": StashFilter(color_family="green"),
        "expected_in": [1],
        "expected_out": [2],
    },
    {
        "items": [_make_item(stash_id=42), _make_item(stash_id=99)],
        "stash_filter": StashFilter(specific_stash_id=42),
        "expected_in": [42],
        "expected_out": [99],
    },
    {
        # Same yarn/colorway → group total 1200 yds ≥ min_yards=1000 → all pass
        "items": [
            _make_item(
                stash_id=i, yarn_id=5, weight=WeightCategory.DK, yards_total=200.0
            )
            for i in range(1, 7)
        ],
        "stash_filter": StashFilter(min_yards=1000.0),
        "expected_in": [1, 2, 3, 4, 5, 6],
        "expected_out": [],
    },
    {
        # max_yards is per-item: 400 yd items exceed max_yards=350 → both excluded
        "items": [
            _make_item(
                stash_id=1, yarn_id=5, weight=WeightCategory.DK, yards_total=400.0
            ),
            _make_item(
                stash_id=2, yarn_id=5, weight=WeightCategory.DK, yards_total=400.0
            ),
        ],
        "stash_filter": StashFilter(max_yards=350.0),
        "expected_in": [],
        "expected_out": [1, 2],
    },
]


@pytest.mark.parametrize("scenario", STASH_FIRST_FILTER_SCENARIOS)
def test_stash_first_filter_by_criterion(scenario: dict[str, Any]) -> None:
    result = stash_first_filter(
        _make_state(stash=scenario["items"], stash_filter=scenario["stash_filter"])
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    for item_id in scenario["expected_in"]:
        assert item_id in ids
    for item_id in scenario["expected_out"]:
        assert item_id not in ids


def test_stash_first_filter_excludes_weaving_yarn() -> None:
    items = [
        _make_item(stash_id=1, is_weaving_yarn=False),
        _make_item(stash_id=2, is_weaving_yarn=True),
    ]
    result = stash_first_filter(_make_state(stash=items, stash_filter=StashFilter()))
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert 1 in ids
    assert 2 not in ids


def test_project_first_filter_with_real_stash(
    normalized_stash: list[StashItem],
) -> None:
    result = project_first_filter(
        _make_state(stash=normalized_stash, user_goal="I want a cozy cardigan")
    )
    filtered = result["filtered_stash"]
    assert len(filtered) <= 20
    assert all(i.yards_total > 0 for i in filtered)


def test_stash_first_filter_sorts_oldest_first_ascending() -> None:
    old = datetime(2016, 3, 1, tzinfo=timezone.utc)
    mid = datetime(2020, 6, 15, tzinfo=timezone.utc)
    recent = datetime(2024, 1, 10, tzinfo=timezone.utc)
    items = [
        _make_item(stash_id=1, yards_total=900.0, added_date=recent),
        _make_item(stash_id=2, yards_total=600.0, added_date=old),
        _make_item(stash_id=3, yards_total=750.0, added_date=mid),
    ]
    result = stash_first_filter(
        _make_state(stash=items, stash_filter=StashFilter(oldest_first=True))
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert ids == [2, 3, 1]  # old → mid → recent


def test_stash_first_filter_sorts_none_date_last() -> None:
    dated = datetime(2016, 3, 1, tzinfo=timezone.utc)
    items = [
        _make_item(stash_id=1, yards_total=1000.0, added_date=None),
        _make_item(stash_id=2, yards_total=500.0, added_date=dated),
    ]
    result = stash_first_filter(
        _make_state(stash=items, stash_filter=StashFilter(oldest_first=True))
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert ids == [2, 1]  # dated item before undated (None sorts last via sentinel)


def test_stash_first_filter_handles_naive_added_date_without_crash() -> None:
    naive = datetime(2016, 3, 1)  # no tzinfo
    items = [
        _make_item(stash_id=1, yards_total=900.0, added_date=naive),
        _make_item(stash_id=2, yards_total=500.0, added_date=None),
    ]
    result = stash_first_filter(
        _make_state(stash=items, stash_filter=StashFilter(oldest_first=True))
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert ids == [1, 2]  # naive date sorts before None (None is sentinel = last)
