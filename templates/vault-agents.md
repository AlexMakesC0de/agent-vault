# Project vault

This folder is the memory vault for one project. It lives outside the project repository, and nothing in it is committed there.

- [MEMORY.md](MEMORY.md): the project core, at most 2,200 characters, generated from [state](docs/knowledge/memory/state.json).
- [Knowledge](docs/knowledge/README.md): home map of a graph of linked topic notes, uncapped and read on demand. Follow links to only the notes the task needs; build it with the vault-knowledge skill.
- [Conventions](docs/knowledge/CONVENTIONS.md): how to record facts, evidence and history.

The project's own instructions stay in its repository `AGENTS.md`, owned by its team. Keep learning here, not there. Change memory only through the memory CLI command given in the session context.
If the session context reports a sync conflict, do not write memory; follow the reconcile steps it gives.
