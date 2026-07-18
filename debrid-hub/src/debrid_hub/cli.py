from __future__ import annotations

import asyncio
import json as _json

import typer
from rich.console import Console
from rich.table import Table

from .aggregator import Aggregator, filter_sort
from .config import get_settings
from .store import MANAGED, SecretStore, credential_status

app = typer.Typer(
    add_completion=False,
    help="Aggregate and resolve debrid links (Real-Debrid, AllDebrid, TorBox) for JDownloader2.",
    no_args_is_help=True,
)
console = Console()


def _human(n: float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _agg() -> Aggregator:
    return Aggregator(get_settings())


@app.command()
def providers():
    """Show configured providers and whether their credentials work."""

    async def run():
        a = _agg()
        try:
            return await a.health()
        finally:
            await a.aclose()

    health = asyncio.run(run())
    if not health:
        console.print("[yellow]No providers configured. Set DEBRID_*_TOKEN/APIKEY env vars.[/]")
        raise typer.Exit(1)
    for name, ok in health.items():
        dot = "[green]●[/]" if ok else "[red]○[/]"
        console.print(f"{dot} {name}")


@app.command("list")
def list_cmd(
    search: str = typer.Option(None, "--search", "-s", help="Filter by filename/host substring."),
    provider: str = typer.Option(None, "--provider", "-p", help="Only this provider."),
    kind: str = typer.Option(None, "--kind", "-k", help="download|torrent|webdl|usenet|magnet|saved."),
    sort: str = typer.Option("name", "--sort", help="name|size|host|provider|added|kind."),
    order: str = typer.Option("asc", "--order", help="asc|desc."),
    resolve: bool = typer.Option(False, "--resolve", help="Resolve direct URLs (slower, may be metered)."),
    urls_only: bool = typer.Option(False, "--urls", help="Print only direct URLs, one per line (pipe into JD2)."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON."),
):
    """List every link across your debrid accounts."""

    async def run():
        a = _agg()
        try:
            links = await a.list_links()
            items = filter_sort(links, search, provider, kind, sort, order)
            resolved: dict[str, str | None] = {}
            if resolve or urls_only:
                for l in items:
                    try:
                        resolved[l.id] = l.direct_url or await a.resolve(l.id)
                    except Exception as exc:  # noqa: BLE001
                        resolved[l.id] = None
                        if not urls_only and not json_out:
                            console.print(f"[red]resolve failed[/] {l.name}: {exc}", highlight=False)
            return items, resolved, a.errors
        finally:
            await a.aclose()

    items, resolved, errors = asyncio.run(run())

    if urls_only:
        for l in items:
            url = resolved.get(l.id) or l.direct_url
            if url:
                print(url)
        return

    if json_out:
        rows = []
        for l in items:
            d = l.to_dict()
            d["direct_url"] = resolved.get(l.id, l.direct_url)
            rows.append(d)
        print(_json.dumps(rows, indent=2))
        return

    table = Table(box=None, header_style="bold cyan")
    table.add_column("provider")
    table.add_column("name", overflow="fold", max_width=64)
    table.add_column("size", justify="right")
    table.add_column("host")
    table.add_column("kind")
    for l in items:
        table.add_row(l.provider, l.name, _human(l.size), l.host, l.kind)
    console.print(table)
    console.print(f"[dim]{len(items)} link(s)[/]")
    for name, msg in errors.items():
        console.print(f"[red]! {name}: {msg}[/]")


@app.command()
def resolve(link_id: str = typer.Argument(..., help="Opaque link id from `list --json`.")):
    """Resolve a single link id to a direct download URL."""

    async def run():
        a = _agg()
        try:
            return await a.resolve(link_id)
        finally:
            await a.aclose()

    print(asyncio.run(run()))


config_app = typer.Typer(
    help="Manage provider API keys, stored encrypted on disk.",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")


def _store() -> SecretStore:
    s = get_settings()
    return SecretStore(s.data_dir, s.secret_key)


@config_app.command("list")
def config_list():
    """Show which provider credentials are set and where they come from."""
    try:
        rows = credential_status(get_settings())
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    for r in rows:
        dot = "[green]●[/]" if r["configured"] else "[dim]○[/]"
        tag = f"[dim]({r['source']})[/]" if r["configured"] else "[dim](not set)[/]"
        console.print(f"{dot} {r['provider']} {tag}")
    console.print(f"[dim]store: {get_settings().data_dir}[/]")


@config_app.command("set")
def config_set(
    provider: str = typer.Argument(..., help=f"One of: {', '.join(MANAGED)}."),
    value: str = typer.Argument(None, help="API key/token. Omit to enter it hidden."),
):
    """Store a provider credential (encrypted at rest)."""
    if provider not in MANAGED:
        console.print(f"[red]Unknown provider '{provider}'. Choose from: {', '.join(MANAGED)}[/]")
        raise typer.Exit(1)
    if value is None:
        value = typer.prompt(f"{provider} key", hide_input=True)
    try:
        _store().set(provider, value)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(f"[green]saved[/] {provider} [dim](encrypted)[/]")


@config_app.command("remove")
def config_remove(
    provider: str = typer.Argument(..., help=f"One of: {', '.join(MANAGED)}."),
):
    """Delete a stored provider credential (env vars, if any, still apply)."""
    if provider not in MANAGED:
        console.print(f"[red]Unknown provider '{provider}'.[/]")
        raise typer.Exit(1)
    try:
        _store().delete(provider)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(f"[yellow]removed[/] {provider}")


@config_app.command("path")
def config_path():
    """Print the directory holding the encrypted credential store."""
    console.print(get_settings().data_dir)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8080, "--port"),
    reload: bool = typer.Option(False, "--reload"),
):
    """Start the web UI + REST API."""
    import uvicorn

    console.print(f"[cyan]Debrid Hub[/] on http://{host}:{port}")
    uvicorn.run("debrid_hub.api:app", host=host, port=port, reload=reload)


def main():
    app()


if __name__ == "__main__":
    main()
