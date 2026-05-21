from __future__ import annotations

from skeinminder.graph.nodes import project_first_filter, stash_first_filter
from skeinminder.graph.state import GraphState, StashFilter
from skeinminder.ravelry.normalizer import (
    ProjectQuantity,
    StashItem,
    WeightCategory,
)


def _make_item(
    *,
    stash_id: int = 1,
    weight: WeightCategory = WeightCategory.WORSTED,
    yards_total: float = 1000.0,
    color_family: str | None = None,
    project_quantity: ProjectQuantity = ProjectQuantity.SWEATER,
) -> StashItem:
    return StashItem(
        stash_id=stash_id,
        brand="Test Brand",
        yarn_name="Test Yarn",
        colorway=None,
        weight_category=weight,
        fiber=["Wool"],
        color_family=color_family,
        skeins=5.0,
        yards_per_skein=yards_total / 5.0,
        yards_total=yards_total,
        grams_total=None,
        notes=None,
        project_quantity=project_quantity,
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
    )


# --- project_first_filter ---


def test_project_first_filter_no_weight_returns_all_non_scrap_for_sweater_goal() -> (
    None
):
    items = [
        _make_item(stash_id=1, project_quantity=ProjectQuantity.SWEATER),
        _make_item(stash_id=2, project_quantity=ProjectQuantity.ACCESSORY),
        _make_item(stash_id=3, project_quantity=ProjectQuantity.SCRAP),
    ]
    result = project_first_filter(
        _make_state(stash=items, user_goal="I want a cardigan")
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert 1 in ids
    assert 2 in ids
    assert 3 not in ids  # scraps excluded for sweater goals


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


# --- stash_first_filter ---


def test_stash_first_filter_no_filter_returns_up_to_20() -> None:
    items = [_make_item(stash_id=i) for i in range(30)]
    result = stash_first_filter(_make_state(stash=items, stash_filter=StashFilter()))
    assert len(result["filtered_stash"]) == 20


def test_stash_first_filter_by_weight() -> None:
    items = [
        _make_item(stash_id=1, weight=WeightCategory.SPORT),
        _make_item(stash_id=2, weight=WeightCategory.BULKY),
    ]
    result = stash_first_filter(
        _make_state(stash=items, stash_filter=StashFilter(weight=WeightCategory.SPORT))
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert 1 in ids
    assert 2 not in ids


def test_stash_first_filter_by_min_yards() -> None:
    items = [
        _make_item(stash_id=1, yards_total=400.0),
        _make_item(stash_id=2, yards_total=1000.0),
    ]
    result = stash_first_filter(
        _make_state(stash=items, stash_filter=StashFilter(min_yards=600.0))
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert 1 not in ids
    assert 2 in ids


def test_stash_first_filter_by_specific_stash_id() -> None:
    items = [
        _make_item(stash_id=42),
        _make_item(stash_id=99),
    ]
    result = stash_first_filter(
        _make_state(stash=items, stash_filter=StashFilter(specific_stash_id=42))
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert ids == [42]


def test_stash_first_filter_by_color_family() -> None:
    items = [
        _make_item(stash_id=1, color_family="Greens"),
        _make_item(stash_id=2, color_family="Blues"),
    ]
    result = stash_first_filter(
        _make_state(stash=items, stash_filter=StashFilter(color_family="green"))
    )
    ids = [i.stash_id for i in result["filtered_stash"]]
    assert 1 in ids
    assert 2 not in ids


def test_stash_first_filter_by_max_yards() -> None:
    items = [
        _make_item(stash_id=1, yards_total=400.0),
        _make_item(stash_id=2, yards_total=1000.0),
    ]
    result = stash_first_filter(
        _make_state(stash=items, stash_filter=StashFilter(max_yards=600.0))
    )
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
