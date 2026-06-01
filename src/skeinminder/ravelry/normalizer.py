"""Normalizes raw Ravelry stash items into typed domain models.

Provides StashItem (the central domain model), weight/fiber scoring utilities,
and the normalize_stash pipeline. All application logic works with StashItem;
raw API models (RawStashItem etc.) should not leak past the normalizer layer.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from enum import Enum

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# --- Enums ---


class WeightCategory(str, Enum):
    THREAD = "thread"
    COBWEB = "cobweb"
    LACE = "lace"
    LIGHT_FINGERING = "light_fingering"
    FINGERING = "fingering"
    SPORT = "sport"
    DK = "dk"
    WORSTED = "worsted"
    ARAN = "aran"
    BULKY = "bulky"
    SUPER_BULKY = "super_bulky"
    UNKNOWN = "unknown"


_WEIGHT_MAP: dict[str, WeightCategory] = {
    "thread": WeightCategory.THREAD,
    "cobweb": WeightCategory.COBWEB,
    "lace": WeightCategory.LACE,
    "light fingering": WeightCategory.LIGHT_FINGERING,
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
    """Map a Ravelry yarn weight name to WeightCategory.

    Returns UNKNOWN for None or any string not in _WEIGHT_MAP.
    """
    if not value:
        return WeightCategory.UNKNOWN
    return _WEIGHT_MAP.get(value.lower().strip(), WeightCategory.UNKNOWN)


def find_weight_in_text(text: str) -> WeightCategory | None:
    """Find the first weight keyword in free text; longest keyword wins.

    Returns None if no weight keyword is found.
    """
    for keyword in sorted(_WEIGHT_MAP, key=len, reverse=True):
        if keyword in text:
            return _WEIGHT_MAP[keyword]
    return None


_WEAVING_YARN_RE = re.compile(r"\b\d+/\d+\b")


def is_weaving_yarn(yarn_name: str) -> bool:
    """Return True if the name matches count/ply weaving yarn convention.

    Examples: '16/2 Bamboo', '8/4 Cotton'.
    """
    return bool(_WEAVING_YARN_RE.search(yarn_name))


class ProjectQuantity(str, Enum):
    SCRAP = "scrap"
    ACCESSORY = "accessory"
    SWEATER = "sweater"


_SCRAP_THRESHOLD = 200.0

_SWEATER_YARDS_BY_WEIGHT: dict[WeightCategory, float] = {
    WeightCategory.THREAD: 2000.0,
    WeightCategory.COBWEB: 2000.0,
    WeightCategory.LACE: 1500.0,
    WeightCategory.LIGHT_FINGERING: 1100.0,  # below FINGERING: rare weight
    WeightCategory.FINGERING: 1200.0,
    WeightCategory.SPORT: 1000.0,
    WeightCategory.DK: 900.0,
    WeightCategory.WORSTED: 800.0,
    WeightCategory.ARAN: 650.0,
    WeightCategory.BULKY: 500.0,
    WeightCategory.SUPER_BULKY: 300.0,
    WeightCategory.UNKNOWN: 800.0,
}


def project_quantity_from_yards(
    yards: float, weight: WeightCategory
) -> ProjectQuantity:
    """Classify yardage as SCRAP, ACCESSORY, or SWEATER using per-weight thresholds.

    Thresholds are defined in _SWEATER_YARDS_BY_WEIGHT; anything under 200 yards
    is always SCRAP regardless of weight.
    """
    if yards < _SCRAP_THRESHOLD:
        return ProjectQuantity.SCRAP
    if yards < _SWEATER_YARDS_BY_WEIGHT[weight]:
        return ProjectQuantity.ACCESSORY
    return ProjectQuantity.SWEATER


class MatchScore(str, Enum):
    EXACT = "exact"
    ADJACENT = "adjacent"
    MISMATCH = "mismatch"


# --- Normalized model ---


class StashItem(BaseModel):
    """Normalized domain model for a single Ravelry stash entry.

    This is the type all application logic works with. Never pass RawStashItem
    into graph nodes or scoring helpers — always normalize first.
    """

    stash_id: int
    yarn_id: int
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
    is_weaving_yarn: bool = False
    added_date: datetime | None = None


from skeinminder.ravelry.exceptions import NormalizationError  # noqa: E402
from skeinminder.ravelry.models import RawPack, RawStashItem  # noqa: E402


def _parse_ravelry_date(s: str | None) -> datetime | None:
    """Parse a Ravelry stash date string into a timezone-aware datetime.

    Format: "YYYY/MM/DD HH:MM:SS ±HH:MM". Returns None for None input or
    any string that does not match the expected format.
    """
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y/%m/%d %H:%M:%S %z")
    except ValueError:
        logger.debug("could not parse stash date %r", s)
        return None


def _primary_pack_skeins(packs: list[RawPack]) -> float | None:
    """Return skeins from the primary pack (primary_pack_id is None).

    Returns None if no primary pack is found or its skeins field is null.
    """
    for pack in packs:
        if pack.primary_pack_id is None:
            return pack.skeins
    return None


def normalize_stash_item(raw: RawStashItem) -> StashItem:
    """Convert a raw API stash item to a StashItem.

    Skeins resolution order: primary pack skeins → raw.skeins → defaults to 1.0.
    Raises NormalizationError if yarn is absent or yarn.yardage is None.
    """
    yarn = raw.yarn
    if yarn is None:
        raise NormalizationError(
            f"stash item {raw.id} has no yarn data; cannot compute yardage"
        )
    if yarn.yardage is None:
        raise NormalizationError(
            f"stash item {raw.id} has no yardage value (yarn id {yarn.id})"
        )

    pack_skeins = _primary_pack_skeins(raw.packs)
    skeins = (
        pack_skeins
        if pack_skeins is not None
        else (raw.skeins if raw.skeins is not None else 1.0)
    )
    yards_per_skein = float(yarn.yardage)
    grams_per_skein = float(yarn.grams) if yarn.grams is not None else None
    brand = yarn.yarn_company_name or "Unknown"
    weight_str = yarn.yarn_weight.name if yarn.yarn_weight else None
    weight_category = weight_category_from_string(weight_str)
    fibers = [fc.name for fc in yarn.fiber_categories]

    yards_total = skeins * yards_per_skein
    grams_total = skeins * grams_per_skein if grams_per_skein is not None else None
    yarn_name_str = raw.yarn_name or (yarn.name or "Unknown")

    return StashItem(
        stash_id=raw.id,
        yarn_id=yarn.id,
        brand=brand,
        yarn_name=yarn_name_str,
        colorway=raw.colorway_name,
        weight_category=weight_category,
        fiber=fibers,
        color_family=raw.color_family_name,
        skeins=skeins,
        yards_per_skein=yards_per_skein,
        yards_total=yards_total,
        grams_total=grams_total,
        notes=raw.notes,
        project_quantity=project_quantity_from_yards(yards_total, weight_category),
        is_weaving_yarn=is_weaving_yarn(yarn_name_str),
        added_date=_parse_ravelry_date(raw.created_at),
    )


def normalize_stash(raw_items: list[RawStashItem]) -> list[StashItem]:
    """Normalize a list of raw stash items, silently skipping any that fail.

    Items that raise NormalizationError (no linked yarn, no yardage) are logged
    at DEBUG and excluded from the result rather than raising.
    """
    results = []
    for item in raw_items:
        try:
            results.append(normalize_stash_item(item))
        except NormalizationError:
            logger.debug("skipping stash item %s: normalization failed", item.id)
    return results


# Weight ordering for adjacency checks (lower index = lighter)
_WEIGHT_ORDER: list[WeightCategory] = [
    WeightCategory.THREAD,
    WeightCategory.COBWEB,
    WeightCategory.LACE,
    WeightCategory.LIGHT_FINGERING,
    WeightCategory.FINGERING,
    WeightCategory.SPORT,
    WeightCategory.DK,
    WeightCategory.WORSTED,
    WeightCategory.ARAN,
    WeightCategory.BULKY,
    WeightCategory.SUPER_BULKY,
]


def yardage_buffer(item: StashItem, pattern_yards: float) -> float:
    """Return percent overage (positive) or deficit (negative) vs pattern yardage."""
    return (item.yards_total - pattern_yards) / pattern_yards * 100.0


def weight_match(item: StashItem, pattern_weight: WeightCategory) -> MatchScore:
    """Return EXACT, ADJACENT (one step), or MISMATCH."""
    if item.weight_category == WeightCategory.UNKNOWN:
        return MatchScore.MISMATCH
    if item.weight_category == pattern_weight:
        return MatchScore.EXACT
    try:
        stash_idx = _WEIGHT_ORDER.index(item.weight_category)
        pattern_idx = _WEIGHT_ORDER.index(pattern_weight)
    except ValueError:
        return MatchScore.MISMATCH
    if abs(stash_idx - pattern_idx) == 1:
        return MatchScore.ADJACENT
    return MatchScore.MISMATCH


# Fiber rules: maps lowercase fiber keywords to garment type scores.
# Structure: {fiber_keyword: {garment_keyword: MatchScore}}
_FIBER_RULES: dict[str, dict[str, MatchScore]] = {
    "wool": {
        "cardigan": MatchScore.EXACT,
        "sweater": MatchScore.EXACT,
        "hat": MatchScore.EXACT,
        "mittens": MatchScore.EXACT,
        "socks": MatchScore.ADJACENT,
        "baby": MatchScore.ADJACENT,
        "cables": MatchScore.EXACT,
        "shawl": MatchScore.EXACT,
    },
    "superwash": {
        "baby": MatchScore.EXACT,
        "socks": MatchScore.EXACT,
        "cardigan": MatchScore.EXACT,
        "sweater": MatchScore.EXACT,
        "cables": MatchScore.EXACT,
    },
    "alpaca": {
        "cardigan": MatchScore.EXACT,
        "sweater": MatchScore.EXACT,
        "shawl": MatchScore.EXACT,
        "cables": MatchScore.ADJACENT,
        "socks": MatchScore.MISMATCH,
    },
    "cotton": {
        "cardigan": MatchScore.ADJACENT,
        "sweater": MatchScore.ADJACENT,
        "tank": MatchScore.EXACT,
        "summer": MatchScore.EXACT,
        "cables": MatchScore.MISMATCH,
    },
    "acrylic": {
        "cardigan": MatchScore.ADJACENT,
        "sweater": MatchScore.ADJACENT,
        "baby": MatchScore.EXACT,
        "cables": MatchScore.ADJACENT,
        "socks": MatchScore.ADJACENT,
    },
    "silk": {
        "shawl": MatchScore.EXACT,
        "cardigan": MatchScore.ADJACENT,
        "cables": MatchScore.MISMATCH,
        "socks": MatchScore.MISMATCH,
    },
    "nylon": {
        "socks": MatchScore.EXACT,
        "cardigan": MatchScore.ADJACENT,
    },
    "linen": {
        "summer": MatchScore.EXACT,
        "tank": MatchScore.EXACT,
        "cardigan": MatchScore.ADJACENT,
        "cables": MatchScore.MISMATCH,
    },
}


def fiber_suitability(item: StashItem, garment_type: str) -> MatchScore:
    """Return best MatchScore across all fibers in the item for the given garment."""
    garment = garment_type.lower().strip()
    best = MatchScore.ADJACENT  # default for unknown fiber

    for fiber_name in item.fiber:
        fiber_lower = fiber_name.lower()
        for keyword, rules in _FIBER_RULES.items():
            if keyword in fiber_lower:
                score = rules.get(garment, MatchScore.ADJACENT)
                if score == MatchScore.EXACT:
                    return MatchScore.EXACT
                if score == MatchScore.MISMATCH and best != MatchScore.EXACT:
                    best = MatchScore.MISMATCH

    return best
