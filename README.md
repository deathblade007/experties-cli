# Experties-CLI

A local, terminal-driven skill mastery and rank-progression tracker.

Create skill tracks (e.g. Coding, Mathematics, Guitar), log timed focus
sessions against them, and watch your rank climb an RPG-style tier ladder
based on accumulated hours — all stored locally, with no cloud dependence.

**Status:** early development. The rank engine and its tests are in place;
the CLI itself is not runnable yet.

## Requirements

- macOS
- Python 3.11+

## Development setup

```bash
git clone <your-repo-url>
cd experties-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Usage instructions for the actual commands (`experties start`, `experties
log`, etc.) will be added here once the CLI is built out.