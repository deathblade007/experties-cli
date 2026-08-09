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
package:

- `experties.database.Database` — read or write skills and sessions
- `experties.rank_engine.get_rank_status`, `RANK_TABLE`, `crossed_rank_up`, `division_thresholds`
- `experties.duration.parse_duration`
- `experties.notifications.notify_level_up`, `notify_all_level_ups`

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