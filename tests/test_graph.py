from __future__ import annotations

from typing import Any, cast
from unittest.mock import patch

from skeinminder.graph.state import GraphState, Recommendation, StashFilter
from skeinminder.ravelry.normalizer import (
    ProjectQuantity,
    StashItem,
    WeightCategory,
)


def _make_item(*, stash_id: int = 1, yards_total: float = 1000.0) -> StashItem:
    return StashItem(
        stash_id=stash_id,
        brand="Test Brand",
        yarn_name="Test Yarn",
        colorway="Mossy Green",
        weight_category=WeightCategory.WORSTED,
        fiber=["Wool"],
        color_family="Greens",
        skeins=5.0,
        yards_per_skein=yards_total / 5.0,
        yards_total=yards_total,
        grams_total=None,
        notes=None,
        project_quantity=ProjectQuantity.SWEATER,
    )


def _make_state(**overrides: Any) -> GraphState:
    state: dict[str, Any] = {
        "user_input": "I want a cardigan",
        "mode": "project_first",
        "user_goal": "I want a cardigan",
        "stash_filter": None,
        "normalized_stash": [],
        "filtered_stash": [],
        "recommendations": None,
        "requires_approval": False,
        "formatted_output": None,
        "filter_confidence": "",
        "force_recommend": False,
    }
    state.update(overrides)
    return cast(GraphState, state)


def _canned_recommendations(stash_id: int = 1) -> list[Recommendation]:
    return [
        Recommendation(
            title=f"Project {i}",
            rationale="This yarn is well suited for this project.",
            risks=["Swatch required", "Check gauge"],
            yarn_candidate_ids=[stash_id],
        )
        for i in range(1, 4)
    ]


# --- format_output ---


def test_format_output_renders_all_recommendations() -> None:
    from skeinminder.graph.nodes import format_output

    item = _make_item(stash_id=1)
    recs = _canned_recommendations(stash_id=1)

    result = format_output(_make_state(filtered_stash=[item], recommendations=recs))
    output = result["formatted_output"]
    assert isinstance(output, str)
    assert "Project 1" in output
    assert "Project 2" in output
    assert "Project 3" in output
    assert "Swatch required" in output
    assert "Test Brand Test Yarn" in output


def test_format_output_handles_empty_recommendations() -> None:
    from skeinminder.graph.nodes import format_output

    result = format_output(
        _make_state(user_input="", user_goal=None, recommendations=[])
    )
    assert isinstance(result["formatted_output"], str)


# --- full graph integration (recommend mocked) ---


def test_graph_project_first_routes_and_formats(
    normalized_stash: list[StashItem],
) -> None:
    from skeinminder.graph.graph import build_graph

    canned = _canned_recommendations(stash_id=normalized_stash[0].stash_id)

    with (
        patch("skeinminder.graph.nodes.recommend") as mock_rec,
        patch(
            "click.confirm", return_value=True
        ),  # fixture stash has no sweater-qty yarn → low-confidence path
        patch("click.echo"),
    ):
        mock_rec.return_value = {"recommendations": canned}
        graph = build_graph()
        result = graph.invoke(
            _make_state(
                user_input="I want a cozy cardigan",
                mode="",
                user_goal=None,
                normalized_stash=normalized_stash,
            )
        )

    assert result["mode"] == "project_first"
    assert result["recommendations"] is not None
    assert len(result["recommendations"]) == 3
    assert "Project 1" in result["formatted_output"]


def test_graph_stash_first_routes_and_formats(
    normalized_stash: list[StashItem],
) -> None:
    from skeinminder.graph.graph import build_graph

    canned = _canned_recommendations(stash_id=normalized_stash[0].stash_id)

    with patch("skeinminder.graph.nodes.recommend") as mock_rec:
        mock_rec.return_value = {"recommendations": canned}
        graph = build_graph()
        result = graph.invoke(
            _make_state(
                user_input="What can I make with my worsted wool?",
                mode="",
                user_goal=None,
                normalized_stash=normalized_stash,
            )
        )

    assert result["mode"] == "stash_first"
    assert result["recommendations"] is not None
    assert "Project 1" in result["formatted_output"]


# --- assess_filter_quality ---


def test_assess_filter_quality_low_when_filtered_stash_empty() -> None:
    from skeinminder.graph.nodes import assess_filter_quality

    result = assess_filter_quality(_make_state())
    assert result["filter_confidence"] == "low"


def test_assess_filter_quality_low_when_sweater_goal_has_insufficient_yards() -> None:
    from skeinminder.graph.nodes import assess_filter_quality

    small_item = _make_item(stash_id=1, yards_total=300.0)
    result = assess_filter_quality(
        _make_state(normalized_stash=[small_item], filtered_stash=[small_item])
    )
    assert result["filter_confidence"] == "low"


def test_assess_filter_quality_high_when_adequate_stash() -> None:
    from skeinminder.graph.nodes import assess_filter_quality

    item = _make_item(stash_id=1, yards_total=1000.0)
    result = assess_filter_quality(
        _make_state(normalized_stash=[item], filtered_stash=[item])
    )
    assert result["filter_confidence"] == "high"


def test_assess_filter_quality_high_for_stash_first_mode() -> None:
    from skeinminder.graph.nodes import assess_filter_quality

    item = _make_item(stash_id=1, yards_total=400.0)
    result = assess_filter_quality(
        _make_state(
            user_input="Use my worsted wool",
            mode="stash_first",
            user_goal=None,
            stash_filter=StashFilter(weight=WeightCategory.WORSTED),
            normalized_stash=[item],
            filtered_stash=[item],
        )
    )
    # stash_first has no user_goal → not a sweater goal → yardage check skipped → high
    assert result["filter_confidence"] == "high"


# --- low_confidence_output ---


def test_low_confidence_output_user_confirms() -> None:
    from skeinminder.graph.nodes import low_confidence_output

    state = _make_state(filter_confidence="low")
    with patch("click.confirm", return_value=True), patch("click.echo"):
        result = low_confidence_output(state)

    assert result["force_recommend"] is True
    assert "formatted_output" not in result


def test_low_confidence_output_user_declines() -> None:
    from skeinminder.graph.nodes import low_confidence_output

    state = _make_state(filter_confidence="low")
    with patch("click.confirm", return_value=False), patch("click.echo"):
        result = low_confidence_output(state)

    assert result["force_recommend"] is False
    assert "No recommendations generated" in result["formatted_output"]


# --- low-confidence integration path ---


def test_graph_low_confidence_user_confirms() -> None:
    from skeinminder.graph.graph import build_graph

    canned = [
        Recommendation(
            title=f"Project {i}",
            rationale="Works with available yarn.",
            risks=["Check gauge"],
            yarn_candidate_ids=[],
        )
        for i in range(1, 4)
    ]

    with (
        patch("skeinminder.graph.nodes.recommend") as mock_rec,
        patch("click.confirm", return_value=True),
        patch("click.echo"),
    ):
        mock_rec.return_value = {"recommendations": canned}
        graph = build_graph()
        result = graph.invoke(
            _make_state(
                mode="",
                user_goal=None,
                normalized_stash=[],  # empty → filtered_stash = [] → low confidence
            )
        )

    assert result["filter_confidence"] == "low"
    assert result["force_recommend"] is True
    assert result["recommendations"] is not None
    assert len(result["recommendations"]) == 3


def test_graph_low_confidence_user_declines() -> None:
    from skeinminder.graph.graph import build_graph

    with patch("click.confirm", return_value=False), patch("click.echo"):
        graph = build_graph()
        result = graph.invoke(_make_state(mode="", user_goal=None, normalized_stash=[]))

    assert result["filter_confidence"] == "low"
    assert result["force_recommend"] is False
    assert "No recommendations generated" in result["formatted_output"]
