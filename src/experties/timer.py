"""
Live focus-session timer for Experties-CLI.
"""

from __future__ import annotations

import os
import select
import sys
import termios
import time
import tty
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from experties.database import ActiveTimerInfo, Database
from experties.theme import console

TICK_SECONDS = 1.0
SLEEP_GAP_THRESHOLD = 10.0


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

    return state, elapsed, message


class _RawKeyReader:
    def __enter__(self) -> "_RawKeyReader":
        self._fd = sys.stdin.fileno()
        self._old_settings = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        no_echo = termios.tcgetattr(self._fd)
        no_echo[3] &= ~termios.ECHO
        termios.tcsetattr(self._fd, termios.TCSADRAIN, no_echo)
        return self

    def __exit__(self, *exc_info) -> None:
        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)

    def read_key(self, timeout: float) -> str | None:
        ready, _, _ = select.select([self._fd], [], [], timeout)
        if not ready:
            return None
        # os.read(), not sys.stdin.read(): the latter is a buffered
        # TextIOWrapper that can silently pull an entire escape sequence
        # into its own internal buffer on the very first read, leaving
        # select() reporting nothing further available even though the
        # rest of the sequence is sitting right there, just unconsumed
        # by the OS's view of the fd. Reading the fd directly keeps
        # select() and the actual read in sync.
        ch = os.read(self._fd, 1).decode(errors="replace")
        if ch != "\x1b":
            return ch

        # Might be the start of an arrow-key escape sequence (xterm/VT100
        # send ESC [ A/B for up/down). A real terminal sends the rest of
        # the sequence essentially instantly, so a short timeout reliably
        # tells that apart from someone just pressing Escape on its own.
        ready2, _, _ = select.select([self._fd], [], [], 0.05)
        if not ready2:
            return "esc"
        ch2 = os.read(self._fd, 1).decode(errors="replace")
        if ch2 != "[":
            return "esc"
        ready3, _, _ = select.select([self._fd], [], [], 0.05)
        if not ready3:
            return "esc"
        ch3 = os.read(self._fd, 1).decode(errors="replace")
        if ch3 == "A":
            return "up"
        if ch3 == "B":
            return "down"
        return "esc"


def _render(skill_name: str, elapsed: float, state: TimerState, message: str) -> Panel:
    clock_style = "accent" if state == TimerState.RUNNING else "warning"
    body = Text()
    body.append(f"{skill_name}\n\n", style="bold")
    body.append(f"{format_hms(elapsed)}\n", style=clock_style)

    if state == TimerState.RUNNING:
        status = "[success]\u25cf RUNNING[/success]"
    elif state == TimerState.SLEEP_PAUSED:
        status = "[warning]\u23f8 PAUSED \u2014 Mac was asleep[/warning]"
    else:
        status = "[warning]\u23f8 PAUSED[/warning]"

    lines = [Text.from_markup(status)]
    if message:
        lines.append(Text.from_markup(f"[warning]{message}[/warning]"))
    lines.append(Text.from_markup("[muted][space] pause/resume   [s] stop & save   [c] cancel[/muted]"))

    return Panel(
        Group(body, *lines), title="[brand]Experties Timer[/brand]", border_style="accent", expand=False
    )


def run_timer(skill_name: str) -> TimerResult:
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


@dataclass
class _MultiSlot:
    skill_name: str
    elapsed: float
    state: TimerState


def _render_multi(slots: list[_MultiSlot], selected: int, message: str) -> Group:
    panels = []
    for i, slot in enumerate(slots):
        is_selected = i == selected
        clock_style = "accent" if slot.state == TimerState.RUNNING else "warning"
        body = Text()
        body.append(f"{format_hms(slot.elapsed)}\n", style=clock_style)

        if slot.state == TimerState.RUNNING:
            status = "[success]\u25cf RUNNING[/success]"
        elif slot.state == TimerState.SLEEP_PAUSED:
            status = "[warning]\u23f8 PAUSED \u2014 Mac was asleep[/warning]"
        else:
            status = "[warning]\u23f8 PAUSED[/warning]"

        title = f"\u25b8 {slot.skill_name}" if is_selected else f"  {slot.skill_name}"
        border_style = "accent" if is_selected else "muted"
        panels.append(
            Panel(Group(body, Text.from_markup(status)), title=title, border_style=border_style, expand=False)
        )

    footer = []
    if message:
        footer.append(Text.from_markup(f"[warning]{message}[/warning]"))
    footer.append(
        Text.from_markup(
            "[muted][\u2191/\u2193] select   [space] pause/resume   [s] stop & save   "
            "[c] cancel   [q] exit \u2014 keeps running[/muted]"
        )
    )
    return Group(*panels, *footer)


def run_multi_timer_watch(
    db: Database,
    commit_session: Callable[[str, float, str | None, str], None],
) -> None:
    """
    Live dialog controlling however many background timers are currently
    running or paused, all in one window. Arrow keys move the selection;
    space pauses/resumes whichever timer is selected; 's' stops and logs
    it via commit_session (prompting for a note first, same as
    `experties start`); 'c' cancels it outright, logging nothing; 'q'
    exits without touching anything still running — those keep going
    exactly as `experties timer start` left them, ready to pick back up
    with another `experties timer watch`.
    """
    initial = db.list_active_timers()
    if not initial:
        console.print("[muted]No timers running.[/muted] Start one with [bold]experties timer start <skill>[/bold].")
        return

    order = [info.skill.name for info in initial]
    slots = {
        info.skill.name: _MultiSlot(
            skill_name=info.skill.name,
            elapsed=info.elapsed_seconds,
            state=TimerState.PAUSED if info.is_paused else TimerState.RUNNING,
        )
        for info in initial
    }
    selected = 0
    message = ""

    with _RawKeyReader() as reader:
        while order:
            # Re-sync from the database every time we (re)enter the dialog
            # -- not just once at the top -- so real wall-clock time that
            # passed outside the tick loop (the note prompt after a stop,
            # or another terminal touching one of these timers) is never
            # silently missing from what's shown. The actual logged hours
            # were never at risk either way -- stop_timer() always computes
            # those fresh from the database, not from this display state --
            # but the display should never lie about what's really running.
            fresh_by_name = {info.skill.name: info for info in db.list_active_timers()}
            for name in list(order):
                if name not in fresh_by_name:
                    # Stopped or cancelled elsewhere while this dialog was open.
                    order.remove(name)
                    slots.pop(name, None)
                    continue
                info = fresh_by_name[name]
                slots[name].elapsed = info.elapsed_seconds
                slots[name].state = TimerState.PAUSED if info.is_paused else TimerState.RUNNING

            if not order:
                break

            selected = max(0, min(selected, len(order) - 1))
            action: tuple[str, str | None] = ("", None)

            try:
                with Live(console=console, refresh_per_second=4) as live:
                    live.update(_render_multi([slots[n] for n in order], selected, message))
                    while True:
                        tick_start = time.time()
                        key = reader.read_key(timeout=TICK_SECONDS)
                        actual_gap = time.time() - tick_start
                        if key is not None:
                            key = key.lower()

                        # A real sleep affects the whole machine at once, so
                        # every currently-running timer pauses together —
                        # there's no way for one to have slept and not the
                        # others when it's all the same process clock.
                        if actual_gap > TICK_SECONDS + SLEEP_GAP_THRESHOLD:
                            message = f"Detected {format_hms(actual_gap)} away — resume when ready"
                            for slot in slots.values():
                                if slot.state == TimerState.RUNNING:
                                    slot.state = TimerState.SLEEP_PAUSED
                        else:
                            for name in order:
                                if slots[name].state == TimerState.RUNNING:
                                    slots[name].elapsed += actual_gap

                        if key == "up":
                            selected = (selected - 1) % len(order)
                            message = ""
                        elif key == "down":
                            selected = (selected + 1) % len(order)
                            message = ""
                        elif key == " ":
                            name = order[selected]
                            slot = slots[name]
                            if slot.state == TimerState.RUNNING:
                                slot.state = TimerState.PAUSED
                                db.pause_timer(name)
                            elif slot.state in (TimerState.PAUSED, TimerState.SLEEP_PAUSED):
                                slot.state = TimerState.RUNNING
                                db.resume_timer(name)
                            message = ""
                        elif key == "s":
                            action = ("stop", order[selected])
                            break
                        elif key == "c":
                            action = ("cancel", order[selected])
                            break
                        elif key == "q":
                            action = ("quit", None)
                            break

                        live.update(_render_multi([slots[n] for n in order], selected, message))
            except KeyboardInterrupt:
                action = ("quit", None)

            kind, name = action
            if kind == "quit" or kind == "":
                return
            if kind == "cancel":
                db.cancel_timer(name)
                order.remove(name)
                del slots[name]
                console.print(f'[warning]Timer for "{name}" cancelled \u2014 nothing logged.[/warning]')
            elif kind == "stop":
                started_at, hours = db.stop_timer(name)
                order.remove(name)
                del slots[name]
                note = input(f'Add a note for "{name}"? (press Enter to skip) ')
                commit_session(name, hours, note.strip() or None, started_at)
                message = ""

    console.print("[muted]No timers left running.[/muted]")