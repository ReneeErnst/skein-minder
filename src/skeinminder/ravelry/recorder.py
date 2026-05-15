"""One-shot fixture recorder.

Run with:
    uv run python -m skeinminder.ravelry.recorder

Add --raw to also save pre-Pydantic JSON for field inspection:
    uv run python -m skeinminder.ravelry.recorder --raw

Requires RAVELRY_USERNAME and RAVELRY_PASSWORD in .env.
Writes sanitized JSON to tests/fixtures/ and prints a summary.
Raw output (--raw) goes to tests/fixtures/raw/ (gitignored — personal data).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from skeinminder.config import get_ravelry_credentials
from skeinminder.ravelry.client import RavelryClient
from skeinminder.ravelry.models import RawStashItem
from skeinminder.ravelry.sanitizer import (
    sanitize_current_user,
    sanitize_stash_detail_sample,
    sanitize_stash_list,
)

FIXTURES_DIR = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures"
RAW_DIR = FIXTURES_DIR / "raw"
SAMPLE_SIZE = 5


def record(raw: bool = False) -> None:
    username, password = get_ravelry_credentials()
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Recording fixtures for {username!r} → {FIXTURES_DIR}")

    with RavelryClient(username=username, password=password) as client:
        # current_user
        print("  GET /current_user.json ...")
        user = client.get_current_user()
        current_user_raw = {"user": user.model_dump()}
        sanitized_user = sanitize_current_user(current_user_raw)
        _write(FIXTURES_DIR / "current_user.json", sanitized_user)
        print("    → saved (username redacted)")

        ravelry_username = user.username

        # stash list
        print(f"  GET /people/{ravelry_username}/stash/list.json (all pages) ...")
        stash_items = client.get_stash_list(ravelry_username)
        stash_list_raw = {
            "stash": [item.model_dump() for item in stash_items],
            "paginator": {
                "page": 1,
                "page_size": 100,
                "results": len(stash_items),
                "pages": 1,
                "last_page": 1,
            },
        }
        sanitized_list = sanitize_stash_list(stash_list_raw)
        _write(FIXTURES_DIR / "stash_list.json", sanitized_list)
        print(f"    → saved {len(stash_items)} items")

        # stash detail sample
        sample_ids = [item.id for item in stash_items[:SAMPLE_SIZE]]
        print(f"  GET stash detail for {len(sample_ids)} items ...")
        detail_items = []
        for stash_id in sample_ids:
            detail = client.get_stash_detail(ravelry_username, stash_id)
            detail_items.append(detail.model_dump())
            print(f"    → {stash_id}")
        sanitized_details = sanitize_stash_detail_sample(detail_items)
        _write(FIXTURES_DIR / "stash_detail_sample.json", sanitized_details)
        print(f"    → saved {len(sanitized_details)} detail records")

        if raw:
            _record_raw(client, ravelry_username)

    print("\nDone. Review the files in tests/fixtures/ before committing.")
    print("Check that no personal data remains, then: git add tests/fixtures/")
    print("and: git commit")


def _record_raw(client: RavelryClient, username: str) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    model_fields = set(RawStashItem.model_fields.keys())

    print("\n=== RAW CAPTURE ===")
    print(f"Saving pre-Pydantic JSON to {RAW_DIR}")
    print("These files are gitignored — they contain personal data.\n")

    # List format: first page only (we need field shapes, not all data)
    raw_list_resp = client._get(
        f"/people/{username}/stash/list.json",
        params={"page": 1, "page_size": 10},
    )
    _write(RAW_DIR / "stash_list_raw.json", raw_list_resp)
    list_items_raw = raw_list_resp.get("stash", [])
    if (
        isinstance(list_items_raw, list)
        and list_items_raw
        and isinstance(list_items_raw[0], dict)
    ):
        list_fields = set(list_items_raw[0].keys())
        print(f"List format fields:  {sorted(list_fields)}")
        print(f"  Dropped by model:  {sorted(list_fields - model_fields)}\n")

    # Detail format: sample items
    list_items: list[Any] = list_items_raw if isinstance(list_items_raw, list) else []
    sample_ids = [
        item["id"]
        for item in list_items[:SAMPLE_SIZE]
        if isinstance(item, dict) and "id" in item
    ]
    raw_details: list[Any] = []
    for stash_id in sample_ids:
        raw_detail = client._get(f"/people/{username}/stash/{stash_id}.json")
        raw_details.append(raw_detail)
        print(f"  → raw detail {stash_id}")
    _write(RAW_DIR / "stash_detail_raw.json", raw_details)

    if raw_details:
        detail_stash = raw_details[0].get("stash", {})
        if isinstance(detail_stash, dict):
            detail_fields = set(detail_stash.keys())
            print(f"\nDetail format fields: {sorted(detail_fields)}")
            print(f"  Dropped by model:   {sorted(detail_fields - model_fields)}")


def _write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record Ravelry API fixtures.")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Also save pre-Pydantic JSON to tests/fixtures/raw/ for field inspection",
    )
    args = parser.parse_args()
    record(raw=args.raw)
