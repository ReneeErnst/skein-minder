"""Exceptions for the Ravelry API client and stash normalizer."""

from __future__ import annotations


class RavelryError(Exception):
    pass


class RavelryAuthError(RavelryError):
    pass


class RavelryRateLimitError(RavelryError):
    pass


class RavelryAPIError(RavelryError):
    def __init__(self, status_code: int, url: str, body: str = "") -> None:
        self.status_code = status_code
        self.url = url
        self.body = body
        detail = f" — {body[:200]}" if body else ""
        super().__init__(f"Ravelry API error {status_code} at {url}{detail}")


class NormalizationError(Exception):
    """Raised when a raw stash item cannot be converted to a StashItem."""
