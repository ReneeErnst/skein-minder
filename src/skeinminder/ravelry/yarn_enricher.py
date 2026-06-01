"""Enriches raw stash items with fiber data from the Ravelry yarn detail API.

The stash list endpoint always returns fiber_categories=[] on yarn objects.
This module fetches full yarn data in a single batch call and backfills
fiber_categories before normalize_stash() runs.
"""

from __future__ import annotations

from typing import Protocol

from skeinminder.ravelry.models import RawFiberCategory, RawStashItem, RawYarnFull


class _YarnDetailClient(Protocol):
    def get_yarn_details(self, yarn_ids: list[int]) -> dict[int, RawYarnFull]: ...


def enrich_stash_with_fiber(
    items: list[RawStashItem],
    client: _YarnDetailClient,
) -> list[RawStashItem]:
    """Populate fiber_categories on items that have an empty list.

    Collects unique yarn IDs for items missing fiber data, fetches details
    in one batch call, and backfills fiber_categories in-place.
    Items with yarn=None or already-populated fiber_categories are skipped.
    Returns the same list (mutated in place) for convenience.
    """
    yarn_ids = list(
        {
            item.yarn.id
            for item in items
            if item.yarn is not None and not item.yarn.fiber_categories
        }
    )
    if not yarn_ids:
        return items

    yarn_map = client.get_yarn_details(yarn_ids)

    for item in items:
        if item.yarn is None or item.yarn.fiber_categories:
            continue
        yarn_full = yarn_map.get(item.yarn.id)
        if yarn_full is None:
            continue
        item.yarn.fiber_categories = [
            RawFiberCategory(id=yf.fiber_category.id, name=yf.fiber_category.name)
            for yf in yarn_full.yarn_fibers
            if yf.fiber_category is not None
        ]

    return items
