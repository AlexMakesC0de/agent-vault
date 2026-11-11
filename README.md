# Agent Vault

Give your coding agents **one shared personal memory**, plus a separate memory for each project. It works on Windows, macOS and Linux.

**Anyone with a copy can set up their own system.** This repo contains the tools. Each person creates their own profile; you do not need the author's private profile or any connection to their accounts.

## Where things live

```text
Your chosen folder/
├── agent-vault/          Tools you clone from this repo
├── agent-profile/        Your personal memory, created during setup
│   ├── SOUL.md           One identity shared by every agent
│   ├── USER.md           Your preferences
│   └── MEMORY.md         Lessons that apply across projects
├── agent-vaults/         Your project memory, outside the project repos
│   └── myapp/
│       ├── MEMORY.md     Facts about MyApp only
│       └── docs/knowledge/  Linked notes, read on demand
└── MyApp/                Your existing project; Agent Vault adds nothing to it
```

The profile is a local folder. A separate private GitHub repo is **optional**, for syncing that folder to your other devices. It does not create or connect a Claude, Codex or GitHub account.

## Set up your first machine

You need **Python 3.11+**, **Git**, and Claude Code and/or Codex. On Windows, install Git for Windows with **Git Bash** as well. WSL is unnecessary. Agent Vault needs no extra API key, server or build step.

Examples enable both hook-based clients. **For Claude only, remove `--codex-hooks` from the `install` command.**

### 0. Claude Code: avoid competing memory

Claude's built-in **auto memory** is a separate store. Leaving both systems active can produce duplicate or conflicting notes. **For one shared source of learned memory, turn Claude auto memory off on every device.** Agent Vault's installer does not change this setting for you.

1. **Preserve existing notes.** In Claude, use `/memory` to open the auto memory folder. Copy the whole memory folder, including its MEMORY.md index and topic files, to a private backup. Check home-directory sessions and each project you use; their folders may differ. If you use persistent subagents, also back up `~/.claude/agent-memory/`, `.claude/agent-memory/` and `.claude/agent-memory-local/` where present. Do not delete the originals.
2. **Disable auto memory.** Use the auto memory toggle in `/memory`. Alternatively, merge this top-level key into your existing user settings: `~/.claude/settings.json` on macOS/Linux, or `%USERPROFILE%\.claude\settings.json` on Windows. Keep your other settings:

   ```json
   {
     "autoMemoryEnabled": false
   }
   ```

3. **Transfer useful knowledge deliberately.** After setting up Agent Vault below, review the backed-up notes. Import personal preferences/general lessons through its central memory CLI; put project facts in the owning project's vault. Retain source evidence and the private originals. This is not an automatic import.
4. **Verify in a fresh session.** Restart Claude, check `/memory` shows auto memory off, and confirm learned notes are saved through Agent Vault to the selected profile/project. If auto memory stays on, check [settings overrides](https://code.claude.com/docs/en/settings#settings-precedence) or consult your administrator for managed settings.

**Keep CLAUDE.md and Agent Vault hooks enabled.** Review old instructions that still tell Claude to save into its native memory folder; reconcile those specific instructions after backing them up. Do not redirect `autoMemoryDirectory` or symlink Claude's native memory into an Agent Vault folder: that would let another writer bypass the vault's state/history checks.

See [Claude's official memory controls](https://code.claude.com/docs/en/memory#enable-or-disable-auto-memory). If the toggle is unavailable, update Claude Code. The same setting also disables Claude's built-in [persistent subagent memory](https://code.claude.com/docs/en/sub-agents#enable-persistent-memory).

### 1. Clone the tools and create your profile

Run these from the folder where you want `agent-vault` and `agent-profile` to live.

**Windows — PowerShell**

```powershell
git clone https://github.com/AlexMakesC0de/agent-vault.git
cd agent-vault
python scripts/agent-memory.py --profile ../agent-profile init-profile
python scripts/project-memory-router.py install --profile ../agent-profile --codex-hooks
```

**macOS / Linux — Terminal**

```bash
git clone https://github.com/AlexMakesC0de/agent-vault.git
cd agent-vault
python3 scripts/agent-memory.py --profile ../agent-profile init-profile
python3 scripts/project-memory-router.py install --profile ../agent-profile --codex-hooks
```

This creates your own starter profile and configures the clients to load it. It preserves existing client settings and backs them up. It does not create a GitHub repository.

### 2. Add your project

Stay inside `agent-vault`. Replace the example path with the full path to **your existing Git project**. You can also change `MyApp` and `myapp` to your project's name.

**Windows**

```powershell
python scripts/setup-vault.py --vault ../agent-vaults/myapp --name MyApp
python scripts/project-memory-router.py register --id myapp --name MyApp --root ../agent-vaults/myapp --workspace 'C:\Projects\MyApp'
```

**macOS / Linux**

```bash
python3 scripts/setup-vault.py --vault ../agent-vaults/myapp --name MyApp
python3 scripts/project-memory-router.py register --id myapp --name MyApp --root ../agent-vaults/myapp --workspace /full/path/to/MyApp
```

The vault is a folder of your own. The project repository is not changed, so teammates are unaffected. Working anywhere in MyApp, including its worktrees, loads the vault. To stop using a vault, run `python scripts/project-memory-router.py unregister --id myapp` (`python3` on macOS/Linux); the files stay. Repeat this step for additional projects; keep the same personal profile.

### Team-shared vault (optional)

To share project memory with everyone who clones the repository, put the vault in the repository instead: `setup-vault.py --root /full/path/to/MyApp --name MyApp`, then `register` without `--workspace`. Codex users add `--codex-hooks` to the `setup-vault.py` command. This commits memory scripts, hooks and notes to the repository, and every teammate's agent loads them.

**Already have an Agent Vault?** On another device, [follow the device guide](docs/devices.md) instead of creating empty memory. For an older project with a generated SOUL.md, [migrate it](docs/migration.md) first.

### 3. Check it works

Restart your coding client and review/trust its hooks when prompted. Start a fresh chat, even from your home directory, and ask:

> Which central profile and MyApp project memory did you load? Show their paths and revisions.

Expect the profile path to end in `agent-profile`, and the project path to point to your `agent-vaults/myapp` folder. Ask in the main conversation; Claude's `/btw` cannot inspect files or hooks.

To check the install itself at any time, run `python ~/.config/agent-memory/router.py doctor` (`python3` on macOS/Linux; add `--fetch` to compare with the latest main). It reports whether the installed tools match a merged commit, whether every registered folder exists, whether the hooks are in place and how full your profile is, and it changes nothing. `install` also refuses to replace tools that came from a commit your checkout does not contain, so installing from `main` never silently undoes unmerged work.

## What happens after setup?

Every agent loads the same personal profile. Mentioning a registered project loads its own memory too. Agents are instructed to review useful learning before finishing: personal preferences go into your profile; project facts stay in that project. This depends on the client hooks running and the agent following the instructions.

### Project knowledge is a graph

A project vault has two layers. `MEMORY.md` is a small core (2,200 characters) loaded every session, for rules that apply to almost every task. Everything else lives in `docs/knowledge/` as topic notes: one topic per note, grouped under area maps, linked to each other where they mention each other, and with no size limit. Agents start at the home map and follow links to only the notes a task needs, so context cost stays flat however large the codebase grows.

To build the graph for a project, ask your agent to use the **vault-knowledge** skill. The installer puts it in `~/.claude/skills/` for Claude and in the install folder for other agents. It surveys the repository, writes the maps, fills notes, and verifies the result with `check-knowledge`. When a vault has fewer than five topic notes, the session context asks the agent to offer this.

To find a note without knowing where it lives, agents run `router.py search` with a few words. It ranks matching notes across your profile and every registered vault, and prints a short snippet and the path of each. The search index is a single file in the install folder, built from the Markdown and updated automatically when notes change; deleting it is always safe.

Obsidian is optional: open your profile folder and each project folder as separate vaults. The agents read the Markdown directly, so Obsidian does not need to be running.

**Memory does not sync automatically.** To use it on another device, put your profile in your own private Git repo and make each vault its own private Git repository (`git init` inside `agent-vaults/myapp`); a vault inside another Git checkout, including one repository around the whole `agent-vaults` folder, is refused. A file-sync tool can sync the whole folder. A team-shared vault travels with its project repo. [The device guide shows each step](docs/devices.md).

### Other agents

Claude Code and Codex load memory through hooks. Any other agent that reads an instruction file and can run a shell command can use the same memory: pass its instruction file to `install --instructions PATH` (repeatable). The guidance block tells the agent to run the context command at task start and to record learning through the memory CLI.

[Memory commands](docs/maintenance.md) · [Existing-vault migration](docs/migration.md) · [Technical details and recovery](docs/architecture.md)
