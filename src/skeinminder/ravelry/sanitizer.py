"""Strips personal data from API responses before fixture files are committed."""

from __future__ import annotations

import copy
from typing import Any


def sanitize_current_user(data: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(data)
    user = result.get("user", {})
    for field in (
        "username",
        "permalink",
        "small_photo_url",
        "large_photo_url",
        "tiny_photo_url",
    ):
        if field in user:
            user[field] = "[REDACTED]"
    return result


def sanitize_stash_list(data: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(data)
    for item in result.get("stash", []):
        _sanitize_stash_item(item)
    return result


def sanitize_stash_detail_sample(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = copy.deepcopy(items)
    for item in result:
        _sanitize_stash_item(item)
    return result


def _sanitize_stash_item(item: dict[str, Any]) -> None:
    for field in ("permalink", "notes"):
        if item.get(field) is not None:
            item[field] = "[REDACTED]"
