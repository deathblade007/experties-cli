"""
Experties-CLI's visual theme — one shared Console and a set of named
styles, used by both cli.py and timer.py so the whole app looks and
means the same thing consistently, instead of scattering raw color
strings ("green", "yellow", ...) across every command.

To retheme the app, this is the only file that needs to change.
"""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

EXPERTIES_THEME = Theme(
    {
        "brand": "bold magenta",  # the app's own identity: table and panel titles
        "success": "bold green",  # confirmations, a session logged, a timer running
        "warning": "yellow",  # cautions, cancellations, paused states, hints
        "error": "bold red",  # failures
        "muted": "dim",  # secondary/nested text, footers, keybinding hints
        "accent": "bold cyan",  # the active clock, the selected timer in `timer watch`
        "rank_up": "bold gold1",  # LEVEL UP celebrations, top rank reached
    }
)

console = Console(theme=EXPERTIES_THEME)