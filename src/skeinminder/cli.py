from __future__ import annotations

from pathlib import Path

import click
from dotenv import load_dotenv

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
    items = _load_stash(fixture)
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
    from skeinminder.graph.graph import build_graph

    stash = _load_stash(fixture)
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
        }
    )
    output = result.get("formatted_output") or "No recommendations generated."
    click.echo(output)


def _load_stash(use_fixture: bool) -> list[StashItem]:
    if use_fixture:
        import json

        from skeinminder.ravelry.models import RawStashListResponse

        data = json.loads((FIXTURES_DIR / "stash_list.json").read_text())
        raw_list = RawStashListResponse.model_validate(data)
        return normalize_stash(raw_list.stash)

    from skeinminder.config import ConfigError, get_ravelry_credentials
    from skeinminder.ravelry.client import RavelryClient

    try:
        username, password = get_ravelry_credentials()
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    with RavelryClient(username=username, password=password) as client:
        user = client.get_current_user()
        raw_items = client.get_stash_list(user.username)
    return normalize_stash(raw_items)


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
