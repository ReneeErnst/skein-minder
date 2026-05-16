from __future__ import annotations

from typing import TypedDict

from pydantic import BaseModel

from skeinminder.ravelry.normalizer import StashItem, WeightCategory


class StashFilter(BaseModel):
    weight: WeightCategory | None = None
    min_yards: float | None = None
    max_yards: float | None = None
    color_family: str | None = None
    specific_stash_id: int | None = None


class Recommendation(BaseModel):
    title: str
    rationale: str
    risks: list[str]
    yarn_candidate_ids: list[int]


class GraphState(TypedDict):
    user_input: str
    mode: str  # "project_first" | "stash_first"
    user_goal: str | None
    stash_filter: StashFilter | None
    normalized_stash: list[StashItem]
    filtered_stash: list[StashItem]
    recommendations: list[Recommendation] | None
    requires_approval: bool
    formatted_output: str | None
