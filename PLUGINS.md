# Experties-CLI — Writing Plugins

Any `.py` file dropped into `~/.experties/plugins/` becomes a real
`experties` subcommand — no reinstalling, no editing the app's source.
Run `experties plugins` any time to see the plugins directory and which
files are currently loaded.

## The contract

A plugin file must define one top-level function:

```python
def register(app):
    ...
```

`register()` is called once, at startup, with the live Typer app —
the exact same `app` object `cli.py` itself defines commands on. Inside
`register()`, add commands the normal Typer way:

```python
# ~/.experties/plugins/motivate.py
from experties.database import Database
from experties.rank_engine import get_rank_status

def register(app):
    @app.command("motivate")
    def motivate():
        """Print a one-line nudge based on your global rank."""
        with Database() as db:
            hours = db.get_global_total_hours()
        status = get_rank_status(hours)
        print(f"You're {status.display_name} with {status.hours_to_next or 0:.1f}h to the next rank. Get back to it.")
```

Save that file, then:

```bash
experties motivate
```

No reinstall, no restart of anything — plugins are loaded fresh every
time you run `experties`.

## What plugins can use

A plugin file is a normal Python module imported into the same process
as the rest of the app, so it can import anything from the installed
package. The full surface as of the current build:

**`experties.database`**
- `Database` — open with `Database()` (or `Database(path)` for a
  specific file); use as a context manager (`with Database() as db:`)
- Skills: `add_skill`, `get_skill`, `get_skill_by_id`, `get_or_create_skill`,
  `list_skills`, `rename_skill`, `delete_skill`
- Sessions: `log_session`, `get_sessions(skill_name)` (rolls up a
  group's members automatically), `get_all_sessions()` (every session
  in the database, exactly once each, with **no** group rollup —
  see the warning below), `get_session_by_id`, `delete_session`
- Totals: `get_total_hours(skill_name)` (rolls up for a group),
  `get_global_total_hours()`, `get_all_skills_with_hours()`,
  `get_top_level_skills_with_hours()` (groups + ungrouped skills only)
- Groups: `create_group`, `add_to_group`, `remove_from_group`,
  `get_group_members`, `get_group_of`, `list_groups`,
  `get_ungrouped_skills`

**`experties.rank_engine`**
- `get_rank_status(hours)` → current rank, next rank, progress,
  `display_name` (includes the division, e.g. "Bronze 1 Division 3")
- `RANK_TABLE`, `crossed_rank_up(before, after)`, `division_thresholds(rank_index)`

**`experties.duration`**
- `parse_duration(text)` — the same "1h30m" / "1.5h" / "90m" parser
  `experties log` uses

**`experties.notifications`**
- `notify_level_up(skill_name, rank)`, `notify_all_level_ups(skill_name, ranks)`

### ⚠️ get_sessions() vs get_all_sessions() — read this before summing across skills

If your plugin loops over every skill (`db.list_skills()`) and calls
`db.get_sessions(skill.name)` for each one, **a group member's hours
will be counted twice** — once under its own name, and again when you
reach the group, since `get_sessions()` on a group merges its members
in (that's intentional, and correct for `stats`/`list`, which want a
group's rolled-up total).

If you want a true whole-app total — "everything logged today", "every
session this week" — use `db.get_all_sessions()` instead. It returns
every session exactly once, with no group rollup, and pair it with
`db.get_skill_by_id(session.skill_id)` to find out which skill each one
belongs to. This is exactly the bug the built-in `today` and `goal`
(for its "global" target) plugins had until it was caught by testing
with real grouped data — their source is worth reading as the reference
pattern to copy.

Plugins run with full trust — this is a personal, single-user tool, not
a sandboxed marketplace. There's no restriction on what a plugin can do;
treat a plugin file the same way you'd treat any other Python script you
choose to run.

## Multiple commands in one file

`register()` can add as many commands as you want:

```python
def register(app):
    @app.command("cmd-one")
    def cmd_one():
        ...

    @app.command("cmd-two")
    def cmd_two():
        ...
```

Or add a whole group of related commands as a sub-app:

```python
import typer

def register(app):
    sub = typer.Typer(help="Custom reporting commands")

    @sub.command("weekly")
    def weekly():
        ...

    app.add_typer(sub, name="report")
    # now available as: experties report weekly
```

This is exactly the pattern the built-in `goal` plugin uses for
`experties goal set/check/remove`.

## Disabling a plugin without deleting it

Rename the file with a leading underscore — `motivate.py` →
`_motivate.py`. Files starting with `_` are skipped.

## If a plugin is broken

A plugin with a syntax error, a missing `register()` function, or a
`register()` that raises an exception is reported with a short warning
and skipped — it will never take down `experties list` or any other
command. Run `experties plugins` to see exactly which files loaded
successfully.

## Where plugin commands show up

`experties commands` only lists the built-in commands — it's a
curated, hand-written list and can't see what plugins add. `experties
--help` is always the complete, live list, including every loaded
plugin's commands.

## Example plugins

Three working examples ship in the repo under `examples/plugins/`:
`today.py` (hours logged today), `streak.py` (daily logging streak),
and `goal.py` (weekly hour targets, with its own JSON state file
separate from the core database). Copy any of them into
`~/.experties/plugins/` to use them, or read them as reference for
writing your own.