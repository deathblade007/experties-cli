# Experties-CLI — Command Reference

All data lives locally in `~/.experties/data.db` (override with the
`EXPERTIES_DB_PATH` environment variable — mainly useful for testing).
Plugins load from `~/.experties/plugins` (override with
`EXPERTIES_PLUGINS_DIR`).

For a quick in-terminal summary, run `experties commands`. This file has
the full detail, including every option. `experties --help` (and
`experties <command> --help`) is always the live, authoritative list —
it's the only place that will show plugin-added commands too.

Looking for just the handful of commands you'll actually type every
day? See [`CHEATSHEET.md`](./CHEATSHEET.md) instead.

## Quick reference

| Command | What it does |
|---|---|
| `experties list` | Show every skill, rank, hours, and progress — nested groups shown underneath, at any depth |
| `experties cd <skill>` | Focus `list` on one skill's subtree, like cd into a folder |
| `experties start <skill>` | Run the live focus-session timer (blocks the terminal) |
| `experties log <skill> --time <duration>` | Manually log time |
| `experties timer start <skill>` | Start a background timer — start several at once |
| `experties timer stop <skill>` | Stop a background timer and log the time |
| `experties timer status` | Show every timer currently running |
| `experties timer cancel <skill>` | Abandon a running background timer without logging anything |
| `experties stats <skill>` | Show rank progress + recent sessions |
| `experties rank-table` | Show the full rank ladder |
| `experties delete <id>` | Delete a single logged session |
| `experties skill rename <old> <new>` | Rename a skill (keeps its history) |
| `experties skill delete <skill>` | Delete a skill and its own sessions (members become top-level) |
| `experties group create <name>` | Create an empty skill, ready to nest things under |
| `experties group add <group> <skill>` | Nest a skill under another — both auto-created if new |
| `experties group remove <skill>` | Remove a skill from its parent |
| `experties group rename <old> <new>` | Rename a skill (same as `skill rename`) |
| `experties group list` | Show every skill that currently has members |
| `experties commands` | Quick in-terminal command summary |
| `experties plugins` | Show loaded plugins |

---

## Skills and groups

There's no separate "group" type — every skill can hold other skills as
members. A skill becomes "a group" the moment something is nested under
it, and stops being one the moment its last member leaves; nothing needs
to be declared in advance. Nesting can go arbitrarily deep — a group can
itself be a member of another group.

A skill still has at most one parent, so its hours never roll up into
two different totals at once. `experties group add "Machine Learning"
"Deep Learning"` followed by `experties group add "Deep Learning"
PyTorch` gives you a real tree: PyTorch's hours count toward Deep
Learning's total, which in turn counts toward Machine Learning's.

Both names in `group add` are created automatically if they don't exist
yet — you don't need `group create` first unless you just want an empty
placeholder to nest things into later.

## `experties list`

Shows every skill you've logged time against: current rank, total
hours, a progress bar toward the next rank, and how many hours are left
to get there. Any skill with members shows them indented directly
underneath its row, however deep the nesting goes — no need to `cd` in
just to see what's inside a group. A `GLOBAL` row at the bottom applies
the same rank table to your hours summed across everything.

If you've `cd`'d into a skill, this shows that skill's subtree instead
of the whole top level.

## `experties cd`

Focuses `list` on one skill's subtree, like `cd` into a folder — it
doesn't affect `log`, `start`, `timer`, or `stats`, which always take an
exact skill name regardless of where you've `cd`'d. Works on any
existing skill, including one with no members yet. Run `experties cd`
with no argument (or `..`) to go back to the top level.

## `experties start`

Runs a live, full-screen timer with a countdown, pause/resume
(`space`), and stop-and-save (`s`) or cancel (`c`). Blocks the terminal
for as long as it's running — it's meant for one focused session at a
time. Auto-pauses if your Mac sleeps mid-session, and asks whether to
resume when it wakes. Closing the terminal window mid-session stops it
entirely with nothing logged — there's no background daemon, so commit
or lose it.

## `experties log`

Manually logs a duration after the fact — `--time` accepts `1h30m`,
`1.5h`, or `90m`. No real start/stop moment is recorded for these, so
this time never gets deduped against anything else (see Timers below);
it always just adds on top.

## Timers (`experties timer ...`)

Background timers, separate from `experties start` — they return
immediately instead of taking over the terminal, so you can run several
at once for different skills:

- `experties timer start <skill>` — starts tracking; errors if one's
  already running for that skill
- `experties timer stop <skill>` — ends it, asks for an optional note,
  logs the real time interval
- `experties timer status` — lists everything currently running, with
  live elapsed time
- `experties timer cancel <skill>` — abandons a running timer, logs
  nothing

**Overlapping time only counts once.** If you run two timers at the
same time — say, for two skills in the same group, or just two things
you're doing together — each skill's own total still reflects its own
full duration. But any shared rollup (GLOBAL, or a group both skills
belong to) counts the overlapping stretch once, not once per skill,
since only one hour of your life actually passed. Manually logged time
(`experties log --time`) has no real interval on record, so it's never
part of this — it always adds normally.

## `experties stats`

Shows rank progress and recent session history for one skill. If that
skill has members (at any depth), sessions show which skill in the
subtree they actually came from.

## `experties rank-table`

Shows the full rank ladder and the hours needed for each tier — the
same table used for every skill and for GLOBAL.

## `experties delete`

Deletes a single logged session by its id (find the id via `experties
stats <skill>`). This only removes that one session, not the skill
itself.

## `experties skill rename` / `experties skill delete`

`skill rename` renames a skill in place — its members (if any) and
rolled-up history move with it. `skill delete` permanently deletes a
skill and every session logged *directly* against it; if it has
members, they become top-level skills instead of being deleted. Both
ask for confirmation unless you pass `--yes`/`-y`.

## `experties group create` / `add` / `remove` / `rename` / `list`

- `group create <name>` — creates an empty skill, ready to nest things
  under. Optional; `group add` auto-creates both sides anyway.
- `group add <group> <skill>` — nests `<skill>` under `<group>`. Either
  can already have its own logged hours or its own members. Rejects
  creating a loop (nesting something under its own descendant) and
  rejects moving a skill that already belongs to a different group
  (remove it first).
- `group remove <skill>` — removes a skill from its current parent; it
  becomes top-level again. Its own members, if any, stay attached to it.
- `group rename <old> <new>` — identical to `skill rename`; kept under
  `group` too since it reads more naturally when you're thinking of the
  skill as a group.
- `group list` — every skill that currently has at least one member, its
  rolled-up hours, and those members. A skill you `group create`d but
  haven't put anything into yet won't show up here until it does.

## `experties commands` / `experties plugins`

`commands` prints this same reference, condensed, right in the
terminal. `plugins` shows the plugins directory currently in use and
which plugin files loaded successfully.