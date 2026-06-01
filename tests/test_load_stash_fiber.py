"""Integration test: fiber data flows through enrichment and normalization."""

from __future__ import annotations

from skeinminder.ravelry.client import RavelryClient
from skeinminder.ravelry.fixture_transport import FixtureTransport
from skeinminder.ravelry.normalizer import normalize_stash
from skeinminder.ravelry.yarn_enricher import enrich_stash_with_fiber


def test_fiber_present_after_enrich_and_normalize() -> None:
    client = RavelryClient(
        username="test", password="test", transport=FixtureTransport()
    )
    raw_items = client.get_stash_list("fixture_user")

    # Before enrichment: all fiber lists are empty
    assert all(
        (item.yarn is None or item.yarn.fiber_categories == []) for item in raw_items
    )

    enrich_stash_with_fiber(raw_items, client)
    stash = normalize_stash(raw_items)

    fiber_map = {item.stash_id: item.fiber for item in stash}

    # Katahdin (stash IDs 22702197, 22702189) → yarn_id 110466 → Wool
    katahdin_1 = fiber_map.get(22702197, [])
    katahdin_2 = fiber_map.get(22702189, [])
    assert "Wool" in katahdin_1, f"Katahdin fiber: {katahdin_1}"
    assert "Wool" in katahdin_2, f"Katahdin fiber: {katahdin_2}"

    # Cotton Tale 8 (stash ID 29728024) → yarn_id 66891 → Cotton
    cotton_tale = fiber_map.get(29728024, [])
    assert "Cotton" in cotton_tale, f"Cotton Tale fiber: {cotton_tale}"
