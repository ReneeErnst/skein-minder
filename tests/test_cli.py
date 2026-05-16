from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from skeinminder.cli import cli
from skeinminder.graph.state import Recommendation


def test_stash_fixture_flag_prints_summary() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["stash", "--fixture"])
    assert result.exit_code == 0
    assert (
        "Sweater" in result.output
        or "Accessory" in result.output
        or "Scrap" in result.output
    )


def test_stash_fixture_flag_shows_yarn_names() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["stash", "--fixture"])
    assert result.exit_code == 0
    assert "Millefiori" in result.output or "Sea Wool" in result.output


def test_stash_no_flag_fails_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAVELRY_USERNAME", raising=False)
    monkeypatch.delenv("RAVELRY_PASSWORD", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["stash"])
    assert result.exit_code != 0


def test_recommend_fixture_flag_returns_output() -> None:
    canned = [
        Recommendation(
            title=f"Project {i}",
            rationale="This yarn is ideal.",
            risks=["Swatch required"],
            yarn_candidate_ids=[],
        )
        for i in range(1, 4)
    ]

    with patch("skeinminder.graph.nodes.recommend") as mock_rec:
        mock_rec.return_value = {"recommendations": canned}
        runner = CliRunner()
        result = runner.invoke(
            cli, ["recommend", "I want a fall cardigan", "--fixture"]
        )

    assert result.exit_code == 0
    assert "Project 1" in result.output
    assert "Project 2" in result.output
    assert "Project 3" in result.output


def test_recommend_no_fixture_fails_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAVELRY_USERNAME", raising=False)
    monkeypatch.delenv("RAVELRY_PASSWORD", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["recommend", "I want a cardigan"])
    assert result.exit_code != 0
