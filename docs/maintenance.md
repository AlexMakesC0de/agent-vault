# Maintain memory

[Setup](../README.md) · [Devices](devices.md) · [Architecture and recovery](architecture.md)

Use `python` instead of `python3` on native Windows. Run toolkit commands from the `agent-vault` folder and project-only commands from any folder with an explicit `--root`. The values below are examples; use your actual paths, evidence and current revision.

```bash
# Installed router loads the central profile and cwd-selected project; --prompt selects names.
python3 ~/.config/agent-memory/router.py context --prompt 'YourProject'
# Ranked search across the profile and every registered vault; --project narrows it (id, alias or "profile"):
python3 ~/.config/agent-memory/router.py search merge jobs --project myapp
# Read-only health check: install provenance, registry folders, hooks, profile caps; exit 1 on any problem:
python3 ~/.config/agent-memory/router.py doctor --fetch
# Read-only page of your profile, vaults, people notes and recent changes; refuses to write into a vault or project:
python3 ~/.config/agent-memory/view.py --open
# Central preference, using real evidence and the current revision:
python3 scripts/agent-memory.py --profile /absolute/path/to/private-profile update --target user --id preference --kind explicit --text 'A verified user preference.' --source 'notes/preferences.md#evidence' --agent human --expected-revision 1
# Authored identity, preserved before/after in history:
python3 scripts/agent-memory.py --profile /absolute/path/to/private-profile set-soul --help
# Verify a project's knowledge graph (read-only; non-zero exit on broken links or orphan notes):
python3 ~/.config/agent-memory/agent-memory.py --root /full/path/to/agent-vaults/myapp check-knowledge
# Project facts, from any folder:
python3 ~/.config/agent-memory/agent-memory.py --root /full/path/to/agent-vaults/myapp context
python3 ~/.config/agent-memory/agent-memory.py --root /full/path/to/agent-vaults/myapp update --help
```

Use `--target memory` for general lessons centrally. Inferred entries stay outside projections until supported. Updating or retiring retains prior values. A new entry id is refused when an active entry in the same store shares most of its content words; the error names that entry, so update it instead, or pass `--allow-similar` for a genuinely separate fact. Rewriting an existing id is never refused. Keep detail in linked topic notes (see `skills/vault-knowledge/SKILL.md`), avoid feature encyclopedias in the core, and never invent learning to satisfy a hook. Central `SOUL.md` is canonical; prefer `set-soul` to retain edit history. `render` rebuilds USER/MEMORY projections but **never overwrites authored SOUL**. Memory is context, not training or authorization. Learning depends on agents following instructions and hooks actually running; recall is not guaranteed.


## Obsidian

Open the private profile and each project as separate vaults. Start project navigation at `docs/knowledge/README.md`. Relative Markdown links work in Obsidian and Git viewers. Exact original documents and migration ledgers remain available. Exclude `.git`, dependencies, build output and runtime folders from navigation; keep `.obsidian/` local. The router shares relevant context across vaults without requiring Obsidian to be running.

## Development

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the development setup, the test suite and the rules every change follows. Tests verify our commands and protocol; actual client activation also depends on trust and client support.
