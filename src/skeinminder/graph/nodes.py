"""Graph nodes for the SkeinMinder recommendation workflow."""

from __future__ import annotations

import os
import re
from typing import Any

import click
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langfuse.decorators import (
    langfuse_context,
    observe,
)
from pydantic import BaseModel

from skeinminder.graph.state import GraphState, Recommendation, StashFilter
from skeinminder.ravelry.normalizer import (
    MatchScore,
    ProjectQuantity,
    StashItem,
    fiber_suitability,
    find_weight_in_text,
    weight_match,
)

_STASH_FIRST_TRIGGERS = frozenset({"make with", "use up", "use my", "i have"})

_SWEATER_GARMENTS: list[str] = [
    "cardigan",
    "pullover",
    "sweater",
    "jumper",
    "vest",
    "coat",
]


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


@observe(name="supervisor")  # type: ignore[untyped-decorator]
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
            weight=find_weight_in_text(text),
            min_yards=_extract_yards(text),
        )
        langfuse_context.update_current_observation(metadata={"mode": mode})
        return {"mode": mode, "user_goal": None, "stash_filter": stash_filter}

    langfuse_context.update_current_observation(metadata={"mode": mode})
    return {"mode": mode, "user_goal": state["user_input"], "stash_filter": None}


@observe(name="project_first_filter")  # type: ignore[untyped-decorator]
def project_first_filter(state: GraphState) -> dict[str, Any]:
    """Filter stash for project-first mode, capped at 20 items.

    Excludes: weaving yarn; weight mismatches when a weight keyword is present;
    non-sweater-quantity items when a sweater-scale garment is mentioned;
    fiber mismatches for the detected garment type. Sorts by yards_total descending.
    """
    stash = state["normalized_stash"]
    goal = (state["user_goal"] or "").lower()
    weight = find_weight_in_text(goal)
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
            garment_type is not None
            and fiber_suitability(item, garment_type) == MatchScore.MISMATCH
        ):
            continue
        filtered.append(item)

    filtered.sort(key=lambda i: i.yards_total, reverse=True)
    result = filtered[:20]
    langfuse_context.update_current_observation(
        metadata={"candidate_count": len(result)}
    )
    return {"filtered_stash": result}


@observe(name="stash_first_filter")  # type: ignore[untyped-decorator]
def stash_first_filter(state: GraphState) -> dict[str, Any]:
    """Filter stash by StashFilter fields, capped at 20 items.

    Excludes weaving yarn, then applies filters in order: specific_stash_id, weight,
    min_yards, max_yards, color_family. Results are sorted by yards_total descending.
    """
    stash = state["normalized_stash"]
    f = state["stash_filter"]
    cf = (
        f.color_family.lower() if f is not None and f.color_family is not None else None
    )

    filtered: list[StashItem] = []
    for item in stash:
        if item.is_weaving_yarn:
            continue
        if f is not None:
            if f.specific_stash_id is not None and item.stash_id != f.specific_stash_id:
                continue
            if (
                f.weight is not None
                and weight_match(item, f.weight) == MatchScore.MISMATCH
            ):
                continue
            if f.min_yards is not None and item.yards_total < f.min_yards:
                continue
            if f.max_yards is not None and item.yards_total > f.max_yards:
                continue
            if cf is not None and (
                item.color_family is None or cf not in item.color_family.lower()
            ):
                continue
        filtered.append(item)

    filtered.sort(key=lambda i: i.yards_total, reverse=True)
    result = filtered[:20]
    langfuse_context.update_current_observation(
        metadata={"candidate_count": len(result)}
    )
    return {"filtered_stash": result}


@observe(name="assess_filter_quality")  # type: ignore[untyped-decorator]
def assess_filter_quality(state: GraphState) -> dict[str, Any]:
    """Assess whether filtered_stash is sufficient to support recommendations.

    Sets filter_confidence to 'low' if the filtered stash is empty, or if total
    available yardage is clearly insufficient for a sweater-scale goal (< 500 yards).
    """
    filtered = state["filtered_stash"]
    if not filtered:
        langfuse_context.update_current_observation(
            metadata={"filter_confidence": "low"}
        )
        return {"filter_confidence": "low"}
    total_yards = sum(i.yards_total for i in filtered)
    goal = (state["user_goal"] or "").lower()
    is_sweater_goal = _extract_garment_type(goal) is not None
    if is_sweater_goal and total_yards < 500:
        langfuse_context.update_current_observation(
            metadata={"filter_confidence": "low"}
        )
        return {"filter_confidence": "low"}
    langfuse_context.update_current_observation(metadata={"filter_confidence": "high"})
    return {"filter_confidence": "high"}


@observe(name="low_confidence_output")  # type: ignore[untyped-decorator]
def low_confidence_output(state: GraphState) -> dict[str, Any]:
    """Summarise what the filter found and ask the user whether to proceed anyway.

    Prints the filtered items (or a 'nothing matched' message), then prompts via
    click.confirm. Returns force_recommend=True if the user wants to continue,
    or sets formatted_output to an exit message if not.
    """
    filtered = state["filtered_stash"]

    lines = ["No strong yarn matches found for your goal."]
    if filtered:
        lines.append(f"\nFound {len(filtered)} item(s) that may not be ideal:")
        for item in filtered:
            lines.append(
                f"  • {item.brand} {item.yarn_name}"
                f" — {item.weight_category.value}, {item.yards_total:.0f} yds"
            )
    else:
        lines.append("\nNo yarn in your stash matched the filters for this goal.")

    lines.append(
        "\nNote: a future version of SkeinMinder will be able to suggest yarn"
        " to purchase."
    )
    click.echo("\n".join(lines))

    proceed = click.confirm(
        "\nGet recommendations using available yarn anyway?", default=False
    )
    if proceed:
        langfuse_context.update_current_observation(metadata={"force_recommend": True})
        return {"force_recommend": True}
    langfuse_context.update_current_observation(metadata={"force_recommend": False})
    return {
        "force_recommend": False,
        "formatted_output": (
            "No recommendations generated."
            " Try a different goal or add yarn to your stash."
        ),
    }


class _RecommendationList(BaseModel):
    """Wrapper model for structured LLM output — a list of up to 3 recommendations."""

    recommendations: list[Recommendation]


_SYSTEM_PROMPT = (
    "You are a knitting project advisor. Given yarn from a user's stash and their "
    "goal, recommend projects. For each recommendation provide:\n"
    "- title: short project name and key features\n"
    "- rationale: 2-3 sentences explaining why this yarn suits this project\n"
    "- risks: list of 2-4 specific risks the knitter should know\n"
    "- yarn_candidate_ids: list of stash IDs from the input for this project\n\n"
    "Rules:\n"
    "1. Each recommendation must use yarn of a single weight category. Never suggest "
    "combining yarns of different weights in the same garment body.\n"
    "2. Check yardage before recommending. An adult sweater needs approximately: "
    "1500+ yards at lace/fingering, 1200+ at sport, 1000+ at DK, 800+ at "
    "worsted/aran. Do not recommend a sweater if available yardage is clearly "
    "insufficient.\n"
    "3. Be honest about fiber properties. Silk and bamboo have no elasticity and "
    "provide little warmth — they suit shawls and summer garments, not warm "
    "cardigans. State this honestly in the rationale.\n"
    "4. If fewer than 3 viable recommendations exist given the constraints, return "
    "only the viable ones. Do not invent projects the yarn cannot support.\n"
    "Return as many recommendations as are genuinely feasible, up to 3."
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


@observe(name="recommend")  # type: ignore[untyped-decorator]
def recommend(state: GraphState) -> dict[str, Any]:
    """Call the LLM with filtered stash and return up to 3 Recommendation objects.

    Uses the model named by SKEINMINDER_MODEL env var (default:
    claude-haiku-4-5-20251001). The system prompt is marked for prompt caching to
    reduce cost on repeated calls. Token usage is captured via LangChain callback.
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
    langfuse_context.update_current_observation(
        metadata={"recommendation_count": len(result.recommendations)}
    )
    return {"recommendations": result.recommendations}


@observe(name="format_output")  # type: ignore[untyped-decorator]
def format_output(state: GraphState) -> dict[str, Any]:
    """Format recommendations as a plain-text CLI report.

    Resolves yarn_candidate_ids back to yarn names using normalized_stash.
    """
    recs = state["recommendations"] or []
    stash_by_id = {item.stash_id: item for item in state["filtered_stash"]}

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
