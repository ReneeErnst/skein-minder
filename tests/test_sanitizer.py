from __future__ import annotations

from skeinminder.ravelry.sanitizer import sanitize_current_user, sanitize_stash_list


def test_sanitize_current_user_removes_personal_fields() -> None:
    data = {
        "user": {
            "id": 12345,
            "username": "realuser",
            "small_photo_url": "https://example.com/real_photo.jpg",
            "large_photo_url": "https://example.com/large.jpg",
        }
    }
    result = sanitize_current_user(data)
    assert result["user"]["username"] == "[REDACTED]"
    assert result["user"]["small_photo_url"] == "[REDACTED]"
    assert result["user"]["large_photo_url"] == "[REDACTED]"
    assert result["user"]["id"] == 12345  # id is kept (needed for tests)


def test_sanitize_stash_list_removes_notes_and_permalink() -> None:
    data = {
        "stash": [
            {
                "id": 99,
                "permalink": "realuser-my-yarn",
                "notes": "This is my personal note about this yarn",
                "colorway_name": "Moss",
                "yarn_name": "Test Yarn",
                "yarn": None,
                "skeins": 2.0,
                "stash_status": {"id": 1, "name": "stash"},
                "color_family_name": "Greens",
            }
        ],
        "paginator": {
            "page": 1,
            "page_size": 100,
            "results": 1,
            "pages": 1,
            "last_page": 1,
        },
    }
    result = sanitize_stash_list(data)
    item = result["stash"][0]
    assert item["permalink"] == "[REDACTED]"
    assert item["notes"] == "[REDACTED]"
    assert item["colorway_name"] == "Moss"  # kept
    assert item["yarn_name"] == "Test Yarn"  # kept


def test_sanitize_stash_list_preserves_yarn_data() -> None:
    data = {
        "stash": [
            {
                "id": 99,
                "permalink": "user-yarn",
                "notes": None,
                "colorway_name": "Blue",
                "yarn_name": "Merino DK",
                "yarn": {
                    "id": 5678,
                    "name": "Merino DK",
                    "yarn_company_name": "Brand Co",
                    "yarn_weight": {"id": 4, "name": "DK"},
                    "grams": 100,
                    "yardage": 250,
                    "fiber_categories": [{"id": 1, "name": "Wool"}],
                },
                "skeins": 3.0,
                "stash_status": {"id": 1, "name": "stash"},
                "color_family_name": "Blues",
            }
        ],
        "paginator": {
            "page": 1,
            "page_size": 100,
            "results": 1,
            "pages": 1,
            "last_page": 1,
        },
    }
    result = sanitize_stash_list(data)
    yarn = result["stash"][0]["yarn"]
    assert yarn["name"] == "Merino DK"
    assert yarn["yarn_company_name"] == "Brand Co"
    assert yarn["yardage"] == 250
