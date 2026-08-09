"""
Plugin loading for Experties-CLI.

Drop a .py file into ~/.experties/plugins/ and it becomes a real
subcommand of `experties`. Each plugin file must define a top-level
register(app) function; it's called once at startup with the live
Typer app, and can call app.command(...) or app.add_typer(...) exactly
like cli.py itself does. See PLUGINS.md for a full worked example.

Plugins run with full trust — this is a personal, single-user tool, not
a sandboxed marketplace. A plugin file is just Python imported into this
process, so it can `from experties.database import Database`,
`from experties.rank_engine import get_rank_status`, etc. directly.

A broken plugin (syntax error, missing register(), a register() that
raises) is reported and skipped rather than taking down every other
command — a typo in one plugin file shouldn't cost you `experties list`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import typer
from rich.console import Console

DEFAULT_PLUGINS_DIR = Path.home() / ".experties" / "plugins"

_console = Console(stderr=True)


def _load_plugin_module(path: Path):
    # The module name includes a hash of the full resolved path, not
    # just the filename, so two plugins that happen to share a filename
    # in different directories (or across test runs) never collide in
    # sys.modules.
    unique = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:8]
    module_name = f"experties_plugin_{path.stem}_{unique}"

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load plugin spec for {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_plugins(app: typer.Typer, plugins_dir: Path | None = None) -> list[str]:
    """
    Load every .py file in plugins_dir (default ~/.experties/plugins/),
    calling each one's register(app) function so it can add its own
    commands to the live app. Returns the sorted list of plugin
    filenames that loaded successfully.

    A missing plugins directory is not an error — most users won't have
    any plugins, and this runs on every single CLI invocation.
    """
    directory = plugins_dir if plugins_dir is not None else DEFAULT_PLUGINS_DIR
    if not directory.is_dir():
        return []

    loaded: list[str] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue  # leading underscore = disabled, skip silently

        try:
            module = _load_plugin_module(path)
            register = getattr(module, "register", None)
            if register is None:
                _console.print(
                    f"[yellow]Plugin {path.name} has no register(app) function — skipped.[/yellow]"
                )
                continue
            register(app)
            loaded.append(path.name)
        except Exception as exc:  # noqa: BLE001 - one bad plugin must never break the whole CLI
            _console.print(f"[yellow]Plugin {path.name} failed to load: {exc}[/yellow]")

    return loaded