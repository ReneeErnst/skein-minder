from __future__ import annotations

import json
from pathlib import Path

import pytest

from skeinminder.ravelry.exceptions import NormalizationError
from skeinminder.ravelry.models import (
    RawFiberCategory,
    RawPack,
    RawStashItem,
    RawStashListResponse,
    RawYarn,
    RawYarnWeight,
)
from skeinminder.ravelry.normalizer import (
    _WEIGHT_ORDER,
    ProjectQuantity,
    StashItem,
    WeightCategory,
    normalize_stash,
    normalize_stash_item,
    project_quantity_from_yards,
    weight_category_from_string,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _make_raw_item(
    *,
    item_id: int = 1,
    skeins: float | None = 3.0,
    colorway: str | None = "Mossy Green",
    yarn_name: str | None = None,
    weight: str = "Worsted",
    yardage: float = 218.0,
    grams: float = 100.0,
    fibers: list[str] | None = None,
    company: str = "Sample Brand",
    yarn_id: int = 100,
) -> RawStashItem:
    return RawStashItem(
        id=item_id,
        colorway_name=colorway,
        yarn_name=yarn_name,
        skeins=skeins,
        yarn=RawYarn(
            id=yarn_id,
            name="Test Yarn",
            yarn_company_name=company,
            yarn_weight=RawYarnWeight(id=1, name=weight),
            yardage=yardage,
            grams=grams,
            fiber_categories=[
                RawFiberCategory(id=i, name=f) for i, f in enumerate(fibers or [])
            ],
        ),
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
    assert (
        project_quantity_from_yards(150.0, WeightCategory.WORSTED)
        == ProjectQuantity.SCRAP
    )


def test_project_quantity_accessory_lower_bound() -> None:
    assert (
        project_quantity_from_yards(200.0, WeightCategory.WORSTED)
        == ProjectQuantity.ACCESSORY
    )


def test_project_quantity_accessory_upper_bound() -> None:
    assert (
        project_quantity_from_yards(799.0, WeightCategory.WORSTED)
        == ProjectQuantity.ACCESSORY
    )


def test_project_quantity_sweater_worsted() -> None:
    assert (
        project_quantity_from_yards(800.0, WeightCategory.WORSTED)
        == ProjectQuantity.SWEATER
    )


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
    raw = _make_raw_item(weight="Worsted", skeins=5.0, yardage=218.0, fibers=["Wool"])
    item = normalize_stash_item(raw)
    assert item.weight_category == WeightCategory.WORSTED
    assert item.yards_total == pytest.approx(5.0 * 218.0)
    assert item.project_quantity == ProjectQuantity.SWEATER
    assert "Wool" in item.fiber
    assert item.brand == "Sample Brand"
    assert item.colorway == "Mossy Green"


def test_normalize_stash_item_fingering() -> None:
    raw = _make_raw_item(
        weight="Fingering", skeins=2.0, yardage=400.0, fibers=["Nylon"]
    )
    item = normalize_stash_item(raw)
    assert item.weight_category == WeightCategory.FINGERING
    assert item.yards_total == pytest.approx(2.0 * 400.0)
    assert (
        item.project_quantity == ProjectQuantity.ACCESSORY
    )  # 800 yds < 1200 fingering threshold
    assert "Nylon" in item.fiber


def test_normalize_stash_item_dk_scrap() -> None:
    raw = _make_raw_item(weight="DK", skeins=1.0, yardage=125.0)
    item = normalize_stash_item(raw)
    assert item.weight_category == WeightCategory.DK
    assert item.yards_total == pytest.approx(125.0)
    assert item.project_quantity == ProjectQuantity.SCRAP


def test_normalize_stash_item_defaults_skeins_to_one() -> None:
    raw = _make_raw_item(skeins=None, yardage=400.0)
    item = normalize_stash_item(raw)
    assert item.skeins == 1.0
    assert item.yards_total == pytest.approx(400.0)


def test_normalize_stash_raises_without_yardage() -> None:
    raw = _make_raw_item()
    assert raw.yarn is not None
    raw_no_yardage = raw.model_copy(
        update={"yarn": raw.yarn.model_copy(update={"yardage": None})}
    )
    with pytest.raises(NormalizationError, match="yardage"):
        normalize_stash_item(raw_no_yardage)


def test_normalize_stash_skips_items_without_yarn() -> None:
    items = [
        _make_raw_item(item_id=1, yardage=300.0),
        RawStashItem(id=2),  # no yarn
        _make_raw_item(item_id=3, yardage=500.0),
    ]
    result = normalize_stash(items)
    assert len(result) == 2
    assert all(isinstance(i, StashItem) for i in result)
    assert result[0].stash_id == 1
    assert result[1].stash_id == 3


def test_normalize_stash_returns_list() -> None:
    data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
    raw_list = RawStashListResponse.model_validate(data)
    items = normalize_stash(raw_list.stash)
    assert len(items) == 1313  # 1379 fixture items, 66 have no yarn and are skipped
    assert all(isinstance(i, StashItem) for i in items)


def test_weight_category_thread() -> None:
    assert weight_category_from_string("thread") == WeightCategory.THREAD


def test_weight_category_cobweb() -> None:
    assert weight_category_from_string("cobweb") == WeightCategory.COBWEB


def test_weight_category_light_fingering() -> None:
    assert (
        weight_category_from_string("light fingering") == WeightCategory.LIGHT_FINGERING
    )


def test_weight_order_new_categories_positioned() -> None:
    thread_idx = _WEIGHT_ORDER.index(WeightCategory.THREAD)
    cobweb_idx = _WEIGHT_ORDER.index(WeightCategory.COBWEB)
    lace_idx = _WEIGHT_ORDER.index(WeightCategory.LACE)
    lf_idx = _WEIGHT_ORDER.index(WeightCategory.LIGHT_FINGERING)
    fingering_idx = _WEIGHT_ORDER.index(WeightCategory.FINGERING)
    assert thread_idx < cobweb_idx < lace_idx < lf_idx < fingering_idx


def test_project_quantity_bulky_sweater_at_600_yards() -> None:
    # Bulky threshold is 500 yards; 600 yards qualifies as sweater quantity
    assert (
        project_quantity_from_yards(600.0, WeightCategory.BULKY)
        == ProjectQuantity.SWEATER
    )


def test_project_quantity_fingering_accessory_at_800_yards() -> None:
    # Fingering threshold is 1200 yards; 800 yards is only accessory quantity
    assert (
        project_quantity_from_yards(800.0, WeightCategory.FINGERING)
        == ProjectQuantity.ACCESSORY
    )


def test_project_quantity_lace_sweater_at_1600_yards() -> None:
    # Lace threshold is 1500 yards; 1600 yards qualifies
    assert (
        project_quantity_from_yards(1600.0, WeightCategory.LACE)
        == ProjectQuantity.SWEATER
    )


def test_project_quantity_unknown_falls_back_to_800_threshold() -> None:
    assert (
        project_quantity_from_yards(800.0, WeightCategory.UNKNOWN)
        == ProjectQuantity.SWEATER
    )
    assert (
        project_quantity_from_yards(799.0, WeightCategory.UNKNOWN)
        == ProjectQuantity.ACCESSORY
    )


def test_normalize_stash_item_reads_skeins_from_primary_pack() -> None:
    raw = _make_raw_item(skeins=None, yardage=200.0)
    raw_with_packs = raw.model_copy(
        update={
            "packs": [
                RawPack(id=1, primary_pack_id=None, skeins=4.0),  # primary
                RawPack(id=2, primary_pack_id=1, skeins=4.0),  # secondary — ignored
            ]
        }
    )
    item = normalize_stash_item(raw_with_packs)
    assert item.skeins == 4.0
    assert item.yards_total == pytest.approx(4.0 * 200.0)


def test_normalize_stash_item_falls_back_to_default_when_pack_skeins_null() -> None:
    raw = _make_raw_item(skeins=None, yardage=200.0)
    raw_with_packs = raw.model_copy(
        update={"packs": [RawPack(id=1, primary_pack_id=None, skeins=None)]}
    )
    item = normalize_stash_item(raw_with_packs)
    assert item.skeins == 1.0


def test_normalize_stash_item_falls_back_to_default_when_no_packs() -> None:
    raw = _make_raw_item(skeins=None, yardage=200.0)
    item = normalize_stash_item(raw)
    assert item.skeins == 1.0
