"""Tests for the eval module."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from skeinminder.eval import (
    AssertionResult,
    EvalExample,
    EvalRunResult,
    JudgeResult,
    assert_example,
    format_table,
    judge_example,
    load_examples,
    run_example,
)
from skeinminder.graph.state import GraphState, Recommendation
from skeinminder.ravelry.normalizer import ProjectQuantity, StashItem, WeightCategory


def test_load_examples_returns_nonempty_list() -> None:
    examples = load_examples()
    assert len(examples) >= 1
    assert all(isinstance(e, EvalExample) for e in examples)
    assert all(e.id != "" for e in examples)


def _make_example(
    *,
    example_id: str = "test-example",
    user_goal: str = "I want to knit a hat",
    stash_ids: list[int] | None = None,
    recommendation_count_min: int = 1,
    recommendation_count_max: int = 3,
    filter_confidence: str = "high",
) -> EvalExample:
    ids = stash_ids or [1, 2]
    stash: list[dict[str, Any]] = [
        {
            "stash_id": sid,
            "brand": "Test",
            "yarn_name": f"Yarn {sid}",
            "colorway": "Blue",
            "weight_category": "worsted",
            "fiber": [],
            "color_family": "Blue",
            "skeins": 1.0,
            "yards_per_skein": 200.0,
            "yards_total": 200.0,
            "grams_total": 100.0,
            "notes": None,
            "project_quantity": "accessory",
            "is_weaving_yarn": False,
        }
        for sid in ids
    ]
    return EvalExample.model_validate(
        {
            "id": example_id,
            "input": {"user_goal": user_goal, "normalized_stash": stash},
            "expected": {
                "recommendation_count_min": recommendation_count_min,
                "recommendation_count_max": recommendation_count_max,
                "stash_ids_subset_of_input": True,
                "no_weight_mixing": True,
                "filter_confidence": filter_confidence,
            },
        }
    )


def _make_item(*, stash_id: int = 1, yards_total: float = 200.0) -> StashItem:
    return StashItem(
        stash_id=stash_id,
        brand="Test",
        yarn_name=f"Yarn {stash_id}",
        colorway="Blue",
        weight_category=WeightCategory.WORSTED,
        fiber=[],
        color_family="Blue",
        skeins=1.0,
        yards_per_skein=yards_total,
        yards_total=yards_total,
        grams_total=100.0,
        notes=None,
        project_quantity=ProjectQuantity.ACCESSORY,
        is_weaving_yarn=False,
    )


def _make_state(**overrides: Any) -> GraphState:
    base: dict[str, Any] = {
        "user_input": "I want to knit a hat",
        "mode": "project_first",
        "user_goal": "I want to knit a hat",
        "stash_filter": None,
        "normalized_stash": [_make_item(stash_id=1), _make_item(stash_id=2)],
        "filtered_stash": [_make_item(stash_id=1), _make_item(stash_id=2)],
        "recommendations": [
            Recommendation(
                title="Simple Hat",
                rationale="Worsted weight is perfect.",
                risks=["May be too warm"],
                yarn_candidate_ids=[1],
            )
        ],
        "requires_approval": False,
        "formatted_output": None,
        "filter_confidence": "high",
        "force_recommend": False,
    }
    base.update(overrides)
    return cast(GraphState, base)


def test_assert_example_all_pass() -> None:
    example = _make_example(stash_ids=[1, 2])
    state = _make_state()
    results = assert_example(example, state)
    assert all(r.passed for r in results), [r for r in results if not r.passed]


def test_assert_example_recommendation_count_fail() -> None:
    example = _make_example(recommendation_count_min=2, recommendation_count_max=3)
    state = _make_state(
        recommendations=[
            Recommendation(
                title="Hat", rationale="ok", risks=[], yarn_candidate_ids=[1]
            )
        ]
    )
    results = assert_example(example, state)
    failed = [r for r in results if r.name == "recommendation_count"]
    assert len(failed) == 1 and not failed[0].passed


def test_assert_example_stash_id_not_in_input() -> None:
    example = _make_example(stash_ids=[1, 2])
    # Recommendation references stash_id=99, which is not in the example stash
    state = _make_state(
        recommendations=[
            Recommendation(
                title="Hat", rationale="ok", risks=[], yarn_candidate_ids=[99]
            )
        ]
    )
    results = assert_example(example, state)
    failed = [r for r in results if r.name == "stash_ids_subset_of_input"]
    assert len(failed) == 1 and not failed[0].passed


def test_assert_example_weight_mixing_fail() -> None:
    example = _make_example(stash_ids=[1, 2])
    dk_item = StashItem(
        stash_id=2,
        brand="Test",
        yarn_name="Yarn 2",
        colorway="Blue",
        weight_category=WeightCategory.DK,
        fiber=[],
        color_family="Blue",
        skeins=1.0,
        yards_per_skein=200.0,
        yards_total=200.0,
        grams_total=100.0,
        notes=None,
        project_quantity=ProjectQuantity.ACCESSORY,
        is_weaving_yarn=False,
    )
    state = _make_state(
        filtered_stash=[_make_item(stash_id=1), dk_item],
        recommendations=[
            Recommendation(
                title="Mixed",
                rationale="ok",
                risks=[],
                yarn_candidate_ids=[1, 2],
            )
        ],
    )
    results = assert_example(example, state)
    failed = [r for r in results if r.name == "no_weight_mixing"]
    assert len(failed) == 1 and not failed[0].passed


def test_assert_example_filter_confidence_fail() -> None:
    example = _make_example(filter_confidence="high")
    state = _make_state(filter_confidence="low")
    results = assert_example(example, state)
    failed = [r for r in results if r.name == "filter_confidence"]
    assert len(failed) == 1 and not failed[0].passed


def test_run_example_returns_graph_state() -> None:
    example = _make_example(stash_ids=[1, 2])
    canned_recs = [
        Recommendation(
            title="Hat",
            rationale="Good fit.",
            risks=["Check gauge"],
            yarn_candidate_ids=[1],
        )
    ]
    with patch(
        "skeinminder.graph.nodes.recommend",
        return_value={"recommendations": canned_recs},
    ):
        state = run_example(example)
    assert state["filter_confidence"] in ("high", "low")
    assert isinstance(state["normalized_stash"], list)


def test_judge_example_returns_judge_result() -> None:
    example = _make_example()
    state = _make_state()
    canned = JudgeResult(fit_score=4, reasoning_score=3, rationale="Solid match.")

    with patch("skeinminder.eval.ChatAnthropic") as mock_cls:
        mock_client = mock_cls.return_value
        mock_structured = mock_client.with_structured_output.return_value
        mock_structured.invoke.return_value = canned
        result = judge_example(example, state)

    assert result.fit_score == 4
    assert result.reasoning_score == 3
    assert result.rationale == "Solid match."


def test_format_table_contains_expected_content() -> None:
    results = [
        EvalRunResult(
            example_id="example-one",
            assertions=[
                AssertionResult(name="recommendation_count", passed=True, detail="ok"),
                AssertionResult(name="filter_confidence", passed=True, detail="ok"),
            ],
            judge=JudgeResult(fit_score=4, reasoning_score=3, rationale="Good."),
        ),
        EvalRunResult(
            example_id="example-two",
            assertions=[
                AssertionResult(
                    name="recommendation_count",
                    passed=False,
                    detail="expected [2,3], got 1",
                ),
                AssertionResult(name="filter_confidence", passed=True, detail="ok"),
            ],
            judge=None,
        ),
    ]
    table = format_table(results)
    assert "example-one" in table
    assert "example-two" in table
    assert "PASS" in table
    assert "FAIL" in table
    assert "2 examples" in table
    assert "3/4" in table  # 3 out of 4 assertions passed


@pytest.mark.eval
@pytest.mark.parametrize("example", load_examples(), ids=lambda e: e.id)
def test_eval_full(example: EvalExample) -> None:
    """Run full graph + deterministic assertions for each golden example.

    Requires ANTHROPIC_API_KEY. Excluded from CI (addopts = -m 'not eval').
    Run manually with: uv run pytest -m eval
    """
    with patch("click.confirm", return_value=False), patch("click.echo"):
        state = run_example(example)
    results = assert_example(example, state)
    failures = [r for r in results if not r.passed]
    assert not failures, "\n".join(f"  {r.name}: {r.detail}" for r in failures)


def test_eval_cli_exits_nonzero_on_assertion_failure() -> None:
    from click.testing import CliRunner

    from skeinminder.cli import cli

    failing_example = _make_example(
        example_id="fail-example",
        recommendation_count_min=5,
        recommendation_count_max=10,
    )
    canned_recs = [
        Recommendation(title="Hat", rationale="Good.", risks=[], yarn_candidate_ids=[1])
    ]

    with (
        patch("skeinminder.eval.load_examples", return_value=[failing_example]),
        patch(
            "skeinminder.graph.nodes.recommend",
            return_value={"recommendations": canned_recs},
        ),
        patch(
            "skeinminder.eval.judge_example",
            return_value=JudgeResult(fit_score=4, reasoning_score=4, rationale="ok"),
        ),
        patch("click.confirm", return_value=False),
        patch("click.echo"),
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["eval"])

    assert result.exit_code != 0


def test_upsert_dataset_items_calls_create_for_each_example() -> None:
    from skeinminder.scripts.setup_langfuse_dataset import upsert_dataset_items

    examples = [_make_example(example_id="ex-1"), _make_example(example_id="ex-2")]
    mock_client = MagicMock()

    upsert_dataset_items(mock_client, "skeinminder-eval-v1", examples)

    assert mock_client.create_dataset_item.call_count == 2
    call_ids = [
        call.kwargs.get("id") or call.args[0]
        for call in mock_client.create_dataset_item.call_args_list
    ]
    assert "ex-1" in str(call_ids)
    assert "ex-2" in str(call_ids)
