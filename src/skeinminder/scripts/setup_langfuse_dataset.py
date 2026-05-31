"""Bootstrap script for Langfuse: registers model pricing and creates the eval dataset.

Idempotent — safe to run multiple times. Run this once after every fresh Langfuse
deployment (including after `docker compose down -v` locally). Requires
LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in the environment.

Usage:
    uv run python -m skeinminder.scripts.setup_langfuse_dataset
"""

from __future__ import annotations

from typing import Any

from dotenv import load_dotenv

load_dotenv()

from langfuse.api.resources.commons.types.model_usage_unit import (  # noqa: E402
    ModelUsageUnit,
)
from langfuse.api.resources.models.types.create_model_request import (  # noqa: E402
    CreateModelRequest,
)

from skeinminder.eval import EvalExample, load_examples  # noqa: E402
from skeinminder.observability import get_langfuse_client  # noqa: E402

DATASET_NAME = "skeinminder-eval-v1"

# Anthropic model pricing in USD per token.
# match_pattern is a regex matched against the model name passed to Langfuse.
# Update prices here when Anthropic changes rates, and add rows for new models.
_MODELS: list[dict[str, Any]] = [
    {
        "model_name": "claude-haiku-4-5",
        "match_pattern": "(?i)^claude-haiku-4-5",
        "input_price": 0.80 / 1_000_000,
        "output_price": 4.00 / 1_000_000,
    },
    {
        "model_name": "claude-sonnet-4-6",
        "match_pattern": "(?i)^claude-sonnet-4-6",
        "input_price": 3.00 / 1_000_000,
        "output_price": 15.00 / 1_000_000,
    },
    {
        "model_name": "claude-opus-4-7",
        "match_pattern": "(?i)^claude-opus-4-7",
        "input_price": 15.00 / 1_000_000,
        "output_price": 75.00 / 1_000_000,
    },
]


def register_models(client: Any) -> None:
    """Register Anthropic model pricing in Langfuse. Skips models already present."""
    existing = {m.match_pattern for m in client.client.models.list().data}
    for model in _MODELS:
        if model["match_pattern"] in existing:
            print(f"  Model '{model['model_name']}' already registered — skipping.")
            continue
        client.client.models.create(
            request=CreateModelRequest(
                model_name=model["model_name"],
                match_pattern=model["match_pattern"],
                unit=ModelUsageUnit.TOKENS,
                input_price=model["input_price"],
                output_price=model["output_price"],
            )
        )
        print(f"  Registered model '{model['model_name']}'.")


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
    """Run all Langfuse bootstrap steps."""
    client = get_langfuse_client()
    if client is None:
        print(
            "Langfuse credentials not set. "
            "Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env."
        )
        return

    print("Registering model pricing...")
    register_models(client)

    print("Setting up eval dataset...")
    try:
        existing = client.get_dataset(DATASET_NAME)
        print(f"  Dataset '{DATASET_NAME}' already exists (id={existing.id}).")
    except Exception:
        dataset = client.create_dataset(name=DATASET_NAME)
        print(f"  Created dataset '{DATASET_NAME}' (id={dataset.id}).")

    examples = load_examples()
    upsert_dataset_items(client, DATASET_NAME, examples)
    print(f"  Upserted {len(examples)} dataset item(s).")


if __name__ == "__main__":
    main()
