# Experties-CLI — Cheat Sheet

The handful of commands you'll actually type day to day. For everything
else, see [`COMMANDS.md`](./COMMANDS.md) or run `experties commands`.

## Tracking time

```
experties timer start <skill>      # start tracking — start several at once
experties timer stop <skill>       # stop and log it (asks for a note)
experties timer status             # what's running right now, and for how long
```

Doing two things at once (e.g. two skills in the same group)? Start a
timer for each — the overlap only counts once in any shared total.

Prefer a single live countdown you watch instead? `experties start
<skill>` does that — but it blocks the terminal and only tracks one
thing at a time.

Forgot to start a timer? Log it after the fact:

```
experties log <skill> --time 1h30m
```

## Checking progress

```
experties list                     # everything — nested groups shown underneath
experties cd <skill>                # zoom `list` into just one skill/group
experties cd                        # back to the top level
experties stats <skill>             # rank progress + recent sessions for one skill
```

## Organizing skills into groups

```
experties group add <group> <skill>   # nest one skill under another — both
                                        # auto-created if new; groups can nest
                                        # inside groups
experties group list                  # every skill that currently has members
```

## If you forget everything else

```
experties commands
```