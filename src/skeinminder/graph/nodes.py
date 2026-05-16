"""Graph nodes for the SkeinMinder recommendation workflow."""

from __future__ import annotations

import re
from typing import Any

from skeinminder.graph.state import GraphState, StashFilter
from skeinminder.ravelry.normalizer import (
    MatchScore,
    StashItem,
    WeightCategory,
    weight_match,
)

# Longer multi-word keywords come first to prevent substring matching errors.
_WEIGHT_KEYWORDS: dict[str, WeightCategory] = {
    "light fingering": WeightCategory.LIGHT_FINGERING,
    "super bulky": WeightCategory.SUPER_BULKY,
    "thread": WeightCategory.THREAD,
    "cobweb": WeightCategory.COBWEB,
    "lace": WeightCategory.LACE,
    "fingering": WeightCategory.FINGERING,
    "sock": WeightCategory.FINGERING,
    "sport": WeightCategory.SPORT,
    "dk": WeightCategory.DK,
    "worsted": WeightCategory.WORSTED,
    "aran": WeightCategory.ARAN,
    "bulky": WeightCategory.BULKY,
}

_STASH_FIRST_TRIGGERS = frozenset({"make with", "use up", "use my", "i have"})

_SWEATER_GARMENTS = frozenset(
    {"cardigan", "sweater", "pullover", "vest", "coat", "jumper"}
)


def _extract_weight(text: str) -> WeightCategory | None:
    """Return the first WeightCategory keyword found in text, or None."""
    for keyword, weight in sorted(_WEIGHT_KEYWORDS.items(), key=lambda x: -len(x[0])):
        if keyword in text:
            return weight
    return None


def _extract_yards(text: str) -> float | None:
    """Return the first yardage value found in text (e.g. '900 yards' → 900.0)."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:yards?|yds?)", text)
    return float(m.group(1)) if m else None


def supervisor(state: GraphState) -> dict[str, Any]:
    """Deterministically classify mode and populate user_goal or stash_filter.

    Sets mode to "stash_first" when the input contains a trigger phrase (e.g. "use my",
    "i have"), and extracts weight/yardage into a StashFilter. Otherwise sets mode to
    "project_first" and passes the raw user input as user_goal.
    """
    text = state["user_input"].lower()
    mode = (
        "stash_first"
        if any(trigger in text for trigger in _STASH_FIRST_TRIGGERS)
        else "project_first"
    )

    if mode == "stash_first":
        stash_filter = StashFilter(
            weight=_extract_weight(text),
            min_yards=_extract_yards(text),
        )
        return {"mode": mode, "user_goal": None, "stash_filter": stash_filter}

    return {"mode": mode, "user_goal": state["user_input"], "stash_filter": None}


def project_first_filter(state: GraphState) -> dict[str, Any]:
    """Filter stash by weight match and project quantity, capped at 20 items.

    Excludes weight mismatches when a weight keyword is present in the goal. Excludes
    scrap-quantity items when the goal mentions a sweater-scale garment. Results are
    sorted by yards_total descending.
    """
    stash = state["normalized_stash"]
    goal = (state["user_goal"] or "").lower()
    weight = _extract_weight(goal)
    is_sweater_goal = any(
        re.search(r"\b" + g + r"\b", goal) is not None for g in _SWEATER_GARMENTS
    )

    filtered: list[StashItem] = []
    for item in stash:
        if weight is not None and weight_match(item, weight) == MatchScore.MISMATCH:
            continue
        if is_sweater_goal and item.project_quantity.value == "scrap":
            continue
        filtered.append(item)

    filtered.sort(key=lambda i: i.yards_total, reverse=True)
    return {"filtered_stash": filtered[:20]}


def stash_first_filter(state: GraphState) -> dict[str, Any]:
    """Filter stash by StashFilter fields, capped at 20 items.

    Applies filters in order: specific_stash_id, weight, min_yards, max_yards,
    color_family. Results are sorted by yards_total descending.
    """
    stash = state["normalized_stash"]
    f = state["stash_filter"]

    filtered = list(stash)

    if f is not None:
        if f.specific_stash_id is not None:
            filtered = [i for i in filtered if i.stash_id == f.specific_stash_id]
        if f.weight is not None:
            filtered = [
                i for i in filtered if weight_match(i, f.weight) != MatchScore.MISMATCH
            ]
        if f.min_yards is not None:
            filtered = [i for i in filtered if i.yards_total >= f.min_yards]
        if f.max_yards is not None:
            filtered = [i for i in filtered if i.yards_total <= f.max_yards]
        if f.color_family is not None:
            cf = f.color_family.lower()
            filtered = [
                i
                for i in filtered
                if i.color_family is not None and cf in i.color_family.lower()
            ]

    filtered.sort(key=lambda i: i.yards_total, reverse=True)
    return {"filtered_stash": filtered[:20]}
