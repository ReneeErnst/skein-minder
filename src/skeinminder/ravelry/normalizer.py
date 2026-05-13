from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

# --- Enums ---


class WeightCategory(str, Enum):
    LACE = "lace"
    FINGERING = "fingering"
    SPORT = "sport"
    DK = "dk"
    WORSTED = "worsted"
    ARAN = "aran"
    BULKY = "bulky"
    SUPER_BULKY = "super_bulky"
    UNKNOWN = "unknown"


_WEIGHT_MAP: dict[str, WeightCategory] = {
    "lace": WeightCategory.LACE,
    "fingering": WeightCategory.FINGERING,
    "sock": WeightCategory.FINGERING,
    "sport": WeightCategory.SPORT,
    "dk": WeightCategory.DK,
    "light worsted": WeightCategory.DK,
    "worsted": WeightCategory.WORSTED,
    "aran": WeightCategory.ARAN,
    "bulky": WeightCategory.BULKY,
    "super bulky": WeightCategory.SUPER_BULKY,
    "jumbo": WeightCategory.SUPER_BULKY,
}


def weight_category_from_string(value: str | None) -> WeightCategory:
    if not value:
        return WeightCategory.UNKNOWN
    return _WEIGHT_MAP.get(value.lower().strip(), WeightCategory.UNKNOWN)


class ProjectQuantity(str, Enum):
    SCRAP = "scrap"
    ACCESSORY = "accessory"
    SWEATER = "sweater"


_SCRAP_THRESHOLD = 200.0
_SWEATER_THRESHOLD = 800.0


def project_quantity_from_yards(yards: float) -> ProjectQuantity:
    if yards < _SCRAP_THRESHOLD:
        return ProjectQuantity.SCRAP
    if yards < _SWEATER_THRESHOLD:
        return ProjectQuantity.ACCESSORY
    return ProjectQuantity.SWEATER


class MatchScore(str, Enum):
    EXACT = "exact"
    ADJACENT = "adjacent"
    MISMATCH = "mismatch"


# --- Normalized model ---


class StashItem(BaseModel):
    stash_id: int
    brand: str
    yarn_name: str
    colorway: str | None
    weight_category: WeightCategory
    fiber: list[str]
    color_family: str | None
    skeins: float
    yards_per_skein: float
    yards_total: float
    grams_total: float | None
    notes: str | None
    project_quantity: ProjectQuantity


from skeinminder.ravelry.exceptions import NormalizationError  # noqa: E402
from skeinminder.ravelry.models import RawStashItem  # noqa: E402


def normalize_stash_item(raw: RawStashItem) -> StashItem:
    if raw.skeins is None:
        raise NormalizationError(f"stash item {raw.id} has no skeins value")

    yarn = raw.yarn
    yards_per_skein: float
    grams_per_skein: float | None = None
    brand = "Unknown"
    weight_str: str | None = None
    fibers: list[str] = []

    if yarn is not None:
        if yarn.yardage is None:
            raise NormalizationError(
                f"stash item {raw.id} has no yardage value (yarn id {yarn.id})"
            )
        yards_per_skein = float(yarn.yardage)
        grams_per_skein = float(yarn.grams) if yarn.grams is not None else None
        brand = yarn.yarn_company_name or "Unknown"
        weight_str = yarn.yarn_weight.name if yarn.yarn_weight else None
        fibers = [fc.name for fc in yarn.fiber_categories]
    else:
        raise NormalizationError(
            f"stash item {raw.id} has no yarn data; cannot compute yardage"
        )

    yards_total = raw.skeins * yards_per_skein
    grams_total = raw.skeins * grams_per_skein if grams_per_skein is not None else None

    return StashItem(
        stash_id=raw.id,
        brand=brand,
        yarn_name=raw.yarn_name
        if raw.yarn_name
        else (yarn.name if yarn else "Unknown"),
        colorway=raw.colorway_name,
        weight_category=weight_category_from_string(weight_str),
        fiber=fibers,
        color_family=raw.color_family_name,
        skeins=raw.skeins,
        yards_per_skein=yards_per_skein,
        yards_total=yards_total,
        grams_total=grams_total,
        notes=raw.notes,
        project_quantity=project_quantity_from_yards(yards_total),
    )


def normalize_stash(raw_items: list[RawStashItem]) -> list[StashItem]:
    return [normalize_stash_item(item) for item in raw_items]
