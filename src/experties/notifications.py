"""
Native macOS notifications for Experties-CLI level-ups.

Uses osascript (AppleScript) to post a real Notification Center alert
with a sound — no extra dependencies, works from a plain terminal, and
fires even if Terminal isn't the focused app.

This is macOS-only, matching the rest of the app's scope. If osascript
isn't available for some reason (a non-macOS machine, or the call fails
for any reason), notifications fail silently — a missing notification
should never break `experties log` or `experties start`. The terminal
message cli.py already prints is the source of truth; this is a bonus
on top of it, never a replacement.
"""

from __future__ import annotations

import shutil
import subprocess

from experties.rank_engine import Rank

DEFAULT_SOUND = "Hero"
_TIMEOUT_SECONDS = 5


def _escape_for_applescript(text: str) -> str:
    """
    AppleScript string literals are double-quoted; escape any double
    quotes (and backslashes, so the escaping itself can't be escaped
    out of) that appear in the text so a skill or rank name can never
    break out of the string and inject extra AppleScript.
    """
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify_level_up(skill_name: str, rank: Rank, sound: str = DEFAULT_SOUND) -> bool:
    """
    Post a native macOS notification for a single rank-up.

    Returns True if the notification was sent, False if it couldn't be
    (missing osascript, or the call failed/timed out). Callers should
    treat False as a silent no-op, never as an error worth surfacing.
    """
    if shutil.which("osascript") is None:
        return False

    title = _escape_for_applescript("Level Up!")
    message = _escape_for_applescript(f"{skill_name} is now {rank.name}")
    sound_name = _escape_for_applescript(sound)

    script = f'display notification "{message}" with title "{title}" sound name "{sound_name}"'

    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
        )
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def notify_all_level_ups(skill_name: str, ranks: list[Rank], sound: str = DEFAULT_SOUND) -> None:
    """
    Fire one notification per rank crossed — a single long session can
    cross more than one tier at once. Best-effort: failures for
    individual ranks are swallowed rather than raised, same as
    notify_level_up().
    """
    for rank in ranks:
        notify_level_up(skill_name, rank, sound=sound)