"""Export recent SkeinMinder traces from Langfuse to a JSON file.

Usage:
    uv run python -m skeinminder.scripts.export_traces
    uv run python -m skeinminder.scripts.export_traces --limit 5 --output my_traces.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from skeinminder.observability import get_langfuse_client  # noqa: E402


def _serialize(obj: object) -> object:
    """Recursively convert Langfuse SDK objects to JSON-serializable dicts."""
    if hasattr(obj, "__dict__"):
        return {k: _serialize(v) for k, v in vars(obj).items() if not k.startswith("_")}
    if hasattr(obj, "model_dump"):
        return _serialize(obj.model_dump())
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    # datetime, Decimal, etc.
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def export_traces(limit: int, output: Path) -> None:
    """Fetch the most recent traces and write them to output as JSON."""
    client = get_langfuse_client()
    if client is None:
        print(
            "Langfuse credentials not found. "
            "Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"Fetching up to {limit} recent 'skeinminder-recommend' traces from Langfuse..."
    )
    response = client.fetch_traces(name="skeinminder-recommend", limit=limit)
    traces = response.data

    if not traces:
        print("No traces found. Run 'skeinminder recommend' to generate some.")
        sys.exit(0)

    print(f"Found {len(traces)} trace(s). Fetching full detail...")

    export: list[dict[str, object]] = []
    for trace in traces:
        t = client.fetch_trace(trace.id).data
        record = {
            "id": t.id,
            "name": t.name,
            "timestamp": str(t.timestamp),
            "latency": t.latency,
            "total_cost": t.total_cost,
            "input": t.input,
            "output": t.output,
            "metadata": t.metadata,
            "scores": [_serialize(s) for s in (t.scores or [])],
            "observations": [_serialize(o) for o in (t.observations or [])],
        }
        export.append(record)
        print(f"  {t.name} — {t.id} ({len(t.observations or [])} spans)")

    output.write_text(json.dumps(export, indent=2, default=str))
    print(f"\nExported to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Langfuse traces to JSON.")
    parser.add_argument(
        "--limit", type=int, default=10, help="Number of traces to fetch (default: 10)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("traces_export.json"),
        help="Output file path (default: traces_export.json)",
    )
    args = parser.parse_args()
    export_traces(args.limit, args.output)


if __name__ == "__main__":
    main()
