from __future__ import annotations

import json
from pathlib import Path

from skeinminder.ravelry.models import (
    RawCurrentUserResponse,
    RawStashDetailResponse,
    RawStashItem,
    RawStashListResponse,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_parse_current_user() -> None:
    data = json.loads((FIXTURES_DIR / "current_user.json").read_text())
    response = RawCurrentUserResponse.model_validate(data)
    assert isinstance(response.user.username, str)
    assert isinstance(response.user.id, int)


def test_parse_stash_list() -> None:
    data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
    response = RawStashListResponse.model_validate(data)
    assert len(response.stash) == 24
    assert response.paginator.pages == 1
    assert isinstance(response.stash[0].id, int)
    assert response.stash[0].id == 26963723
    assert response.stash[0].colorway_name == "Happy Assident"


def test_parse_stash_list_item_yarn() -> None:
    data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
    response = RawStashListResponse.model_validate(data)
    yarn = response.stash[0].yarn
    assert yarn is not None
    assert yarn.yarn_company_name == "A Whimsical Wood Yarn Co."
    assert yarn.yarn_weight is not None
    assert yarn.yarn_weight.name == "Fingering"
    assert isinstance(yarn.fiber_categories, list)


def test_parse_stash_list_item_null_yarn() -> None:
    data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
    # Modify a copy to simulate missing yarn
    item_data = dict(data["stash"][0])
    item_data["yarn"] = None
    item = RawStashItem.model_validate(item_data)
    assert item.yarn is None


def test_parse_stash_detail_sample() -> None:
    data = json.loads((FIXTURES_DIR / "stash_detail_sample.json").read_text())
    response = RawStashDetailResponse.model_validate({"stash": data[0]})
    assert isinstance(response.stash.id, int)
    assert response.stash.id == 26963723
