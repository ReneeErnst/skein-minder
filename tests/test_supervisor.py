from __future__ import annotations

import pytest

from skeinminder.graph.nodes import supervisor
from skeinminder.graph.state import GraphState
from skeinminder.ravelry.normalizer import WeightCategory


def _make_state(user_input: str) -> GraphState:
    return GraphState(
        user_input=user_input,
        mode="",
        user_goal=None,
        stash_filter=None,
        normalized_stash=[],
        filtered_stash=[],
        recommendations=None,
        requires_approval=False,
        formatted_output=None,
        filter_confidence="",
        force_recommend=False,
    )


@pytest.mark.parametrize(
    "user_input,expected_mode",
    [
        ("I want a fall cardigan", "project_first"),
        ("Help me make a cozy sweater for winter", "project_first"),
        ("I need a quick hat project, medium difficulty", "project_first"),
        ("Looking for something to finish in 6 weeks", "project_first"),
        ("What can I make with my sport weight silk?", "stash_first"),
        ("Help me use up my worsted wool", "stash_first"),
        ("I have 900 yards of DK weight yarn, what should I knit?", "stash_first"),
        ("Use my fingering weight yarn for something interesting", "stash_first"),
    ],
)
def test_supervisor_classifies_mode(user_input: str, expected_mode: str) -> None:
    result = supervisor(_make_state(user_input))
    assert result["mode"] == expected_mode


def test_supervisor_project_first_sets_user_goal() -> None:
    result = supervisor(_make_state("I want a fall cardigan"))
    assert result["user_goal"] == "I want a fall cardigan"
    assert result["stash_filter"] is None


def test_supervisor_stash_first_sets_stash_filter() -> None:
    result = supervisor(_make_state("What can I make with my sport weight silk?"))
    assert result["user_goal"] is None
    assert result["stash_filter"] is not None


def test_supervisor_stash_first_extracts_weight() -> None:
    result = supervisor(_make_state("Help me use up my worsted wool"))
    assert result["stash_filter"] is not None
    assert result["stash_filter"].weight == WeightCategory.WORSTED


def test_supervisor_stash_first_extracts_yards() -> None:
    result = supervisor(_make_state("I have 900 yards of DK weight yarn"))
    assert result["stash_filter"] is not None
    assert result["stash_filter"].min_yards == pytest.approx(900.0)


def test_supervisor_stash_first_no_weight_sets_weight_none() -> None:
    result = supervisor(_make_state("Use my yarn stash for something fun"))
    assert result["stash_filter"] is not None
    assert result["stash_filter"].weight is None
