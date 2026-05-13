from __future__ import annotations

from pydantic import BaseModel, ConfigDict


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
    grams: int | None = None
    yardage: int | None = None
    fiber_categories: list[RawFiberCategory] = []


class RawStashStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str


class RawStashItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    permalink: str | None = None
    colorway_name: str | None = None
    stash_status: RawStashStatus | None = None
    skeins: float | None = None
    notes: str | None = None
    yarn_name: str | None = None
    yarn: RawYarn | None = None
    color_family_name: str | None = None


class RawPaginator(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page: int
    page_size: int
    results: int
    pages: int
    last_page: int | None = None


class RawStashListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stash: list[RawStashItem]
    paginator: RawPaginator


class RawStashDetailResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stash: RawStashItem
