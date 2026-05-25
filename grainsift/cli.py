"""GrainSift CLI — grainsift start / grainsift init / grainsift status"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="grainsift",
    help="Open source, self-hosted feedback analysis pipeline.",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)


def _check_env_file() -> bool:
    env_file = Path(".env")
    if not env_file.exists():
        console.print(
            "[yellow]No .env file found in current directory.[/yellow]\n"
            "Copy .env.example to .env and add your API key:\n\n"
            "  [bold]cp .env.example .env[/bold]\n"
        )
        return False
    return True


@app.command()
def start(
    host: str = typer.Option("127.0.0.1", help="Bind address"),
    port: int = typer.Option(8000, help="Port number"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload (dev only)"),
    open_browser: bool = typer.Option(True, "--no-browser/--browser", help="Open browser on start"),
) -> None:
    """Start the GrainSift server and open the UI."""
    import uvicorn

    from grainsift import __version__
    from grainsift.config import get_settings

    _check_env_file()

    settings = get_settings()
    effective_host = host or settings.host
    effective_port = port or settings.port

    console.print(
        Panel(
            f"[bold green]GrainSift v{__version__}[/bold green]\n\n"
            f"UI:    [link]http://{effective_host}:{effective_port}[/link]\n"
            f"API:   [link]http://{effective_host}:{effective_port}/api/docs[/link]\n"
            f"Model: {settings.llm_provider} / {settings.active_model}\n"
            f"DB:    {settings.database_url}",
            title="Starting GrainSift",
            border_style="green",
        )
    )

    if open_browser and not reload:
        import threading
        import time
        import webbrowser

        def _open() -> None:
            time.sleep(1.5)
            webbrowser.open(f"http://{effective_host}:{effective_port}")

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(
        "grainsift.api.main:create_app",
        factory=True,
        host=effective_host,
        port=effective_port,
        reload=reload,
        log_level="info" if not settings.debug else "debug",
    )


@app.command()
def init() -> None:
    """Initialize a .env file from the example template."""
    env_example = Path(".env.example")
    env_file = Path(".env")

    if not env_example.exists():
        # try to find it relative to this file (installed package)
        env_example = Path(__file__).parent.parent / ".env.example"

    if env_file.exists():
        overwrite = typer.confirm(".env already exists. Overwrite?", default=False)
        if not overwrite:
            console.print("Skipped.")
            return

    if env_example.exists():
        import shutil

        shutil.copy(env_example, env_file)
        console.print("[green]Created .env from .env.example[/green]")
        console.print("Edit [bold].env[/bold] and add your API key.")
    else:
        env_file.write_text(
            "LLM_PROVIDER=anthropic\nANTHROPIC_API_KEY=sk-ant-...\n"
        )
        console.print("[green]Created minimal .env[/green] — add your API key.")


@app.command()
def status() -> None:
    """Show current configuration and database state."""
    _check_env_file()

    from grainsift import __version__
    from grainsift.config import get_settings

    try:
        settings = get_settings()
    except Exception as exc:
        err_console.print(f"[red]Config error:[/red] {exc}")
        sys.exit(1)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("Version", __version__)
    table.add_row("Provider", settings.llm_provider)
    table.add_row("Model", settings.active_model)
    table.add_row("Database", settings.database_url)
    table.add_row("Batch size", str(settings.batch_size))
    table.add_row("Confidence threshold", str(settings.confidence_threshold))

    api_key_set = bool(settings.anthropic_api_key or settings.openai_api_key or settings.gemini_api_key)
    table.add_row("API key set", "[green]yes[/green]" if api_key_set else "[red]no[/red]")

    console.print(Panel(table, title="GrainSift Status", border_style="blue"))


if __name__ == "__main__":
    app()
