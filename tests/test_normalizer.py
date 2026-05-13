from __future__ import annotations

import json
from pathlib import Path

import pytest

from skeinminder.ravelry.exceptions import NormalizationError
from skeinminder.ravelry.models import RawStashListResponse
from skeinminder.ravelry.normalizer import (
    ProjectQuantity,
    StashItem,
    WeightCategory,
    normalize_stash,
    normalize_stash_item,
    project_quantity_from_yards,
    weight_category_from_string,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_weight_category_worsted() -> None:
    assert weight_category_from_string("Worsted") == WeightCategory.WORSTED


def test_weight_category_fingering() -> None:
    assert weight_category_from_string("Fingering") == WeightCategory.FINGERING


def test_weight_category_dk() -> None:
    assert weight_category_from_string("DK") == WeightCategory.DK


def test_weight_category_lace() -> None:
    assert weight_category_from_string("Lace") == WeightCategory.LACE


def test_weight_category_unknown_string() -> None:
    assert weight_category_from_string("CrazyUnknown") == WeightCategory.UNKNOWN


def test_weight_category_none() -> None:
    assert weight_category_from_string(None) == WeightCategory.UNKNOWN


def test_project_quantity_scrap() -> None:
    assert project_quantity_from_yards(150.0) == ProjectQuantity.SCRAP


def test_project_quantity_accessory_lower_bound() -> None:
    assert project_quantity_from_yards(200.0) == ProjectQuantity.ACCESSORY


def test_project_quantity_accessory_upper_bound() -> None:
    assert project_quantity_from_yards(799.0) == ProjectQuantity.ACCESSORY


def test_project_quantity_sweater() -> None:
    assert project_quantity_from_yards(800.0) == ProjectQuantity.SWEATER


def test_stash_item_construction() -> None:
    item = StashItem(
        stash_id=10001,
        brand="Sample Brand",
        yarn_name="Worsted Wool",
        colorway="Moss",
        weight_category=WeightCategory.WORSTED,
        fiber=["Wool"],
        color_family="Greens",
        skeins=5.0,
        yards_per_skein=218.0,
        yards_total=1090.0,
        grams_total=500.0,
        notes=None,
        project_quantity=ProjectQuantity.SWEATER,
    )
    assert item.stash_id == 10001
    assert item.project_quantity == ProjectQuantity.SWEATER


def test_normalize_stash_item_worsted() -> None:
    data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
    raw_list = RawStashListResponse.model_validate(data)
    item = normalize_stash_item(raw_list.stash[0])  # Worsted Wool, 5 skeins x 218 yds
    assert item.stash_id == 10001
    assert item.weight_category == WeightCategory.WORSTED
    assert item.yards_total == pytest.approx(5.0 * 218.0)
    assert item.project_quantity == ProjectQuantity.SWEATER
    assert "Wool" in item.fiber
    assert item.brand == "Sample Brand"
    assert item.colorway == "Moss"


def test_normalize_stash_item_fingering() -> None:
    data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
    raw_list = RawStashListResponse.model_validate(data)
    item = normalize_stash_item(raw_list.stash[1])  # Fingering, 2 skeins x 400 yds
    assert item.weight_category == WeightCategory.FINGERING
    assert item.yards_total == pytest.approx(2.0 * 400.0)
    assert item.project_quantity == ProjectQuantity.SWEATER
    assert "Nylon" in item.fiber


def test_normalize_stash_item_dk_scrap() -> None:
    data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
    raw_list = RawStashListResponse.model_validate(data)
    item = normalize_stash_item(raw_list.stash[2])  # DK, 1 skein x 125 yds
    assert item.weight_category == WeightCategory.DK
    assert item.yards_total == pytest.approx(125.0)
    assert item.project_quantity == ProjectQuantity.SCRAP


def test_normalize_stash_item_raises_without_skeins() -> None:
    data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
    raw_list = RawStashListResponse.model_validate(data)
    raw = raw_list.stash[0].model_copy(update={"skeins": None})
    with pytest.raises(NormalizationError, match="skeins"):
        normalize_stash_item(raw)


def test_normalize_stash_raises_without_yardage() -> None:
    data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
    raw_list = RawStashListResponse.model_validate(data)
    raw = raw_list.stash[0]
    assert raw.yarn is not None
    modified_yarn = raw.yarn.model_copy(update={"yardage": None})
    raw_no_yardage = raw.model_copy(update={"yarn": modified_yarn})
    with pytest.raises(NormalizationError, match="yardage"):
        normalize_stash_item(raw_no_yardage)


def test_normalize_stash_returns_list() -> None:
    data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
    raw_list = RawStashListResponse.model_validate(data)
    items = normalize_stash(raw_list.stash)
    assert len(items) == 3
    assert all(isinstance(i, StashItem) for i in items)
