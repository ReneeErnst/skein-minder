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
    _parse_ravelry_date,
    is_weaving_yarn,
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


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Worsted", WeightCategory.WORSTED),
        ("Fingering", WeightCategory.FINGERING),
        ("DK", WeightCategory.DK),
        ("Lace", WeightCategory.LACE),
        ("thread", WeightCategory.THREAD),
        ("cobweb", WeightCategory.COBWEB),
        ("light fingering", WeightCategory.LIGHT_FINGERING),
        ("CrazyUnknown", WeightCategory.UNKNOWN),
        (None, WeightCategory.UNKNOWN),
    ],
)
def test_weight_category_from_string(
    value: str | None, expected: WeightCategory
) -> None:
    assert weight_category_from_string(value) == expected


def test_weight_order_lightest_to_heaviest() -> None:
    thread_idx = _WEIGHT_ORDER.index(WeightCategory.THREAD)
    cobweb_idx = _WEIGHT_ORDER.index(WeightCategory.COBWEB)
    lace_idx = _WEIGHT_ORDER.index(WeightCategory.LACE)
    lf_idx = _WEIGHT_ORDER.index(WeightCategory.LIGHT_FINGERING)
    fingering_idx = _WEIGHT_ORDER.index(WeightCategory.FINGERING)
    assert thread_idx < cobweb_idx < lace_idx < lf_idx < fingering_idx


@pytest.mark.parametrize(
    "yarn_name,expected",
    [
        ("16/2 Bamboo", True),
        ("8/4 Cotton", True),
        ("10/2 Mercerised Cotton", True),
        ("Cascade 220", False),
        ("Malabrigo Rios", False),
        ("", False),
    ],
)
def test_is_weaving_yarn(yarn_name: str, expected: bool) -> None:
    assert is_weaving_yarn(yarn_name) == expected


@pytest.mark.parametrize(
    "yarn_name,expected",
    [
        ("16/2 Bamboo", True),
        ("Cascade 220", False),
    ],
)
def test_normalize_stash_item_sets_is_weaving_yarn(
    yarn_name: str, expected: bool
) -> None:
    raw = _make_raw_item(yarn_name=yarn_name)
    item = normalize_stash_item(raw)
    assert item.is_weaving_yarn is expected


@pytest.mark.parametrize(
    "yards,weight,expected",
    [
        (150.0, WeightCategory.WORSTED, ProjectQuantity.SCRAP),
        (200.0, WeightCategory.WORSTED, ProjectQuantity.ACCESSORY),
        (799.0, WeightCategory.WORSTED, ProjectQuantity.ACCESSORY),
        (800.0, WeightCategory.WORSTED, ProjectQuantity.SWEATER),
        (600.0, WeightCategory.BULKY, ProjectQuantity.SWEATER),  # bulky threshold 500
        (
            800.0,
            WeightCategory.FINGERING,
            ProjectQuantity.ACCESSORY,
        ),  # fingering threshold 1200
        (1600.0, WeightCategory.LACE, ProjectQuantity.SWEATER),  # lace threshold 1500
        (800.0, WeightCategory.UNKNOWN, ProjectQuantity.SWEATER),
        (799.0, WeightCategory.UNKNOWN, ProjectQuantity.ACCESSORY),
    ],
)
def test_project_quantity_from_yards(
    yards: float, weight: WeightCategory, expected: ProjectQuantity
) -> None:
    assert project_quantity_from_yards(yards, weight) == expected


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
    assert len(items) == 36  # 39 fixture items, 3 have no yarn and are skipped
    assert all(isinstance(i, StashItem) for i in items)


def test_normalize_stash_item_reads_skeins_from_primary_pack() -> None:
    raw = _make_raw_item(skeins=None, yardage=200.0)
    raw_with_packs = raw.model_copy(
        update={
            "packs": [
                RawPack(id=1, primary_pack_id=None, skeins=4.0),  # primary
                RawPack(
                    id=2, primary_pack_id=1, skeins=99.0
                ),  # secondary — must be ignored
            ]
        }
    )
    item = normalize_stash_item(raw_with_packs)
    assert item.skeins == 4.0
    assert item.yards_total == pytest.approx(4.0 * 200.0)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(
            _make_raw_item(skeins=None, yardage=200.0).model_copy(
                update={"packs": [RawPack(id=1, primary_pack_id=None, skeins=None)]}
            ),
            id="pack_skeins_null",
        ),
        pytest.param(
            _make_raw_item(skeins=None, yardage=200.0),
            id="no_packs",
        ),
    ],
)
def test_normalize_stash_item_falls_back_to_default_skeins(
    raw: RawStashItem,
) -> None:
    item = normalize_stash_item(raw)
    assert item.skeins == 1.0


@pytest.mark.parametrize(
    "raw_str,expected_year,expected_utc_offset_seconds",
    [
        pytest.param("2022/03/15 10:30:00 +05:30", 2022, 19800, id="positive_offset"),
        pytest.param("2019/11/01 08:00:00 -07:00", 2019, -25200, id="negative_offset"),
    ],
)
def test_parse_ravelry_date_valid(
    raw_str: str, expected_year: int, expected_utc_offset_seconds: int
) -> None:
    result = _parse_ravelry_date(raw_str)
    assert result is not None
    assert result.year == expected_year
    assert result.tzinfo is not None
    offset = result.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == expected_utc_offset_seconds


@pytest.mark.parametrize(
    "raw_str",
    [
        pytest.param(None, id="none_input"),
        pytest.param("not-a-date", id="malformed"),
    ],
)
def test_parse_ravelry_date_returns_none_for_invalid(raw_str: str | None) -> None:
    assert _parse_ravelry_date(raw_str) is None


def test_normalize_stash_item_parses_created_at() -> None:
    raw = _make_raw_item()
    raw_with_date = raw.model_copy(update={"created_at": "2022/03/15 10:30:00 +00:00"})
    item = normalize_stash_item(raw_with_date)
    assert item.added_date is not None
    assert item.added_date.year == 2022
    assert item.added_date.tzinfo is not None


def test_normalize_stash_item_added_date_none_when_no_created_at() -> None:
    raw = _make_raw_item()
    item = normalize_stash_item(raw)
    assert item.added_date is None
