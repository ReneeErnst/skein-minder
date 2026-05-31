"""Graph state types for the SkeinMinder recommendation graph."""

from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel

from skeinminder.ravelry.normalizer import StashItem, WeightCategory
from skeinminder.ravelry.patterns import PatternSummary


class StashFilter(BaseModel):
    """Filter criteria for narrowing the normalized stash before LLM recommendation."""

    weight: WeightCategory | None = None
    min_yards: float | None = None
    max_yards: float | None = None
    color_family: str | None = None
    specific_stash_id: int | None = None


class Recommendation(BaseModel):
    """A single project recommendation produced by the recommend node."""

    title: str
    rationale: str
    risks: list[str]
    yarn_candidate_ids: list[int]
    pattern_id: int | None = None
    pattern_name: str | None = None
    pattern_url: str | None = None


class GraphState(TypedDict):
    """Shared state passed between all graph nodes."""

    user_input: str
    mode: Literal["project_first", "stash_first", ""]
    user_goal: str | None
    stash_filter: StashFilter | None
    normalized_stash: list[StashItem]
    filtered_stash: list[StashItem]
    recommendations: list[Recommendation] | None
    requires_approval: bool  # Phase 5 stub: set True before write operations
    formatted_output: str | None
    filter_confidence: Literal["high", "low", ""]
    force_recommend: bool
    ravelry_username: str
    use_fixture: bool
    pattern_candidates: list[PatternSummary]
