"""Command-line interface for SkeinMinder."""

from __future__ import annotations

from pathlib import Path

import click
from dotenv import load_dotenv
from langfuse.decorators import langfuse_context, observe

from skeinminder.ravelry.normalizer import ProjectQuantity, StashItem, normalize_stash

load_dotenv()  # Load environment variables from .env file if present

FIXTURES_DIR = Path(__file__).parent.parent.parent / "tests" / "fixtures"


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option(
    "--fixture",
    is_flag=True,
    help="Read from committed fixture files instead of live Ravelry.",
)
def stash(fixture: bool) -> None:
    """Print a normalized summary of your Ravelry stash."""
    items, _ = _load_stash(fixture)
    _print_summary(items)


@cli.command()
@click.argument("goal")
@click.option(
    "--fixture",
    is_flag=True,
    help="Read from committed fixture files instead of live Ravelry.",
)
def recommend(goal: str, fixture: bool) -> None:
    """Get project recommendations based on a goal or yarn description."""
    stash_items, username = _load_stash(fixture)
    output = _run_recommend(
        goal, stash_items, ravelry_username=username, use_fixture=fixture
    )
    click.echo(output)


@cli.command()
@click.option("--example-id", default=None, help="Run only this example (by id).")
def eval(example_id: str | None) -> None:
    """Run the two-layer eval suite on golden examples."""
    from skeinminder.eval import (
        EvalRunResult,
        assert_example,
        format_table,
        judge_example,
        load_examples,
        run_example,
    )

    examples = load_examples()
    if example_id is not None:
        examples = [e for e in examples if e.id == example_id]
        if not examples:
            raise click.ClickException(f"No example with id '{example_id}'")

    results: list[EvalRunResult] = []
    for example in examples:
        click.echo(f"Running {example.id}...")
        state = run_example(example)
        assertions = assert_example(example, state)
        try:
            judge = judge_example(example, state)
        except Exception as exc:
            click.echo(f"  Judge failed: {exc}", err=True)
            judge = None
        results.append(
            EvalRunResult(example_id=example.id, assertions=assertions, judge=judge)
        )

    click.echo(format_table(results))

    if any(any(not a.passed for a in r.assertions) for r in results):
        raise SystemExit(1)


@cli.command()
@click.option("--port", default=8000, show_default=True, help="Port to listen on.")
@click.option(
    "--fixture",
    is_flag=True,
    help="Use fixture stash and pattern data instead of live Ravelry API.",
)
def web(port: int, fixture: bool) -> None:
    """Start the SkeinMinder web UI."""
    import uvicorn

    from skeinminder.web.server import create_app

    stash, username = _load_stash(fixture)
    app = create_app(stash, username, use_fixture=fixture)
    click.echo(f"SkeinMinder running at http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


@observe(name="skeinminder-recommend")
def _run_recommend(
    goal: str,
    stash: list[StashItem],
    *,
    ravelry_username: str,
    use_fixture: bool,
) -> str:
    """Run the recommendation graph and return formatted output as a string."""
    from skeinminder.graph.graph import build_graph

    langfuse_context.update_current_trace(
        input={"user_goal": goal},
        tags=["cli"],
    )
    graph = build_graph()
    result = graph.invoke(
        {
            "user_input": goal,
            "normalized_stash": stash,
            "filtered_stash": [],
            "mode": "",
            "user_goal": None,
            "stash_filter": None,
            "recommendations": None,
            "requires_approval": False,
            "formatted_output": None,
            "filter_confidence": "",
            "force_recommend": False,
            "ravelry_username": ravelry_username,
            "use_fixture": use_fixture,
            "pattern_candidates": [],
        }
    )
    output: str = result.get("formatted_output") or "No recommendations generated."
    langfuse_context.update_current_trace(output={"formatted_output": output})
    return output


def _load_stash(use_fixture: bool) -> tuple[list[StashItem], str]:
    """Load stash items and return (items, ravelry_username)."""
    from skeinminder.ravelry.yarn_enricher import enrich_stash_with_fiber

    if use_fixture:
        import json

        from skeinminder.ravelry.client import RavelryClient
        from skeinminder.ravelry.fixture_transport import FixtureTransport
        from skeinminder.ravelry.models import RawStashListResponse

        data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
        raw_list = RawStashListResponse.model_validate(data)
        client = RavelryClient(
            username="fixture", password="fixture", transport=FixtureTransport()
        )
        enrich_stash_with_fiber(raw_list.stash, client)
        return normalize_stash(raw_list.stash), "fixture_user"

    from skeinminder.config import ConfigError, get_ravelry_credentials
    from skeinminder.ravelry.client import RavelryClient

    try:
        username, password = get_ravelry_credentials()
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    with RavelryClient(username=username, password=password) as client:
        user = client.get_current_user()
        raw_items = client.get_stash_list(user.username)
        enrich_stash_with_fiber(raw_items, client)
    return normalize_stash(raw_items), user.username


def _format_item(item: StashItem) -> str:
    fiber_str = ", ".join(item.fiber) if item.fiber else "unknown fiber"
    colorway = f" in {item.colorway}" if item.colorway else ""
    weight = item.weight_category.value
    return (
        f"  • {item.yarn_name}{colorway}"
        f" — {item.yards_total:.0f} yds, {weight}, {fiber_str}"
    )


def _print_summary(items: list[StashItem]) -> None:
    sweater = [i for i in items if i.project_quantity == ProjectQuantity.SWEATER]
    accessory = [i for i in items if i.project_quantity == ProjectQuantity.ACCESSORY]
    scrap = [i for i in items if i.project_quantity == ProjectQuantity.SCRAP]

    click.echo("Stash summary")
    click.echo("─" * 40)
    click.echo(f"Sweater quantities (800+ yds):       {len(sweater)} items")
    click.echo(f"Accessory quantities (200–799 yds):  {len(accessory)} items")
    click.echo(f"Scraps (< 200 yds):                  {len(scrap)} items")

    if sweater:
        click.echo("\nSweater quantities:")
        for item in sorted(sweater, key=lambda i: i.yards_total, reverse=True):
            click.echo(_format_item(item))

    if accessory:
        click.echo("\nAccessory quantities:")
        for item in sorted(accessory, key=lambda i: i.yards_total, reverse=True):
            click.echo(_format_item(item))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
