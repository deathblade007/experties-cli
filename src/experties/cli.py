"""
Command-line interface for Experties-CLI.

This wires the pure logic (rank_engine, duration) and the storage layer
(database) into the actual `experties` commands. Kept as thin as
reasonably possible — anything that can be unit tested without a terminal
lives elsewhere; this file is mostly formatting and command wiring.

Read-only commands (list, stats, rank-table) and manual logging (log) are
here. The live timer (`experties start`) lands in a later checkpoint —
it needs sleep detection and a Rich Live display, which are enough on
their own to deserve their own module (timer.py).
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from experties.database import Database, SkillNotFoundError
from experties.duration import parse_duration
from experties.rank_engine import RANK_TABLE, crossed_rank_up, get_rank_status

app = typer.Typer(
    name="experties",
    help="A local, terminal-driven skill mastery and rank-progression tracker.",
    add_completion=True,
)
console = Console()

_BAR_WIDTH = 20


def _progress_bar(fraction: float | None) -> str:
    if fraction is None:
        return "[bold gold1]MAXED[/bold gold1]"
    filled = round(fraction * _BAR_WIDTH)
    return "█" * filled + "░" * (_BAR_WIDTH - filled)


def _rank_row(hours: float) -> tuple[str, str, str, str]:
    """Return (rank_name, hours_display, progress_display, next_display)."""
    status = get_rank_status(hours)
    if status.next is None:
        return status.current.name, f"{hours:.1f}h", _progress_bar(None), "—"

    pct = int(round((status.progress_fraction or 0) * 100))
    progress = f"{_progress_bar(status.progress_fraction)} {pct}%"
    next_display = f"{status.next.name} ({status.hours_to_next:.1f}h)"
    return status.current.name, f"{hours:.1f}h", progress, next_display


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
    table.add_column("Next")

    for skill, hours in skills_with_hours:
        rank_name, hours_display, progress, next_display = _rank_row(hours)
        table.add_row(skill.name, rank_name, hours_display, progress, next_display)

    table.add_section()
    rank_name, hours_display, progress, next_display = _rank_row(global_hours)
    table.add_row("[bold]GLOBAL[/bold]", rank_name, hours_display, progress, next_display)

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
    console.print(f"\n[bold]{skill}[/bold] — {status.current.name} ({hours:.1f}h total)")
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

    with Database() as db:
        existing = db.get_skill(skill)
        hours_before = db.get_total_hours(skill) if existing is not None else 0.0

        db.log_session(skill, hours, note=note)
        hours_after = hours_before + hours

    console.print(f'[green]Logged {hours:.2f}h to "{skill}".[/green] Total: {hours_after:.1f}h')

    for rank in crossed_rank_up(hours_before, hours_after):
        console.print(f"[bold gold1]LEVEL UP![/bold gold1] {skill} is now [bold]{rank.name}[/bold] \U0001F389")
    # notifications.py (native macOS notification + sound) hooks in right
    # here in a later checkpoint — it'll take the same crossed-rank list
    # and fire one notification per tier crossed.


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


if __name__ == "__main__":
    app()
