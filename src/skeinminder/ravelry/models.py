"""Raw Pydantic models for Ravelry API responses.

All models use extra="ignore" — the API returns many undocumented fields and
evolves without notice. Application logic uses the normalized types in normalizer.py,
not these raw models directly.
"""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class RawUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    username: str
    small_photo_url: str | None = None
    large_photo_url: str | None = None


class RawCurrentUserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user: RawUser


class RawFiberCategory(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str


class RawYarnWeight(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str


class RawYarn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    yarn_company_name: str | None = None
    yarn_weight: RawYarnWeight | None = None
    grams: float | None = None
    yardage: float | None = None
    fiber_categories: list[RawFiberCategory] = []


class RawStashStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str


class RawPack(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    primary_pack_id: int | None = None
    skeins: float | None = None
    total_yards: float | None = None
    total_grams: float | None = None
    yards_per_skein: float | None = None
    grams_per_skein: float | None = None


class RawStashItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    permalink: str | None = None
    colorway_name: str | None = None
    stash_status: RawStashStatus | None = None
    skeins: float | None = None  # always null from API; real data is in packs
    notes: str | None = None
    yarn_name: str | None = None
    yarn: RawYarn | None = None
    color_family_name: str | None = None
    packs: list[RawPack] = []
    created_at: str | None = None


class RawPaginator(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page: int
    page_size: int | None = None
    results: int
    pages: int = Field(validation_alias=AliasChoices("pages", "page_count"))
    last_page: int | None = None


class RawStashListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stash: list[RawStashItem]
    paginator: RawPaginator


class RawStashDetailResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stash: RawStashItem
