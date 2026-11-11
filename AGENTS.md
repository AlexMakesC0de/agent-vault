# Agent Vault development

This repository contains reusable tools and empty templates. Never copy a user's project memories, state, private documents or real machine paths into it. Keep fixtures synthetic.

Python 3.11+ standard library only, Windows/macOS/Linux. Preserve existing file contents and configuration values during setup/install; refuse unsafe divergent migrations rather than resetting memory. Do not forge client hook trust or change permissions.

Before source changes, read the relevant script and [architecture](docs/architecture.md). Run `python3 -m unittest discover -s scripts/tests -q`; use real temporary repos/homes for lifecycle and installation tests. Commit only task files after reviewing the diff.
