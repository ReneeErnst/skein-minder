"""Tests for the Langfuse observability module."""

from unittest.mock import MagicMock, patch

import pytest


def test_get_langfuse_client_returns_none_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    from skeinminder.observability import get_langfuse_client

    assert get_langfuse_client() is None


def test_get_langfuse_client_returns_client_with_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "test-pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "test-sk")
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")

    mock_instance = MagicMock()
    with patch(
        "skeinminder.observability.Langfuse", return_value=mock_instance
    ) as MockLangfuse:
        from skeinminder.observability import get_langfuse_client

        result = get_langfuse_client()

    assert result is mock_instance
    MockLangfuse.assert_called_once_with(
        public_key="test-pk",
        secret_key="test-sk",
        host="http://localhost:3000",
    )
