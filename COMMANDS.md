# Experties-CLI — Command Reference

All data lives locally in `~/.experties/data.db` (override with the
`EXPERTIES_DB_PATH` environment variable — mainly useful for testing).

For a quick in-terminal summary, run `experties commands`. This file has
the full detail, including every option. `experties --help` (and
`experties <command> --help`) is always the live, authoritative list —
it's the only place that will show plugin-added commands too.

## Quick reference

| Command | What it does |
|---|---|
| `experties list` | Show every skill, rank, hours, and progress |
| `experties start <skill>` | Run the live focus-session timer |
| `experties log <skill> --time <duration>` | Manually log time |
| `experties stats <skill>` | Show rank progress + recent sessions |
| `experties rank-table` | Show the full rank ladder |
| `experties delete <id>` | Delete a single logged session |
| `experties commands` | Quick in-terminal command summary |

---

## `experties list`

Shows every skill you've logged time against: current rank, total hours,
a progress bar toward the next rank, and how many hours are left to get
there. A `GLOBAL` row at the bottom applies the same rank table to your
hours summed across every skill.

```bash
experties list
```

No options. If you haven't logged anything yet, it tells you to run
`experties log` or `experties start` instead of showing an empty table.

---

## `experties start <skill>`

Runs a live, interactive stopwatch for a skill. This is the main way to
track a focus session as it happens.

```bash
experties start Coding
```

**While it's running:**

| Key | Action |
|---|---|
| `space` | Pause / resume |
| `s` | Stop and save |
| `c` | Cancel — discard the session, nothing is logged |

If your Mac goes to sleep mid-session, the timer detects the gap, pauses
automatically, and shows "PAUSED — Mac was asleep." It will **not**
resume on its own — you have to press `space` again once you're back.
Closing the terminal window instead of pressing `s` ends the session
with nothing saved; there's no background process keeping it alive.

When you stop with `s`, you'll be prompted for an optional note before
it's committed — press Enter to skip.

---

## `experties log <skill> --time <duration> [--note TEXT]`

Manually logs a chunk of time without running the live timer — useful
for a session you tracked some other way, or forgot to start on time.

```bash
experties log Coding --time 1h30m --note "fixed a nasty bug"
experties log Guitar --time 45m
experties log Mathematics --time 2h
```

| Option | Required | Description |
|---|---|---|
| `--time`, `-t` | Yes | Duration — accepts `1h30m`, `1.5h`, `90m`, or a bare number like `1.5` (assumed hours) |
| `--note` | No | A short note about the session |

The skill is created automatically the first time you log time against a
new name — no separate "create skill" step needed.

---

## `experties stats <skill> [--limit N]`

Shows current rank and progress for one skill, plus a table of its most
recent sessions (with their IDs — useful for `experties delete`).

```bash
experties stats Coding
experties stats Coding --limit 25
```

| Option | Default | Description |
|---|---|---|
| `--limit`, `-n` | 10 | How many recent sessions to show |

---

## `experties rank-table`

Shows the full rank ladder — every tier and the hours required to reach
it — with your current global rank highlighted.

```bash
experties rank-table
```

No options.

---

## `experties delete <session_id> [--yes]`

Deletes a single logged session by its ID. Find the ID via
`experties stats <skill>`. Deleting a session never deletes the skill
itself — even if it was the skill's only session, the skill just drops
back to 0 hours / Unranked rather than disappearing.

```bash
experties delete 12
experties delete 12 --yes   # skip the confirmation prompt
```

| Option | Description |
|---|---|
| `--yes`, `-y` | Skip the "are you sure" prompt |

---

## `experties commands`

Prints a compact table of every built-in command with a one-line
description and example — a quicker, terminal-native version of this
file. It does not include any plugin-added commands; use
`experties --help` for the complete list.

```bash
experties commands
```