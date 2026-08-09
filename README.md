# Experties-CLI

A local, terminal-driven skill mastery and rank-progression tracker.

Create skill tracks (e.g. Coding, Mathematics, Guitar), log timed focus
sessions against them, and watch your rank climb an RPG-style tier ladder
based on accumulated hours — all stored locally, with no cloud dependence.

## Requirements

- macOS
- Python 3.11+

## Setup

```bash
git clone <your-repo-url>
cd experties-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Quick start

```bash
experties start Coding      # live timer
experties log Coding --time 1h30m --note "fixed a bug"
experties list
experties stats Coding
```

See [COMMANDS.md](COMMANDS.md) for the full command reference, or run
`experties commands` for a quick in-terminal summary.

Want to add your own commands? See [PLUGINS.md](PLUGINS.md) — drop a
`.py` file in `~/.experties/plugins/` and it becomes a real subcommand,
no reinstalling.

Data lives locally in `~/.experties/data.db` (override with the
`EXPERTIES_DB_PATH` environment variable).