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
    for keyword, weight in sorted(_WEIGHT_KEYWORDS.items(), key=lambda x: -len(x[0])):
        if keyword in text:
            return weight
    return None


def _extract_yards(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:yards?|yds?)", text)
    return float(m.group(1)) if m else None


def supervisor(state: GraphState) -> dict[str, Any]:
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
    stash = state["normalized_stash"]
    goal = (state["user_goal"] or "").lower()
    weight = _extract_weight(goal)
    is_sweater_goal = any(g in goal for g in _SWEATER_GARMENTS)

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
