# Migrate an existing vault

Use this only for an older Agent Vault project that already has a generated SOUL.md. New users should follow the [README](../README.md).

**Claude built-in auto memory is different:** this migration script does not import `~/.claude/projects/.../memory/`. Follow the [backup, disable and manual transfer steps](../README.md#0-claude-code-avoid-competing-memory) for those notes.

Do not rerun blank setup over an old vault. Read the current state and classify entries first. Preview explicitly selected preferences/general lessons into the initialized central profile:

```bash
python3 scripts/migrate-vault.py --project /absolute/path/to/YourProject --profile /absolute/path/to/private-profile --id your-project --name YourProject --move-user preference-id --move-memory general-lesson-id --expected-project-revision 4 --expected-profile-revision 0 --upgrade-tools
```

Use actual revisions and IDs, omit unused move flags, inspect the preview, then repeat with `--apply`. Unselected entries remain project facts. The migration retains exact originals, all entry text/evidence and previous history, archives affected files with SHA-256 hashes, copies source state/evidence into the private profile, and writes a destination ledger. Moved source entries are marked `migrated`, never erased. Only after archive verification does it remove the active project `SOUL.md`; exact bytes remain in the archive. An existing project `MEMORY.md` is archived and linked. Replays are idempotent; an interrupted operation resumes from preserved preimages. Preview never applies recovery changes. Inspect/reconcile unexpected edits or damaged archives rather than forcing migration.

The tool upgrades owned scripts only with `--upgrade-tools`. It adjusts maintained links and entry points; review project-specific prose that still describes the former architecture. Immutable imported source documents remain historical. Reinstall the user router after upgrading and review client hooks; old owned user handlers are replaced, unrelated handlers retained. Older project hook definitions should be upgraded deliberately after backing them up.

