"""Ravelry credentials from environment variables."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

RAVELRY_BASE_URL = "https://api.ravelry.com"


class ConfigError(Exception):
    """Raised when required environment variables are missing."""


def get_ravelry_credentials() -> tuple[str, str]:
    """Return (username, password) from RAVELRY_USERNAME and RAVELRY_PASSWORD env vars.

    Raises ConfigError if either variable is absent.
    """
    username = os.getenv("RAVELRY_USERNAME")
    password = os.getenv("RAVELRY_PASSWORD")
    if not username:
        raise ConfigError(
            "RAVELRY_USERNAME is not set. "
            "Copy .env.example to .env and fill in your credentials."
        )
    if not password:
        raise ConfigError(
            "RAVELRY_PASSWORD is not set. "
            "Copy .env.example to .env and fill in your credentials."
        )
    return username, password
