from __future__ import annotations

import re
from typing import Any

from skeinminder.graph.state import GraphState, StashFilter
from skeinminder.ravelry.normalizer import WeightCategory

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
