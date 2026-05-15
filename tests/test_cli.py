from __future__ import annotations

import pytest
from click.testing import CliRunner

from skeinminder.cli import cli


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
