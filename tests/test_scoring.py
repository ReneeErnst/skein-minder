from __future__ import annotations

import pytest

from skeinminder.ravelry.normalizer import (
    MatchScore,
    ProjectQuantity,
    StashItem,
    WeightCategory,
    fiber_suitability,
    weight_match,
    yardage_buffer,
)


def _make_item(
    *,
    weight: WeightCategory = WeightCategory.WORSTED,
    fiber: list[str] | None = None,
    yards_total: float = 1000.0,
    yards_per_skein: float = 200.0,
    skeins: float = 5.0,
) -> StashItem:
    return StashItem(
        stash_id=1,
        brand="Test",
        yarn_name="Test Yarn",
        colorway=None,
        weight_category=weight,
        fiber=fiber or ["Wool"],
        color_family=None,
        skeins=skeins,
        yards_per_skein=yards_per_skein,
        yards_total=yards_total,
        grams_total=None,
        notes=None,
        project_quantity=ProjectQuantity.SWEATER,
    )


# --- yardage_buffer ---


@pytest.mark.parametrize(
    "yards_total,pattern_yards,expected_pct",
    [
        (1100.0, 950.0, (1100.0 - 950.0) / 950.0 * 100),
        (800.0, 950.0, (800.0 - 950.0) / 950.0 * 100),
        (1000.0, 1000.0, 0.0),
    ],
)
def test_yardage_buffer(
    yards_total: float, pattern_yards: float, expected_pct: float
) -> None:
    item = _make_item(yards_total=yards_total)
    assert yardage_buffer(item, pattern_yards) == pytest.approx(expected_pct, rel=1e-3)


# --- weight_match ---


@pytest.mark.parametrize(
    "item_weight,pattern_weight,expected",
    [
        (WeightCategory.WORSTED, WeightCategory.WORSTED, MatchScore.EXACT),
        (WeightCategory.DK, WeightCategory.WORSTED, MatchScore.ADJACENT),
        (WeightCategory.ARAN, WeightCategory.WORSTED, MatchScore.ADJACENT),
        (WeightCategory.LACE, WeightCategory.BULKY, MatchScore.MISMATCH),
        (WeightCategory.UNKNOWN, WeightCategory.WORSTED, MatchScore.MISMATCH),
    ],
)
def test_weight_match(
    item_weight: WeightCategory, pattern_weight: WeightCategory, expected: MatchScore
) -> None:
    item = _make_item(weight=item_weight)
    assert weight_match(item, pattern_weight) == expected


# --- fiber_suitability ---


@pytest.mark.parametrize(
    "fibers,garment,expected",
    [
        (["Wool"], "cardigan", MatchScore.EXACT),
        (["Acrylic"], "cardigan", MatchScore.ADJACENT),
        (["Superwash Wool"], "baby", MatchScore.EXACT),
        (["Silk"], "cables", MatchScore.MISMATCH),
        (["Unicorn Hair"], "cardigan", MatchScore.ADJACENT),  # unknown fiber → ADJACENT
    ],
)
def test_fiber_suitability(
    fibers: list[str], garment: str, expected: MatchScore
) -> None:
    item = _make_item(fiber=fibers)
    assert fiber_suitability(item, garment) == expected
