"""
Command-line interface for Experties-CLI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from experties.database import Database, SkillAlreadyExistsError, SkillNotFoundError, resolve_db_path
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


def _current_group_file() -> Path:
    return resolve_db_path().parent / "current_group"


def _get_current_group() -> Optional[str]:
    path = _current_group_file()
    if not path.exists():
        return None
    name = path.read_text().strip()
    return name or None


def _set_current_group(name: Optional[str]) -> None:
    path = _current_group_file()
    if name is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)


def _progress_bar(fraction: float | None) -> str:
    if fraction is None:
        return "[bold gold1]MAXED[/bold gold1]"
    filled = round(fraction * _BAR_WIDTH)
    return "\u2588" * filled + "\u2591" * (_BAR_WIDTH - filled)


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
    """Show skills, ranks, hours, and progress. If you've `cd`'d into a group, shows that group's members instead of everything."""
    current_group_name = _get_current_group()

    with Database() as db:
        group = db.get_skill(current_group_name) if current_group_name else None
        if current_group_name and (group is None or not group.is_group):
            _set_current_group(None)
            current_group_name = None
            group = None

        if group is not None:
            member_skills = db.get_group_members(group.name)
            skills_with_hours = [(m, db.get_total_hours(m.name)) for m in member_skills]
            group_total = db.get_total_hours(group.name)
        else:
            skills_with_hours = db.get_top_level_skills_with_hours()
            group_total = None

        global_hours = db.get_global_total_hours()

    if group is not None:
        console.print(f'[dim]Inside group "{group.name}" — run [bold]experties cd[/bold] to go back[/dim]\n')

    if not skills_with_hours and group is None:
        console.print(
            "[yellow]No skills yet.[/yellow] Log your first session with "
            "[bold]experties log <skill> --time <duration>[/bold]."
        )
        return
    if not skills_with_hours and group is not None:
        console.print(
            f'[yellow]"{group.name}" has no members yet.[/yellow] Add one with '
            f'[bold]experties group add "{group.name}" <skill>[/bold].'
        )
        return

    table = Table(title=f'Experties — {group.name}' if group is not None else "Experties")
    table.add_column("Skill", style="bold")
    table.add_column("Rank")
    table.add_column("Hours", justify="right")
    table.add_column("Progress")
    table.add_column("Left", justify="right")

    for skill, hours in skills_with_hours:
        label = f"\u25b8 {skill.name}" if skill.is_group else skill.name
        rank_name, hours_display, progress, hours_left = _rank_row(hours)
        table.add_row(label, rank_name, hours_display, progress, hours_left)

    table.add_section()
    if group is not None:
        rank_name, hours_display, progress, hours_left = _rank_row(group_total)
        table.add_row(f"[bold]{group.name.upper()}[/bold]", rank_name, hours_display, progress, hours_left)
    else:
        rank_name, hours_display, progress, hours_left = _rank_row(global_hours)
        table.add_row("[bold]GLOBAL[/bold]", rank_name, hours_display, progress, hours_left)

    console.print(table)


@app.command()
def cd(
    group: Optional[str] = typer.Argument(
        None, help="Group to focus `list` on. Omit (or use \"..\") to go back to the top level."
    ),
) -> None:
    """Focus `experties list` on one group's members, like cd into a folder — doesn't affect log/start/stats, which always take an exact skill name."""
    if group is None or group in ("..", "/", "~"):
        _set_current_group(None)
        console.print("[green]Back to the top level.[/green]")
        return

    with Database() as db:
        skill = db.get_skill(group)

    if skill is None or not skill.is_group:
        console.print(
            f'[red]"{group}" is not a group.[/red] Run [bold]experties group list[/bold] to see what exists.'
        )
        raise typer.Exit(code=1)

    _set_current_group(skill.name)
    console.print(f'[green]Now focused on "{skill.name}".[/green] Run [bold]experties list[/bold] to see it.')


@app.command()
def stats(
    skill: str = typer.Argument(..., help="Skill name"),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of recent sessions to show"),
) -> None:
    """Show rank progress and recent session history for one skill. For a group, sessions from every member are merged in, so each row is labeled with which skill it came from."""
    with Database() as db:
        skill_obj = db.get_skill(skill)
        if skill_obj is None:
            console.print(f'[red]No skill named "{skill}" yet.[/red]')
            raise typer.Exit(code=1)

        hours = db.get_total_hours(skill)
        sessions = db.get_sessions(skill, limit=limit)

        skill_names_by_id: dict[int, str] = {}
        if skill_obj.is_group:
            skill_names_by_id[skill_obj.id] = skill_obj.name
            for member in db.get_group_members(skill):
                skill_names_by_id[member.id] = member.name

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
    if skill_obj.is_group:
        table.add_column("Skill")
    table.add_column("When")
    table.add_column("Hours", justify="right")
    table.add_column("Note")
    for s in sessions:
        row = [str(s.id)]
        if skill_obj.is_group:
            row.append(skill_names_by_id.get(s.skill_id, "?"))
        row += [s.logged_at, f"{s.hours:.2f}h", s.note or ""]
        table.add_row(*row)
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
    _CommandInfo("skill rename", "Rename a skill (keeps all its history).", "experties skill rename Coding Programming"),
    _CommandInfo("skill delete", "Delete a skill and every session logged against it.", "experties skill delete Guitar"),
    _CommandInfo("group create", "Create a new group.", "experties group create \"Machine Learning\""),
    _CommandInfo("group add", "Add a skill as a member of a group.", "experties group add \"Machine Learning\" Python"),
    _CommandInfo("group remove", "Remove a skill from its group.", "experties group remove Python"),
    _CommandInfo("group rename", "Rename a group (members and history move with it).", "experties group rename \"Machine Learning\" ML"),
    _CommandInfo("group list", "Show every group, its hours, and its members.", "experties group list"),
    _CommandInfo("cd", "Focus `list` on one group, like cd into a folder.", "experties cd \"Machine Learning\""),
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


skill_app = typer.Typer(help="Manage skills themselves — renaming or deleting a skill entirely.")


@skill_app.command("rename")
def skill_rename(
    old_name: str = typer.Argument(..., help="Current skill name"),
    new_name: str = typer.Argument(..., help="New skill name"),
) -> None:
    """Rename a skill. All of its sessions and history move with it."""
    with Database() as db:
        try:
            renamed = db.rename_skill(old_name, new_name)
        except SkillNotFoundError:
            console.print(f'[red]No skill named "{old_name}".[/red]')
            raise typer.Exit(code=1)
        except SkillAlreadyExistsError:
            console.print(f'[red]A skill named "{new_name}" already exists.[/red]')
            raise typer.Exit(code=1)

    console.print(f'[green]Renamed "{old_name}" to "{renamed.name}".[/green]')


@skill_app.command("delete")
def skill_delete(
    name: str = typer.Argument(..., help="Skill to delete, including every session logged against it"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
) -> None:
    """Delete a skill and every session ever logged against it. This cannot be undone."""
    with Database() as db:
        skill = db.get_skill(name)
        if skill is None:
            console.print(f'[red]No skill named "{name}".[/red]')
            raise typer.Exit(code=1)

        hours = db.get_total_hours(name)
        session_count = len(db.get_sessions(name))
        console.print(
            f'[yellow]This permanently deletes "{skill.name}" and all {session_count} '
            f"session(s) ({hours:.1f}h total). There's no undo.[/yellow]"
        )

        if not yes and not typer.confirm("Are you sure?"):
            console.print("Cancelled.")
            raise typer.Exit(code=0)

        db.delete_skill(name)

    console.print(f'[green]Deleted "{name}".[/green]')


app.add_typer(skill_app, name="skill")


group_app = typer.Typer(help='Group skills into a "super skill" whose hours roll up from its members.')


@group_app.command("create")
def group_create(name: str = typer.Argument(..., help="Name for the new group")) -> None:
    """Create a new group. Add members to it with `experties group add`."""
    with Database() as db:
        try:
            db.create_group(name)
        except SkillAlreadyExistsError:
            console.print(f'[red]A skill named "{name}" already exists.[/red]')
            raise typer.Exit(code=1)

    console.print(f'[green]Created group "{name}".[/green] Add members with [bold]experties group add "{name}" <skill>[/bold].')


@group_app.command("add")
def group_add(
    group: str = typer.Argument(..., help="Group to add to (must already exist)"),
    skill: str = typer.Argument(..., help="Skill to add — created automatically if new"),
) -> None:
    """Add a skill as a member of a group. Its own hours keep counting toward it AND roll up into the group's total."""
    with Database() as db:
        try:
            member = db.add_to_group(group, skill)
        except (SkillNotFoundError, ValueError) as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1)

    console.print(f'[green]Added "{member.name}" to "{group}".[/green]')


@group_app.command("remove")
def group_remove(skill: str = typer.Argument(..., help="Skill to remove from its group")) -> None:
    """Remove a skill from whatever group it's in. The skill itself, and its hours, are untouched — it's just ungrouped."""
    with Database() as db:
        try:
            removed = db.remove_from_group(skill)
        except SkillNotFoundError:
            console.print(f'[red]No skill named "{skill}".[/red]')
            raise typer.Exit(code=1)

    if removed:
        console.print(f'[green]Removed "{skill}" from its group.[/green]')
    else:
        console.print(f'[yellow]"{skill}" wasn\'t in a group.[/yellow]')


@group_app.command("rename")
def group_rename(
    old_name: str = typer.Argument(..., help="Current group name"),
    new_name: str = typer.Argument(..., help="New group name"),
) -> None:
    """Rename a group. Its members and rolled-up history move with it — this is `experties skill rename`, guarded so it only accepts an actual group."""
    with Database() as db:
        skill = db.get_skill(old_name)
        if skill is None or not skill.is_group:
            console.print(
                f'[red]"{old_name}" is not a group.[/red] Run [bold]experties group list[/bold] to see what exists.'
            )
            raise typer.Exit(code=1)

        try:
            renamed = db.rename_skill(old_name, new_name)
        except SkillAlreadyExistsError:
            console.print(f'[red]A skill named "{new_name}" already exists.[/red]')
            raise typer.Exit(code=1)

    console.print(f'[green]Renamed group "{old_name}" to "{renamed.name}".[/green]')


@group_app.command("list")
def group_list() -> None:
    """Show every group, its rolled-up hours, and its members — like `ls` at the top level."""
    with Database() as db:
        groups = db.list_groups()
        if not groups:
            console.print(
                '[yellow]No groups yet.[/yellow] Create one with [bold]experties group create <name>[/bold].'
            )
            return

        table = Table(title="Groups")
        table.add_column("Group", style="bold")
        table.add_column("Hours", justify="right")
        table.add_column("Rank")
        table.add_column("Members")

        for group in groups:
            hours = db.get_total_hours(group.name)
            status = get_rank_status(hours)
            members = db.get_group_members(group.name)
            member_list = ", ".join(m.name for m in members) if members else "[dim](empty)[/dim]"
            table.add_row(group.name, f"{hours:.1f}h", status.display_name, member_list)

    console.print(table)


app.add_typer(group_app, name="group")


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


_plugins_dir_override = os.environ.get("EXPERTIES_PLUGINS_DIR")
_effective_plugins_dir = Path(_plugins_dir_override) if _plugins_dir_override else DEFAULT_PLUGINS_DIR
_loaded_plugins = load_plugins(app, plugins_dir=_effective_plugins_dir)


if __name__ == "__main__":
    app()