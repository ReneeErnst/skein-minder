"""HTTP client for the Ravelry API with Basic Auth, pagination, and retry."""

from __future__ import annotations

import logging

import httpx
from pydantic import ValidationError
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
from skeinminder.ravelry.patterns import (
    RawLibrarySearchResponse,
    RawPattern,
    RawPatternFull,
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
    """Ravelry API client using HTTP Basic Auth.

    Pass username and password for live usage, or transport= in tests to avoid
    network calls. Retries automatically on 429 and 5xx responses (3 attempts,
    exponential backoff). Supports use as a context manager.
    """

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
        """Authenticated GET; retries on 429 and 5xx responses."""
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
        """Fetch all stash items for a user, following pagination automatically."""
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

    def get_library_pattern_ids(self, username: str) -> set[int]:
        """Return the set of pattern IDs in the user's Ravelry library.

        Paginates /people/{username}/library/search.json?type=pattern using
        page_size=100. Returns an empty set on any API failure — callers treat
        absence of library data as graceful degradation, not an error.
        """
        ids: set[int] = set()
        page = 1
        try:
            while True:
                data = self._get(
                    f"/people/{username}/library/search.json",
                    params={"type": "pattern", "page": page, "page_size": 100},
                )
                parsed = RawLibrarySearchResponse.model_validate(data)
                for vol in parsed.volumes:
                    if vol.pattern_id is not None:
                        ids.add(vol.pattern_id)
                if page >= parsed.paginator.pages:
                    break
                page += 1
        except (
            RavelryAPIError,
            RavelryAuthError,
            RavelryRateLimitError,
            ValidationError,
        ):
            logger.warning(
                "Library pattern ID fetch failed on page %d;"
                " returning %d IDs collected so far.",
                page,
                len(ids),
            )
            return ids
        return ids

    def search_patterns(
        self,
        weight: str,
        query: str | None = None,
        availability: str | None = None,
        sort: str = "projects",
        page_size: int = 20,
    ) -> list[RawPattern]:
        """Search the Ravelry pattern database for knitting patterns by weight.

        Always passes craft=knitting. Returns an empty list on any API failure.

        Args:
            weight: Ravelry weight slug (e.g. "worsted", "dk").
            query: Optional goal keyword (e.g. "cardigan").
            availability: Optional filter (e.g. "free").
            sort: Sort order — "projects" (default) or "best".
            page_size: Number of results per page. Defaults to 20.
        """
        params: dict[str, str | int] = {
            "craft": "knitting",
            "weight": weight,
            "sort": sort,
            "page_size": page_size,
        }
        if query:
            params["query"] = query
        if availability:
            params["availability"] = availability

        try:
            data = self._get("/patterns/search.json", params=params)
        except (RavelryAPIError, RavelryAuthError, RavelryRateLimitError):
            logger.warning("Pattern search failed; returning empty list.")
            return []

        raw_list = data.get("patterns", [])
        if not isinstance(raw_list, list):
            return []
        result_patterns: list[RawPattern] = []
        for item in raw_list:
            try:
                result_patterns.append(RawPattern.model_validate(item))
            except ValidationError:
                logger.debug("Could not parse pattern entry; skipping.")
        return result_patterns

    def get_pattern_details(self, pattern_ids: list[int]) -> dict[int, RawPatternFull]:
        """Fetch full pattern details for a list of IDs in a single batch call.

        Calls /patterns.json?ids=ID1+ID2+... Returns a map of pattern_id to
        RawPatternFull. IDs absent from the response are simply missing from the
        map — callers handle partial results. Returns an empty dict on complete failure.
        """
        if not pattern_ids:
            return {}

        ids_param = " ".join(str(i) for i in pattern_ids)
        try:
            data = self._get("/patterns.json", params={"ids": ids_param})
        except (RavelryAPIError, RavelryAuthError, RavelryRateLimitError):
            logger.warning("Pattern detail fetch failed; returning empty dict.")
            return {}

        raw_map = data.get("patterns", {})
        if not isinstance(raw_map, dict):
            return {}
        requested = set(pattern_ids)
        result: dict[int, RawPatternFull] = {}
        for key, value in raw_map.items():
            try:
                pattern = RawPatternFull.model_validate(value)
                if pattern.id in requested:
                    result[pattern.id] = pattern
            except ValidationError:
                logger.debug("Could not parse pattern %s; skipping.", key)
        return result

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RavelryClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
