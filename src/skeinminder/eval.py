"""Two-layer eval suite for SkeinMinder — deterministic assertions + LLM-as-judge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_anthropic import ChatAnthropic
from langfuse.decorators import langfuse_context, observe
from pydantic import BaseModel

from skeinminder.graph.state import GraphState, Recommendation
from skeinminder.ravelry.normalizer import StashItem

_EVAL_DIR = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "eval"


class EvalInput(BaseModel, extra="ignore"):
    """Input fields for one golden example."""

    user_goal: str
    normalized_stash: list[dict[str, Any]]


class EvalExpected(BaseModel, extra="ignore"):
    """Expected output properties for one golden example."""

    recommendation_count_min: int
    recommendation_count_max: int
    stash_ids_subset_of_input: bool
    no_weight_mixing: bool
    filter_confidence: str
    pattern_ids_from_candidates: bool = False


class EvalExample(BaseModel, extra="ignore"):
    """One golden eval example — input + expected properties."""

    id: str
    input: EvalInput
    expected: EvalExpected


class AssertionResult(BaseModel):
    """Result of a single deterministic assertion check."""

    name: str
    passed: bool
    detail: str


class JudgeResult(BaseModel):
    """LLM-as-judge quality scores for a set of recommendations."""

    fit_score: int
    reasoning_score: int
    rationale: str


class EvalRunResult(BaseModel):
    """Full result for one golden example run."""

    example_id: str
    assertions: list[AssertionResult]
    judge: JudgeResult | None = None


def load_examples() -> list[EvalExample]:
    """Load all golden examples from tests/fixtures/eval/.

    Skips example-schema.json.
    """
    paths = sorted(
        p for p in _EVAL_DIR.glob("*.json") if p.name != "example-schema.json"
    )
    examples: list[EvalExample] = []
    for path in paths:
        data = json.loads(path.read_text())
        try:
            examples.append(EvalExample.model_validate(data))
        except Exception as exc:
            raise ValueError(f"Failed to parse {path.name}: {exc}") from exc
    return examples


def assert_example(example: EvalExample, state: GraphState) -> list[AssertionResult]:
    """Run four deterministic checks against example.expected.

    Returns one AssertionResult per check.
    """
    results: list[AssertionResult] = []
    exp = example.expected
    recs: list[Recommendation] = state.get("recommendations") or []

    # 1. recommendation_count
    count = len(recs)
    in_range = exp.recommendation_count_min <= count <= exp.recommendation_count_max
    results.append(
        AssertionResult(
            name="recommendation_count",
            passed=in_range,
            detail=(
                f"expected [{exp.recommendation_count_min},"
                f" {exp.recommendation_count_max}], got {count}"
            ),
        )
    )

    # 2. stash_ids_subset_of_input
    input_ids = {d["stash_id"] for d in example.input.normalized_stash}
    rec_ids = {sid for rec in recs for sid in rec.yarn_candidate_ids}
    is_subset = rec_ids <= input_ids
    results.append(
        AssertionResult(
            name="stash_ids_subset_of_input",
            passed=is_subset,
            detail=f"rogue IDs: {rec_ids - input_ids}" if not is_subset else "ok",
        )
    )

    # 3. no_weight_mixing
    if recs:
        stash_by_id = {item.stash_id: item for item in state["filtered_stash"]}
        weights = {
            stash_by_id[sid].weight_category
            for rec in recs
            for sid in rec.yarn_candidate_ids
            if sid in stash_by_id
        }
        no_mixing = len(weights) <= 1
        results.append(
            AssertionResult(
                name="no_weight_mixing",
                passed=no_mixing,
                detail=(
                    f"weights found: {[w.value for w in weights]}"
                    if not no_mixing
                    else "ok"
                ),
            )
        )
    else:
        results.append(
            AssertionResult(
                name="no_weight_mixing", passed=True, detail="ok (no recommendations)"
            )
        )

    # 4. filter_confidence
    got_conf = state["filter_confidence"]
    results.append(
        AssertionResult(
            name="filter_confidence",
            passed=got_conf == exp.filter_confidence,
            detail=f"expected '{exp.filter_confidence}', got '{got_conf}'",
        )
    )

    # 5. pattern_ids_from_candidates
    if exp.pattern_ids_from_candidates:
        candidate_ids = {p.pattern_id for p in (state["pattern_candidates"] or [])}
        rogue = [
            rec.pattern_id
            for rec in recs
            if rec.pattern_id is not None and rec.pattern_id not in candidate_ids
        ]
        results.append(
            AssertionResult(
                name="pattern_ids_from_candidates",
                passed=not rogue,
                detail=f"rogue pattern IDs: {rogue}" if rogue else "ok",
            )
        )

    return results


def run_example(example: EvalExample) -> GraphState:
    """Run the full LangGraph pipeline for one golden example.

    Stash is injected directly from the example rather than fetched from Ravelry.
    Uses fixture transport for pattern_search so no live Ravelry credentials needed.
    """
    from typing import cast

    from skeinminder.graph.graph import build_graph

    stash = [StashItem.model_validate(d) for d in example.input.normalized_stash]
    graph = build_graph()
    result = graph.invoke(
        {
            "user_input": example.input.user_goal,
            "normalized_stash": stash,
            "filtered_stash": [],
            "mode": "",
            "user_goal": None,
            "stash_filter": None,
            "recommendations": None,
            "requires_approval": False,
            "formatted_output": None,
            "filter_confidence": "",
            "force_recommend": False,
            "ravelry_username": "fixture_user",
            "use_fixture": True,
            "pattern_candidates": [],
        }
    )
    return cast(GraphState, result)


@observe(name="skeinminder-judge")
def judge_example(example: EvalExample, state: GraphState) -> JudgeResult:
    """Call the LLM to score recommendation quality on two dimensions (1–5 each).

    Logs fit_score and reasoning_score as named scores on the Langfuse trace.
    Is a no-op for Langfuse when credentials are absent.
    """
    import os

    recs: list[Recommendation] = state.get("recommendations") or []
    rec_text = (
        "\n".join(
            f"{i + 1}. {rec.title}\n   Rationale: {rec.rationale}"
            for i, rec in enumerate(recs)
        )
        or "(no recommendations)"
    )

    prompt = (
        f"User goal: {example.input.user_goal}\n\n"
        f"Recommendations:\n{rec_text}\n\n"
        "Score these recommendations on two dimensions (1–5 each):\n"
        "- fit_score: Does each recommended yarn suit the stated goal? "
        "Consider weight appropriateness, yardage adequacy, fiber suitability.\n"
        "- reasoning_score: Is each justification coherent and accurate? "
        "Penalize hallucinated yarn properties, internal contradictions, "
        "or generic answers.\n"
        "Score the set as a whole. Return fit_score and reasoning_score "
        "as integers 1-5 and a rationale string explaining your scores."
    )

    model_name = os.getenv("SKEINMINDER_MODEL", "claude-haiku-4-5-20251001")
    client: ChatAnthropic = ChatAnthropic(model=model_name)  # type: ignore[call-arg]
    structured = client.with_structured_output(JudgeResult)

    langfuse_context.update_current_observation(
        metadata={"example_id": example.id, "user_goal": example.input.user_goal}
    )

    result: JudgeResult = structured.invoke(prompt)  # type: ignore[assignment]

    langfuse_context.score_current_observation(
        name="fit_score", value=float(result.fit_score)
    )
    langfuse_context.score_current_observation(
        name="reasoning_score", value=float(result.reasoning_score)
    )

    return result


def _eval_status(result: EvalRunResult) -> str:
    if any(not a.passed for a in result.assertions):
        return "FAIL"
    if result.judge and (
        result.judge.fit_score < 3 or result.judge.reasoning_score < 3
    ):
        return "WARN"
    return "PASS"


def format_table(results: list[EvalRunResult]) -> str:
    """Render a plain-text scores table, one row per example."""
    col_id = 36
    header = (
        f"{'example_id':<{col_id}} {'assertions':<14}"
        f" {'fit':>3} {'reasoning':>9} {'status':>6}"
    )
    sep = "─" * len(header)
    rows = [header, sep]

    for r in results:
        passed = sum(1 for a in r.assertions if a.passed)
        total = len(r.assertions)
        fit = str(r.judge.fit_score) if r.judge else "—"
        reasoning = str(r.judge.reasoning_score) if r.judge else "—"
        status = _eval_status(r)
        rows.append(
            f"{r.example_id:<{col_id}} {passed}/{total:<12}"
            f" {fit:>3} {reasoning:>9} {status:>6}"
        )

    # Footer
    total_examples = len(results)
    total_assertions = sum(len(r.assertions) for r in results)
    passed_assertions = sum(sum(1 for a in r.assertions if a.passed) for r in results)
    judge_results = [r.judge for r in results if r.judge is not None]
    footer_parts = [
        f"{total_examples} examples",
        f"{passed_assertions}/{total_assertions} assertions passed",
    ]
    if judge_results:
        mean_fit = sum(j.fit_score for j in judge_results) / len(judge_results)
        mean_reasoning = sum(j.reasoning_score for j in judge_results) / len(
            judge_results
        )
        footer_parts.append(f"mean fit: {mean_fit:.1f}")
        footer_parts.append(f"mean reasoning: {mean_reasoning:.1f}")

    rows.extend([sep, " | ".join(footer_parts)])
    return "\n".join(rows)
