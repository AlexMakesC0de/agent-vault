# Turn off Claude's auto memory

[Setup](../README.md#quick-start) · [Memory commands](maintenance.md)

Claude Code's built-in **auto memory** is a separate store. With both systems active, the same lesson can end up in two places and the copies drift apart. For one source of learned memory, turn Claude's auto memory off on every device. Agent Vault's installer does not change this setting for you.

1. **Keep your existing notes.** In Claude, run `/memory` to open the auto memory folder. Copy the whole folder, including its `MEMORY.md` index and topic files, to a private backup. Check sessions started in your home folder and in each project you use, because their folders can differ. If you use persistent subagents, also back up `~/.claude/agent-memory/`, `.claude/agent-memory/` and `.claude/agent-memory-local/` where they exist. Do not delete the originals.
2. **Turn auto memory off.** Use the toggle in `/memory`, or add this key to your user settings (`~/.claude/settings.json` on macOS and Linux, `%USERPROFILE%\.claude\settings.json` on Windows), keeping your other settings:

   ```json
   {
     "autoMemoryEnabled": false
   }
   ```

3. **Move what is worth keeping.** After setting up Agent Vault, read the backed-up notes. Save personal preferences and general lessons through the central memory CLI, and put project facts in the owning project's vault, with their source as evidence. This is deliberate, not an automatic import.
4. **Check in a fresh session.** Restart Claude, confirm `/memory` shows auto memory off, and confirm new learning is saved through Agent Vault. If auto memory stays on, check [settings precedence](https://code.claude.com/docs/en/settings#settings-precedence) or ask your administrator about managed settings.

Keep `CLAUDE.md` and the Agent Vault hooks enabled. Review any old instruction that still tells Claude to save into its native memory folder. Do not point `autoMemoryDirectory` at, or symlink it into, an Agent Vault folder: another writer would then bypass the vault's revision and history checks.

See [Claude's memory controls](https://code.claude.com/docs/en/memory#enable-or-disable-auto-memory). If the toggle is missing, update Claude Code. The same setting also turns off Claude's [persistent subagent memory](https://code.claude.com/docs/en/sub-agents#enable-persistent-memory).
