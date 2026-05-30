"""Langfuse observability client for SkeinMinder.

Provides get_langfuse_client() for explicit Langfuse operations (dataset setup,
manual trace management). The @observe decorator for node instrumentation is imported
directly from langfuse.decorators in consuming modules — it is a no-op when
LANGFUSE_PUBLIC_KEY is absent.
"""

from __future__ import annotations

import os

from langfuse import Langfuse


def get_langfuse_client() -> Langfuse | None:
    """Return a configured Langfuse client, or None if credentials are absent."""
    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        return Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),
        )
    return None
