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
    assert response.user.username == "testuser"
    assert response.user.id == 99999


def test_parse_stash_list() -> None:
    data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
    response = RawStashListResponse.model_validate(data)
    assert len(response.stash) == 3
    assert response.paginator.pages == 1
    assert response.stash[0].id == 10001
    assert response.stash[0].colorway_name == "Moss"


def test_parse_stash_list_item_yarn() -> None:
    data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
    response = RawStashListResponse.model_validate(data)
    yarn = response.stash[0].yarn
    assert yarn is not None
    assert yarn.yarn_company_name == "Sample Brand"
    assert yarn.yarn_weight is not None
    assert yarn.yarn_weight.name == "Worsted"
    assert len(yarn.fiber_categories) == 1
    assert yarn.fiber_categories[0].name == "Wool"


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
    assert response.stash.id == 10001
