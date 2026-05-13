"""One-shot fixture recorder.

Run with:
    uv run python -m skeinminder.ravelry.recorder

Requires RAVELRY_USERNAME and RAVELRY_PASSWORD in .env.
Writes sanitized JSON to tests/fixtures/ and prints a summary.
"""

from __future__ import annotations

import json
from pathlib import Path

from skeinminder.config import get_ravelry_credentials
from skeinminder.ravelry.client import RavelryClient
from skeinminder.ravelry.sanitizer import (
    sanitize_current_user,
    sanitize_stash_detail_sample,
    sanitize_stash_list,
)

FIXTURES_DIR = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures"
SAMPLE_SIZE = 5


def record() -> None:
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

        # stash list
        print(f"  GET /stash/{username}/list.json (all pages) ...")
        stash_items = client.get_stash_list(username)
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
            detail = client.get_stash_detail(username, stash_id)
            detail_items.append(detail.model_dump())
            print(f"    → {stash_id}")
        sanitized_details = sanitize_stash_detail_sample(detail_items)
        _write(FIXTURES_DIR / "stash_detail_sample.json", sanitized_details)
        print(f"    → saved {len(sanitized_details)} detail records")

    print("\nDone. Review the files in tests/fixtures/ before committing.")
    print("Check that no personal data remains, then: git add tests/fixtures/")
    print("and: git commit")


def _write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    record()
