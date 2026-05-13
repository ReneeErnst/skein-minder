import pytest

from skeinminder.config import ConfigError, get_ravelry_credentials


def test_get_credentials_raises_when_username_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAVELRY_USERNAME", raising=False)
    monkeypatch.delenv("RAVELRY_PASSWORD", raising=False)
    with pytest.raises(ConfigError, match="RAVELRY_USERNAME"):
        get_ravelry_credentials()


def test_get_credentials_raises_when_password_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAVELRY_USERNAME", "user")
    monkeypatch.delenv("RAVELRY_PASSWORD", raising=False)
    with pytest.raises(ConfigError, match="RAVELRY_PASSWORD"):
        get_ravelry_credentials()


def test_get_credentials_returns_tuple(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAVELRY_USERNAME", "myuser")
    monkeypatch.setenv("RAVELRY_PASSWORD", "mypass")
    username, password = get_ravelry_credentials()
    assert username == "myuser"
    assert password == "mypass"
