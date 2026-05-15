from __future__ import annotations

import json
from pathlib import Path

from skeinminder.ravelry.models import (
    RawCurrentUserResponse,
    RawPack,
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
    assert len(response.stash) == 36
    assert response.paginator.pages == 1
    assert isinstance(response.stash[0].id, int)
    assert response.stash[0].id == 15878461
    assert response.stash[0].colorway_name == "7888 Iris"


def test_parse_stash_list_item_yarn() -> None:
    data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
    response = RawStashListResponse.model_validate(data)
    item = next(i for i in response.stash if i.id == 16182972)
    yarn = item.yarn
    assert yarn is not None
    assert yarn.yarn_company_name == "Fleece Artist"
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
    assert response.stash.id == 15952696


def test_raw_pack_parses_primary_pack() -> None:
    pack = RawPack.model_validate(
        {"id": 101, "primary_pack_id": None, "skeins": 3.5, "total_yards": 700.0}
    )
    assert pack.id == 101
    assert pack.primary_pack_id is None
    assert pack.skeins == 3.5
    assert pack.total_yards == 700.0


def test_raw_pack_parses_secondary_pack() -> None:
    pack = RawPack.model_validate(
        {"id": 102, "primary_pack_id": 101, "skeins": 3.5, "total_yards": 700.0}
    )
    assert pack.primary_pack_id == 101


def test_raw_stash_item_parses_packs() -> None:
    item = RawStashItem.model_validate(
        {
            "id": 999,
            "packs": [
                {"id": 1, "primary_pack_id": None, "skeins": 2.0},
                {"id": 2, "primary_pack_id": 1, "skeins": 2.0},
            ],
        }
    )
    assert len(item.packs) == 2
    assert item.packs[0].primary_pack_id is None
    assert item.packs[1].primary_pack_id == 1


def test_raw_stash_item_defaults_packs_to_empty_list() -> None:
    item = RawStashItem.model_validate({"id": 998})
    assert item.packs == []
