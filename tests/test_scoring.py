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


def test_yardage_buffer_positive_overage() -> None:
    item = _make_item(yards_total=1100.0)
    result = yardage_buffer(item, pattern_yards=950.0)
    assert result == pytest.approx((1100.0 - 950.0) / 950.0 * 100, rel=1e-3)


def test_yardage_buffer_deficit() -> None:
    item = _make_item(yards_total=800.0)
    result = yardage_buffer(item, pattern_yards=950.0)
    assert result < 0


def test_yardage_buffer_exact() -> None:
    item = _make_item(yards_total=1000.0)
    result = yardage_buffer(item, pattern_yards=1000.0)
    assert result == pytest.approx(0.0)


# --- weight_match ---


def test_weight_match_exact() -> None:
    item = _make_item(weight=WeightCategory.WORSTED)
    assert weight_match(item, WeightCategory.WORSTED) == MatchScore.EXACT


def test_weight_match_adjacent_heavier() -> None:
    item = _make_item(weight=WeightCategory.DK)
    assert weight_match(item, WeightCategory.WORSTED) == MatchScore.ADJACENT


def test_weight_match_adjacent_lighter() -> None:
    item = _make_item(weight=WeightCategory.ARAN)
    assert weight_match(item, WeightCategory.WORSTED) == MatchScore.ADJACENT


def test_weight_match_mismatch() -> None:
    item = _make_item(weight=WeightCategory.LACE)
    assert weight_match(item, WeightCategory.BULKY) == MatchScore.MISMATCH


def test_weight_match_unknown() -> None:
    item = _make_item(weight=WeightCategory.UNKNOWN)
    assert weight_match(item, WeightCategory.WORSTED) == MatchScore.MISMATCH


# --- fiber_suitability ---


def test_fiber_wool_cardigan_exact() -> None:
    item = _make_item(fiber=["Wool"])
    assert fiber_suitability(item, "cardigan") == MatchScore.EXACT


def test_fiber_acrylic_cardigan_adjacent() -> None:
    item = _make_item(fiber=["Acrylic"])
    assert fiber_suitability(item, "cardigan") == MatchScore.ADJACENT


def test_fiber_superwash_baby_exact() -> None:
    item = _make_item(fiber=["Superwash Wool"])
    assert fiber_suitability(item, "baby") == MatchScore.EXACT


def test_fiber_silk_cables_mismatch() -> None:
    item = _make_item(fiber=["Silk"])
    assert fiber_suitability(item, "cables") == MatchScore.MISMATCH


def test_fiber_unknown_returns_adjacent() -> None:
    item = _make_item(fiber=["Unicorn Hair"])
    # Unknown fiber → ADJACENT (not disqualifying, but flagged)
    assert fiber_suitability(item, "cardigan") == MatchScore.ADJACENT
