"""
Plugin loading for Experties-CLI.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import typer
from rich.console import Console

from experties.theme import EXPERTIES_THEME

DEFAULT_PLUGINS_DIR = Path.home() / ".experties" / "plugins"

# Its own console, kept separate from the shared one and pinned to
# stderr on purpose -- plugin load warnings shouldn't land in stdout
# and interfere with piped or scripted use of the CLI.
_console = Console(stderr=True, theme=EXPERTIES_THEME)


def _load_plugin_module(path: Path):
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
    directory = plugins_dir if plugins_dir is not None else DEFAULT_PLUGINS_DIR
    if not directory.is_dir():
        return []

    loaded: list[str] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue

        try:
            module = _load_plugin_module(path)
            register = getattr(module, "register", None)
            if register is None:
                _console.print(
                    f"[warning]Plugin {path.name} has no register(app) function — skipped.[/warning]"
                )
                continue
            register(app)
            loaded.append(path.name)
        except Exception as exc:  # noqa: BLE001
            _console.print(f"[warning]Plugin {path.name} failed to load: {exc}[/warning]")

    return loaded