"""
Command-line interface for Experties-CLI.

This wires the pure logic (rank_engine, duration, timer) and the storage
layer (database) into the actual `experties` commands. Kept as thin as
reasonably possible — anything that can be unit tested without a terminal
lives elsewhere; this file is mostly formatting and command wiring.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from experties.database import Database, SkillNotFoundError
from experties.duration import parse_duration
from experties.notifications import notify_all_level_ups
from experties.plugins import DEFAULT_PLUGINS_DIR, load_plugins
from experties.rank_engine import RANK_TABLE, crossed_rank_up, get_rank_status
from experties.timer import run_timer

app = typer.Typer(
    name="experties",
    help="A local, terminal-driven skill mastery and rank-progression tracker.",
    add_completion=True,
)
console = Console()

_BAR_WIDTH = 12


def _progress_bar(fraction: float | None) -> str:
    if fraction is None:
        return "[bold gold1]MAXED[/bold gold1]"
    filled = round(fraction * _BAR_WIDTH)
    return "█" * filled + "░" * (_BAR_WIDTH - filled)


def _rank_row(hours: float) -> tuple[str, str, str, str]:
    """Return (rank_name, hours_display, progress_display, hours_left_display)."""
    status = get_rank_status(hours)
    if status.next is None:
        return status.display_name, f"{hours:.1f}h", _progress_bar(None), "—"

    pct = int(round((status.progress_fraction or 0) * 100))
    progress = f"{_progress_bar(status.progress_fraction)} {pct}%"
    hours_left_display = f"{status.hours_to_next:.1f}h"
    return status.display_name, f"{hours:.1f}h", progress, hours_left_display


@app.command("list")
def list_skills() -> None:
    """Show every skill, its current rank, hours, and progress to the next rank."""
    with Database() as db:
        skills_with_hours = db.get_all_skills_with_hours()
        global_hours = db.get_global_total_hours()

    if not skills_with_hours:
        console.print(
            "[yellow]No skills yet.[/yellow] Log your first session with "
            "[bold]experties log <skill> --time <duration>[/bold]."
        )
        return

    table = Table(title="Experties")
    table.add_column("Skill", style="bold")
    table.add_column("Rank")
    table.add_column("Hours", justify="right")
    table.add_column("Progress")
    table.add_column("Left", justify="right")

    for skill, hours in skills_with_hours:
        rank_name, hours_display, progress, hours_left = _rank_row(hours)
        table.add_row(skill.name, rank_name, hours_display, progress, hours_left)

    table.add_section()
    rank_name, hours_display, progress, hours_left = _rank_row(global_hours)
    table.add_row("[bold]GLOBAL[/bold]", rank_name, hours_display, progress, hours_left)

    console.print(table)


@app.command()
def stats(
    skill: str = typer.Argument(..., help="Skill name"),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of recent sessions to show"),
) -> None:
    """Show rank progress and recent session history for one skill."""
    with Database() as db:
        try:
            hours = db.get_total_hours(skill)
            sessions = db.get_sessions(skill, limit=limit)
        except SkillNotFoundError:
            console.print(f'[red]No skill named "{skill}" yet.[/red]')
            raise typer.Exit(code=1)

    status = get_rank_status(hours)
    console.print(f"\n[bold]{skill}[/bold] — {status.display_name} ({hours:.1f}h total)")
    if status.next is not None:
        pct = int(round((status.progress_fraction or 0) * 100))
        console.print(
            f"{_progress_bar(status.progress_fraction)} {pct}% "
            f"-> {status.next.name} ({status.hours_to_next:.1f}h to go)\n"
        )
    else:
        console.print("[bold gold1]Top rank reached.[/bold gold1]\n")

    if not sessions:
        console.print("[dim]No sessions logged yet.[/dim]")
        return

    table = Table(title=f"Recent sessions ({len(sessions)})")
    table.add_column("ID", justify="right")
    table.add_column("When")
    table.add_column("Hours", justify="right")
    table.add_column("Note")
    for s in sessions:
        table.add_row(str(s.id), s.logged_at, f"{s.hours:.2f}h", s.note or "")
    console.print(table)


@app.command("rank-table")
def rank_table() -> None:
    """Show the full rank ladder and required hours for each tier."""
    with Database() as db:
        global_hours = db.get_global_total_hours()
    current_rank_name = get_rank_status(global_hours).current.name

    table = Table(title="Rank Ladder")
    table.add_column("Rank")
    table.add_column("Hours Required", justify="right")

    for rank in RANK_TABLE:
        label = rank.name
        if rank.name == current_rank_name:
            label = f"[bold reverse] {label} [/bold reverse]"
        table.add_row(label, f"{rank.threshold_hours:.0f}h")

    console.print(table)


@dataclass(frozen=True)
class _CommandInfo:
    name: str
    description: str
    example: str


_COMMAND_REFERENCE: list[_CommandInfo] = [
    _CommandInfo("list", "Show every skill, its rank, hours, and progress to the next rank.", "experties list"),
    _CommandInfo("start", "Run a live focus-session timer for a skill.", "experties start Coding"),
    _CommandInfo("log", "Manually log time spent on a skill.", 'experties log Coding --time 1h30m --note "fixed a bug"'),
    _CommandInfo("stats", "Show rank progress and recent session history for one skill.", "experties stats Coding"),
    _CommandInfo("rank-table", "Show the full rank ladder and required hours per tier.", "experties rank-table"),
    _CommandInfo("delete", "Delete a single logged session by its id.", "experties delete 12"),
    _CommandInfo("commands", "Show this list.", "experties commands"),
    _CommandInfo("plugins", "Show the plugins directory and which plugin files are loaded.", "experties plugins"),
]


@app.command()
def commands() -> None:
    """List every built-in command with a short description and example."""
    table = Table(title="Experties Commands")
    table.add_column("Command", style="bold")
    table.add_column("What it does")
    table.add_column("Example", style="dim")

    for cmd in _COMMAND_REFERENCE:
        table.add_row(cmd.name, cmd.description, cmd.example)

    console.print(table)
    console.print(
        "\n[dim]Plugin commands you've added won't show up in this curated list — "
        "run [bold]experties --help[/bold] for the complete, live list including "
        "plugins. See COMMANDS.md in the repo for full option details.[/dim]"
    )


def _commit_and_report(skill: str, hours: float, note: Optional[str]) -> None:
    """Shared by `log` and `start`: write the session, print the new
    total, and announce any rank-ups crossed."""
    with Database() as db:
        existing = db.get_skill(skill)
        hours_before = db.get_total_hours(skill) if existing is not None else 0.0
        db.log_session(skill, hours, note=note)
        hours_after = hours_before + hours

    console.print(f'[green]Logged {hours:.2f}h to "{skill}".[/green] Total: {hours_after:.1f}h')

    leveled_up = crossed_rank_up(hours_before, hours_after)
    for rank in leveled_up:
        console.print(f"[bold gold1]LEVEL UP![/bold gold1] {skill} is now [bold]{rank.name}[/bold] \U0001F389")

    notify_all_level_ups(skill, leveled_up)


@app.command()
def log(
    skill: str = typer.Argument(..., help="Skill name"),
    time: str = typer.Option(..., "--time", "-t", help='Duration, e.g. "1h30m", "1.5h", "90m"'),
    note: Optional[str] = typer.Option(None, "--note", help="Optional note about the session"),
) -> None:
    """Manually log time spent on a skill."""
    try:
        hours = parse_duration(time)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    _commit_and_report(skill, hours, note)


@app.command()
def start(skill: str = typer.Argument(..., help="Skill name")) -> None:
    """Start a live focus-session timer for a skill."""
    console.print(f'Starting timer for "{skill}"...\n')
    result = run_timer(skill)

    if result.cancelled or result.elapsed_seconds <= 0:
        console.print("[yellow]Session cancelled — nothing logged.[/yellow]")
        raise typer.Exit(code=0)

    hours = result.elapsed_seconds / 3600
    note = typer.prompt("Add a note? (press Enter to skip)", default="", show_default=False)

    _commit_and_report(skill, hours, note or None)


@app.command()
def delete(
    session_id: int = typer.Argument(..., help="Session id to delete — find it via `experties stats <skill>`"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
) -> None:
    """Delete a single logged session by its id."""
    with Database() as db:
        session = db.get_session_by_id(session_id)
        if session is None:
            console.print(f"[red]No session with id {session_id}.[/red]")
            raise typer.Exit(code=1)

        skill = db.get_skill_by_id(session.skill_id)
        skill_name = skill.name if skill else "(unknown skill)"
        note_part = f' — "{session.note}"' if session.note else ""
        console.print(
            f'Session #{session.id}: {session.hours:.2f}h on "{skill_name}", '
            f"logged {session.logged_at}{note_part}"
        )

        if not yes and not typer.confirm("Delete this session?"):
            console.print("Cancelled.")
            raise typer.Exit(code=0)

        db.delete_session(session_id)

    console.print(f"[green]Deleted session #{session_id}.[/green]")


@app.command()
def plugins() -> None:
    """Show the plugins directory and which plugin files are currently loaded."""
    console.print(f"Plugins directory: [bold]{_effective_plugins_dir}[/bold]")
    if not _effective_plugins_dir.is_dir():
        console.print(
            "[dim]Doesn't exist yet — create it and drop a .py file in to add a command. "
            "See PLUGINS.md for the format.[/dim]"
        )
        return

    if not _loaded_plugins:
        console.print("[dim]No plugins loaded.[/dim]")
        return

    console.print(f"Loaded ({len(_loaded_plugins)}):")
    for name in _loaded_plugins:
        console.print(f"  \u2022 {name}")


# Loaded after every built-in command is registered, so a plugin can't
# accidentally shadow a built-in one without at least a warning from
# Typer/Click's own duplicate-command handling. Respects
# EXPERTIES_PLUGINS_DIR the same way database.py respects
# EXPERTIES_DB_PATH — mainly so the test suite never loads whatever
# real plugins happen to be installed on the machine running it.
_plugins_dir_override = os.environ.get("EXPERTIES_PLUGINS_DIR")
_effective_plugins_dir = Path(_plugins_dir_override) if _plugins_dir_override else DEFAULT_PLUGINS_DIR
_loaded_plugins = load_plugins(app, plugins_dir=_effective_plugins_dir)


if __name__ == "__main__":
    app()