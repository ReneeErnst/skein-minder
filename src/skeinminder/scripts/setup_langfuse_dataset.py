"""One-shot script to create the Langfuse eval dataset.

Creates the 'skeinminder-eval-v1' dataset in Langfuse. Idempotent — safe to run
multiple times. Requires LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in the
environment (copy from .env.example after docker compose up).

Usage:
    uv run python -m skeinminder.scripts.setup_langfuse_dataset
"""

from __future__ import annotations

from skeinminder.observability import get_langfuse_client

DATASET_NAME = "skeinminder-eval-v1"


def main() -> None:
    client = get_langfuse_client()
    if client is None:
        print(
            "Langfuse credentials not set. "
            "Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env."
        )
        return

    try:
        existing = client.get_dataset(DATASET_NAME)
        print(f"Dataset '{DATASET_NAME}' already exists (id={existing.id}).")
        print("Nothing to do.")
    except Exception:
        dataset = client.create_dataset(name=DATASET_NAME)
        print(f"Created dataset '{DATASET_NAME}' (id={dataset.id}).")


if __name__ == "__main__":
    main()
