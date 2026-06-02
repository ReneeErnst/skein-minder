"""Graph nodes for the SkeinMinder recommendation workflow."""

from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Literal

import click
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langfuse.decorators import (
    langfuse_context,
    observe,
)
from langfuse.model import ModelUsage
from pydantic import BaseModel

from skeinminder.graph.state import GraphState, Recommendation, StashFilter
from skeinminder.ravelry.client import RavelryClient
from skeinminder.ravelry.fixture_transport import FixtureTransport
from skeinminder.ravelry.normalizer import (
    SWEATER_YARDS_BY_WEIGHT,
    WEIGHT_ORDER,
    MatchScore,
    StashItem,
    WeightCategory,
    fiber_suitability,
    find_weight_in_text,
    weight_category_from_string,
    weight_match,
)
from skeinminder.ravelry.patterns import PatternSummary, RawPattern, normalize_pattern

_STASH_FIRST_TRIGGERS = frozenset({"make with", "use up", "use my", "i have"})

_TEMPORAL_TRIGGERS = frozenset({"oldest", "longest", "been sitting", "first acquired"})

_GARMENT_TO_PC: dict[str, str] = {
    "cardigan": "cardigan",
    "pullover": "pullover",
    "jumper": "pullover",
    "sweater": "sweater",
    "vest": "vest",
    "coat": "coat",
    "jacket": "coat",
    "shrug": "shrug",
    "bolero": "shrug",
    "hat": "hat",
    "beanie": "hat",
    "toque": "hat",
    "beret": "beret-tam",
    "tam": "beret-tam",
    "scarf": "scarf",
    "cowl": "cowl",
    "shawl": "shawl-wrap",
    "wrap": "shawl-wrap",
    "poncho": "poncho",
    "cape": "cape",
    "mittens": "mittens",
    "gloves": "gloves",
    "fingerless": "fingerless",
    "socks": "socks",
    "sock": "socks",
    "slippers": "slippers",
    "legwarmers": "legwarmers",
    "headband": "headband",
    "earwarmers": "earwarmers",
    "blanket": "blanket",
    "throw": "blanket",
    "bag": "bag",
    "tote": "tote",
    "dress": "dress",
    "skirt": "skirt",
    "top": "tops",
}

_SWEATER_SCALE_GARMENTS: frozenset[str] = frozenset(
    {"cardigan", "pullover", "sweater", "vest", "coat", "shrug"}
)

_TIER_ORDER: dict[str, int] = {"library": 0, "free": 1, "popular": 2}

_DATE_SORT_SENTINEL = datetime.max.replace(tzinfo=timezone.utc)


def _group_yards(items: list[StashItem]) -> dict[tuple[int, str | None], float]:
    """Map (yarn_id, colorway) → total yards across all items in the list."""
    totals: dict[tuple[int, str | None], float] = defaultdict(float)
    for item in items:
        totals[(item.yarn_id, item.colorway)] += item.yards_total
    return dict(totals)


def _date_sort_key(item: StashItem) -> datetime:
    """Return a sortable datetime, handling naive/tz-aware/None dates.

    Naive datetimes are converted to UTC. None becomes datetime.max (sorts last).
    """
    d = item.added_date
    if d is None:
        return _DATE_SORT_SENTINEL
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _pattern_from_raw(raw: RawPattern, library_ids: set[int]) -> PatternSummary:
    """Build a PatternSummary from a list-format RawPattern (no yardage or weight)."""
    owned = raw.id in library_ids
    tier: Literal["library", "free", "popular"] = (
        "library" if owned else ("free" if raw.free else "popular")
    )
    return PatternSummary(
        pattern_id=raw.id,
        name=raw.name,
        permalink=raw.permalink,
        url=f"https://www.ravelry.com/patterns/library/{raw.permalink}",
        free=raw.free,
        library_owned=owned,
        yardage_min=None,
        yardage_max=None,
        weight_name=None,
        tier=tier,
    )


def _format_patterns_for_prompt(patterns: list[PatternSummary]) -> str:
    """Format pattern candidates as a numbered list for the LLM prompt."""
    lines: list[str] = []
    for p in patterns:
        if p.yardage_min is not None and p.yardage_max is not None:
            yardage = f"{p.yardage_min}–{p.yardage_max} yds"
        elif p.yardage_min is not None:
            yardage = f"{p.yardage_min}+ yds"
        elif p.yardage_max is not None:
            yardage = f"up to {p.yardage_max} yds"
        else:
            yardage = "yardage unknown"
        weight = p.weight_name or "weight unknown"
        lines.append(f"[P{p.pattern_id}] {p.name} — {p.tier}, {yardage}, {weight}")
    return "\n".join(lines)


def _extract_yards(text: str) -> float | None:
    """Return the first yardage value found in text (e.g. '900 yards' → 900.0)."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:yards?|yds?)", text)
    return float(m.group(1)) if m else None


def _extract_garment_pc(goal: str) -> str | None:
    """Return the Ravelry category permalink for the first garment keyword in goal.

    Scans goal for any key in _GARMENT_TO_PC using word-boundary matching and
    returns the corresponding permalink (e.g. "jumper" → "pullover"). Returns
    None if no garment keyword is present.
    """
    for keyword, permalink in _GARMENT_TO_PC.items():
        if re.search(r"\b" + keyword + r"\b", goal) is not None:
            return permalink
    return None


def _filter_by_weight_adjacency(
    summaries: list[PatternSummary],
    dominant: WeightCategory,
) -> list[PatternSummary]:
    """Remove patterns whose weight is more than one step from dominant.

    Patterns with no weight_name, or whose weight maps to UNKNOWN, pass through
    unchanged. When dominant is UNKNOWN (not in WEIGHT_ORDER), all patterns pass.
    """
    if dominant not in WEIGHT_ORDER:
        return summaries
    dominant_idx = WEIGHT_ORDER.index(dominant)
    kept: list[PatternSummary] = []
    for s in summaries:
        if s.weight_name is None:
            kept.append(s)
            continue
        pattern_weight = weight_category_from_string(s.weight_name)
        if pattern_weight not in WEIGHT_ORDER:
            kept.append(s)
            continue
        if abs(WEIGHT_ORDER.index(pattern_weight) - dominant_idx) <= 1:
            kept.append(s)
    return kept


@observe(name="supervisor")
def supervisor(state: GraphState) -> dict[str, Any]:
    """Deterministically classify mode and populate user_goal or stash_filter.

    Sets mode to "stash_first" when the input contains a trigger phrase (e.g. "use my",
    "i have"), and extracts weight/yardage into a StashFilter. Otherwise sets mode to
    "project_first" and passes the raw user input as user_goal.
    """
    langfuse_context.update_current_observation(
        input={
            "user_input": state["user_input"],
            "stash_count": len(state["normalized_stash"]),
        }
    )
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
            oldest_first=any(t in text for t in _TEMPORAL_TRIGGERS),
        )
        langfuse_context.update_current_observation(metadata={"mode": mode})
        return {"mode": mode, "user_goal": None, "stash_filter": stash_filter}

    langfuse_context.update_current_observation(metadata={"mode": mode})
    return {"mode": mode, "user_goal": state["user_input"], "stash_filter": None}


@observe(name="project_first_filter")
def project_first_filter(state: GraphState) -> dict[str, Any]:
    """Filter stash for project-first mode, capped at 20 items.

    Excludes: weaving yarn; weight mismatches when a weight keyword is present;
    fiber mismatches for the detected garment type; yarn whose group-total yardage
    falls below the per-weight sweater threshold when a sweater-scale garment is
    mentioned. Sorts by added_date ascending (oldest first) if oldest_first is True,
    otherwise by yards_total descending.
    """
    langfuse_context.update_current_observation(
        input={
            "user_goal": state.get("user_goal"),
            "stash_count": len(state["normalized_stash"]),
        }
    )
    stash = state["normalized_stash"]
    goal = (state["user_goal"] or "").lower()
    weight = find_weight_in_text(goal)
    garment_pc = _extract_garment_pc(goal)

    # First pass: per-item filters (weaving, weight, fiber).
    partially_filtered: list[StashItem] = []
    for item in stash:
        if item.is_weaving_yarn:
            continue
        if weight is not None and weight_match(item, weight) == MatchScore.MISMATCH:
            continue
        if (
            garment_pc is not None
            and fiber_suitability(item, garment_pc) == MatchScore.MISMATCH
        ):
            continue
        partially_filtered.append(item)

    # Second pass: group-total sweater threshold (sweater-scale garments only).
    group_yards = _group_yards(partially_filtered)
    filtered: list[StashItem] = []
    for item in partially_filtered:
        if garment_pc is not None and garment_pc in _SWEATER_SCALE_GARMENTS:
            group_total = group_yards[(item.yarn_id, item.colorway)]
            if group_total < SWEATER_YARDS_BY_WEIGHT[item.weight_category]:
                continue
        filtered.append(item)

    sf = state.get("stash_filter")
    if sf is not None and sf.oldest_first:
        filtered.sort(key=_date_sort_key)
    else:
        filtered.sort(key=lambda i: i.yards_total, reverse=True)
    result = filtered[:20]
    langfuse_context.update_current_observation(
        metadata={"candidate_count": len(result)}
    )
    return {"filtered_stash": result}


@observe(name="stash_first_filter")
def stash_first_filter(state: GraphState) -> dict[str, Any]:
    """Filter stash by StashFilter fields, capped at 20 items.

    Excludes weaving yarn, then applies per-item filters: specific_stash_id, weight,
    max_yards, color_family. Applies min_yards using group-total yardage so that
    multiple skeins of the same yarn count together. Results are sorted by added_date
    ascending (oldest first) if oldest_first is True, otherwise by yards_total desc.

    """
    f = state["stash_filter"]
    langfuse_context.update_current_observation(
        input={
            "stash_filter": f.model_dump() if f is not None else None,
            "stash_count": len(state["normalized_stash"]),
        }
    )
    stash = state["normalized_stash"]
    cf = (
        f.color_family.lower() if f is not None and f.color_family is not None else None
    )

    # First pass: per-item filters (weaving, stash id, weight, max_yards, color).
    partially_filtered: list[StashItem] = []
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
            if f.max_yards is not None and item.yards_total > f.max_yards:
                continue
            if cf is not None and (
                item.color_family is None or cf not in item.color_family.lower()
            ):
                continue
        partially_filtered.append(item)

    # Second pass: min_yards using group totals.
    group_yards = _group_yards(partially_filtered)
    filtered: list[StashItem] = []
    for item in partially_filtered:
        if f is not None and f.min_yards is not None:
            group_total = group_yards[(item.yarn_id, item.colorway)]
            if group_total < f.min_yards:
                continue
        filtered.append(item)

    if f is not None and f.oldest_first:
        filtered.sort(key=_date_sort_key)
    else:
        filtered.sort(key=lambda i: i.yards_total, reverse=True)
    result = filtered[:20]
    langfuse_context.update_current_observation(
        metadata={"candidate_count": len(result)}
    )
    return {"filtered_stash": result}


@observe(name="assess_filter_quality")
def assess_filter_quality(state: GraphState) -> dict[str, Any]:
    """Assess whether filtered_stash is sufficient to support recommendations.

    Sets filter_confidence to 'low' if the filtered stash is empty, or if total
    available yardage is clearly insufficient for a sweater-scale goal (< 500 yards).
    """
    filtered = state["filtered_stash"]
    langfuse_context.update_current_observation(
        input={"filtered_count": len(filtered), "user_goal": state.get("user_goal")}
    )
    if not filtered:
        langfuse_context.update_current_observation(
            metadata={"filter_confidence": "low"}
        )
        return {"filter_confidence": "low"}
    total_yards = sum(i.yards_total for i in filtered)
    goal = (state["user_goal"] or "").lower()
    garment_pc = _extract_garment_pc(goal)
    is_sweater_goal = garment_pc is not None and garment_pc in _SWEATER_SCALE_GARMENTS
    if is_sweater_goal and total_yards < 500:
        langfuse_context.update_current_observation(
            metadata={"filter_confidence": "low"}
        )
        return {"filter_confidence": "low"}
    langfuse_context.update_current_observation(metadata={"filter_confidence": "high"})
    return {"filter_confidence": "high"}


@observe(name="pattern_search")
def pattern_search(state: GraphState) -> dict[str, Any]:
    """Fetch and rank Ravelry pattern candidates for the filtered stash.

    Runs four API calls (library ID collection, free search, popular search,
    batch detail), each independently graceful. Writes pattern_candidates to
    state sorted by tier (library → free → popular), capped at 10. If all
    calls fail or filtered_stash is empty, writes an empty list — recommend
    falls back to abstract archetypes.

    Langfuse metadata: candidate_count, library_owned_count, detail_enriched.
    """
    filtered = state["filtered_stash"]

    if not filtered:
        langfuse_context.update_current_observation(
            metadata={
                "candidate_count": 0,
                "library_owned_count": 0,
                "detail_enriched": False,
            }
        )
        return {"pattern_candidates": []}

    goal_text = (state.get("user_goal") or "").lower()

    # Weight priority: goal text → stash_filter → modal stash → heaviest item
    weight_cat: WeightCategory | None = find_weight_in_text(goal_text)
    if weight_cat is None and state.get("stash_filter") is not None:
        weight_cat = state["stash_filter"].weight  # type: ignore[union-attr]
    if weight_cat is None:
        counts: Counter[WeightCategory] = Counter(
            item.weight_category for item in filtered
        )
        if counts:
            weight_cat = counts.most_common(1)[0][0]
    if weight_cat is None:
        weight_cat = max(filtered, key=lambda i: i.yards_total).weight_category
    weight = weight_cat.value

    garment_pc = _extract_garment_pc(goal_text)
    query = None if garment_pc else state.get("user_goal")
    username = state["ravelry_username"]

    if state["use_fixture"]:
        client = RavelryClient(transport=FixtureTransport())
    else:
        from skeinminder.config import get_ravelry_credentials

        creds_user, password = get_ravelry_credentials()
        client = RavelryClient(username=creds_user, password=password)

    try:
        library_ids = client.get_library_pattern_ids(username)
        free_patterns = client.search_patterns(
            weight, query=query, pc=garment_pc, availability="free"
        )
        popular_patterns = client.search_patterns(
            weight, query=query, pc=garment_pc, sort="projects"
        )

        # Combine, deduplicate, preserving first-seen order (free before popular)
        seen: dict[int, RawPattern] = {}
        for p in free_patterns + popular_patterns:
            if p.id not in seen:
                seen[p.id] = p
        candidates = list(seen.values())

        if not candidates:
            langfuse_context.update_current_observation(
                metadata={
                    "candidate_count": 0,
                    "library_owned_count": 0,
                    "detail_enriched": False,
                }
            )
            return {"pattern_candidates": []}

        detail_map = client.get_pattern_details([p.id for p in candidates])
        detail_enriched = bool(detail_map)

        summaries: list[PatternSummary] = []
        library_owned_count = 0
        for raw in candidates:
            if raw.id in detail_map:
                summary = normalize_pattern(detail_map[raw.id], library_ids)
            else:
                summary = _pattern_from_raw(raw, library_ids)
            if summary.library_owned:
                library_owned_count += 1
            summaries.append(summary)

        summaries = _filter_by_weight_adjacency(summaries, weight_cat)
        summaries.sort(key=lambda s: _TIER_ORDER[s.tier])
        result_candidates = summaries[:10]

        langfuse_context.update_current_observation(
            metadata={
                "candidate_count": len(result_candidates),
                "library_owned_count": library_owned_count,
                "detail_enriched": detail_enriched,
            }
        )
        return {"pattern_candidates": result_candidates}
    finally:
        client.close()


@observe(name="low_confidence_output")
def low_confidence_output(state: GraphState) -> dict[str, Any]:
    """Summarise what the filter found and ask the user whether to proceed anyway.

    Prints the filtered items (or a 'nothing matched' message), then prompts via
    click.confirm. Returns force_recommend=True if the user wants to continue,
    or sets formatted_output to an exit message if not.
    """
    filtered = state["filtered_stash"]
    langfuse_context.update_current_observation(
        input={"filtered_count": len(filtered), "user_goal": state.get("user_goal")}
    )

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

_PATTERN_RULE = (
    "5. When patterns are provided, pair each recommendation with the "
    "highest-priority pattern (library > free > popular) whose yardage range "
    "the available yarn can meet. If no pattern fits the yarn, omit the pattern "
    "fields rather than forcing a mismatch."
)


def _format_stash_for_prompt(items: list[StashItem]) -> str:
    """Format filtered stash items as a numbered list for the LLM prompt.

    Items with the same yarn_id and colorway are grouped into one line with
    summed yardage and all stash IDs listed.
    """
    groups: dict[tuple[int, str | None], list[StashItem]] = defaultdict(list)
    for item in items:
        groups[(item.yarn_id, item.colorway)].append(item)

    lines: list[str] = []
    for group_items in groups.values():
        first = group_items[0]
        fiber = ", ".join(first.fiber) if first.fiber else "unknown fiber"
        colorway = f" ({first.colorway})" if first.colorway else ""
        total_yards = sum(i.yards_total for i in group_items)

        if len(group_items) == 1:
            id_str = f"ID {first.stash_id}"
            yards_str = f"{total_yards:.0f} yds"
        else:
            ids = ", ".join(str(i.stash_id) for i in group_items)
            id_str = f"IDs {ids}"
            all_same = all(i.yards_total == first.yards_total for i in group_items)
            if all_same:
                yards_str = (
                    f"{total_yards:.0f} yds"
                    f" ({len(group_items)} × {first.yards_total:.0f} yds)"
                )
            else:
                yards_str = f"{total_yards:.0f} yds"

        lines.append(
            f"[{id_str}] {first.brand} {first.yarn_name}{colorway}"
            f" — {first.weight_category.value}, {yards_str}, {fiber}"
        )
    return "\n".join(lines)


@observe(name="recommend", as_type="generation")
def recommend(state: GraphState) -> dict[str, Any]:
    """Call the LLM with filtered stash and return up to 3 Recommendation objects.

    Uses the model named by SKEINMINDER_MODEL env var (default:
    claude-haiku-4-5-20251001). The system prompt is marked for prompt caching to
    reduce cost on repeated calls. Token usage is read from usage_metadata on the
    raw response and reported to Langfuse via update_current_observation.
    """
    model_name = os.getenv("SKEINMINDER_MODEL", "claude-haiku-4-5-20251001")
    langfuse_context.update_current_observation(
        input={"candidate_count": len(state["filtered_stash"]), "mode": state["mode"]},
        model=model_name,
    )
    client: ChatAnthropic = ChatAnthropic(model=model_name)  # type: ignore[call-arg]

    stash_summary = _format_stash_for_prompt(state["filtered_stash"])
    pattern_candidates = state.get("pattern_candidates") or []

    if pattern_candidates:
        system_text = _SYSTEM_PROMPT + "\n" + _PATTERN_RULE
        pattern_list = _format_patterns_for_prompt(pattern_candidates)
        if state["mode"] == "project_first":
            human_text = (
                f"Goal: {state['user_goal']}\n\nAvailable yarn:\n{stash_summary}"
                f"\n\nAvailable patterns:\n{pattern_list}"
            )
        else:
            human_text = (
                f"Yarn in stash:\n{stash_summary}\n\n"
                "What projects would work well with this yarn?"
                f"\n\nAvailable patterns:\n{pattern_list}"
            )
    else:
        system_text = _SYSTEM_PROMPT
        if state["mode"] == "project_first":
            human_text = (
                f"Goal: {state['user_goal']}\n\nAvailable yarn:\n{stash_summary}"
            )
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
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        ),
        HumanMessage(content=human_text),
    ]

    structured = client.with_structured_output(_RecommendationList, include_raw=True)
    response: dict[str, Any] = structured.invoke(messages)  # type: ignore[assignment]
    result: _RecommendationList = response["parsed"]

    raw_msg = response.get("raw")
    if (
        raw_msg is not None
        and hasattr(raw_msg, "usage_metadata")
        and raw_msg.usage_metadata
    ):
        um = raw_msg.usage_metadata
        langfuse_context.update_current_observation(
            usage=ModelUsage(
                input=um.get("input_tokens", 0),
                output=um.get("output_tokens", 0),
                total=um.get("total_tokens", 0),
                unit="TOKENS",
            )
        )
    langfuse_context.update_current_observation(
        metadata={"recommendation_count": len(result.recommendations)}
    )
    return {"recommendations": result.recommendations}


@observe(name="format_output")
def format_output(state: GraphState) -> dict[str, Any]:
    """Format recommendations as a plain-text CLI report.

    Resolves yarn_candidate_ids back to yarn names using normalized_stash.
    """
    langfuse_context.update_current_observation(
        input={
            "recommendation_count": len(state["recommendations"] or []),
            "mode": state["mode"],
        }
    )
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
            seen: set[tuple[str, str]] = set()
            for sid in rec.yarn_candidate_ids:
                item = stash_by_id.get(sid)
                if item:
                    seen.add((item.brand, item.yarn_name))
            if seen:
                name_strs = [f"{b} {n}" for b, n in sorted(seen)]
                lines.append(f"   Yarn: {', '.join(name_strs)}")
        if rec.pattern_name and rec.pattern_url:
            lines.append(f"   Pattern: {rec.pattern_name} — {rec.pattern_url}")

    return {"formatted_output": "\n".join(lines)}
