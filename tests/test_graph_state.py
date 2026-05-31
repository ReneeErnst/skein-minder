from __future__ import annotations

from typing import get_type_hints

from skeinminder.graph.state import GraphState, Recommendation, StashFilter
from skeinminder.ravelry.normalizer import WeightCategory


def test_stash_filter_defaults_all_none() -> None:
    f = StashFilter()
    assert f.weight is None
    assert f.min_yards is None
    assert f.max_yards is None
    assert f.color_family is None
    assert f.specific_stash_id is None


def test_stash_filter_with_weight() -> None:
    f = StashFilter(weight=WeightCategory.WORSTED)
    assert f.weight == WeightCategory.WORSTED


def test_recommendation_requires_all_fields() -> None:
    rec = Recommendation(
        title="Cozy Cardigan",
        rationale="Wool worsted is ideal for structured knitwear.",
        risks=["Swatch required", "Gauge may shift with cables"],
        yarn_candidate_ids=[101, 202],
    )
    assert rec.title == "Cozy Cardigan"
    assert len(rec.risks) == 2
    assert rec.yarn_candidate_ids == [101, 202]


def test_graph_state_is_typed_dict() -> None:
    hints = get_type_hints(GraphState)
    assert "user_input" in hints
    assert "mode" in hints
    assert "filtered_stash" in hints
    assert "recommendations" in hints
    assert "formatted_output" in hints


def test_recommendation_pattern_fields_default_to_none() -> None:
    rec = Recommendation(
        title="Simple Hat",
        rationale="Works well.",
        risks=["Check gauge"],
        yarn_candidate_ids=[1],
    )
    assert rec.pattern_id is None
    assert rec.pattern_name is None
    assert rec.pattern_url is None


def test_recommendation_accepts_pattern_fields() -> None:
    rec = Recommendation(
        title="Simple Hat",
        rationale="Works well.",
        risks=["Check gauge"],
        yarn_candidate_ids=[1],
        pattern_id=1234,
        pattern_name="Simple Textured Hat",
        pattern_url="https://www.ravelry.com/patterns/library/simple-textured-hat",
    )
    assert rec.pattern_id == 1234
    assert rec.pattern_name == "Simple Textured Hat"
    assert (
        rec.pattern_url
        == "https://www.ravelry.com/patterns/library/simple-textured-hat"
    )


def test_graph_state_has_pattern_integration_keys() -> None:
    hints = get_type_hints(GraphState)
    assert "ravelry_username" in hints
    assert "use_fixture" in hints
    assert "pattern_candidates" in hints
