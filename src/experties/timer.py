"""
Live focus-session timer for Experties-CLI.

`experties start <skill>` runs an interactive stopwatch until the user
stops or cancels it. On stop, the elapsed time is committed through the
same log_session() path `experties log` uses — the database doesn't know
or care whether hours came from typing a duration or running this timer.

Two things this module deliberately does NOT do, matching earlier design
decisions:
  - No idle/AFK detection — only full system sleep pauses the timer.
  - No background persistence. There's no daemon and nothing autosaves
    mid-session; closing the terminal window ends the session outright,
    and elapsed time is only written to the database when the user
    explicitly stops.

Sleep detection needs no macOS-specific API. Each tick compares the
actual wall-clock gap against the requested tick interval; a gap much
bigger than requested means this process (and the Mac underneath it)
was suspended for roughly that long — a sleeping Mac doesn't run Python
code at all, so there's no other way to lose time like that. The
state-transition math for this lives in _process_tick(), kept separate
from the actual terminal I/O (raw keypresses, Rich Live) so it can be
unit tested without a real tty.
"""

from __future__ import annotations

import select
import sys
import termios
import time
import tty
from dataclasses import dataclass
from enum import Enum, auto

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

TICK_SECONDS = 1.0
SLEEP_GAP_THRESHOLD = 10.0  # extra seconds beyond TICK_SECONDS that counts as "was asleep"

console = Console()


class TimerState(Enum):
    RUNNING = auto()
    PAUSED = auto()
    SLEEP_PAUSED = auto()


@dataclass
class TimerResult:
    elapsed_seconds: float
    cancelled: bool


def format_hms(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _process_tick(
    state: TimerState,
    elapsed: float,
    actual_gap: float,
    key: str | None,
    message: str = "",
) -> tuple[TimerState, float, str]:
    """
    Pure per-tick state transition. Returns (new_state, new_elapsed, new_message).

    'key' here only ever carries the pause/resume key (" ") — 's' (stop)
    and 'c' (cancel) end the whole session and are handled by the caller
    before this function is even called.
    """
    # A gap much bigger than one tick means the Mac was asleep, regardless
    # of what state we were in or whether a key happened to come in right
    # as it woke up. The gap itself is never added to elapsed.
    if actual_gap > TICK_SECONDS + SLEEP_GAP_THRESHOLD:
        new_message = f"Detected {format_hms(actual_gap)} away — resume when ready"
        return TimerState.SLEEP_PAUSED, elapsed, new_message

    if state == TimerState.RUNNING:
        elapsed = elapsed + actual_gap

    if key == " ":
        if state == TimerState.RUNNING:
            return TimerState.PAUSED, elapsed, ""
        if state in (TimerState.PAUSED, TimerState.SLEEP_PAUSED):
            return TimerState.RUNNING, elapsed, ""

    # No relevant transition this tick — keep whatever message was
    # already showing (a sleep notice stays up until explicitly resumed).
    return state, elapsed, message


class _RawKeyReader:
    """
    Puts stdin into cbreak mode (single keypresses, no waiting for Enter)
    with echo turned off, and always restores the terminal's original
    settings on exit — including on a crash or Ctrl-C, since __exit__
    runs during exception unwinding too.
    """

    def __enter__(self) -> "_RawKeyReader":
        self._fd = sys.stdin.fileno()
        self._old_settings = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        no_echo = termios.tcgetattr(self._fd)
        no_echo[3] &= ~termios.ECHO  # index 3 = lflag
        termios.tcsetattr(self._fd, termios.TCSADRAIN, no_echo)
        return self

    def __exit__(self, *exc_info) -> None:
        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)

    def read_key(self, timeout: float) -> str | None:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1) if ready else None


def _render(skill_name: str, elapsed: float, state: TimerState, message: str) -> Panel:
    clock_style = "bold cyan" if state == TimerState.RUNNING else "bold yellow"
    body = Text()
    body.append(f"{skill_name}\n\n", style="bold")
    body.append(f"{format_hms(elapsed)}\n", style=clock_style)

    if state == TimerState.RUNNING:
        status = "[green]\u25cf RUNNING[/green]"
    elif state == TimerState.SLEEP_PAUSED:
        status = "[yellow]\u23f8 PAUSED \u2014 Mac was asleep[/yellow]"
    else:
        status = "[yellow]\u23f8 PAUSED[/yellow]"

    lines = [Text.from_markup(status)]
    if message:
        lines.append(Text.from_markup(f"[yellow]{message}[/yellow]"))
    lines.append(Text.from_markup("[dim][space] pause/resume   [s] stop & save   [c] cancel[/dim]"))

    return Panel(Group(body, *lines), title="Experties Timer", expand=False)


def run_timer(skill_name: str) -> TimerResult:
    """
    Run the interactive live timer until the user stops or cancels (or
    Ctrl-C, which is treated the same as stop — better to save what was
    tracked than lose it to an accidental interrupt).
    """
    elapsed = 0.0
    state = TimerState.RUNNING
    message = ""

    with _RawKeyReader() as reader:
        with Live(_render(skill_name, elapsed, state, message), console=console, refresh_per_second=4) as live:
            try:
                while True:
                    tick_start = time.time()
                    key = reader.read_key(timeout=TICK_SECONDS)
                    actual_gap = time.time() - tick_start

                    if key is not None:
                        key = key.lower()

                    state, elapsed, message = _process_tick(state, elapsed, actual_gap, key, message)

                    if key == "s":
                        return TimerResult(elapsed_seconds=elapsed, cancelled=False)
                    if key == "c":
                        return TimerResult(elapsed_seconds=elapsed, cancelled=True)

                    live.update(_render(skill_name, elapsed, state, message))
            except KeyboardInterrupt:
                return TimerResult(elapsed_seconds=elapsed, cancelled=False)
