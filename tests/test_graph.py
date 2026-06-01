from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from skeinminder.graph.graph import build_graph
from skeinminder.graph.nodes import (
    _format_stash_for_prompt,
    assess_filter_quality,
    format_output,
    low_confidence_output,
    pattern_search,
    recommend,
)
from skeinminder.graph.state import GraphState, Recommendation, StashFilter
from skeinminder.ravelry.normalizer import (
    ProjectQuantity,
    StashItem,
    WeightCategory,
)
from skeinminder.ravelry.patterns import (
    PatternSummary,
    RawPattern,
    RawPatternFull,
    RawPatternYarnWeight,
)


def _make_item(*, stash_id: int = 1, yards_total: float = 1000.0) -> StashItem:
    return StashItem(
        stash_id=stash_id,
        yarn_id=100,
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
        "ravelry_username": "fixture_user",
        "use_fixture": True,
        "pattern_candidates": [],
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


def _make_raw_pattern(pid: int, name: str, free: bool) -> RawPattern:
    return RawPattern(
        id=pid,
        name=name,
        permalink=name.lower().replace(" ", "-"),
        free=free,
    )


def _make_pattern_summary(
    pid: int,
    tier: str,
    yardage_min: int | None = 800,
) -> PatternSummary:
    return PatternSummary(
        pattern_id=pid,
        name=f"Pattern {pid}",
        permalink=f"pattern-{pid}",
        url=f"https://www.ravelry.com/patterns/library/pattern-{pid}",
        free=(tier == "free"),
        library_owned=(tier == "library"),
        yardage_min=yardage_min,
        yardage_max=yardage_min + 200 if yardage_min else None,
        weight_name="Worsted",
        tier=tier,  # type: ignore[arg-type]
    )


def _make_client_mock(
    *,
    library_ids: set[int],
    free_patterns: list[RawPattern],
    popular_patterns: list[RawPattern],
    detail_map: dict[int, Any],
) -> MagicMock:
    mock = MagicMock()
    mock.get_library_pattern_ids.return_value = library_ids
    mock.search_patterns.side_effect = [free_patterns, popular_patterns]
    mock.get_pattern_details.return_value = detail_map
    return mock


# --- pattern_search node ---


def test_pattern_search_happy_path_fixture_transport() -> None:
    """All 4 API calls succeed via FixtureTransport; assert tier ordering and cap."""
    state = _make_state(
        filtered_stash=[_make_item(stash_id=1, yards_total=1000.0)],
        user_goal="I want a cardigan",
        use_fixture=True,
        ravelry_username="fixture_user",
    )
    result = pattern_search(state)
    candidates: list[PatternSummary] = result["pattern_candidates"]

    # Fixture: library={1001,1002}, free={1001-1004}, popular={2001-2004,1002}
    # Combined unique: 1001, 1002, 1003, 1004, 2001, 2002, 2003, 2004 — 8 total
    assert len(candidates) <= 10
    assert len(candidates) > 0
    tiers = [c.tier for c in candidates]
    library_indices = [i for i, t in enumerate(tiers) if t == "library"]
    free_indices = [i for i, t in enumerate(tiers) if t == "free"]
    popular_indices = [i for i, t in enumerate(tiers) if t == "popular"]
    # Library candidates come first, then free, then popular
    if library_indices and free_indices:
        assert max(library_indices) < min(free_indices)
    if free_indices and popular_indices:
        assert max(free_indices) < min(popular_indices)
    # Library candidates correspond to IDs in {1001, 1002}
    for c in candidates:
        if c.tier == "library":
            assert c.pattern_id in {1001, 1002}


PATTERN_SEARCH_FAILURE_SCENARIOS = [
    pytest.param(
        {
            "description": "library_failure_only",
            "library_ids": set(),  # graceful degradation: empty set
            "free_patterns": [
                _make_raw_pattern(101, "Free Hat", True),
                _make_raw_pattern(102, "Free Scarf", True),
            ],
            "popular_patterns": [
                _make_raw_pattern(201, "Popular Cardigan", False),
            ],
            "detail_map": {
                101: RawPatternFull(
                    id=101,
                    name="Free Hat",
                    permalink="free-hat",
                    free=True,
                    yardage=200,
                    yardage_max=300,
                    yarn_weight=RawPatternYarnWeight(id=1, name="Worsted"),
                ),
                102: RawPatternFull(
                    id=102,
                    name="Free Scarf",
                    permalink="free-scarf",
                    free=True,
                    yardage=150,
                    yardage_max=200,
                    yarn_weight=RawPatternYarnWeight(id=1, name="Worsted"),
                ),
                201: RawPatternFull(
                    id=201,
                    name="Popular Cardigan",
                    permalink="popular-cardigan",
                    free=False,
                    yardage=900,
                    yardage_max=1100,
                    yarn_weight=RawPatternYarnWeight(id=1, name="Worsted"),
                ),
            },
            "assert_fn": lambda candidates: (
                len(candidates) == 3 and all(c.tier != "library" for c in candidates)
            ),
        },
        id="library_failure_only",
    ),
    pytest.param(
        {
            "description": "both_searches_fail",
            "library_ids": {999},
            "free_patterns": [],
            "popular_patterns": [],
            "detail_map": {},
            "assert_fn": lambda candidates: candidates == [],
        },
        id="both_searches_fail",
    ),
    pytest.param(
        {
            "description": "batch_detail_failure",
            "library_ids": set(),
            "free_patterns": [
                _make_raw_pattern(101, "Free Hat", True),
            ],
            "popular_patterns": [
                _make_raw_pattern(201, "Popular Sweater", False),
            ],
            "detail_map": {},  # empty = batch detail failed
            "assert_fn": lambda candidates: (
                len(candidates) == 2 and all(c.yardage_min is None for c in candidates)
            ),
        },
        id="batch_detail_failure",
    ),
]


@pytest.mark.parametrize("scenario", PATTERN_SEARCH_FAILURE_SCENARIOS)
def test_pattern_search_failure_scenarios(scenario: dict[str, Any]) -> None:
    state = _make_state(
        filtered_stash=[_make_item(stash_id=1, yards_total=1000.0)],
        use_fixture=True,
        ravelry_username="fixture_user",
    )
    mock_client = _make_client_mock(
        library_ids=scenario["library_ids"],
        free_patterns=scenario["free_patterns"],
        popular_patterns=scenario["popular_patterns"],
        detail_map=scenario["detail_map"],
    )
    with patch("skeinminder.graph.nodes.RavelryClient", return_value=mock_client):
        result = pattern_search(state)

    candidates = result["pattern_candidates"]
    assert scenario["assert_fn"](candidates), (
        f"Scenario '{scenario['description']}' failed: candidates={candidates}"
    )


def test_pattern_search_empty_filtered_stash() -> None:
    state = _make_state(
        filtered_stash=[],
        use_fixture=True,
        ravelry_username="fixture_user",
    )
    result = pattern_search(state)
    assert result["pattern_candidates"] == []


# --- recommend ---


def test_recommend_extracts_parsed_from_include_raw_response() -> None:
    """recommend must unpack response['parsed'] from with_structured_output.

    include_raw=True returns a dict, not the model directly.
    """
    canned = _canned_recommendations(stash_id=1)

    mock_raw = MagicMock()
    mock_raw.usage_metadata = {
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
    }
    mock_parsed = MagicMock()
    mock_parsed.recommendations = canned

    mock_structured = MagicMock()
    mock_structured.invoke.return_value = {
        "raw": mock_raw,
        "parsed": mock_parsed,
        "parsing_error": None,
    }

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured

    state = _make_state(
        filtered_stash=[_make_item(stash_id=1)],
        mode="project_first",
        user_goal="I want a cardigan",
    )

    with patch("skeinminder.graph.nodes.ChatAnthropic", return_value=mock_llm):
        result = recommend(state)

    assert result["recommendations"] == canned


def test_recommend_includes_pattern_list_when_candidates_present() -> None:
    """When pattern_candidates is non-empty, the prompt must include pattern data."""
    canned = [
        Recommendation(
            title="Cozy Hat",
            rationale="Good match.",
            risks=["Swatch required"],
            yarn_candidate_ids=[1],
            pattern_id=101,
            pattern_name="Free Hat",
            pattern_url="https://www.ravelry.com/patterns/library/free-hat",
        )
    ]
    mock_raw = MagicMock()
    mock_raw.usage_metadata = {
        "input_tokens": 50,
        "output_tokens": 20,
        "total_tokens": 70,
    }
    mock_parsed = MagicMock()
    mock_parsed.recommendations = canned

    mock_structured = MagicMock()
    mock_structured.invoke.return_value = {
        "raw": mock_raw,
        "parsed": mock_parsed,
        "parsing_error": None,
    }
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured

    candidates = [_make_pattern_summary(101, "free")]
    state = _make_state(
        filtered_stash=[_make_item(stash_id=1)],
        mode="project_first",
        user_goal="I want a hat",
        pattern_candidates=candidates,
    )

    captured_messages: list[Any] = []

    def capture_invoke(msgs: list[Any]) -> dict[str, Any]:
        captured_messages.extend(msgs)
        return {"raw": mock_raw, "parsed": mock_parsed, "parsing_error": None}

    mock_structured.invoke.side_effect = capture_invoke

    with patch("skeinminder.graph.nodes.ChatAnthropic", return_value=mock_llm):
        result = recommend(state)

    assert result["recommendations"] == canned
    human_content = captured_messages[-1].content
    assert "Available patterns:" in human_content
    assert "[P101]" in human_content


def test_recommend_omits_pattern_list_when_no_candidates() -> None:
    """When pattern_candidates is empty, the prompt must not include pattern data."""
    canned = [
        Recommendation(
            title="Cozy Hat",
            rationale="Good match.",
            risks=["Swatch required"],
            yarn_candidate_ids=[1],
        )
    ]
    mock_raw = MagicMock()
    mock_raw.usage_metadata = {
        "input_tokens": 50,
        "output_tokens": 20,
        "total_tokens": 70,
    }
    mock_parsed = MagicMock()
    mock_parsed.recommendations = canned

    mock_structured = MagicMock()
    captured_messages: list[Any] = []

    def capture_invoke(msgs: list[Any]) -> dict[str, Any]:
        captured_messages.extend(msgs)
        return {"raw": mock_raw, "parsed": mock_parsed, "parsing_error": None}

    mock_structured.invoke.side_effect = capture_invoke
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured

    state = _make_state(
        filtered_stash=[_make_item(stash_id=1)],
        mode="project_first",
        user_goal="I want a hat",
        pattern_candidates=[],
    )

    with patch("skeinminder.graph.nodes.ChatAnthropic", return_value=mock_llm):
        result = recommend(state)

    assert result["recommendations"] == canned
    human_content = captured_messages[-1].content
    assert "Available patterns:" not in human_content


# --- format_output ---


def test_format_output_renders_all_recommendations() -> None:
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
    result = format_output(
        _make_state(user_input="", user_goal=None, recommendations=[])
    )
    assert isinstance(result["formatted_output"], str)


def test_format_output_renders_pattern_line_when_fields_present() -> None:
    item = _make_item(stash_id=1)
    recs = [
        Recommendation(
            title="Simple Textured Cardigan",
            rationale="Excellent match for worsted wool.",
            risks=["Swatch required"],
            yarn_candidate_ids=[1],
            pattern_id=12345,
            pattern_name="Simple Textured Cardigan",
            pattern_url="https://www.ravelry.com/patterns/library/simple-textured-cardigan",
        )
    ]
    result = format_output(_make_state(filtered_stash=[item], recommendations=recs))
    output = result["formatted_output"]
    assert isinstance(output, str)
    assert "Simple Textured Cardigan" in output
    assert "ravelry.com/patterns/library/simple-textured-cardigan" in output
    assert "Pattern:" in output


def test_format_output_omits_pattern_line_when_fields_absent() -> None:
    item = _make_item(stash_id=1)
    recs = [
        Recommendation(
            title="Abstract Cardigan",
            rationale="Good match.",
            risks=["Check gauge"],
            yarn_candidate_ids=[1],
        )
    ]
    result = format_output(_make_state(filtered_stash=[item], recommendations=recs))
    output = result["formatted_output"]
    assert "Pattern:" not in output
    assert "Abstract Cardigan" in output


def test_format_output_deduplicates_yarn_names() -> None:
    items = [_make_item(stash_id=i) for i in range(1, 7)]
    recs = [
        Recommendation(
            title="Big Cardigan",
            rationale="Enough yarn for a sweater.",
            risks=[],
            yarn_candidate_ids=[1, 2, 3, 4, 5, 6],
        )
    ]
    result = format_output(_make_state(filtered_stash=items, recommendations=recs))
    output = result["formatted_output"]
    assert output.count("Test Brand Test Yarn") == 1


def test_format_stash_for_prompt_groups_same_yarn_colorway() -> None:
    items = [
        StashItem(
            stash_id=12345,
            yarn_id=5,
            brand="madelinetosh",
            yarn_name="High Twist DK",
            colorway="T'Challa",
            weight_category=WeightCategory.DK,
            fiber=["Wool"],
            color_family=None,
            skeins=1.0,
            yards_per_skein=200.0,
            yards_total=200.0,
            grams_total=None,
            notes=None,
            project_quantity=ProjectQuantity.SWEATER,
        ),
        StashItem(
            stash_id=12346,
            yarn_id=5,
            brand="madelinetosh",
            yarn_name="High Twist DK",
            colorway="T'Challa",
            weight_category=WeightCategory.DK,
            fiber=["Wool"],
            color_family=None,
            skeins=1.0,
            yards_per_skein=200.0,
            yards_total=200.0,
            grams_total=None,
            notes=None,
            project_quantity=ProjectQuantity.SWEATER,
        ),
    ]
    output = _format_stash_for_prompt(items)
    lines = output.splitlines()
    assert len(lines) == 1, f"Expected 1 line, got {len(lines)}: {output!r}"
    assert "12345" in lines[0]
    assert "12346" in lines[0]
    assert "400" in lines[0]  # summed yardage


# --- full graph integration (recommend mocked) ---


def test_graph_project_first_routes_and_formats(
    normalized_stash: list[StashItem],
) -> None:
    """Should route through low-confidence path and return formatted recommendations.

    The fixture stash contains no sweater-quantity yarn, so a cardigan goal triggers
    low_confidence_output. click.confirm is patched to simulate the user choosing
    to proceed anyway.
    """
    canned = _canned_recommendations(stash_id=normalized_stash[0].stash_id)

    with (
        patch("skeinminder.graph.nodes.recommend") as mock_rec,
        patch("click.confirm", return_value=True),
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

ASSESS_FILTER_QUALITY_SCENARIOS: list[dict[str, Any]] = [
    {
        "state": _make_state(),
        "expected": "low",
    },
    {
        "state": _make_state(
            normalized_stash=[_make_item(stash_id=1, yards_total=300.0)],
            filtered_stash=[_make_item(stash_id=1, yards_total=300.0)],
        ),
        "expected": "low",  # sweater goal + 300 yards < worsted threshold of 800
    },
    {
        "state": _make_state(
            normalized_stash=[_make_item(stash_id=1, yards_total=1000.0)],
            filtered_stash=[_make_item(stash_id=1, yards_total=1000.0)],
        ),
        "expected": "high",
    },
    {
        "state": _make_state(
            user_input="Use my worsted wool",
            mode="stash_first",
            user_goal=None,
            stash_filter=StashFilter(weight=WeightCategory.WORSTED),
            normalized_stash=[_make_item(stash_id=1, yards_total=400.0)],
            filtered_stash=[_make_item(stash_id=1, yards_total=400.0)],
        ),
        "expected": "high",  # stash_first has no user_goal → yardage check skipped
    },
]


@pytest.mark.parametrize("scenario", ASSESS_FILTER_QUALITY_SCENARIOS)
def test_assess_filter_quality(scenario: dict[str, Any]) -> None:
    result = assess_filter_quality(scenario["state"])
    assert result["filter_confidence"] == scenario["expected"]


# --- low_confidence_output ---


def test_low_confidence_output_user_confirms() -> None:
    state = _make_state(filter_confidence="low")
    with patch("click.confirm", return_value=True), patch("click.echo"):
        result = low_confidence_output(state)

    assert result["force_recommend"] is True
    assert "formatted_output" not in result


def test_low_confidence_output_user_declines() -> None:
    state = _make_state(filter_confidence="low")
    with patch("click.confirm", return_value=False), patch("click.echo"):
        result = low_confidence_output(state)

    assert result["force_recommend"] is False
    assert "No recommendations generated" in result["formatted_output"]


# --- low-confidence integration path ---


def test_graph_low_confidence_user_confirms() -> None:
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
    with patch("click.confirm", return_value=False), patch("click.echo"):
        graph = build_graph()
        result = graph.invoke(_make_state(mode="", user_goal=None, normalized_stash=[]))

    assert result["filter_confidence"] == "low"
    assert result["force_recommend"] is False
    assert "No recommendations generated" in result["formatted_output"]
