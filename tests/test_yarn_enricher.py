"""Tests for yarn fiber enrichment."""

from __future__ import annotations

from skeinminder.ravelry.models import (
    RawFiberCategory,
    RawStashItem,
    RawYarnFiber,
    RawYarnFull,
)
from skeinminder.ravelry.yarn_enricher import enrich_stash_with_fiber


def _make_stash_item(
    yarn_id: int, fiber_categories: list[dict[str, object]] | None = None
) -> RawStashItem:
    return RawStashItem.model_validate(
        {
            "id": yarn_id * 1000,
            "stash_status": {"id": 1, "name": "stashed"},
            "skeins": 1.0,
            "yarn": {
                "id": yarn_id,
                "name": f"Yarn {yarn_id}",
                "yarn_company_name": "Test Brand",
                "yarn_weight": {"id": 4, "name": "Worsted"},
                "grams": 100.0,
                "yardage": 200.0,
                "fiber_categories": fiber_categories or [],
            },
        }
    )


def _make_yarn_detail(yarn_id: int, fiber_names: list[str]) -> RawYarnFull:
    return RawYarnFull(
        id=yarn_id,
        name=f"Yarn {yarn_id}",
        yarn_fibers=[
            RawYarnFiber(
                id=i,
                percentage=100 // len(fiber_names),
                fiber_category=RawFiberCategory(id=i, name=name),
            )
            for i, name in enumerate(fiber_names, start=1)
        ],
    )


class FakeClient:
    """Minimal stand-in for RavelryClient — only implements get_yarn_details."""

    def __init__(self, yarn_details: dict[int, RawYarnFull]) -> None:
        self._yarn_details = yarn_details
        self.called_with: list[int] = []

    def get_yarn_details(self, yarn_ids: list[int]) -> dict[int, RawYarnFull]:
        self.called_with = list(yarn_ids)
        return {
            yid: self._yarn_details[yid]
            for yid in yarn_ids
            if yid in self._yarn_details
        }


def test_enrich_populates_fiber_categories() -> None:
    item = _make_stash_item(42)
    assert item.yarn is not None
    assert item.yarn.fiber_categories == []

    client = FakeClient({42: _make_yarn_detail(42, ["Wool"])})
    result = enrich_stash_with_fiber([item], client)

    assert result[0].yarn is not None
    assert len(result[0].yarn.fiber_categories) == 1
    assert result[0].yarn.fiber_categories[0].name == "Wool"


def test_enrich_skips_already_populated() -> None:
    item = _make_stash_item(42, fiber_categories=[{"id": 1, "name": "Cotton"}])
    assert item.yarn is not None
    assert len(item.yarn.fiber_categories) == 1

    client = FakeClient({42: _make_yarn_detail(42, ["Wool"])})
    result = enrich_stash_with_fiber([item], client)

    # Already had Cotton — should not be overwritten
    assert result[0].yarn is not None
    assert result[0].yarn.fiber_categories[0].name == "Cotton"
    assert client.called_with == []


def test_enrich_skips_items_with_no_yarn() -> None:
    item = RawStashItem.model_validate(
        {
            "id": 9999,
            "stash_status": {"id": 1, "name": "stashed"},
            "skeins": 1.0,
            "yarn": None,
        }
    )
    client = FakeClient({})
    result = enrich_stash_with_fiber([item], client)
    assert result[0].yarn is None
    assert client.called_with == []


def test_enrich_deduplicates_yarn_ids_in_batch_call() -> None:
    item_a = _make_stash_item(42)
    item_b = _make_stash_item(42)  # same yarn_id

    client = FakeClient({42: _make_yarn_detail(42, ["Wool"])})
    enrich_stash_with_fiber([item_a, item_b], client)

    assert len(client.called_with) == 1
    assert client.called_with[0] == 42


def test_enrich_handles_missing_yarn_in_response_gracefully() -> None:
    item = _make_stash_item(99)
    client = FakeClient({})  # empty — yarn 99 not in response

    result = enrich_stash_with_fiber([item], client)
    assert result[0].yarn is not None
    assert result[0].yarn.fiber_categories == []  # unchanged, no crash


def test_enrich_skips_yarn_fiber_with_null_fiber_category() -> None:
    item = _make_stash_item(42)
    yarn_with_null_fc = RawYarnFull(
        id=42,
        name="Mystery Yarn",
        yarn_fibers=[RawYarnFiber(id=1, percentage=100, fiber_category=None)],
    )
    client = FakeClient({42: yarn_with_null_fc})
    result = enrich_stash_with_fiber([item], client)
    assert result[0].yarn is not None
    assert result[0].yarn.fiber_categories == []


def test_enrich_batches_multiple_distinct_yarn_ids_in_one_call() -> None:
    item_a = _make_stash_item(10)
    item_b = _make_stash_item(20)

    client = FakeClient(
        {
            10: _make_yarn_detail(10, ["Wool"]),
            20: _make_yarn_detail(20, ["Cotton"]),
        }
    )
    enrich_stash_with_fiber([item_a, item_b], client)

    assert sorted(client.called_with) == [10, 20]
    assert item_a.yarn is not None
    assert item_b.yarn is not None
    assert item_a.yarn.fiber_categories[0].name == "Wool"
    assert item_b.yarn.fiber_categories[0].name == "Cotton"
