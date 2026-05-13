from __future__ import annotations

import logging

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from skeinminder.config import RAVELRY_BASE_URL, ConfigError
from skeinminder.ravelry.exceptions import (
    RavelryAPIError,
    RavelryAuthError,
    RavelryRateLimitError,
)
from skeinminder.ravelry.models import (
    RawCurrentUserResponse,
    RawStashDetailResponse,
    RawStashItem,
    RawStashListResponse,
    RawUser,
)

logger = logging.getLogger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, RavelryRateLimitError):
        return True
    if isinstance(exc, RavelryAPIError) and (
        exc.status_code >= 500 or exc.status_code == 0
    ):
        return True
    return False


class RavelryClient:
    def __init__(
        self,
        *,
        username: str | None = None,
        password: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if transport is None and (not username or not password):
            raise ConfigError(
                "RavelryClient requires username and password "
                "when no transport is provided. "
                "Copy .env.example to .env and fill in "
                "your Ravelry Basic Auth credentials."
            )

        auth: httpx.Auth | None = (
            httpx.BasicAuth(username, password) if username and password else None
        )

        self._client = httpx.Client(
            base_url=RAVELRY_BASE_URL,
            auth=auth,
            transport=transport,
            timeout=httpx.Timeout(10.0, read=30.0),
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    def _get(
        self, path: str, params: dict[str, str | int] | None = None
    ) -> dict[str, object]:
        logger.debug("GET %s params=%s", path, params)
        try:
            response = self._client.get(path, params=params)
        except httpx.RequestError as exc:
            raise RavelryAPIError(0, path) from exc

        if response.status_code in (401, 403):
            raise RavelryAuthError(f"Authentication failed for {path}")
        if response.status_code == 429:
            raise RavelryRateLimitError(f"Rate limited on {path}")
        if response.status_code >= 400:
            raise RavelryAPIError(response.status_code, path, response.text)

        try:
            result: dict[str, object] = response.json()
        except Exception as exc:
            raise RavelryAPIError(response.status_code, path) from exc
        return result

    def get_current_user(self) -> RawUser:
        data = self._get("/current_user.json")
        return RawCurrentUserResponse.model_validate(data).user

    def get_stash_list(self, username: str) -> list[RawStashItem]:
        items: list[RawStashItem] = []
        page = 1
        while True:
            data = self._get(
                f"/people/{username}/stash/list.json",
                params={"page": page, "page_size": 100},
            )
            parsed = RawStashListResponse.model_validate(data)
            items.extend(parsed.stash)
            if page >= parsed.paginator.pages:
                break
            page += 1
        return items

    def get_stash_detail(self, username: str, stash_id: int) -> RawStashItem:
        data = self._get(f"/people/{username}/stash/{stash_id}.json")
        return RawStashDetailResponse.model_validate(data).stash

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RavelryClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
