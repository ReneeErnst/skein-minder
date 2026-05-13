from __future__ import annotations


class RavelryError(Exception):
    pass


class RavelryAuthError(RavelryError):
    pass


class RavelryRateLimitError(RavelryError):
    pass


class RavelryAPIError(RavelryError):
    def __init__(self, status_code: int, url: str) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(f"Ravelry API error {status_code} at {url}")


class NormalizationError(Exception):
    pass
