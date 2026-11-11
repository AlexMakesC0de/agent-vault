# Central identity implementation plan

> **For agentic workers:** Implement inline with superpowers:executing-plans; request an independent final review before applying the real migration.

**Goal:** One central SOUL.md shared by Claude/Codex, separate project vaults, lossless migration, portable Windows/macOS/Linux installation.

**Architecture:** A private profile repository owns canonical SOUL.md plus generated USER.md/MEMORY.md and revisioned evidence/history. Each project owns its project MEMORY.md and knowledge graph; it no longer generates SOUL.md. The machine-local router points at a cloned profile and project paths and loads central context for both clients, even outside a project.

**Tech stack:** Python 3.11+ standard library, existing cross-platform locks and hook contracts, Git for transport, existing native Windows CI.

**Spec:** Alex's approved request in this conversation: “one central soul shared by claude and codex, with separate project vaults. migrate everything without losing any information ... across my devices including windows”.

## Constraints

- Keep generic code and blank templates in agent-vault; private profile data in its own private repo. Do not copy project knowledge or personal facts into the toolkit.
- SOUL.md is canonical identity Markdown, not a per-repo generated file. USER.md holds preferences; profile MEMORY.md holds general lessons. Project MEMORY.md holds repo facts. Existing user identity text is never reset by reinstallation.
- Preserve every original state/entry/history and exact affected file bytes with SHA-256 manifests before replacing/deleting anything. Import only explicitly selected user-entry IDs; do not guess scope or promote inferences.
- New schema remains readable alongside legacy schema 1 until migration. Migrated entries retain original content/provenance and a destination marker. Original history is a preserved prefix; destination imports retain exact source state/evidence.
- Migration requires current source/profile revisions, locks both stores in a consistent order, journals the transfer, and resumes idempotently after interruption. Overflow/collisions fail before source changes. Delete a repo SOUL only after archived bytes and destination writes are verified.
- User/project hook handlers are identical per client and replace only known owned previous definitions. Preserve unrelated hooks, instructions, permissions and TOML values. Never forge client hook trust.
- Local config stores paths; profile Git data has no machine path dependency. Windows needs native Python, Git Bash for Claude, PowerShell for Codex; WSL is not required. Git sync stays explicit and concurrent offline histories require reconciliation.

## Implementation

### 1. Store/schema and profile lifecycle

Files: scripts/agent-memory.py, scripts/profile_memory.py, tests/test_central_profile.py.

- [ ] Add failing CLI tests for profile init/context, shared identity from both agents, target=user/memory changes, identity edits/history, cap/stale-write preservation, and fresh project MEMORY with no SOUL.
- [ ] Implement profile schema/paths and direct SOUL loading; generated bounded USER/MEMORY; retain legacy project reading and review commands.
- [ ] Run focused/full suites and inspect revisions/history.

### 2. Lossless migration

Files: scripts/migrate-vault.py, tests/test_central_migration.py.

- [ ] Test exact originals/hashes, all entries and history preserved, explicit scope transfer, unchanged project facts, inactive root SOUL, idempotent rerun, interrupted transfer recovery, stale revisions, target collisions and overflow refusal.
- [ ] Implement preview/apply with source/profile locks, immutable archives, evidence copies and a journal. Upgrade owned tools only with an explicit flag; preserve their originals. Update owned entry references and hook arrays.
- [ ] Verify a migrated vault cloned into another device path retains all identity/project facts after local registration.

### 3. Shared router and client installation

Files: scripts/project-memory-router.py, scripts/vault_runtime.py, scripts/setup-vault.py, templates, existing integration tests.

- [ ] Test central injection on unrelated/home prompts for Claude/Codex, selected project context, review ownership, no duplicate tokens, missing/stale profile errors, additive config/instruction preservation, and no copied SOUL in project setup.
- [ ] Install engine/runtime alongside router; point local config to profile root; add Codex user hooks/AGENTS fallback and preserve its config. Support Claude-only installation and both clients explicitly.
- [ ] Keep central content visible within hook limits; defer oversized project detail using explicit read pointers. Retain native shell/Unicode/locking behavior.

### 4. Review, apply, verify and publish

- [ ] Update README, architecture, migration/device docs and templates. Run the complete suite on native Windows Python 3.11/3.13, macOS, Linux; independent review.
- [ ] Snapshot current Zethus state revision 4, including Claude's uncommitted learning; explicitly migrate automatic-learning, lossless-knowledge, connected-knowledge, project-vault-discovery and subagent-model-economy to central USER. Keep Zethus-specific entries in its project core. Preserve all 72 original instruction sections and original document archives.
- [ ] Create private agent-profile repo and machine-local profile registration. Install both clients without touching unrelated config or forging trust. Verify actual installed commands from home and migrated project context; no live-client activation claims without evidence.
- [ ] Commit only task changes, publish agent-vault/profile repos, and record exact verification and sync instructions. Existing Zethus in-flight source changes stay isolated.

## Review focus

Missing profile must never silently create a fresh identity; reruns must not overwrite central identity or duplicate imported preferences; source/profile crash boundaries must remain recoverable; old hook versions must not renew tokens twice; personal data must never enter the reusable toolkit. Central settings are one shared profile across apps, not separate Claude/Codex identities.
