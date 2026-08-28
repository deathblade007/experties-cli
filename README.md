# Experties-CLI

A local, terminal-driven skill mastery and rank-progression tracker.

Create skill tracks (e.g. Coding, Mathematics, Guitar), log timed focus
sessions against them, and watch your rank climb an RPG-style tier ladder
based on accumulated hours — all stored locally, with no cloud dependence.
Group related skills into a "super skill" (e.g. Python + Maths under
Machine Learning) whose hours roll up automatically, and extend the app
yourself with plugins — no forking required.

## Requirements

- macOS
- Python 3.11+

## Installation (daily use)

The recommended way to run `experties` from any Terminal window, in any
folder, is [pipx](https://pipx.pypa.io):

```bash
brew install pipx
pipx ensurepath      # restart Terminal after this once
cd experties-cli
pipx install --editable .
```

`--editable` matters if you're actively developing this: it keeps
`experties` pointed at your live source folder, so changes take effect
immediately with no reinstall.

## Development setup

For working on the code itself and running the test suite:

```bash
git clone <your-repo-url>
cd experties-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

This `.venv` is separate from the pipx install above — use it only when
verifying changes (`pytest`), not for everyday use.

## Quick start

```bash
experties start Coding      # live timer
experties log Coding --time 1h30m --note "fixed a bug"
experties list
experties stats Coding
```

See [COMMANDS.md](COMMANDS.md) for the full command reference (including
groups and `cd`), or run `experties commands` for a quick in-terminal
summary.

Want to add your own commands? See [PLUGINS.md](PLUGINS.md) — drop a
`.py` file in `~/.experties/plugins/` and it becomes a real subcommand,
no reinstalling. Three working examples ship in `examples/plugins/`.

Data lives locally in `~/.experties/data.db` (override with the
`EXPERTIES_DB_PATH` environment variable).