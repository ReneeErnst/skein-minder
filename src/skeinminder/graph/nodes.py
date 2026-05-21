"""Graph nodes for the SkeinMinder recommendation workflow."""

from __future__ import annotations

import os
import re
from typing import Any

import click  # noqa: F401
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from skeinminder.graph.state import GraphState, Recommendation, StashFilter
from skeinminder.ravelry.normalizer import (
    MatchScore,
    ProjectQuantity,
    StashItem,
    WeightCategory,
    fiber_suitability,
    weight_match,
)

# Sorted longest-first so multi-word entries like "light fingering" match
# before their single-word substrings like "fingering".
_WEIGHT_KEYWORDS: list[tuple[str, WeightCategory]] = [
    ("light fingering", WeightCategory.LIGHT_FINGERING),
    ("super bulky", WeightCategory.SUPER_BULKY),
    ("thread", WeightCategory.THREAD),
    ("cobweb", WeightCategory.COBWEB),
    ("lace", WeightCategory.LACE),
    ("fingering", WeightCategory.FINGERING),
    ("sock", WeightCategory.FINGERING),
    ("sport", WeightCategory.SPORT),
    ("dk", WeightCategory.DK),
    ("worsted", WeightCategory.WORSTED),
    ("aran", WeightCategory.ARAN),
    ("bulky", WeightCategory.BULKY),
]

_STASH_FIRST_TRIGGERS = frozenset({"make with", "use up", "use my", "i have"})

_SWEATER_GARMENTS = frozenset(
    {"cardigan", "sweater", "pullover", "vest", "coat", "jumper"}
)


def _extract_weight(text: str) -> WeightCategory | None:
    """Return the first WeightCategory keyword found in text, or None."""
    for keyword, weight in _WEIGHT_KEYWORDS:
        if keyword in text:
            return weight
    return None


def _extract_yards(text: str) -> float | None:
    """Return the first yardage value found in text (e.g. '900 yards' → 900.0)."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:yards?|yds?)", text)
    return float(m.group(1)) if m else None


def _extract_garment_type(goal: str) -> str | None:
    """Return the first garment keyword from _SWEATER_GARMENTS found in goal, or None.

    Returns None if no garment keyword is present.
    """
    for garment in _SWEATER_GARMENTS:
        if re.search(r"\b" + garment + r"\b", goal) is not None:
            return garment
    return None


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
    """Filter stash for project-first mode, capped at 20 items.

    Excludes: weaving yarn; weight mismatches when a weight keyword is present;
    non-sweater-quantity items when a sweater-scale garment is mentioned;
    fiber mismatches for the detected garment type. Sorts by yards_total descending.
    """
    stash = state["normalized_stash"]
    goal = (state["user_goal"] or "").lower()
    weight = _extract_weight(goal)
    garment_type = _extract_garment_type(goal)

    filtered: list[StashItem] = []
    for item in stash:
        if item.is_weaving_yarn:
            continue
        if weight is not None and weight_match(item, weight) == MatchScore.MISMATCH:
            continue
        if (
            garment_type is not None
            and item.project_quantity != ProjectQuantity.SWEATER
        ):
            continue
        if (
            garment_type
            and fiber_suitability(item, garment_type) == MatchScore.MISMATCH
        ):
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


class _RecommendationList(BaseModel):
    """Wrapper model for structured LLM output — a list of exactly 3 recommendations."""

    recommendations: list[Recommendation]


_SYSTEM_PROMPT = (
    "You are a knitting project advisor. Given yarn from a user's stash and their"
    " goal, recommend exactly 3 projects. For each recommendation provide:\n"
    "- title: short project name and key features\n"
    "- rationale: 2-3 sentences explaining why this yarn suits this project\n"
    "- risks: list of 2-4 specific risks the knitter should know\n"
    "- yarn_candidate_ids: list of stash IDs from the input for this project\n"
    "Always return exactly 3 recommendations."
)


def _format_stash_for_prompt(items: list[StashItem]) -> str:
    """Format filtered stash items as a numbered list for the LLM prompt."""
    lines: list[str] = []
    for item in items:
        fiber = ", ".join(item.fiber) if item.fiber else "unknown fiber"
        colorway = f" ({item.colorway})" if item.colorway else ""
        lines.append(
            f"[ID {item.stash_id}] {item.brand} {item.yarn_name}{colorway}"
            f" — {item.weight_category.value}, {item.yards_total:.0f} yds, {fiber}"
        )
    return "\n".join(lines)


def recommend(state: GraphState) -> dict[str, Any]:
    """Call the LLM with filtered stash context and return 3 Recommendation objects.

    Uses the model named by SKEINMINDER_MODEL env var (default:
    claude-haiku-4-5-20251001). The system prompt is marked for prompt caching to
    reduce cost on repeated calls.
    """
    model_name = os.getenv("SKEINMINDER_MODEL", "claude-haiku-4-5-20251001")
    client: ChatAnthropic = ChatAnthropic(model=model_name)  # type: ignore[call-arg]
    structured = client.with_structured_output(_RecommendationList)

    stash_summary = _format_stash_for_prompt(state["filtered_stash"])

    if state["mode"] == "project_first":
        human_text = f"Goal: {state['user_goal']}\n\nAvailable yarn:\n{stash_summary}"
    else:
        human_text = (
            f"Yarn in stash:\n{stash_summary}\n\n"
            "What projects would work well with this yarn?"
        )

    messages = [
        SystemMessage(
            content=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        ),
        HumanMessage(content=human_text),
    ]

    result: _RecommendationList = structured.invoke(messages)  # type: ignore[assignment]
    return {"recommendations": result.recommendations}


def format_output(state: GraphState) -> dict[str, Any]:
    """Format recommendations as a plain-text CLI report.

    Resolves yarn_candidate_ids back to yarn names using normalized_stash.
    """
    recs = state["recommendations"] or []
    stash_by_id = {item.stash_id: item for item in state["normalized_stash"]}

    lines: list[str] = ["Project recommendations", "─" * 40]
    for i, rec in enumerate(recs, 1):
        lines.append(f"\n{i}. {rec.title}")
        lines.append(f"   {rec.rationale}")
        if rec.risks:
            lines.append("   Risks:")
            for risk in rec.risks:
                lines.append(f"     • {risk}")
        if rec.yarn_candidate_ids:
            yarn_names: list[str] = []
            for sid in rec.yarn_candidate_ids:
                item = stash_by_id.get(sid)
                if item:
                    yarn_names.append(f"{item.brand} {item.yarn_name}")
            if yarn_names:
                lines.append(f"   Yarn: {', '.join(yarn_names)}")

    return {"formatted_output": "\n".join(lines)}
