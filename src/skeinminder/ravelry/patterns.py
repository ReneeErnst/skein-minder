"""Ravelry pattern models and normalization.

Raw models (RawPattern, RawPatternFull) map API response shapes. PatternSummary
is the normalized domain model used by graph nodes. All models use extra="ignore"
— the Ravelry API evolves without notice.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from skeinminder.ravelry.models import RawPaginator


class RawPatternYarnWeight(BaseModel):
    """Yarn weight embedded in a pattern detail response."""

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str


class RawFirstPhoto(BaseModel):
    """Photo thumbnail embedded in a pattern detail response."""

    model_config = ConfigDict(extra="ignore")

    medium_url: str | None = None


class RawPattern(BaseModel):
    """Pattern shape returned by patterns/search (list format). No yardage."""

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    permalink: str
    free: bool


class RawPatternFull(BaseModel):
    """Pattern shape returned by /patterns.json batch detail. Includes yardage."""

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    permalink: str
    free: bool
    yardage: int | None = None
    yardage_max: int | None = None
    yarn_weight: RawPatternYarnWeight | None = None
    first_photo: RawFirstPhoto | None = None


class RawLibraryVolume(BaseModel):
    """A single volume entry from the library/search response."""

    model_config = ConfigDict(extra="ignore")

    id: int
    pattern_id: int | None = None


class RawLibrarySearchResponse(BaseModel):
    """Response shape from /people/{username}/library/search.json."""

    model_config = ConfigDict(extra="ignore")

    volumes: list[RawLibraryVolume] = []
    paginator: RawPaginator


class PatternSummary(BaseModel):
    """Normalized pattern candidate ready for LLM consumption.

    Constructed via normalize_pattern() from RawPatternFull. Yardage and
    weight_name are None when batch detail was unavailable for this pattern.
    """

    model_config = ConfigDict(extra="ignore")

    pattern_id: int
    name: str
    permalink: str
    url: str
    free: bool
    library_owned: bool
    yardage_min: int | None
    yardage_max: int | None
    weight_name: str | None
    tier: Literal["library", "free", "popular"]
    photo_url: str | None = None


def normalize_pattern(raw: RawPatternFull, library_ids: set[int]) -> PatternSummary:
    """Convert a RawPatternFull into a PatternSummary domain object.

    Args:
        raw: Pattern detail from the batch API response.
        library_ids: Set of pattern IDs in the user's Ravelry library. Library
            ownership takes priority over free/popular in tier assignment.
    """
    owned = raw.id in library_ids
    if owned:
        tier: Literal["library", "free", "popular"] = "library"
    elif raw.free:
        tier = "free"
    else:
        tier = "popular"

    return PatternSummary(
        pattern_id=raw.id,
        name=raw.name,
        permalink=raw.permalink,
        url=f"https://www.ravelry.com/patterns/library/{raw.permalink}",
        free=raw.free,
        library_owned=owned,
        yardage_min=raw.yardage,
        yardage_max=raw.yardage_max,
        weight_name=raw.yarn_weight.name if raw.yarn_weight else None,
        tier=tier,
        photo_url=raw.first_photo.medium_url if raw.first_photo else None,
    )
