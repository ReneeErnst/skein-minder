from __future__ import annotations

from skeinminder.ravelry.normalizer import (
    ProjectQuantity,
    StashItem,
    WeightCategory,
    project_quantity_from_yards,
    weight_category_from_string,
)


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
