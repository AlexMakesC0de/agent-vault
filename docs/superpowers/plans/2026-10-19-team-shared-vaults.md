# Team-Shared Vaults and First-Run Interview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A small team shares external project vaults through a synced OneDrive or SharePoint folder without silent data loss, each teammate sets up with two VS Code Tasks, and a new profile's agent interviews its user before first use.

**Architecture:** External vaults (vault roots outside any Git checkout) keep locks and review receipts per user under `~/.config/agent-memory/runtime/`, so nothing machine-specific syncs. The engine detects sync-client conflict copies of memory files, reports them in context, blocks writes and offers a `conflicts` command that diffs and archives them. A new profile carries `onboarding: pending`; its context tells any agent to interview the user and save the answers, and `finish-onboarding` closes it. `scripts/onboard.py` plus `.vscode/tasks.json` wrap profile creation, installation and project connection.

**Tech Stack:** Python 3.11+ standard library, unittest, VS Code tasks.json.

**Spec:** The "Design" section below, agreed in conversation on 2026-10-19. No separate spec file.

## Global Constraints

- Python 3.11+ standard library only; Windows, macOS and Linux.
- Preserve existing files and configuration values; refuse rather than reset.
- Wording is agent-neutral: it addresses any coding agent, never only Claude or Codex.
- Docs state rules in the present tense with their technical reason; never describe earlier designs or past mistakes; no em dashes in new text.
- Fixtures and examples are synthetic (`DemoApp`, `OTHERPC`, `myapp`); never real machine paths, people or company projects.
- Commit messages carry no trailer of any kind.
- Run `python -m unittest discover -s scripts/tests -q` before each commit (about 2 minutes).

## Design

1. **Per-user runtime.** `agent-memory.py` puts `.memory-runtime/` inside the store root only when the root is a Git checkout (`.git` exists) or a central profile. Any other root is an external vault that may sit in a team sync folder, so its lock and receipts live in `~/.config/agent-memory/runtime/<first 16 hex of sha256(normcase(resolved root))>/`.
2. **Sync conflicts.** Canonical files are `.agent-vault-profile.json`, `SOUL.md`, `USER.md`, `MEMORY.md` and `docs/knowledge/memory/state.json`. A conflict copy is a sibling file named `<stem><space, "(", "_" or "-"><anything><same suffix>` (case-insensitive), which covers the OneDrive form `state-OTHERPC.json`, `state (1).json` and similar. Context starts with a notice listing copies; every write command refuses while copies exist; `conflicts` prints entries that differ, and `conflicts --archive` moves the copies to `<root>/.sync-conflicts/<UTC timestamp>/` so writes resume and the agent re-applies missing entries through `update`.
3. **First-run interview.** `init-profile` writes `"onboarding": "pending"`. While pending, profile context starts with an interview instruction. `finish-onboarding --source --agent --expected-revision` sets it to `done` with a history record. Profiles without the key are never interviewed. `--agent` accepts `other` for agents beyond Claude and Codex.
4. **Teammate setup.** `onboard.py machine --profile DIR` creates the profile if missing and installs the router. `onboard.py project --vault DIR --workspace DIR` creates the vault if missing, then registers it with id from the vault folder name. Two VS Code Tasks call these with prompts.
5. **Docs.** README gets a "Share project memory with your team" section; devices, architecture, maintenance and the vault template follow.

---

### Task 1: Keep external vault runtime per user

**Files:**
- Modify: `scripts/agent-memory.py:39-40` (`locked`), `scripts/agent-memory.py:145-147` (`session_path`)
- Test: `scripts/tests/test_external_vaults.py`

**Interfaces:**
- Produces: `runtime(root: Path) -> Path` in `agent-memory.py`. Tasks 2 and 3 use `locked(root)` unchanged.

- [ ] **Step 1: Write the failing test**

Add to `ExternalVaultTests` in `scripts/tests/test_external_vaults.py`:

```python
    def test_external_vault_keeps_runtime_out_of_the_shared_folder(self):
        self.create()
        self.hook(prompt='Explain DemoApp')
        self.assertFalse((self.vault / '.memory-runtime').exists())
        receipts = list((self.config / 'runtime').glob('*/session-*.json'))
        self.assertTrue(receipts)
        self.assertTrue(list((self.config / 'runtime').glob('*/write.lock')))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd scripts/tests && python -m unittest test_external_vaults.ExternalVaultTests.test_external_vault_keeps_runtime_out_of_the_shared_folder -q`
Expected: FAIL on `assertFalse((self.vault / '.memory-runtime').exists())`.

- [ ] **Step 3: Implement**

In `scripts/agent-memory.py`, replace `locked` and `session_path`:

```python
def runtime(root):
    # A vault outside any Git checkout may sit in a team sync folder; keep locks and receipts per user.
    if (root / ".git").exists() or (root / profile.PROFILE_STORE).exists():
        return root / ".memory-runtime"
    key = hashlib.sha256(os.path.normcase(str(root.resolve())).encode("utf-8")).hexdigest()[:16]
    return Path.home() / ".config/agent-memory/runtime" / key


def locked(root):
    return file_lock(runtime(root) / "write.lock")
```

```python
def session_path(root, session):
    key = hashlib.sha256(session.encode()).hexdigest()
    return runtime(root) / f"session-{key}.json"
```

- [ ] **Step 4: Run focused tests, then check the real home stays clean**

Run: `cd scripts/tests && python -m unittest test_external_vaults test_agent_memory test_project_memory_router test_central_router -q`
Expected: OK.

Then record `ls ~/.config/agent-memory/runtime 2>/dev/null | wc -l` before and after the full suite. Expected: the count does not change (every test that runs an external vault isolates HOME through `home_env`). If it grows, pass `env=home_env(...)` in the offending test's subprocess call.

- [ ] **Step 5: Full suite and commit**

```bash
python -m unittest discover -s scripts/tests -q
git add scripts/agent-memory.py scripts/tests/test_external_vaults.py
git commit -m "feat: keep external vault locks and receipts per user"
```

---

### Task 2: Detect sync-client conflict copies and block writes

**Files:**
- Modify: `scripts/agent-memory.py` (new `CANONICAL`, `sync_conflicts`, `conflict_notice`, `conflicts`; `context`; `change`; `main`)
- Modify: `templates/vault-agents.md`
- Test: `scripts/tests/test_external_vaults.py`, `scripts/tests/test_central_profile.py`

**Interfaces:**
- Consumes: `runtime`, `locked` from Task 1.
- Produces: `sync_conflicts(root: Path) -> list[Path]`; CLI `conflicts [--archive]` printing JSON `{"root", "copies", "differences", "archived", "next"}`. Task 3's `finish-onboarding` goes through `change()` and inherits the write block.

- [ ] **Step 1: Write the failing tests**

Add to `ExternalVaultTests` in `scripts/tests/test_external_vaults.py`:

```python
    def test_sync_conflict_copy_blocks_writes_until_archived(self):
        self.create()
        store = self.vault / 'docs/knowledge/memory/state.json'
        other = json.loads(store.read_text(encoding='utf-8'))
        other['entries'].append({'id': 'other-fact', 'text': 'Fact saved on another computer.', 'kind': 'explicit',
                                 'status': 'active', 'source': 'test', 'updated_at': '2026-01-01T00:00:00+00:00'})
        copy = store.with_name('state-OTHERPC.json')
        copy.write_text(json.dumps(other), encoding='utf-8')
        (self.vault / 'MEMORY (1).md').write_text('# copy\n', encoding='utf-8')
        text = self.hook(prompt='Explain DemoApp')
        self.assertIn('Sync conflict', text)
        self.assertIn('state-OTHERPC.json', text)
        update = ('update', '--id', 'later', '--kind', 'explicit', '--agent', 'other', '--expected-revision', '1',
                  '--source', 'test', '--text', 'Later fact.')
        blocked = self.run_script(ENGINE, '--root', str(self.vault), *update, check=False)
        self.assertEqual(blocked.returncode, 1)
        self.assertIn('Sync conflict', blocked.stderr)
        report = json.loads(self.run_script(ENGINE, '--root', str(self.vault), 'conflicts').stdout)
        self.assertEqual(len(report['copies']), 2)
        self.assertEqual([e['id'] for e in report['differences'][0]['only_in_copy']], ['other-fact'])
        self.assertIsNone(report['archived'])
        self.assertTrue(copy.exists())
        archived = json.loads(self.run_script(ENGINE, '--root', str(self.vault), 'conflicts', '--archive').stdout)
        self.assertFalse(copy.exists())
        self.assertTrue((Path(archived['archived']) / 'docs/knowledge/memory/state-OTHERPC.json').is_file())
        self.assertTrue((Path(archived['archived']) / 'MEMORY (1).md').is_file())
        self.run_script(ENGINE, '--root', str(self.vault), *update)
        self.assertNotIn('Sync conflict', self.hook(prompt='Explain DemoApp'))

    def test_ordinary_files_are_not_conflict_copies(self):
        self.create()
        (self.vault / 'docs/knowledge/memory/README.md').write_text('notes\n', encoding='utf-8')
        (self.vault / 'MEMORY.md.txt').write_text('archive\n', encoding='utf-8')
        report = json.loads(self.run_script(ENGINE, '--root', str(self.vault), 'conflicts').stdout)
        self.assertEqual(report['copies'], [])
```

Add to `ProfileTests` in `scripts/tests/test_central_profile.py`:

```python
    def test_conflicting_soul_copy_blocks_identity_change(self):
        self.init()
        (self.root / 'SOUL-OTHERPC.md').write_text('# Other identity\n', encoding='utf-8')
        self.assertIn('Sync conflict', self.cli('context').stdout)
        result = self.cli('set-soul', '--text', '# New\n', '--source', 'test', '--agent', 'human', '--expected-revision', '0')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Sync conflict', result.stderr)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd scripts/tests && python -m unittest test_external_vaults.ExternalVaultTests.test_sync_conflict_copy_blocks_writes_until_archived test_external_vaults.ExternalVaultTests.test_ordinary_files_are_not_conflict_copies test_central_profile.ProfileTests.test_conflicting_soul_copy_blocks_identity_change -q`
Expected: FAIL (no "Sync conflict" text; `conflicts` and `--agent other` are unknown arguments; Step 3 adds both).

- [ ] **Step 3: Implement**

In `scripts/agent-memory.py` (`datetime`, `timezone`, `os` and `re` are already imported), add after `STORE`:

```python
CANONICAL = [".agent-vault-profile.json", "SOUL.md", "USER.md", "MEMORY.md", "docs/knowledge/memory/state.json"]
```

Add after `load`:

```python
def sync_conflicts(root):
    # Sync clients keep both sides of a concurrent save as a sibling copy, e.g. state-OTHERPC.json.
    copies = []
    for relative in CANONICAL:
        path = root / relative
        if not path.parent.is_dir():
            continue
        pattern = re.compile(re.escape(path.stem) + r"[ (_-].*" + re.escape(path.suffix), re.IGNORECASE)
        copies += sorted(p for p in path.parent.iterdir()
                         if p.is_file() and p.name != path.name and pattern.fullmatch(p.name))
    return copies


def conflict_notice(root):
    copies = sync_conflicts(root)
    if not copies:
        return ""
    command = shell_command([sys.executable, str(Path(__file__).resolve()), "--root", str(root), "conflicts"])
    return ("Sync conflict: another computer saved this memory at the same time and left "
            + ", ".join(str(c) for c in copies) + ". Writes to this store are blocked until it is reconciled. "
            f"List the differences with `{command}`, archive the copies by adding --archive, "
            "then re-apply each missing entry with update, citing the archived copy as source.\n")


def conflicts(root, archive=False):
    with locked(root):
        state = load(root)
        copies = sync_conflicts(root)
        active = {e["id"]: e for e in state["entries"]}
        differences = []
        for copy in copies:
            if copy.suffix.lower() != ".json":
                continue
            try:
                other = [e for e in json.loads(copy.read_text(encoding="utf-8"))["entries"] if isinstance(e, dict)]
            except (ValueError, KeyError, TypeError):
                differences.append({"copy": str(copy), "unreadable": True})
                continue
            differences.append({"copy": str(copy),
                                "only_in_copy": [e for e in other if e.get("id") not in active],
                                "changed_in_copy": [e for e in other if e.get("id") in active and
                                                    (e.get("text"), e.get("status")) !=
                                                    (active[e["id"]]["text"], active[e["id"]]["status"])]})
        archived = None
        if archive and copies:
            target = root / ".sync-conflicts" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            for copy in copies:
                destination = target / copy.relative_to(root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(copy, destination)
            archived = str(target)
    return {"root": str(root), "copies": [str(c) for c in copies], "differences": differences, "archived": archived,
            "next": ("Re-apply each needed entry with update, citing the archived copy as source. "
                     "Compare SOUL.md copies by hand." if archived else
                     "Review the differences, then run conflicts --archive." if copies else "No conflict copies.")}
```

Change `context` to prefix the notice:

```python
def context(root):
    state = load(root)
    notice = conflict_notice(root)
    if profile.is_profile(state):
        return notice + profile.context(root, state)
    core = render(state)
    projection = root / profile.projection(state)
    if not projection.exists() or projection.read_text(encoding="utf-8") != core:
        print(f"{projection.name} projection is stale; authoritative memory is intact. Run agent-memory.py render.", file=sys.stderr)
    return f"{notice}Shared memory root: {root}\nMemory revision: {state['revision']}\n{core}"
```

In `change`, immediately after `with locked(root):` and before `state = load(root)`:

```python
        copies = sync_conflicts(root)
        if copies:
            raise ValueError("Sync conflict copies exist (" + ", ".join(c.name for c in copies) +
                             "); reconcile them with the conflicts command before writing")
```

In `main`, add the parser after the `review` parser:

```python
    command = commands.add_parser("conflicts")
    command.add_argument("--archive", action="store_true")
```

change the `--agent` choices of `update`, `retire` and `set-soul` to `["codex", "claude", "human", "other"]`, and add the dispatch before the final `else`:

```python
        elif args.command == "conflicts":
            print(json.dumps(conflicts(root, args.archive), ensure_ascii=False))
```

In `templates/vault-agents.md`, append this line:

```markdown
If the session context reports a sync conflict, do not write memory; follow the reconcile steps it gives.
```

- [ ] **Step 4: Run focused tests**

Run: `cd scripts/tests && python -m unittest test_external_vaults test_central_profile test_agent_memory -q`
Expected: OK.

- [ ] **Step 5: Full suite and commit**

```bash
python -m unittest discover -s scripts/tests -q
git add scripts/agent-memory.py templates/vault-agents.md scripts/tests/test_external_vaults.py scripts/tests/test_central_profile.py
git commit -m "feat: block memory writes while sync conflict copies exist"
```

---

### Task 3: Interview the user when a profile is new

**Files:**
- Modify: `scripts/profile_memory.py` (`INTERVIEW`, `init`, `context`)
- Modify: `scripts/agent-memory.py` (`change`, `main`)
- Test: `scripts/tests/test_central_profile.py`

**Interfaces:**
- Consumes: `change()` write block from Task 2; `--agent other` from Task 2.
- Produces: profile state key `onboarding` (`"pending"` or `"done"`); CLI `finish-onboarding --source TEXT --agent AGENT --expected-revision N` printing `{"revision", "root", "onboarding": "done"}`. Task 4's `onboard.py machine` relies on `init-profile` creating a pending profile.

- [ ] **Step 1: Write the failing tests**

Add to `ProfileTests` in `scripts/tests/test_central_profile.py`:

```python
    def test_new_profile_asks_for_an_interview_until_finished(self):
        self.init()
        self.assertIn('First-run setup', self.cli('context').stdout)
        result = self.cli('finish-onboarding', '--source', 'User skipped the interview', '--agent', 'other',
                          '--expected-revision', '0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('First-run setup', self.cli('context').stdout)
        state = json.loads((self.root / '.agent-vault-profile.json').read_text(encoding='utf-8'))
        self.assertEqual(state['onboarding'], 'done')
        self.assertEqual(state['history'][-1]['action'], 'finish-onboarding')
        again = self.cli('finish-onboarding', '--source', 'again', '--agent', 'other', '--expected-revision', '1')
        self.assertEqual(again.returncode, 1)

    def test_profile_without_onboarding_key_is_not_interviewed(self):
        self.init()
        path = self.root / '.agent-vault-profile.json'
        state = json.loads(path.read_text(encoding='utf-8'))
        del state['onboarding']
        path.write_text(json.dumps(state), encoding='utf-8')
        self.assertNotIn('First-run setup', self.cli('context').stdout)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd scripts/tests && python -m unittest test_central_profile -q`
Expected: FAIL (no "First-run setup"; `finish-onboarding` unknown; `KeyError: 'onboarding'`).

- [ ] **Step 3: Implement**

In `scripts/profile_memory.py`, add after `DEFAULT_SOUL`:

```python
INTERVIEW = ('First-run setup: this profile is new. Before working on the request, introduce yourself in one sentence '
             'and ask the user, in one message: (1) their name, role and team, and what they work on; (2) what they want '
             'you to be for them, for example a patient teacher, a fast pair programmer or a careful reviewer, and '
             'anything you must never do; (3) how they like answers: length, tone, level of technical detail and '
             'language; (4) tools, systems and standing rules you should know. Ask only for work context; never ask '
             'for passwords, secrets or private-life details. Any question may be skipped. Then save: your role, whom '
             'you work for and their work in SOUL.md through set-soul, keeping its rules on where memory belongs and '
             'that memory never grants authorization; each preference as its own update --target user --kind explicit '
             'entry citing the answers as source. Show the user what you saved. Finally run finish-onboarding with a '
             'source that summarizes what was saved or that the user skipped.\n')
```

In `init`, add `'onboarding': 'pending',` to the new `state` dict (after `'imports': {},`).

Replace `context`:

```python
def context(root, state):
    identity = validate_identity((root / 'SOUL.md').read_text(encoding='utf-8'))
    interview = INTERVIEW if state.get('onboarding') == 'pending' else ''
    return (f'{interview}Central shared profile: {root}\nProfile revision: {state["revision"]}\n'
            'The same canonical identity and preferences apply to every coding agent. Project vaults supply facts, not another identity.\n'
            f'Canonical identity: {root / "SOUL.md"}\n{identity}\n{render(state,"user")}\n{render(state,"memory")}')
```

In `scripts/agent-memory.py` `change`, insert directly after the stale-revision check:

```python
        if args.command == "finish-onboarding":
            if not profile.is_profile(state) or state.get("onboarding") != "pending":
                raise ValueError("No pending onboarding interview in this profile")
            if not args.source.strip():
                raise ValueError("Record what was saved or that the user skipped")
            state["onboarding"] = "done"
            state["revision"] += 1
            state["history"].append({"revision": state["revision"], "at": now(), "agent": args.agent,
                                     "action": "finish-onboarding", "source": args.source})
            atomic_write(profile.state_path(root), json.dumps(state, indent=2, ensure_ascii=False) + "\n")
            return {"revision": state["revision"], "root": str(root), "onboarding": "done"}
```

In `main`, change the write-command loop and dispatch:

```python
    for name in ["update", "retire", "set-soul", "finish-onboarding"]:
        command = commands.add_parser(name)
        if name in ["update", "retire"]:
            command.add_argument("--id", required=True)
```

(keep the remaining lines of that loop unchanged) and

```python
        elif args.command in ["update", "retire", "set-soul", "finish-onboarding"]:
            print(json.dumps(change(root, args)))
```

- [ ] **Step 4: Run focused tests**

Run: `cd scripts/tests && python -m unittest test_central_profile test_central_router test_external_vaults -q`
Expected: OK. If the context-overflow test in `test_external_vaults.py` changes outcome because the interview adds about 1,100 characters to a fresh profile, run `finish-onboarding` on that test's profile in its own setup rather than raising its limits.

- [ ] **Step 5: Full suite and commit**

```bash
python -m unittest discover -s scripts/tests -q
git add scripts/profile_memory.py scripts/agent-memory.py scripts/tests/test_central_profile.py
git commit -m "feat: interview the user when a profile is new"
```

---

### Task 4: One-step teammate setup with VS Code Tasks

**Files:**
- Create: `scripts/onboard.py`
- Create: `.vscode/tasks.json`
- Test: `scripts/tests/test_onboard.py`

**Interfaces:**
- Consumes: CLIs `agent-memory.py --profile DIR init-profile`, `project-memory-router.py install|register`, `setup-vault.py --vault --name`.
- Produces: `onboard.py machine --profile DIR [--instructions PATH]... [--codex-hooks]` and `onboard.py project --vault DIR --workspace DIR [--name NAME] [--alias NAME]...`, each printing one JSON object. Task 5 documents both.

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_onboard.py`:

```python
"""Teammate setup through onboard.py, as the VS Code Tasks run it."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from platform_helpers import home_env

SCRIPTS = Path(__file__).resolve().parents[1]
ONBOARD = SCRIPTS / 'onboard.py'
ROUTER = SCRIPTS / 'project-memory-router.py'


class OnboardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.shared = self.base / 'Team library' / 'agent-vaults'
        self.app = self.base / 'repos' / 'DemoApp'; self.app.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(self.app)], check=True)
        (self.app / 'AGENTS.md').write_text('# Team rules\n', encoding='utf-8')

    def person(self, name):
        home = self.base / name; (home / '.claude').mkdir(parents=True)
        return home

    def run_as(self, home, *args, check=True):
        result = subprocess.run([sys.executable, str(ONBOARD), *map(str, args)], capture_output=True, text=True,
                                encoding='utf-8', cwd=home, env=home_env(home))
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def context(self, home):
        result = subprocess.run([sys.executable, str(home / '.config/agent-memory/router.py'), 'context',
                                 '--cwd', str(self.app)], capture_output=True, text=True, encoding='utf-8',
                                env=home_env(home))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)['context']

    def test_machine_creates_private_profile_once_and_installs(self):
        home = self.person('ana')
        first = json.loads(self.run_as(home, 'machine', '--profile', '').stdout)
        self.assertEqual(Path(first['profile']), home / 'agent-profile')
        self.assertTrue((home / 'agent-profile/.agent-vault-profile.json').is_file())
        self.assertIn('project-memory-router', (home / '.claude/CLAUDE.md').read_text(encoding='utf-8'))
        before = (home / 'agent-profile/.agent-vault-profile.json').read_bytes()
        self.run_as(home, 'machine', '--profile', home / 'agent-profile')
        self.assertEqual((home / 'agent-profile/.agent-vault-profile.json').read_bytes(), before)

    def test_first_teammate_creates_vault_and_second_joins_it(self):
        ana, ben = self.person('ana'), self.person('ben')
        for home in [ana, ben]:
            self.run_as(home, 'machine', '--profile', '')
        created = json.loads(self.run_as(ana, 'project', '--vault', self.shared / 'demoapp',
                                         '--workspace', self.app).stdout)
        self.assertTrue(created['created'])
        self.assertEqual(created['project']['id'], 'demoapp')
        joined = json.loads(self.run_as(ben, 'project', '--vault', self.shared / 'demoapp',
                                        '--workspace', self.app).stdout)
        self.assertFalse(joined['created'])
        for home in [ana, ben]:
            self.assertIn(f'Shared memory root: {self.shared / "demoapp"}', self.context(home))
        self.assertFalse((self.shared / 'demoapp/.memory-runtime').exists())

    def test_project_refuses_a_workspace_that_is_not_a_checkout(self):
        home = self.person('ana')
        self.run_as(home, 'machine', '--profile', '')
        result = self.run_as(home, 'project', '--vault', self.shared / 'demoapp', '--workspace', self.base,
                             check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('primary root of a Git checkout', result.stderr)
        self.assertFalse((self.shared / 'demoapp').exists())

    def test_vscode_tasks_call_both_steps(self):
        tasks = json.loads((SCRIPTS.parent / '.vscode/tasks.json').read_text(encoding='utf-8'))
        labels = {t['label']: t for t in tasks['tasks']}
        self.assertIn('machine', labels['Agent Vault: set up this computer']['args'])
        self.assertIn('project', labels['Agent Vault: connect a project']['args'])
        inputs = {i['id'] for i in tasks['inputs']}
        for task in tasks['tasks']:
            for arg in task['args'] + task['windows']['args']:
                if arg.startswith('${input:'):
                    self.assertIn(arg[8:-1], inputs)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd scripts/tests && python -m unittest test_onboard -q`
Expected: FAIL (`onboard.py` and `.vscode/tasks.json` do not exist).

- [ ] **Step 3: Implement `scripts/onboard.py`**

```python
#!/usr/bin/env python3
"""Set up Agent Vault on this computer and connect projects; built for VS Code Tasks."""
import sys

if sys.version_info < (3, 11):
    raise SystemExit('Agent Vault needs Python 3.11 or newer')

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from vault_runtime import configure_io

HERE = Path(__file__).resolve().parent
ENGINE, ROUTER, SETUP = HERE / 'agent-memory.py', HERE / 'project-memory-router.py', HERE / 'setup-vault.py'


def run(script, *args):
    result = subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True,
                            encoding='utf-8')
    if result.returncode:
        raise ValueError(result.stderr.strip() or f'{script.name} failed')
    return json.loads(result.stdout)


def folder(value, default=None):
    value = (value or '').strip().strip('"').strip("'")
    if not value:
        if default is None:
            raise ValueError('A folder path is required')
        return default
    return Path(value).expanduser().absolute()


def machine(args):
    # The default stays outside Documents, which OneDrive often syncs; the profile is private.
    profile = folder(args.profile, Path.home() / 'agent-profile')
    if not (profile / '.agent-vault-profile.json').exists():
        run(ENGINE, '--profile', profile, 'init-profile')
    extra = [item for path in args.instructions for item in ['--instructions', folder(path)]]
    run(ROUTER, 'install', '--profile', profile, *extra, *(['--codex-hooks'] if args.codex_hooks else []))
    return {'profile': str(profile),
            'next': 'Restart VS Code, open a new agent chat and say hello. On first use your agent asks about you '
                    'and saves your answers to your private profile.'}


def checkout(path):
    # Validate before creating anything, so a wrong folder leaves no half-made vault behind.
    result = subprocess.run(['git', '-C', str(path), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                            capture_output=True, text=True, encoding='utf-8')
    root = Path(result.stdout.strip()).resolve().parent if result.returncode == 0 else None
    if root is None or os.path.normcase(str(root)) != os.path.normcase(str(path.resolve())):
        raise ValueError(f'Workspace must be the primary root of a Git checkout: {path}')


def project(args):
    vault, workspace = folder(args.vault), folder(args.workspace)
    checkout(workspace)
    store = vault / 'docs/knowledge/memory/state.json'
    created = not store.exists()
    if created:
        run(SETUP, '--vault', vault, '--name', args.name or workspace.name)
    name = json.loads(store.read_text(encoding='utf-8')).get('project') or workspace.name
    key = re.sub(r'[^a-z0-9]+', '-', vault.name.lower()).strip('-')[:80]
    if not key:
        raise ValueError('Name the vault folder with letters or digits')
    aliases = [item for alias in args.alias for item in ['--alias', alias]]
    registered = run(ROUTER, 'register', '--id', key, '--name', name, '--root', vault, '--workspace', workspace,
                     *aliases)
    return {'project': registered, 'created': created,
            'next': 'Open a new agent chat in the project; it loads this shared vault.'}


def main():
    configure_io()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('machine', help='Create your private profile if needed and install the router')
    command.add_argument('--profile', default='', help='Private profile folder; empty means ~/agent-profile')
    command.add_argument('--instructions', action='append', default=[],
                         help="Another agent's instruction file to receive the guidance block")
    command.add_argument('--codex-hooks', action='store_true')
    command = commands.add_parser('project', help='Create or join a shared project vault and register it')
    command.add_argument('--vault', required=True, help='Project vault folder inside the synced team library')
    command.add_argument('--workspace', required=True, help='Your local clone of the project')
    command.add_argument('--name', help='Project name for a new vault; defaults to the clone folder name')
    command.add_argument('--alias', action='append', default=[])
    args = parser.parse_args()
    try:
        print(json.dumps(machine(args) if args.command == 'machine' else project(args), ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Agent Vault setup: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 4: Implement `.vscode/tasks.json`**

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Agent Vault: set up this computer",
      "type": "process",
      "command": "python3",
      "args": ["${workspaceFolder}/scripts/onboard.py", "machine", "--profile", "${input:profileFolder}"],
      "windows": {
        "command": "py",
        "args": ["-3", "${workspaceFolder}/scripts/onboard.py", "machine", "--profile", "${input:profileFolder}"]
      },
      "problemMatcher": []
    },
    {
      "label": "Agent Vault: connect a project",
      "type": "process",
      "command": "python3",
      "args": ["${workspaceFolder}/scripts/onboard.py", "project", "--vault", "${input:vaultFolder}",
               "--workspace", "${input:projectFolder}"],
      "windows": {
        "command": "py",
        "args": ["-3", "${workspaceFolder}/scripts/onboard.py", "project", "--vault", "${input:vaultFolder}",
                 "--workspace", "${input:projectFolder}"]
      },
      "problemMatcher": []
    }
  ],
  "inputs": [
    {
      "id": "profileFolder",
      "type": "promptString",
      "description": "Folder for your private profile. Leave empty for agent-profile in your home folder. Never pick a synced folder.",
      "default": ""
    },
    {
      "id": "vaultFolder",
      "type": "promptString",
      "description": "Project vault folder inside the synced team library, for example ...\\agent-vaults\\myapp"
    },
    {
      "id": "projectFolder",
      "type": "promptString",
      "description": "Your local clone of the project"
    }
  ]
}
```

- [ ] **Step 5: Run focused tests**

Run: `cd scripts/tests && python -m unittest test_onboard -q`
Expected: OK.

- [ ] **Step 6: Full suite and commit**

```bash
python -m unittest discover -s scripts/tests -q
git add scripts/onboard.py .vscode/tasks.json scripts/tests/test_onboard.py
git commit -m "feat: set up teammates with onboard.py and VS Code Tasks"
```

---

### Task 5: Document team sharing, conflicts and the first-run interview

**Files:**
- Modify: `README.md`, `docs/devices.md`, `docs/architecture.md`, `docs/maintenance.md`

**Interfaces:**
- Consumes: commands and flags from Tasks 1 to 4, exactly as their argparse defines them.

- [ ] **Step 1: README, setup step 1**

After the paragraph ending "It does not create a GitHub repository." add:

```markdown
Your first chat after setup asks about you: your role and work, what the agent should be for you, and how you like answers. Your answers go into your private profile, and you can skip any question.
```

- [ ] **Step 2: README, team section**

After the "Team-shared vault (optional)" section and before "**Already have an Agent Vault?**", add:

````markdown
### Share project memory with your team (OneDrive or SharePoint)

A small team can share project vaults through a synced folder instead of a repository. Each person keeps a private profile; only project vaults are shared.

1. Create an `agent-vaults` folder in a SharePoint or Teams document library that only the team can edit, and sync it with OneDrive. Use a team library rather than a folder in one person's OneDrive, so access does not depend on one account.
2. In File Explorer, right-click the synced `agent-vaults` folder and choose **Always keep on this device**, so agents read local files.
3. Each person clones this repository, opens it in VS Code and runs **Terminal > Run Task > Agent Vault: set up this computer**. Leave the profile folder empty to use `agent-profile` in the home folder. Keep the profile out of synced folders; on Windows, OneDrive often syncs Documents.
4. For each project, run **Agent Vault: connect a project** and give the vault folder (for example `...\agent-vaults\myapp`) and your own clone of the project. The first person creates the vault; everyone else joins it.

Without VS Code, run the same steps from a terminal:

```bash
python scripts/onboard.py machine --profile ""
python scripts/onboard.py project --vault "/path/to/Team library/agent-vaults/myapp" --workspace /path/to/MyApp
```

Rules that keep shared memory safe:

- Locks and review receipts stay on each computer, in `~/.config/agent-memory/runtime/`, because file locks do not cross computers.
- When two people save the same vault before their computers sync, OneDrive keeps both versions and names one after the computer, such as `state-OTHERPC.json`. Agents then see a sync conflict notice and every memory write is blocked until someone reconciles it with the `conflicts` command, so no fact disappears silently.
- Everything written to a shared vault reaches every teammate's agent. Write project facts only, never personal preferences, secrets or customer data. Memory never grants permission to act.
````

- [ ] **Step 3: README, sync paragraph**

In the "**Memory does not sync automatically.**" paragraph, replace "A file-sync tool can sync the whole folder." with:

```markdown
To share vaults with a team through OneDrive or SharePoint, follow [Share project memory with your team](#share-project-memory-with-your-team-onedrive-or-sharepoint).
```

- [ ] **Step 4: devices.md**

In section "4. Keep machines in sync", replace "A file-sync tool can sync the whole folder." with:

```markdown
A synced OneDrive or SharePoint folder also works for vaults: locks and receipts stay per computer, and conflict copies block writes until reconciled. See [Share project memory with your team](../README.md#share-project-memory-with-your-team-onedrive-or-sharepoint). Keep your private profile out of team folders.
```

- [ ] **Step 5: architecture.md**

At the end of the first section (after the "Schema 1 remains readable..." paragraph), add:

```markdown
A new profile records `onboarding: pending`. While it is pending, profile context asks the agent to interview the user about their work, the agent's role and answer style, save the answers through `set-soul` and `update --target user`, and close the interview with `finish-onboarding`. Profiles without the key are never interviewed.
```

At the end of "Concurrency and recovery", add:

```markdown
Runtime locks and review receipts live in the store's `.memory-runtime/` when the root is a Git checkout or the central profile. Any other root is an external vault that may sit in a team sync folder, so its runtime lives per user in `~/.config/agent-memory/runtime/<hash of the root path>/`. Sync clients keep both sides of a concurrent save as a sibling copy, such as `state-OTHERPC.json` or `MEMORY (1).md`. The engine treats such copies of `.agent-vault-profile.json`, `SOUL.md`, `USER.md`, `MEMORY.md` and `state.json` as a conflict: context reports them, every write refuses, `conflicts` lists entries that differ, and `conflicts --archive` moves the copies to `.sync-conflicts/<timestamp>/` so the missing entries can be re-applied through `update` with the archive as evidence.
```

- [ ] **Step 6: maintenance.md**

In the first code block, after the project facts example, add:

```bash
# Sync conflict copies (team folders): list differences, then archive and re-apply:
python ~/.config/agent-memory/agent-memory.py --root ../agent-vaults/myapp conflicts
python ~/.config/agent-memory/agent-memory.py --root ../agent-vaults/myapp conflicts --archive
```

- [ ] **Step 7: Verify and commit**

Check that every relative link and anchor added resolves, that every command shown matches argparse in `scripts/onboard.py` and `scripts/agent-memory.py`, and that new text has no em dashes (`grep -n "—" README.md docs/*.md` shows only lines that existed before).

```bash
python -m unittest discover -s scripts/tests -q
git add README.md docs/devices.md docs/architecture.md docs/maintenance.md
git commit -m "docs: share project vaults through a team sync folder"
```

---

### Task 6: Acceptance on a real OneDrive folder (operational, with the user)

No code change. Run after Tasks 1 to 5 pass, on a machine with OneDrive for Business.

- [ ] **Step 1:** In a synced team library, create `agent-vaults`, mark it **Always keep on this device**, and run **Agent Vault: connect a project** for one test repository. Expected: success; the symlink guard accepts the OneDrive path; no `.memory-runtime` folder appears in the vault.
- [ ] **Step 2:** Ask an agent in that repository which vault it loaded. Expected: the OneDrive vault path and revision.
- [ ] **Step 3:** Pause OneDrive syncing. Save one fact locally through `update`. Edit `docs/knowledge/memory/state.json` of the same vault in the browser (change one entry text). Resume syncing. Expected: OneDrive leaves a copy whose name matches the conflict pattern; the next agent context shows the sync conflict notice; `update` refuses; `conflicts`, then `conflicts --archive`, then re-applying the entry restores normal writes.
- [ ] **Step 4:** Record the observed conflict file name in the ledger. If it does not match the pattern, stop and extend `sync_conflicts` with a test for that name before release.

---

## Part 2: Memory viewer

**Goal:** Anyone can see what their agents remember, without reading JSON: one read-only HTML page shows the profile, every registered project vault, people notes and the latest changes.

**Architecture:** `scripts/view.py` (standard library) reads `config.json` and `projects.json` from the router folder, loads each store through the engine's read-only `load` and `sync_conflicts`, reads `notes/people/*.md` from the profile, and writes one self-contained HTML file, by default `~/.config/agent-memory/view.html`. It takes no lock and writes no memory. The page carries a Content-Security-Policy of `default-src 'none'` with inline style and script and `data:` images only, so it loads nothing from the network; its favicon (an open book with a minium ribbon) is an inline SVG. Router install copies `view.py` next to the engine so an agent in any project can run it. The look follows the "Pressroom Index" design system: warm paper and ink, zero radius, one serif that names and one monospace that measures, one printing ink per project vault, dashed cards for inferred entries that are not loaded. The page uses the system fallbacks (Georgia, the platform monospace) because it fetches no fonts.

**Design rules for the page:**
- Read only. Each card offers a "Copy request" button that copies a sentence to paste into the agent chat; the agent makes the change through the CLI with evidence and the expected revision.
- The page holds private profile content and people notes, so `view.py` refuses an `--output` inside any registered vault root or workspace.
- Every value from memory or notes is HTML-escaped.
- People notes show the fields of `_template.md` and the latest dated history line; `README.md` and files starting with `_` are skipped.
- The page follows the operating system's light or dark setting; a System / Light / Dark toggle overrides it and the choice is kept in the browser's local storage for this page. Colours use CSS `light-dark()`, and the group inks have lighter dark-mode values so they stay readable.
- Section links scroll smoothly, except when the reader's system asks for reduced motion.
- Section headings are bold serif, and a full-width ink rule separates every section.

### Task 7: Read-only HTML memory page

**Files:**
- Create: `scripts/view.py`
- Create: `scripts/tests/test_view.py`
- Modify: `scripts/project-memory-router.py:257` (install copies `view.py`)
- Modify: `.vscode/tasks.json` (from Task 4: add a third task)
- Modify: `README.md`, `docs/maintenance.md`

**Interfaces:**
- Consumes: `agent-memory.py` module functions `load(root) -> dict`, `sync_conflicts(root) -> list[Path]`, `render(state, target) -> str` and constant `LIMIT`; `profile_memory.LIMITS` and `atomic_write(path, content)`; `vault_runtime.configure_io()`; Task 4's `.vscode/tasks.json` and its test `test_vscode_tasks_call_both_steps`, which checks every task's `windows.args`.
- Produces: `view.py [--config DIR] [--output FILE] [--open]`, printing `{"view": PATH, "vaults": N, "people": N}`.

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_view.py`:

```python
"""The read-only HTML memory page, built from a real profile, an external vault and people notes."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from platform_helpers import home_env

SCRIPTS = Path(__file__).resolve().parents[1]


class ViewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.home = Path(temp.name).resolve() / 'home'; (self.home / '.claude').mkdir(parents=True)
        self.config = self.home / '.config/agent-memory'
        self.profile = self.home / 'agent-profile'
        self.app = self.home / 'repos/DemoApp'; self.app.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(self.app)], check=True)
        self.vault = self.home / 'Team library/agent-vaults/demoapp'
        self.script(SCRIPTS / 'agent-memory.py', '--profile', self.profile, 'init-profile')
        self.script(SCRIPTS / 'project-memory-router.py', 'install', '--profile', self.profile)
        self.script(SCRIPTS / 'setup-vault.py', '--vault', self.vault, '--name', 'DemoApp')
        self.script(SCRIPTS / 'project-memory-router.py', 'register', '--id', 'demoapp', '--name', 'DemoApp',
                    '--root', self.vault, '--workspace', self.app)
        self.update(self.profile, 'answer-style', 'Short answers <script>alert(1)</script> & no jargon', 'explicit',
                    '--target', 'user')
        self.update(self.profile, 'maybe-tabs', 'Probably prefers tabs', 'inferred', '--target', 'user')
        self.update(self.vault, 'stack', 'DemoApp runs FastAPI and Next.js', 'explicit')
        people = self.profile / 'notes/people'; people.mkdir(parents=True)
        (people / 'README.md').write_text('# People\n', encoding='utf-8')
        (people / '_template.md').write_text('# Full Name\n\n- **Role:** job title, team\n', encoding='utf-8')
        (people / 'sam-demo.md').write_text(
            '# Sam Demo\n\n- **Role:** Data analyst, Demo team\n- **Relationship to me:** Stakeholder of DemoApp\n'
            '- **Work contact:** sam@example.com\n- **Projects:**\n\n## History\n\n'
            '- 2026-01-05: asked for a weekly export.\n- 2026-02-10: approved the dashboard layout.\n', encoding='utf-8')

    def script(self, path, *args, check=True):
        result = subprocess.run([sys.executable, str(path), *map(str, args)], capture_output=True, text=True,
                                encoding='utf-8', cwd=self.home, env=home_env(self.home))
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def update(self, root, key, text, kind, *extra):
        flag = '--profile' if root == self.profile else '--root'
        status = json.loads(self.script(SCRIPTS / 'agent-memory.py', flag, root, 'status').stdout)
        self.script(SCRIPTS / 'agent-memory.py', flag, root, 'update', '--id', key, '--text', text, '--kind', kind,
                    '--source', 'synthetic test', '--agent', 'other', '--expected-revision', status['revision'], *extra)

    def view(self, *args, check=True):
        return self.script(self.config / 'view.py', *args, check=check)

    def files(self):
        return {p: p.read_bytes() for root in [self.profile, self.vault] for p in root.rglob('*') if p.is_file()}

    def test_page_shows_profile_vault_people_and_changes_without_writing_memory(self):
        before = self.files()
        result = json.loads(self.view().stdout)
        self.assertEqual(self.files(), before)
        self.assertEqual(Path(result['view']), self.config / 'view.html')
        self.assertEqual([result['vaults'], result['people']], [1, 1])
        html = (self.config / 'view.html').read_text(encoding='utf-8')
        self.assertIn('Shared agent identity', html)
        self.assertIn('Short answers &lt;script&gt;alert(1)&lt;/script&gt; &amp; no jargon', html)
        self.assertNotIn('<script>alert(1)', html)
        self.assertIn('DemoApp runs FastAPI and Next.js', html)
        self.assertIn(f'Workspace: {self.app}', html)
        self.assertIn('Sam Demo', html)
        self.assertIn('Data analyst, Demo team', html)
        self.assertIn('2026-02-10: approved the dashboard layout.', html)
        self.assertNotIn('Full Name', html)
        self.assertIn('<td>update</td>', html)
        self.assertRegex(html, r'USER\.md</span><span>[\d,]+ / 1,375')

    def test_inferred_entries_are_marked_as_not_loaded(self):
        self.view()
        html = (self.config / 'view.html').read_text(encoding='utf-8')
        card = re.search(r'<article class="card card--draft"[^>]*>.*?</article>', html, re.DOTALL)
        self.assertIsNotNone(card)
        self.assertIn('maybe-tabs', card.group(0))
        self.assertIn('Inferred, not loaded', card.group(0))

    def test_page_loads_nothing_from_the_network(self):
        self.view()
        html = (self.config / 'view.html').read_text(encoding='utf-8')
        self.assertIn("default-src 'none'", html)
        self.assertIn('<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,', html)
        self.assertNotRegex(html, r'(src|href)\s*=\s*["\']?\s*(https?:)?//')

    def test_theme_toggle_offers_system_light_and_dark(self):
        self.view()
        html = (self.config / 'view.html').read_text(encoding='utf-8')
        for choice in ['system', 'light', 'dark']:
            self.assertIn(f'data-theme-choice="{choice}"', html)
        self.assertIn('data-theme-choice="system" aria-pressed="true"', html)
        self.assertIn('light-dark(', html)
        self.assertIn('scroll-behavior:smooth', html)

    def test_sync_conflict_copy_shows_a_notice(self):
        memory = self.vault / 'docs/knowledge/memory'
        (memory / 'state-OTHERPC.json').write_bytes((memory / 'state.json').read_bytes())
        self.view()
        html = (self.config / 'view.html').read_text(encoding='utf-8')
        self.assertIn('Sync conflict.', html)
        self.assertIn('docs/knowledge/memory/state-OTHERPC.json', html)

    def test_refuses_to_write_the_page_into_a_vault_or_project(self):
        for target in [self.vault / 'view.html', self.app / 'docs/view.html']:
            result = self.view('--output', target, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn('outside shared vaults and project folders', result.stderr)
            self.assertFalse(target.exists())

    def test_without_setup_names_the_setup_task(self):
        result = self.script(SCRIPTS / 'view.py', '--config', self.home / 'empty', check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Agent Vault: set up this computer', result.stderr)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd scripts/tests && python -m unittest test_view -q`
Expected: FAIL (`view.py` does not exist, so the installed copy is missing).

- [ ] **Step 3: Implement `scripts/view.py`**

```python
#!/usr/bin/env python3
"""Write a read-only HTML page of your profile, project vaults, people notes and recent memory changes."""
import sys

if sys.version_info < (3, 11):
    raise SystemExit('Agent Vault needs Python 3.11 or newer')

import argparse
import base64
from datetime import datetime, timezone
from html import escape
import importlib.util
import json
from pathlib import Path
import re
import webbrowser

from profile_memory import LIMITS, atomic_write
from vault_runtime import configure_io

HERE = Path(__file__).resolve().parent
# One printing ink per project vault, cycling after eight, as in the design system's group inks.
INKS = [f'var(--ink-{n})' for n in range(1, 9)]
THEMES = [('system', 'System'), ('light', 'Light'), ('dark', 'Dark')]
FIELDS = ['Role', 'Organisation', 'Relationship to me', 'Work contact', 'How to write to them', 'Projects']
SECTIONS = [('profile', 'Profile'), ('projects', 'Projects'), ('people', 'People'), ('changes', 'Recent changes')]
# The page holds private notes, so it may load nothing from the network and send nothing anywhere.
CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:"
# An open book with a ribbon bookmark, inline because the page fetches nothing.
FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" fill="#F2EFE6"/>'
           '<path d="M16 9.5C13 7.5 8.5 7 4 7.5v17c4.5-.5 9 0 12 2 3-2 7.5-2.5 12-2v-17c-4.5-.5-9 0-12 2z" '
           'fill="#FAF8F2" stroke="#17150F" stroke-width="2" stroke-linejoin="round"/>'
           '<path d="M16 9.5v17" stroke="#17150F" stroke-width="2"/>'
           '<path d="M20 8.2V17l2.2-1.8 2.2 1.8V7.7" fill="#B4471C"/></svg>')

STYLE = """
/* light-dark() follows color-scheme: the OS setting by default, or the reader's choice from the theme toggle. */
:root{color-scheme:light dark;
--paper:light-dark(#F2EFE6,#1A1813);--paper-raised:light-dark(#FAF8F2,#23201A);--ink:light-dark(#17150F,#F2EFE6);
--ink-soft:light-dark(#6B6455,#A69E8B);--rule:light-dark(#D8D2C2,#3D382D);
--ink-1:light-dark(#B4471C,#E2805A);--ink-2:light-dark(#2C6551,#6DB396);--ink-3:light-dark(#2B4A87,#88A4E3);
--ink-4:light-dark(#93325A,#D97BA1);--ink-5:light-dark(#5E4491,#A991DB);--ink-6:light-dark(#7C5A10,#CFA54F);
--ink-7:light-dark(#24657F,#68B4D2);--ink-8:light-dark(#7A3A2A,#C9806C);
--serif:"Libre Caslon Display",Georgia,"Times New Roman",serif;
--mono:"Sometype Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
--xs:4px;--sm:8px;--md:16px;--lg:24px;--xl:40px;--xxl:64px;--gutter:24px;--group-ink:var(--ink)}
:root[data-theme="light"]{color-scheme:light}
:root[data-theme="dark"]{color-scheme:dark}
@media (min-width:900px){:root{--gutter:40px}}
html{scroll-behavior:smooth}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:400 13px/1.6 var(--mono);
font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
::selection{background:var(--ink);color:var(--paper)}
:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.wrap{max-width:1600px;margin:0 auto;padding:0 var(--gutter)}
h1,h2,h3{font-family:var(--serif);font-weight:400;margin:0}
h1{font-size:clamp(2rem,4vw,2.75rem);line-height:1.02;letter-spacing:-0.01em}
h2{font-size:clamp(2rem,3.2vw,2.5rem);line-height:1.05;font-weight:700;color:var(--ink)}
.vault__title{font-size:1.75rem;line-height:1.05;font-weight:700}
.label{margin:0;font-size:11px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-soft)}
.masthead{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:var(--lg);
padding:var(--xl) 0 var(--lg)}
.masthead .label{margin-top:var(--sm)}
.tabs{display:flex;flex-wrap:wrap;gap:var(--lg);padding-bottom:12px;border-bottom:1px solid var(--ink)}
.tab{font:400 20px/1 var(--serif);color:var(--ink-soft);text-decoration:none;padding:18px 0 8px;
border-bottom:1px solid transparent}
.tab:hover{color:var(--ink);border-bottom-color:var(--ink)}
section{padding:var(--xl) 0;border-bottom:1px solid var(--ink);scroll-margin-top:var(--md)}
.section__head{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:var(--md);
margin-bottom:var(--lg)}
.sub{margin:var(--xl) 0 var(--md);padding-top:var(--md);border-top:1px solid var(--rule);font-size:12px;color:var(--ink)}
.vault+.vault{margin-top:var(--xl);padding-top:var(--xl);border-top:1px solid var(--rule)}
.meters{display:grid;gap:var(--md);grid-template-columns:repeat(auto-fit,minmax(220px,1fr));margin-bottom:var(--lg)}
.meter__line{display:flex;justify-content:space-between;font-size:12px;letter-spacing:.02em;color:var(--ink-soft)}
.meter__bar{height:6px;border:1px solid var(--ink);background:var(--paper-raised);margin-top:var(--xs)}
.meter__bar span{display:block;height:100%;background:var(--ink)}
.meter--over .meter__bar{border-style:dashed}
.grid{display:grid;grid-template-columns:1fr;gap:var(--lg)}
@media (min-width:760px){.grid{grid-template-columns:repeat(2,1fr)}}
@media (min-width:1200px){.grid{grid-template-columns:repeat(3,1fr)}}
.card{display:flex;flex-direction:column;background:var(--paper-raised);border:1px solid var(--rule)}
.card:hover,.card:focus-within{border-color:var(--ink)}
.card--draft{border-style:dashed;border-color:var(--ink-soft)}
.card__caption{padding:var(--md);display:flex;flex-direction:column;gap:12px;flex:1}
.card__line{display:flex;align-items:baseline;justify-content:space-between;gap:var(--md)}
.card__title{font-size:26px;line-height:1.05;overflow-wrap:anywhere}
.card__desc{margin:0;font-size:12px;line-height:1.35;letter-spacing:.02em;color:var(--ink-soft);text-align:right;
flex:none;max-width:52%;text-wrap:balance}
.card--draft .card__desc{font-size:11px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;color:var(--ink)}
.card__text{margin:0;white-space:pre-wrap;max-width:68ch;overflow-wrap:anywhere}
.card__source{margin:0;font-size:12px;letter-spacing:.02em;color:var(--ink-soft);overflow-wrap:anywhere}
.card__foot{display:flex;align-items:center;justify-content:space-between;gap:var(--md);margin-top:auto;
padding-top:12px;border-top:1px solid var(--rule)}
.card__index{font-size:12px;color:var(--ink-soft)}
.group-mark{display:inline-flex;align-items:center;gap:var(--sm);font-size:11px;font-weight:500;letter-spacing:.12em;
text-transform:uppercase;color:var(--group-ink)}
.group-mark::before{content:"";width:6px;height:6px;background:var(--group-ink);transform:rotate(45deg);flex:none}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:var(--md)}
.tag{font:400 12px/1 var(--mono);letter-spacing:.02em;color:var(--ink-soft);background:var(--paper);
border:1px solid var(--rule);padding:7px 10px;overflow-wrap:anywhere}
.masthead .tags{margin:0}
.masthead__tools{display:flex;flex-direction:column;align-items:flex-end;gap:var(--md)}
.themes{display:flex;gap:0}
.chip{font:500 11px/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--ink);background:var(--paper);
border:1px solid var(--ink);border-radius:0;padding:11px 14px;cursor:pointer}
.chip+.chip{border-left:0}
.chip:hover{background:var(--paper-raised)}
.chip[aria-pressed="true"]{background:var(--ink);color:var(--paper)}
.copy{font:500 11px/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--ink);
background:var(--paper-raised);border:1px solid var(--ink);border-radius:0;padding:8px 12px;cursor:pointer;
flex:none;min-width:88px}
.copy:hover{background:var(--paper)}
.copy[data-done="true"]{background:var(--ink);color:var(--paper)}
.artifact{border:1px solid var(--rule);background:var(--paper-raised)}
.artifact summary{display:flex;justify-content:space-between;gap:var(--md);padding:10px var(--md);cursor:pointer;
list-style:none;font-size:11px;font-weight:500;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-soft)}
.artifact summary::-webkit-details-marker{display:none}
.artifact summary:hover{color:var(--ink)}
.artifact[open] summary{border-bottom:1px solid var(--rule)}
.artifact__text{margin:0;padding:var(--md);font:400 13px/1.6 var(--mono);white-space:pre-wrap;max-width:68ch}
.notice{margin:0 0 var(--lg);padding:var(--md);background:var(--paper-raised);border:1px solid var(--ink);
font-size:12px;max-width:100ch}
.notice strong{font-weight:500}
code{font-family:var(--mono);background:var(--paper);border:1px solid var(--rule);padding:2px 6px}
.fields{margin:0;display:grid;grid-template-columns:max-content 1fr;gap:6px var(--md);font-size:12px}
.fields dt{font-size:11px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-soft)}
.fields dd{margin:0;overflow-wrap:anywhere}
.blank{margin:0;color:var(--ink-soft);font-style:italic}
.table{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12px;letter-spacing:.02em}
th{text-align:left;font-size:11px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-soft);
padding:0 var(--md) var(--sm) 0;border-bottom:1px solid var(--ink)}
td{padding:var(--sm) var(--md) var(--sm) 0;border-bottom:1px solid var(--rule);vertical-align:top}
.colophon{display:flex;justify-content:space-between;flex-wrap:wrap;gap:var(--md);padding:var(--lg) 0 var(--xl);
font-size:11px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-soft)}
"""

# Runs in <head> so a saved theme applies before the first paint, without a flash of the other theme.
EARLY = """try { const t = localStorage.getItem('agent-vault-theme');
if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t; } catch {}"""

SCRIPT = """
function applyTheme(choice) {
  if (choice === 'light' || choice === 'dark') document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
  for (const button of document.querySelectorAll('[data-theme-choice]')) {
    button.setAttribute('aria-pressed', String(button.dataset.themeChoice === (choice || 'system')));
  }
}
applyTheme(document.documentElement.dataset.theme);
document.addEventListener('click', async (event) => {
  const theme = event.target.closest('[data-theme-choice]');
  if (theme) {
    applyTheme(theme.dataset.themeChoice);
    try { localStorage.setItem('agent-vault-theme', theme.dataset.themeChoice); } catch {}
    return;
  }
  const button = event.target.closest('[data-copy]');
  if (!button) return;
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
  } catch {
    const area = document.createElement('textarea');
    area.value = button.dataset.copy;
    document.body.append(area);
    area.select();
    document.execCommand('copy');
    area.remove();
  }
  button.dataset.done = 'true';
  button.textContent = 'Copied';
  setTimeout(() => { button.dataset.done = 'false'; button.textContent = 'Copy request'; }, 1400);
});
"""


def e(value):
    return escape(str(value), quote=True)


def engine():
    # agent-memory.py is a script, not a package; load it for its read-only load and sync_conflicts helpers.
    spec = importlib.util.spec_from_file_location('agent_memory', HERE / 'agent-memory.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measure(render, state, target):
    # render refuses an oversize projection; the page reports that instead of failing.
    try:
        return len(render(state, target))
    except ValueError:
        return None


def changes(store, state):
    for item in state['history']:
        if not isinstance(item, dict):
            continue
        subject = next((v for v in (item.get('after'), item.get('before')) if isinstance(v, dict)), {})
        yield {'at': str(item.get('at', '')), 'store': store, 'revision': item.get('revision', ''),
               'agent': item.get('agent', ''), 'action': item.get('action', ''),
               'entry': subject.get('id', 'SOUL.md' if item.get('action') == 'set-soul' else ''),
               'source': subject.get('source', item.get('source', ''))}


def people(profile_root):
    folder = profile_root / 'notes' / 'people'
    cards = []
    for path in sorted(folder.glob('*.md')) if folder.is_dir() else []:
        if path.name.lower() == 'readme.md' or path.name.startswith('_'):
            continue
        text = path.read_text(encoding='utf-8')
        name = next((line[2:].strip() for line in text.splitlines() if line.startswith('# ')), path.stem)
        fields = dict(re.findall(r'^- \*\*(.+?):\*\*[ \t]*(.*)$', text, re.MULTILINE))
        history = re.findall(r'^- (\d{4}-\d{2}-\d{2}: .+)$', text, re.MULTILINE)
        cards.append({'file': path.name, 'name': name, 'latest': max(history) if history else '',
                      'fields': {k: fields[k].strip() for k in FIELDS if fields.get(k, '').strip()}})
    return cards


def snapshot(config_dir):
    config = config_dir / 'config.json'
    if not config.is_file():
        raise ValueError('No profile is set up on this computer; run "Agent Vault: set up this computer" first')
    memory = engine()
    root = Path(json.loads(config.read_text(encoding='utf-8'))['profile_root'])
    state = memory.load(root)
    soul = (root / 'SOUL.md').read_text(encoding='utf-8')
    sizes = [('SOUL.md', len(soul), LIMITS['soul']), ('USER.md', measure(memory.render, state, 'user'), LIMITS['user']),
             ('MEMORY.md', measure(memory.render, state, 'memory'), LIMITS['memory'])]
    history = list(changes('Profile', state))
    registry = config_dir / 'projects.json'
    vaults = []
    for project in json.loads(registry.read_text(encoding='utf-8'))['projects'] if registry.is_file() else []:
        item = {'project': project, 'limit': memory.LIMIT}
        try:
            item['state'] = memory.load(Path(project['root']))
            item['conflicts'] = memory.sync_conflicts(Path(project['root']))
        except (OSError, ValueError) as error:
            item['error'] = str(error)
        else:
            item['size'] = measure(memory.render, item['state'], 'memory')
            history += changes(project['name'], item['state'])
        vaults.append(item)
    return {'generated': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
            'profile': {'root': root, 'state': state, 'soul': soul, 'sizes': sizes,
                        'conflicts': memory.sync_conflicts(root)},
            'vaults': vaults, 'people': people(root),
            'history': sorted(history, key=lambda row: row['at'], reverse=True)[:20]}


def meter(name, used, limit):
    over = used is None
    width = 100 if over else min(100, round(used * 100 / limit))
    figure = f'over {limit:,}' if over else f'{used:,} / {limit:,}'
    return (f'<div class="meter{" meter--over" if over else ""}"><div class="meter__line"><span>{e(name)}</span>'
            f'<span>{figure}</span></div><div class="meter__bar"><span style="width:{width}%"></span></div></div>')


def grid(cards, empty):
    return f'<div class="grid">{"".join(cards)}</div>' if cards else f'<p class="blank">{e(empty)}</p>'


def copy(request):
    return f'<button class="copy" type="button" data-copy="{e(request)}">Copy request</button>'


def card(entry, store, revision, ink):
    inferred = entry.get('kind') == 'inferred'
    request = f'In Agent Vault ({store}, revision {revision}), change entry "{entry["id"]}" so it says: '
    return (f'<article class="card{" card--draft" if inferred else ""}" style="--group-ink:{ink}">'
            '<div class="card__caption"><div class="card__line">'
            f'<h3 class="card__title">{e(entry["id"])}</h3>'
            f'<p class="card__desc">{e("Inferred, not loaded" if inferred else entry.get("kind", ""))}</p></div>'
            f'<p class="card__text">{e(entry.get("text", ""))}</p>'
            f'<p class="card__source">Source: {e(entry.get("source", ""))}</p>'
            f'<div class="card__foot"><span class="group-mark">{e(store)}</span>'
            f'<span class="card__index">{e(str(entry.get("updated_at", ""))[:10])}</span>{copy(request)}</div>'
            '</div></article>')


def conflict(copies, root):
    if not copies:
        return ''
    names = ', '.join(f'<code>{e(c.relative_to(root).as_posix())}</code>' for c in copies)
    return ('<div class="notice"><strong>Sync conflict.</strong> Another computer saved this memory at the same time. '
            f'Memory writes are blocked until your agent reconciles it. Copies: {names}</div>')


def profile_section(item):
    state, label = item['state'], 'Profile'
    active = [x for x in state['entries'] if x.get('status') == 'active']
    groups = ''.join(
        f'<p class="label sub">{name}</p>'
        + grid([card(x, label, state['revision'], 'var(--ink)') for x in active if x.get('target', 'memory') == target],
               'No entries yet.')
        for name, target in [('USER.md: your preferences', 'user'), ('MEMORY.md: general lessons', 'memory')])
    return ('<section id="profile"><div class="section__head"><h2>Your profile</h2>'
            f'<span class="label">Revision {e(state["revision"])}</span></div>'
            f'<div class="tags"><span class="tag">Profile: {e(item["root"])}</span></div>'
            + conflict(item['conflicts'], item['root'])
            + '<div class="meters">' + ''.join(meter(*size) for size in item['sizes']) + '</div>'
            + f'<details class="artifact" open><summary><span>SOUL.md: who your agent is</span>'
            f'<span>{len(item["soul"]):,} characters</span></summary>'
            f'<pre class="artifact__text">{e(item["soul"])}</pre></details>' + groups + '</section>')


def vault_block(item, ink):
    project = item['project']
    places = [f'Vault: {project["root"]}'] + [f'Workspace: {w}' for w in project.get('workspaces', [])]
    if 'state' in item:
        places.insert(0, f'Revision {item["state"]["revision"]}')
    head = (f'<div class="vault" style="--group-ink:{ink}"><div class="section__head">'
            f'<h3 class="vault__title">{e(project["name"])}</h3>'
            f'<span class="group-mark">{e(project["id"])}</span></div>'
            '<div class="tags">' + ''.join(f'<span class="tag">{e(p)}</span>' for p in places) + '</div>')
    if 'error' in item:
        return head + f'<p class="notice">This vault cannot be read: {e(item["error"])}</p></div>'
    state = item['state']
    active = [x for x in state['entries'] if x.get('status') == 'active']
    return (head + conflict(item['conflicts'], Path(project['root']))
            + f'<div class="meters">{meter("MEMORY.md", item["size"], item["limit"])}</div>'
            + grid([card(x, project['name'], state['revision'], ink) for x in active], 'No entries yet.') + '</div>')


def person(note):
    fields = ''.join(f'<dt>{e(k)}</dt><dd>{e(v)}</dd>' for k, v in note['fields'].items() if k != 'Role')
    request = f'Update my people note for {note["name"]}: '
    return ('<article class="card"><div class="card__caption"><div class="card__line">'
            f'<h3 class="card__title">{e(note["name"])}</h3>'
            f'<p class="card__desc">{e(note["fields"].get("Role", ""))}</p></div>'
            f'<dl class="fields">{fields}</dl>'
            f'<p class="card__source">{e(note["latest"] or "No history yet.")}</p>'
            f'<div class="card__foot"><span class="card__index">{e(note["file"])}</span>{copy(request)}</div>'
            '</div></article>')


def history_section(rows):
    columns = ['Revision', 'When', 'Store', 'Agent', 'Action', 'Entry', 'Source']
    if not rows:
        return '<section id="changes"><div class="section__head"><h2>Recent changes</h2></div><p class="blank">No changes yet.</p></section>'
    body = ''.join('<tr>' + ''.join(f'<td>{e(v)}</td>' for v in [
        row['revision'], row['at'][:16].replace('T', ' '), row['store'], row['agent'], row['action'], row['entry'],
        row['source']]) + '</tr>' for row in rows)
    return ('<section id="changes"><div class="section__head"><h2>Recent changes</h2>'
            f'<span class="label">Latest {len(rows)}</span></div><div class="table"><table><thead><tr>'
            + ''.join(f'<th>{c}</th>' for c in columns) + f'</tr></thead><tbody>{body}</tbody></table></div></section>')


def page(data):
    vaults = data['vaults']
    counts = [f'Profile revision {data["profile"]["state"]["revision"]}',
              f'{len(vaults)} project vault{"" if len(vaults) == 1 else "s"}', f'{len(data["people"])} people']
    parts = [
        '<header class="masthead"><div><h1>Agent Vault</h1>',
        f'<p class="label">Memory index · read only · {e(data["generated"])}</p></div>',
        '<div class="masthead__tools"><div class="themes" role="group" aria-label="Theme">'
        + ''.join(f'<button class="chip" type="button" data-theme-choice="{k}" aria-pressed="{str(k == "system").lower()}">'
                  f'{v}</button>' for k, v in THEMES) + '</div>'
        '<div class="tags">' + ''.join(f'<span class="tag">{e(c)}</span>' for c in counts) + '</div></div></header>',
        '<nav class="tabs" aria-label="Sections">' + ''.join(f'<a class="tab" href="#{k}">{v}</a>' for k, v in SECTIONS)
        + '</nav>',
        profile_section(data['profile']),
        '<section id="projects"><div class="section__head"><h2>Project vaults</h2>'
        '<span class="label">Shared with everyone who works on the project</span></div>'
        + (''.join(vault_block(v, INKS[i % len(INKS)]) for i, v in enumerate(vaults))
           or '<p class="blank">No project vaults registered.</p>') + '</section>',
        '<section id="people"><div class="section__head"><h2>People</h2>'
        '<span class="label">Private to your profile; never copied into project vaults</span></div>'
        + grid([person(n) for n in data['people']], 'No people notes yet.') + '</section>',
        history_section(data['history']),
        '<footer class="colophon"><span>Generated by Agent Vault view.py</span>'
        '<span>Change memory through your agent; this page never writes</span></footer>']
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
            '<meta name="viewport" content="width=device-width, initial-scale=1"><title>Agent Vault memory</title>'
            '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,'
            + base64.b64encode(FAVICON.encode('utf-8')).decode('ascii') + '">'
            f'<script>{EARLY}</script>'
            f'<style>{STYLE}</style></head><body><div class="wrap">' + ''.join(parts)
            + f'</div><script>{SCRIPT}</script></body></html>\n')


def destination(value, config_dir, data):
    path = (value.expanduser() if value else config_dir / 'view.html').absolute()
    # The page holds the private profile and people notes; keep it out of every shared vault and project.
    for item in data['vaults']:
        for root in [item['project']['root'], *item['project'].get('workspaces', [])]:
            if path.resolve().is_relative_to(Path(root).resolve()):
                raise ValueError(f'Write the page outside shared vaults and project folders: {path}')
    return path


def main():
    configure_io()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path.home() / '.config/agent-memory',
                        help='Installed router folder with config.json and projects.json')
    parser.add_argument('--output', type=Path, help='HTML file to write; defaults to view.html in the router folder')
    parser.add_argument('--open', action='store_true', help='Open the page in the default browser')
    args = parser.parse_args()
    try:
        data = snapshot(args.config)
        path = destination(args.output, args.config, data)
        atomic_write(path, page(data))
        if args.open:
            webbrowser.open(path.as_uri())
        print(json.dumps({'view': str(path), 'vaults': len(data['vaults']), 'people': len(data['people'])}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Agent Vault view: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 4: Install `view.py` with the router**

In `scripts/project-memory-router.py`, change the installed engine list:

```python
    for name in ['agent-memory.py','profile_memory.py','vault_runtime.py','view.py']:
```

- [ ] **Step 5: Add the VS Code Task**

Append to the `tasks` array of `.vscode/tasks.json`:

```json
    {
      "label": "Agent Vault: show my memory",
      "type": "process",
      "command": "python3",
      "args": ["${workspaceFolder}/scripts/view.py", "--open"],
      "windows": {
        "command": "py",
        "args": ["-3", "${workspaceFolder}/scripts/view.py", "--open"]
      },
      "problemMatcher": []
    }
```

Add to `test_vscode_tasks_call_both_steps` in `scripts/tests/test_onboard.py`:

```python
        self.assertIn('--open', labels['Agent Vault: show my memory']['args'])
```

- [ ] **Step 6: Run focused tests**

Run: `cd scripts/tests && python -m unittest test_view test_onboard -q`
Expected: OK.

- [ ] **Step 7: Document the page**

In `README.md`, after the "Share project memory with your team (OneDrive or SharePoint)" section from Task 5, add:

```markdown
### See what your agents remember

Run **Terminal > Run Task > Agent Vault: show my memory**, or ask your agent to run `python ~/.config/agent-memory/view.py --open`. It writes one page to `~/.config/agent-memory/view.html` and opens it: your profile with its size limits, every registered project vault, your people notes and the latest changes. The page is read only and loads nothing from the network. To change something, use **Copy request** on a card and paste it into your agent chat. The page contains your private profile and people notes, so `view.py` refuses to write it into a project or vault folder.
```

In `docs/maintenance.md`, in the first code block after the conflicts commands from Task 5, add:

```bash
# Read-only page of the profile, vaults, people notes and recent changes:
python ~/.config/agent-memory/view.py --open
```

- [ ] **Step 8: Full suite and commit**

Check that new doc text has no em dashes and that the README command matches `view.py` argparse.

```bash
python -m unittest discover -s scripts/tests -q
git add scripts/view.py scripts/tests/test_view.py scripts/project-memory-router.py .vscode/tasks.json scripts/tests/test_onboard.py README.md docs/maintenance.md
git commit -m "feat: add a read-only HTML page of profile, vaults and people"
```
