---
name: vault-knowledge
description: Build and grow an Agent Vault project knowledge graph of small, linked topic notes. Use when initialising or populating a project vault from its repository, when session context says a vault has few topic notes, when asked to document or map a codebase into the vault, or when a task taught something about one part of a project that belongs in a note rather than the memory core.
---

# Vault knowledge graph

A project vault keeps knowledge as a graph of topic notes, not one large file. The agent reads the map, follows links to the two or three notes the task needs, and ignores the rest. Context cost stays flat as the codebase grows.

| Layer | Path in the vault | Loaded | Limit |
| --- | --- | --- | --- |
| Core | `MEMORY.md` | Every session | 2,200 characters, through the memory CLI |
| Home map | `docs/knowledge/README.md` | When the task needs project detail | Keep it a short list of areas |
| Area maps | `docs/knowledge/<area>/README.md` | When the task touches the area | One line per note |
| Topic notes | `docs/knowledge/<area>/<topic>.md` | Only when followed from a map or link | None; split by topic, not size |

The core holds only rules that apply to almost every task in the project. Everything else is a note.

## Note rules

- **One topic per note.** A topic is one thing a reader asks about: a module, a data flow, an integration, a decision, a runbook. If a note answers two unrelated questions, split it.
- **Link at the mention.** When a note mentions another topic, link that topic's note in the sentence that mentions it. If the note does not exist yet, write the name without a link and add it to the area map as planned (see Initialise).
- **Every note is reachable.** Each note is linked from its area map, and starts with an up-link to that map. `check-knowledge` reports orphans.
- **Relative Markdown links only**, e.g. `[Auth flow](../backend/auth-flow.md)`. They work in Obsidian, Git viewers and plain file reads. No wikilinks, no absolute paths, no links into the project repository.
- **Point at code, do not copy it.** Name repository files as `` `backend/app/auth.py` `` with the symbol, not line numbers. The code stays the source of truth; the note says where things are, how they connect and why.
- **Write what is expensive to rediscover**: how a request or record flows across files, invariants the code relies on, conventions no linter enforces, environment and external-system facts, decisions with their reasons, gotchas and their fixes. Skip what one file read answers.
- **Frontmatter** on every note and area map:

  ```yaml
  ---
  type: map | reference | decision | runbook | lesson
  status: current | proposed | historical | superseded
  verified: 2026-01-31    # only when checked against code or by the user
  sources: [backend/app/auth.py, user 2026-01-31]
  ---
  ```

- **Evidence.** Every claim comes from code you read, a command you ran, or the user. Mark anything else as unverified in the note.
- **Never store** secrets, tokens, connection strings, customer data or personal information. Name environment variables, never their values.
- **Kebab-case filenames that never change.** Other notes link to them.

Note shape:

```markdown
---
type: reference
status: current
verified: 2026-01-31
sources: [backend/app/auth.py, backend/app/deps.py]
---

# Auth flow

Up: [Backend](README.md)

One-paragraph summary: what it is and when it matters.

## Where it lives
## How it works
## Connections
Links to related topics, each with one line on how they relate.
## Gotchas
```

## Initialise a vault from its repository

Do this when the vault is new or sparse. The vault root and workspace come from session context. Write only inside the vault; never write into the project repository.

1. **Survey read-only.** Read the README, `AGENTS.md`/`CLAUDE.md`, manifests (`package.json`, `pyproject.toml`), CI workflows, Dockerfiles, env examples and existing docs. List tracked files with `git -C <workspace> ls-files` to see the real shape and to skip ignored output.
2. **Choose areas.** Group the codebase into 3 to 8 areas a newcomer would ask about, e.g. architecture, backend, frontend, data model, integrations, auth, build and deploy, local development, testing. Use the project's own words.
3. **Write the maps first.** Replace the home map's placeholder text with the area list. Each area map lists its planned topics; a planned topic is plain text marked `(planned)` until its note exists, so no link is ever broken.
4. **Fill notes breadth-first.** Start with one overview note per area, then the topics with the most cross-file behaviour. Read the code for each note before writing it. Turn each `(planned)` entry into a link as its note lands.
5. **Link pass.** Re-read each note, link every mention of another topic, and add a Connections line in both notes when two topics depend on each other.
6. **Check.** Run `check-knowledge` (below) until it reports no broken links, orphans or missing frontmatter.
7. **Core last.** Only now ask whether one to three facts apply to nearly every task. Add those through the memory CLI with evidence. Do not copy notes into the core.
8. **Report** to the user: areas and notes created, what is still planned, and anything unverified.

For a large codebase, do not try to cover everything in one session. Map every area, write the overview notes, then go deep only where current work happens. The graph grows from use.

## Grow it during normal work

- Before changing an area, open the home map, then the area map, then only the notes the task needs.
- If a note contradicts the code, fix the note and its `verified` date in the same task.
- At the end-of-task memory review, put new project detail in the matching note, or create a note and link it from its area map. The core changes only for project-wide rules.
- Replacing a decision: set the old note to `status: superseded` and link it to the new one. Keep the old note; vault notes have no other history.

## Check the graph

```bash
python ~/.config/agent-memory/agent-memory.py --root <vault root> check-knowledge
```

It is read-only. It prints JSON with broken links, orphan notes, links that leave the vault, and notes without `type` frontmatter, and exits non-zero when links or reachability fail. Use `python3` on macOS and Linux.
