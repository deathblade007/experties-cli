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
| `experties skill rename <old> <new>` | Rename a skill (keeps its history) |
| `experties skill delete <skill>` | Delete a skill and all its sessions |
| `experties group create <name>` | Create a group ("super skill") |
| `experties group add <group> <skill>` | Add a skill as a member of a group |
| `experties group remove <skill>` | Remove a skill from its group |
| `experties group list` | Show every group, hours, and members |
| `experties cd <group>` | Focus `list` on one group, like cd into a folder |
| `experties commands` | Quick in-terminal command summary |
| `experties plugins` | Show loaded plugins |

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

## `experties skill rename <old_name> <new_name>`

Renames a skill. Its id and every session logged against it are
unaffected — the full history moves to the new name.

```bash
experties skill rename Codnig Coding
```

Renaming to a name already used by a *different* skill fails. Renaming
to the same name with different casing (`coding` → `Coding`) is fine.

---

## `experties skill delete <skill> [--yes]`

Deletes a skill **and every session ever logged against it.** Unlike
`experties delete <id>`, which only removes one session and leaves the
skill in place, this takes the skill's entire history with it. There is
no undo — back up `~/.experties/data.db` first if you're unsure.

```bash
experties skill delete Guitar
experties skill delete Guitar --yes   # skip the confirmation prompt
```

It shows the skill's total hours and session count before asking you to
confirm.

---

## Groups — "super skills"

A group is a skill that other skills can belong to. Its hours are the
sum of its own direct sessions (if any) plus every member's hours —
automatically, everywhere: `list`, `stats`, and its rank all reflect
the rolled-up total with no extra steps.

```bash
experties group create "Machine Learning"
experties group add "Machine Learning" Python
experties group add "Machine Learning" Maths
experties log Python --time 3h
experties log Maths --time 2h
experties list   # "Machine Learning" shows 5h total
```

A skill belongs to at most one group. Groups can't be nested (a group's
members must be regular skills, not other groups). `experties delete
<skill>`/`log`/`start`/`stats` all still work on a group's individual
members exactly as before — grouping only changes how the *group's own*
total is calculated and how `list` displays things; it never merges the
members' identities together. Deleting a group (`experties skill
delete`) does not delete its members, just ungroups them.

### `experties group create <name>`
Creates a new, empty group.

### `experties group add <group> <skill>`
Adds a skill to a group. The skill is created automatically if it
doesn't exist yet. A skill already in a different group must be
removed from that one first (`experties group remove`).

### `experties group remove <skill>`
Removes a skill from its group. The skill and its history are
untouched — only the grouping is undone.

### `experties group list`
Shows every group: rolled-up hours, rank, and its members.

---

## `experties cd <group>`

Focuses `experties list` on one group's members — like `cd` into a
folder. Run with no argument (or `experties cd ..`) to go back to
showing everything.

```bash
experties cd "Machine Learning"
experties list      # now shows Python and Maths individually
experties cd
experties list      # back to showing "Machine Learning" rolled up
```

This only changes what `list` *displays*. `log`, `start`, `stats`, and
`delete` always take an exact skill name and work identically whether
or not you're "inside" a group — skill names are globally unique, so
there's never any ambiguity about which skill a command means.

If the group you `cd`'d into gets renamed or deleted, `list` notices
and quietly falls back to the top level rather than getting stuck.

---

## `experties commands`

Prints a compact table of every built-in command with a one-line
description and example — a quicker, terminal-native version of this
file. It does not include any plugin-added commands; use
`experties --help` for the complete list.

```bash
experties commands
```

---

## `experties plugins`

Shows where your plugins directory is, and which `.py` files in it
loaded successfully as commands. See [PLUGINS.md](PLUGINS.md) for how
to write one.

```bash
experties plugins
```