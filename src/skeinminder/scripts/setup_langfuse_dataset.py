"""One-shot script to create the Langfuse eval dataset.

Creates the 'skeinminder-eval-v1' dataset in Langfuse and upserts golden examples
as dataset items. Idempotent — safe to run multiple times. Requires
LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in the environment (copy from
.env.example after docker compose up).

Usage:
    uv run python -m skeinminder.scripts.setup_langfuse_dataset
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from skeinminder.eval import EvalExample, load_examples
from skeinminder.observability import get_langfuse_client

if TYPE_CHECKING:
    pass

DATASET_NAME = "skeinminder-eval-v1"


def upsert_dataset_items(
    client: Any, dataset_name: str, examples: list[EvalExample]
) -> None:
    """Upsert each golden example as a Langfuse dataset item (keyed by id)."""
    for example in examples:
        client.create_dataset_item(
            dataset_name=dataset_name,
            id=example.id,
            input={"user_goal": example.input.user_goal},
            expected_output=example.expected.model_dump(),
        )


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
    except Exception:
        dataset = client.create_dataset(name=DATASET_NAME)
        print(f"Created dataset '{DATASET_NAME}' (id={dataset.id}).")

    examples = load_examples()
    upsert_dataset_items(client, DATASET_NAME, examples)
    print(f"Upserted {len(examples)} dataset item(s).")


if __name__ == "__main__":
    main()
