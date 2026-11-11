# Use your memory on another device

[First-time setup](../README.md) · [Memory commands](maintenance.md)

Each device needs the tools, **your same profile**, and the projects you work on. Git carries the memory files between machines. Installation tells each machine where those files are.

## 1. Put your profile in a private Git repo — once

Skip this if your profile already has a Git remote.

1. In **your own GitHub account**, create an **empty private repository**. Choose any name, such as `agent-profile`. Do not add a README, license or .gitignore on GitHub.
2. Copy its repository URL.
3. From your local `agent-vault` folder, run the following, replacing `YOUR-USER` and `YOUR-PROFILE`:

```bash
git -C ../agent-profile init -b main
git -C ../agent-profile add SOUL.md USER.md MEMORY.md .agent-vault-profile.json .gitignore .gitattributes
git -C ../agent-profile commit -m "Create my agent profile"
git -C ../agent-profile remote add origin https://github.com/YOUR-USER/YOUR-PROFILE.git
git -C ../agent-profile push -u origin main
```

These Git commands work in PowerShell and Unix shells. Git needs your usual commit identity and GitHub authentication. Review and commit any additional evidence/notes you create, too. Keep the profile repo private because its contents are personal.

Also review and commit the generated vault files in **each project's own repo**: project MEMORY.md, AGENTS.md/CLAUDE.md, docs/knowledge, the memory scripts, project hook configuration and ignore rules. Push those project changes through your normal workflow. Cloning the toolkit does not copy project knowledge.

## 2. Clone on the other device

Replace the profile URL with **your private repo**, and `PROJECT-REPO-URL` with your project's URL. Use the project branch containing its committed vault files.

```bash
git clone https://github.com/AlexMakesC0de/agent-vault.git
git clone https://github.com/YOUR-USER/YOUR-PROFILE.git agent-profile
git clone PROJECT-REPO-URL MyApp
cd agent-vault
```

If you already have these folders, fetch/pull them instead. Preserve uncommitted work before switching branches. **Do not create an empty profile or initialize project memory over these clones.**

## 3. Connect this device to the existing files

Install Python 3.11+ and Git. Native Windows also needs Git for Windows/Git Bash for Claude hooks; Codex uses native PowerShell. No WSL is required.

**Windows — PowerShell**

```powershell
python scripts/project-memory-router.py install --profile ../agent-profile --codex-hooks
python scripts/project-memory-router.py register --id myapp --name MyApp --root ../agent-vaults/myapp --workspace ..\MyApp
```

**macOS / Linux — Terminal**

```bash
python3 scripts/project-memory-router.py install --profile ../agent-profile --codex-hooks
python3 scripts/project-memory-router.py register --id myapp --name MyApp --root ../agent-vaults/myapp --workspace ../MyApp
```

On every Claude device, [disable built-in auto memory and preserve existing notes](../README.md#0-claude-code-avoid-competing-memory). This user setting is separate from the profile Git repo.

For Claude only, remove `--codex-hooks`. A team-shared vault inside the repository is registered with `--root ../MyApp` and no `--workspace`. Register other cloned projects using their own names and paths. Restart clients, review/trust hooks, and ask a fresh main conversation to report the profile and project paths/revisions.

You do **not** run `init-profile` or `setup-vault.py` here: you already cloned the memory they would create.

## 4. Keep machines in sync

External vaults are local folders. To sync them to another device with Git, make each vault its own private repository (`git init` inside `agent-vaults/myapp`). A vault inside another Git checkout, including one repository around the whole `agent-vaults` folder, is refused. A file-sync tool can sync the whole folder. Then register each vault with that device's paths.

Before a writing session, pull the profile, the relevant project repos and each vault repository. Afterward, review, commit and push intentional changes. The toolkit does not sync automatically.

Runtime receipts, `.memory-runtime/`, `.vault-backups/`, `.obsidian/`, Python caches and client trust/settings stay local. The profile's `.agent-vault-profile.json` **does** belong in Git: it contains memory entries and history. The installer stores local paths in `~/.config/agent-memory/config.json` and `projects.json`; rebuild these by installing/registering on each machine rather than copying another device's files.

Local locks and revision checks protect one computer. If devices wrote offline at the same time, preserve both versions and reconcile their entries, evidence and histories before regenerating USER/MEMORY. Reconcile authored SOUL explicitly. Do not choose one state wholesale, force-push away the other device's changes, or fix a conflict by only increasing the revision number. There is no automatic cross-device merge.
