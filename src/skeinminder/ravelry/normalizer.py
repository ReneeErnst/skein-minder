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
