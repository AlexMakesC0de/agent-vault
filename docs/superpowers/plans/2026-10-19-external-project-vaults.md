# External Project Vaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep a project's memory vault in a folder outside the project repository, load it automatically whenever any agent works in that repository, and add nothing to the repository itself.

**Architecture:** A registry entry gains an optional `workspaces` list. The entry's `root` is then an external vault folder, and the router selects it when a prompt names the project or a cwd/tool path resolves to one of its workspaces (worktrees included) or to the vault folder itself. External vaults use the installed engine, so they carry no scripts or hooks. In-repo vaults keep working unchanged for teams that want shared, committed memory. Agents without hooks use the same `router.py context` command through a guidance block that `install --instructions` writes into any instruction file.

**Tech Stack:** Python 3.11+ standard library only; `unittest`; Git; Windows/macOS/Linux.

**Spec:** the Design section below.

## Design

| Layer | Location | Always loaded | Bound |
| --- | --- | --- | --- |
| Identity, preferences, general lessons | Central profile (`SOUL.md`, `USER.md`, `MEMORY.md`) | Yes | 2,200 / 1,375 / 2,200 characters |
| Project facts | External vault `MEMORY.md` | When the project is selected | 2,200 characters |
| Project detail | External vault `docs/knowledge/` notes | No; read on demand | One fact per note |
| Team instructions | The repository's own `AGENTS.md` | Pointer only, never embedded | Owned by the team |

External vault layout, identical to the in-repo layout so the engine needs no changes to load it:

```text
agent-vaults/<id>/
├── AGENTS.md                       vault guide (template)
├── MEMORY.md                       generated core
├── .gitignore
└── docs/knowledge/
    ├── README.md
    ├── CONVENTIONS.md
    └── memory/{README.md,state.json}
```

Registry entry for an external vault (`projects.json`, schema 1 unchanged, field added):

```json
{"id": "myapp", "name": "myapp", "aliases": ["myapp"],
 "root": "C:\\...\\agent-vaults\\myapp",
 "workspaces": ["C:\\...\\GitHub\\myapp"]}
```

Rules:
- A workspace must be the primary root of a Git checkout. Worktrees resolve to it through `git rev-parse --git-common-dir`.
- An external vault must not sit inside a Git checkout other than its own, and never inside its workspace.
- No two entries may claim the same root or workspace.
- `unregister` removes a registry entry only, backs up `projects.json`, and never touches vault or project files.

## Global Constraints

- Python 3.11+ standard library only; Windows, macOS and Linux.
- Preserve existing file contents and configuration values; refuse unsafe changes rather than resetting memory.
- Do not forge client hook trust or change permissions.
- Tests use real temporary homes, repositories and subprocesses. Fixtures stay synthetic.
- Run the full suite with `python -m unittest discover -s scripts/tests -q` (`python3` on macOS/Linux).
- Commits carry no AI attribution trailer. Work on branch `feat/external-project-vaults`; never commit to `main`.
- Docs state rules in the present tense; no history of earlier designs.
- Match the existing terse code style in `scripts/`.

---

### Task 1: Registry workspaces, external registration and unregister

**Files:**
- Modify: `scripts/project-memory-router.py` (`registry`, `register`, new `inside`, new `unregister`, `main`)
- Create: `scripts/tests/test_external_vaults.py`

**Interfaces:**
- Produces: `inside(path, parent) -> bool`; `register(directory, args)` accepting `args.workspace: list[str]`; `unregister(directory, args) -> dict`; registry entries with optional `workspaces: list[str]` (absolute, primary Git roots).
- CLI: `register ... --workspace PATH` (repeatable), `unregister --id ID`.

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_external_vaults.py`. The vault is built by hand here; Task 3 replaces `make_vault` with `setup-vault.py --vault`.

```python
"""External project vaults: memory outside the project repo, selected by workspace path."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from platform_helpers import home_env, run_review

SCRIPTS = Path(__file__).resolve().parents[1]
ROUTER = SCRIPTS / 'project-memory-router.py'
ENGINE = SCRIPTS / 'agent-memory.py'
SETUP = SCRIPTS / 'setup-vault.py'


class ExternalVaultTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.home = self.base / 'home'; self.home.mkdir()
        self.config = self.home / '.config/agent-memory'; self.config.mkdir(parents=True)
        self.app = self.base / 'repos' / 'DemoApp'; self.app.mkdir(parents=True)
        self.git('init', '-q', str(self.app))
        (self.app / 'AGENTS.md').write_text('# Team rules\nTeam-owned instructions.\n', encoding='utf-8')
        self.git('-C', str(self.app), 'add', 'AGENTS.md')
        self.git('-C', str(self.app), '-c', 'user.name=t', '-c', 'user.email=t@example.test', 'commit', '-qm', 'init')
        self.vault = self.base / 'agent-vaults' / 'demo'
        profile = self.home / 'profile'
        self.run_script(ENGINE, '--profile', str(profile), 'init-profile')
        (self.config / 'config.json').write_text(json.dumps({'schema': 2, 'profile_root': str(profile)}))

    def git(self, *args):
        subprocess.run(['git', *args], check=True, capture_output=True)

    def run_script(self, script, *args, payload=None, check=True):
        result = subprocess.run([sys.executable, str(script), *args], input=json.dumps(payload) if payload else None,
                                capture_output=True, text=True, encoding='utf-8', cwd=self.home, env=home_env(self.home))
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def router(self, *args, **kwargs):
        return self.run_script(ROUTER, '--directory', str(self.config), *args, **kwargs)

    def write_store(self):
        # Hand-built vault: also used where setup-vault.py would refuse the location.
        store = self.vault / 'docs/knowledge/memory/state.json'
        store.parent.mkdir(parents=True)
        store.write_text(json.dumps({'schema': 2, 'scope': 'project', 'project': 'DemoApp', 'revision': 0,
                                     'entries': [], 'history': []}), encoding='utf-8')
        (self.vault / 'AGENTS.md').write_text('# DemoApp vault\n', encoding='utf-8')
        self.run_script(ENGINE, '--root', str(self.vault), 'render')

    def make_vault(self):
        self.write_store()

    def remember(self):
        self.run_script(ENGINE, '--root', str(self.vault), 'update', '--id', 'fact', '--kind', 'explicit',
                        '--agent', 'human', '--expected-revision', '0', '--source', 'test',
                        '--text', 'Unique DemoApp vault fact.')

    def register(self, *extra, check=True):
        return self.router('register', '--id', 'demo', '--name', 'DemoApp', '--root', str(self.vault),
                           '--workspace', str(self.app), *extra, check=check)

    def create(self):
        self.make_vault(); self.remember(); self.register()

    def hook(self, event='UserPromptSubmit', **fields):
        result = self.router('hook', payload={'hook_event_name': event, 'session_id': 's1', 'cwd': str(self.home), **fields})
        return json.loads(result.stdout).get('hookSpecificOutput', {}).get('additionalContext', '')

    def test_register_records_vault_and_workspace(self):
        self.create()
        project = json.loads((self.config / 'projects.json').read_text())['projects'][0]
        self.assertEqual(Path(project['root']), self.vault)
        self.assertEqual([Path(w) for w in project['workspaces']], [self.app])

    def test_register_rejects_vault_inside_workspace(self):
        self.vault = self.app / 'memory-vault'
        self.write_store()
        result = self.register(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('outside its workspace', result.stderr)
        self.assertFalse((self.config / 'projects.json').exists())

    def test_workspace_must_be_a_primary_git_checkout(self):
        self.make_vault()
        plain = self.base / 'not-a-repo'; plain.mkdir()
        result = self.router('register', '--id', 'demo', '--name', 'DemoApp', '--root', str(self.vault),
                             '--workspace', str(plain), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('primary root of a Git checkout', result.stderr)

    def test_two_projects_cannot_claim_one_workspace(self):
        self.create()
        first = self.vault
        self.vault = self.base / 'agent-vaults' / 'other'; self.make_vault()
        result = self.router('register', '--id', 'other', '--name', 'Other', '--root', str(self.vault),
                             '--workspace', str(self.app), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Duplicate', result.stderr)
        self.assertEqual(len(json.loads((self.config / 'projects.json').read_text())['projects']), 1)
        self.assertTrue(first.exists())

    def test_unregister_removes_only_the_registry_entry(self):
        self.create()
        self.router('unregister', '--id', 'demo')
        self.assertEqual(json.loads((self.config / 'projects.json').read_text())['projects'], [])
        self.assertIn('Unique DemoApp vault fact.', (self.vault / 'MEMORY.md').read_text(encoding='utf-8'))
        self.assertTrue(list((self.config / 'backups').glob('*-projects.json')))
        self.assertNotEqual(self.router('unregister', '--id', 'demo', check=False).returncode, 0)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest scripts/tests/test_external_vaults.py -v` from the repo root, or `python -m unittest discover -s scripts/tests -p "test_external_vaults.py" -v`.
Expected: FAIL. `register` rejects `--workspace` ("unrecognized arguments") and `unregister` is not a known command.

- [ ] **Step 3: Implement**

In `scripts/project-memory-router.py`, add after `primary`:

```python
def inside(path, parent):
    path, parent = os.path.normcase(str(path)), os.path.normcase(str(parent)).rstrip('\\/')
    return path == parent or path.startswith(parent + os.sep)
```

In `registry`, replace the root uniqueness check (current lines 91-95) with:

```python
        workspaces = project.get('workspaces')
        if workspaces is not None and (not isinstance(workspaces, list) or not workspaces
                                       or not all(isinstance(w, str) and Path(w).is_absolute() for w in workspaces)):
            raise ValueError('Project workspaces must be a non-empty list of absolute paths')
        claimed = {os.path.normcase(str(Path(p).resolve())) for p in [root, *(workspaces or [])]}
        if key in ids or roots.intersection(claimed) or aliases.intersection(folded):
            raise ValueError('Duplicate project id, root, workspace, or alias')
        ids.add(key)
        roots.update(claimed)
        aliases.update(folded)
```

Replace the opening of `register` (current lines 100-112) with:

```python
def register(directory, args):
    workspaces = getattr(args, 'workspace', None) or []
    claimed = []
    if workspaces:
        root = Path(args.root).expanduser().resolve()
        for value in workspaces:
            workspace = primary(value)
            if workspace is None or workspace != Path(value).expanduser().resolve():
                raise ValueError(f'Workspace must be the primary root of a Git checkout: {value}')
            if inside(root, workspace):
                raise ValueError('Keep an external vault outside its workspace; omit --workspace for an in-repo vault')
            claimed.append(str(workspace))
        required = ['docs/knowledge/memory/state.json', 'MEMORY.md', 'AGENTS.md']
    else:
        root = primary(args.root)
        if root is None:
            raise ValueError('Register an existing non-bare Git checkout')
        required = ['scripts/agent-memory.py', 'docs/knowledge/memory/state.json', 'AGENTS.md']
    for relative in required:
        if not (root / relative).is_file():
            raise ValueError(f'Compatible project vault missing {relative}; initialize its own vault first')
    state=json.loads((root/'docs/knowledge/memory/state.json').read_text(encoding='utf-8'))
    if workspaces and state.get('scope')!='project':
        raise ValueError('An external vault needs a schema-2 project store')
    projection='SOUL.md' if state.get('schema')==1 else 'MEMORY.md'
    if not (root/projection).is_file():raise ValueError(f'Project missing {projection}')
    data = registry(directory)
    project = {'id': args.id, 'name': args.name, 'root': str(root),
               'aliases': list(dict.fromkeys([args.name, *args.alias]))}
    if claimed:
        project['workspaces'] = claimed
```

Leave the rest of `register` unchanged. Add after `register`:

```python
def unregister(directory, args):
    data = registry(directory)
    remaining = [p for p in data['projects'] if p['id'] != args.id]
    if len(remaining) == len(data['projects']):
        raise ValueError(f'No registered project has id {args.id}')
    path = directory / 'projects.json'
    atomic(directory / 'backups' / (str(time.time_ns()) + '-projects.json'), path.read_bytes())
    save(path, {'schema': 1, 'projects': remaining})
    return {'unregistered': args.id, 'files': 'unchanged'}
```

In `main`, register the new arguments and command:

```python
    commands.add_parser('unregister').add_argument('--id', required=True)
```

inside the `for name in ['register', 'install']` loop:

```python
        if name == 'register':
            command.add_argument('--workspace', action='append', default=[],
                                 help='Project checkout served by an external vault at --root')
```

and in the dispatch chain, before `else: output = install(...)`:

```python
            elif args.command == 'unregister':
                output = unregister(args.directory, args)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s scripts/tests -p "test_external_vaults.py" -v`
Expected: 5 tests PASS.
Run: `python -m unittest discover -s scripts/tests -q`
Expected: all existing tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/project-memory-router.py scripts/tests/test_external_vaults.py
git commit -m "feat: register project vaults outside their repositories"
```

---

### Task 2: Select external vaults from workspace, worktree and vault paths

**Files:**
- Modify: `scripts/project-memory-router.py` (`matching_paths`, `engine`, `route` chunk)
- Modify: `scripts/tests/test_external_vaults.py`

**Interfaces:**
- Consumes: `inside(path, parent)`, registry `workspaces` from Task 1.
- Produces: external entries route through the installed engine (`Path(__file__).with_name('agent-memory.py')`). Context for an external vault names its workspaces and points to each workspace `AGENTS.md` without embedding it.

- [ ] **Step 1: Write the failing tests**

Add to `ExternalVaultTests`:

```python
    def test_working_inside_workspace_selects_external_vault(self):
        self.create()
        text = self.hook(prompt='fix the login bug', cwd=str(self.app))
        self.assertIn('Unique DemoApp vault fact.', text)
        self.assertIn(str(self.vault), text)

    def test_worktree_tool_path_selects_external_vault(self):
        self.create()
        worktree = self.base / 'repos' / 'DemoApp-feature'
        self.git('-C', str(self.app), 'worktree', 'add', '-q', '-b', 'feature', str(worktree))
        self.hook(prompt='unrelated')
        text = self.hook('PreToolUse', tool_name='Read', tool_input={'file_path': str(worktree / 'AGENTS.md')})
        self.assertIn('Unique DemoApp vault fact.', text)

    def test_tool_path_inside_vault_selects_it(self):
        self.create()
        self.hook(prompt='unrelated')
        text = self.hook('PreToolUse', tool_name='Read',
                         tool_input={'file_path': str(self.vault / 'docs/knowledge/README.md')})
        self.assertIn('Unique DemoApp vault fact.', text)

    def test_team_instructions_are_pointed_to_never_embedded(self):
        self.create()
        text = self.hook(prompt='Explain DemoApp')
        self.assertIn(str(self.app / 'AGENTS.md'), text)
        self.assertNotIn('Team-owned instructions.', text)

    def test_unregistered_workspace_selects_nothing(self):
        self.make_vault(); self.remember()
        text = self.hook(prompt='fix the login bug', cwd=str(self.app))
        self.assertNotIn('Unique DemoApp vault fact.', text)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s scripts/tests -p "test_external_vaults.py" -v`
Expected: the first four new tests FAIL (vault fact or workspace pointer missing). The external engine call also fails because `<vault>/scripts/agent-memory.py` does not exist. `test_unregistered_workspace_selects_nothing` PASSES already.

- [ ] **Step 3: Implement**

Replace `matching_paths`:

```python
def matching_paths(projects, values, cwd):
    roots, paths = set(), []
    for value in values:
        if not isinstance(value, str) or not value or '\x00' in value:
            continue
        path = native_path(value)
        path = path if path.is_absolute() else cwd / path
        paths.append(path.resolve())
        root = primary(path)
        if root:
            roots.add(os.path.normcase(str(root)))

    def owns(project):
        claimed = [project['root'], *project.get('workspaces', [])]
        if any(os.path.normcase(str(Path(p).resolve())) in roots for p in claimed):
            return True
        return bool(project.get('workspaces')) and any(inside(p, Path(project['root']).resolve()) for p in paths)
    return [p for p in projects if owns(p)]
```

In `engine`, use the installed engine for external vaults:

```python
    script = (Path(__file__).with_name("agent-memory.py") if project.get("profile") or project.get("workspaces")
              else root / "scripts/agent-memory.py")
```

In `route`, directly after the line that sets `chunk` to `'Keep this project\'s facts ...'` (the second `chunk +=`), add:

```python
        for workspace in project.get('workspaces', []):
            chunk += f'Workspace: {workspace}\n'
            if (Path(workspace) / 'AGENTS.md').is_file():
                chunk += (f'Team instructions: {Path(workspace) / "AGENTS.md"}. Read only the sections relevant to the task. '
                          'Never write memory or knowledge files into a workspace.\n')
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s scripts/tests -p "test_external_vaults.py" -v`
Expected: 10 tests PASS.
Run: `python -m unittest discover -s scripts/tests -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/project-memory-router.py scripts/tests/test_external_vaults.py
git commit -m "feat: load external vaults from workspace, worktree and vault paths"
```

---

### Task 3: `setup-vault.py --vault` creates an external vault

**Files:**
- Modify: `scripts/setup-vault.py` (new `external`, `main` argument group)
- Create: `templates/vault-agents.md`
- Modify: `scripts/tests/test_external_vaults.py` (`make_vault` uses setup; new tests)

**Interfaces:**
- Produces: CLI `setup-vault.py --vault DIR --name NAME`. It writes only inside `DIR`, refuses a `DIR` inside another Git checkout, preserves an existing valid project store and writes no scripts, hooks or client settings.

- [ ] **Step 1: Write the failing tests**

Replace `make_vault` in `ExternalVaultTests` (keep `write_store`; `test_register_rejects_vault_inside_workspace` still uses it):

```python
    def make_vault(self):
        self.run_script(SETUP, '--vault', str(self.vault), '--name', 'DemoApp')
```

Add:

```python
    def test_setup_writes_only_into_the_vault(self):
        self.create()
        status = subprocess.run(['git', '-C', str(self.app), 'status', '--porcelain'], capture_output=True, text=True)
        self.assertEqual(status.stdout, '')
        for relative in ['AGENTS.md', 'MEMORY.md', 'docs/knowledge/README.md', 'docs/knowledge/CONVENTIONS.md',
                         'docs/knowledge/memory/README.md', 'docs/knowledge/memory/state.json']:
            self.assertTrue((self.vault / relative).is_file(), relative)
        self.assertFalse((self.vault / 'scripts').exists())
        self.assertFalse((self.vault / '.claude').exists())

    def test_setup_refuses_a_vault_inside_another_checkout(self):
        result = self.run_script(SETUP, '--vault', str(self.app / 'vault'), '--name', 'DemoApp', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('inside a Git checkout', result.stderr)
        self.assertFalse((self.app / 'vault').exists())

    def test_setup_over_existing_vault_preserves_memory(self):
        self.create()
        before = (self.vault / 'docs/knowledge/memory/state.json').read_bytes()
        self.run_script(SETUP, '--vault', str(self.vault), '--name', 'DemoApp')
        self.assertEqual((self.vault / 'docs/knowledge/memory/state.json').read_bytes(), before)

    def test_vault_may_be_its_own_git_repository(self):
        self.vault.mkdir(parents=True)
        self.git('init', '-q', str(self.vault))
        self.create()
        self.assertIn('Unique DemoApp vault fact.', self.hook(prompt='fix the login bug', cwd=str(self.app)))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s scripts/tests -p "test_external_vaults.py" -v`
Expected: every test that calls `make_vault` FAILS with "the following arguments are required: --root" or "unrecognized arguments: --vault".

- [ ] **Step 3: Implement**

Create `templates/vault-agents.md`:

```markdown
# Project vault

This folder is the memory vault for one project. It lives outside the project repository, and nothing in it is committed there.

- [MEMORY.md](MEMORY.md): the project core, at most 2,200 characters, generated from [state](docs/knowledge/memory/state.json).
- [Knowledge](docs/knowledge/README.md): linked notes. Read only the notes the task needs.
- [Conventions](docs/knowledge/CONVENTIONS.md): how to record facts, evidence and history.

The project's own instructions stay in its repository `AGENTS.md`, owned by its team. Keep learning here, not there. Change memory only through the memory CLI command given in the session context.
```

In `scripts/setup-vault.py`, add before `main`:

```python
def external(args):
    root = args.vault.expanduser().resolve()
    owner = router.primary(root)
    if owner is not None and owner != root:
        raise ValueError('An external vault must not be inside a Git checkout; use --root for an in-repo vault')
    if any(p.is_symlink() for p in [root, *root.parents]):
        raise ValueError('Inspect symlinks before creating an external vault')
    name = args.name.strip()
    if not name or len(name) > 120 or any(c in name for c in ['\n', '\r', '\x00']):
        raise ValueError('Use a non-empty, single-line project name of at most 120 characters')
    if (root / 'SOUL.md').exists():
        raise ValueError('Legacy or independent SOUL.md found; use migrate-vault.py before setup')
    files = {}
    if (root / 'docs/knowledge/memory/state.json').exists():
        state = memory.load(root)
        if state.get('scope') != 'project' or not (root / 'MEMORY.md').is_file():
            raise ValueError('Partial/legacy memory; recover or migrate it before setup')
    else:
        if (root / 'MEMORY.md').exists():
            raise ValueError('Existing MEMORY.md must be imported explicitly; nothing was reset')
        state = {'schema': 2, 'scope': 'project', 'project': name, 'revision': 0, 'entries': [], 'history': []}
        files['docs/knowledge/memory/state.json'] = json.dumps(state, indent=2, ensure_ascii=False) + '\n'
        files['MEMORY.md'] = memory.render(state)
    for source, destination in [('knowledge-home.md', 'docs/knowledge/README.md'),
                                ('conventions.md', 'docs/knowledge/CONVENTIONS.md'),
                                ('memory-readme.md', 'docs/knowledge/memory/README.md'),
                                ('vault-agents.md', 'AGENTS.md')]:
        if not (root / destination).exists():
            files[destination] = (TEMPLATES / source).read_text(encoding='utf-8')
    if not (root / '.gitignore').exists():
        files['.gitignore'] = '.memory-runtime/\n.obsidian/\n__pycache__/\n*.pyc\n'
    for relative, content in files.items():
        router.atomic(root / relative, content)
    return {'root': str(root), 'project': name, 'changed': list(files),
            'next': 'Register it: project-memory-router.py register --id ID --name NAME --root VAULT --workspace REPO'}
```

Replace the argument setup and dispatch in `main`:

```python
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument('--root', type=Path, help='Project repository for a team-shared, committed vault')
    location.add_argument('--vault', type=Path, help='Folder for a personal vault outside the project repository')
    parser.add_argument('--name', required=True)
    parser.add_argument('--codex-hooks', action='store_true', help='Add Codex hooks/config; client trust review is still required')
    args = parser.parse_args()
    if args.vault and args.codex_hooks:
        parser.error('--codex-hooks applies to in-repo vaults; external vaults use the user-level router hooks')
    try:
        print(json.dumps(external(args) if args.vault else setup(args)))
        return 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s scripts/tests -p "test_external_vaults.py" -v`
Expected: 14 tests PASS.
Run: `python -m unittest discover -s scripts/tests -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/setup-vault.py templates/vault-agents.md scripts/tests/test_external_vaults.py
git commit -m "feat: create project vaults outside the repository with setup --vault"
```

---

### Task 4: Review instructions name absolute paths and a runnable update command

**Files:**
- Modify: `scripts/agent-memory.py` (`review_instruction`)
- Modify: `scripts/tests/test_external_vaults.py`, `scripts/tests/test_central_router.py`

**Interfaces:**
- Produces: review text containing `Read <absolute vault>/docs/knowledge/CONVENTIONS.md.` for projects, and the update help command in backticks: ``the exact update command is `<python> <engine> --root <root> update --help` ``. The profile variant no longer names a README the profile does not have.

- [ ] **Step 1: Write the failing tests**

Add to `ExternalVaultTests`:

```python
    def test_review_names_vault_conventions_and_a_runnable_update_command(self):
        import re
        self.create()
        text = self.hook(prompt='fix the login bug', cwd=str(self.app))
        self.assertIn(str(self.vault / 'docs/knowledge/CONVENTIONS.md'), text)
        commands = re.findall(r'exact update command is `([^`]+)`', text)
        self.assertTrue(commands)
        vault_command = next(c for c in commands if self.vault.name in c)
        result = run_review(vault_command, agent='claude', cwd=self.home, env=home_env(self.home),
                            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--expected-revision', result.stdout)
```

Add to `CentralRouterTests` in `scripts/tests/test_central_router.py`:

```python
    def test_profile_review_names_only_files_the_profile_has(self):
        text=self.text(self.hook(prompt='No project today'))
        self.assertNotIn('README.md',text.split('Before your final response',1)[1])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s scripts/tests -p "test_*.py" -k review_names -v`
Expected: both FAIL. The current text says `Read docs/knowledge/CONVENTIONS.md.` (relative), has no update command, and names `README.md` for the profile.

- [ ] **Step 3: Implement**

Replace `review_instruction` in `scripts/agent-memory.py`:

```python
def review_instruction(root, session, token, agent):
    shell = 'bash' if agent == 'claude' else 'powershell'
    engine = str(Path(__file__).resolve())
    command = shell_command([sys.executable, engine, "--root", str(root), "review",
                             "--session", session, "--token", token], shell=shell)
    update = shell_command([sys.executable, engine, "--root", str(root), "update", "--help"], shell=shell)
    location = ('Put user preferences in USER.md, general lessons in MEMORY.md, and identity changes in SOUL.md through set-soul. '
                if (root/profile.PROFILE_STORE).exists() else
                f'Read {root / "docs/knowledge/CONVENTIONS.md"}. Keep project facts in this vault and user preferences in the central profile. ')
    return ("Before your final response, review this interaction for durable explicit preferences, corrections, "
            "and verified workflow lessons. " + location + "Update shared memory only when useful; the exact update command is `"
            + update + "`. Keep guesses kind=inferred, and preserve history. "
            "Save technical detail in the appropriate knowledge note instead of the core. "
            "Then record that review, including a no-change review, by running: " + command +
            ". Do not invent a learning to satisfy this check. Do not claim a save without a successful tool result.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s scripts/tests -q`
Expected: all PASS, including the two new tests and the existing review-command tests that split on `by running: `.

- [ ] **Step 5: Commit**

```bash
git add scripts/agent-memory.py scripts/tests/test_external_vaults.py scripts/tests/test_central_router.py
git commit -m "fix: give agents absolute vault paths and a runnable update command"
```

---

### Task 5: Agent-neutral install: any instruction file, line endings preserved

**Files:**
- Modify: `scripts/project-memory-router.py` (new `merged_guidance`, `install`, `main`)
- Modify: `scripts/profile_memory.py` (`DEFAULT_SOUL`, `context` wording)
- Modify: `scripts/tests/test_central_router.py`

**Interfaces:**
- Produces: CLI `install ... --instructions PATH` (repeatable) writes the marked guidance block into any agent's instruction file using the OS-native shell form of the context command. `merged_guidance(path, block) -> str` keeps the file's existing line endings (CRLF or LF).

- [ ] **Step 1: Write the failing tests**

Add to `CentralRouterTests`:

```python
    def test_install_adds_guidance_to_any_agents_instruction_file(self):
        other=self.home/'.kimi'/'AGENTS.md';other.parent.mkdir()
        other.write_text('# Kimi rules\nKeep me.\n',encoding='utf-8')
        args=['install','--home',str(self.home),'--profile',str(self.profile),'--instructions',str(other)]
        result=self.run_cli(*args);self.assertEqual(result.returncode,0,result.stderr)
        guidance=other.read_text(encoding='utf-8')
        self.assertTrue(guidance.startswith('# Kimi rules\nKeep me.\n'))
        command=re.search(r'load both with `([^`]+)`',guidance).group(1)
        result=run_review(command,agent='codex',cwd=self.home,env=home_env(self.home),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(self.identity,json.loads(result.stdout)['context'])
        before=other.read_bytes();self.assertEqual(self.run_cli(*args).returncode,0);self.assertEqual(other.read_bytes(),before)

    def test_install_keeps_crlf_line_endings_of_personal_instructions(self):
        claude=self.home/'.claude';claude.mkdir(exist_ok=True)
        original=b'# Personal\r\nKeep me.\r\n'
        (claude/'CLAUDE.md').write_bytes(original)
        result=self.run_cli('install','--home',str(self.home),'--profile',str(self.profile))
        self.assertEqual(result.returncode,0,result.stderr)
        data=(claude/'CLAUDE.md').read_bytes()
        self.assertTrue(data.startswith(original))
        self.assertEqual(data.count(b'\n'),data.count(b'\r\n'))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s scripts/tests -p "test_central_router.py" -v`
Expected: the first FAILS with "unrecognized arguments: --instructions". The second FAILS because `data` starts with `b'# Personal\nKeep me.\n'`.

- [ ] **Step 3: Implement**

Add to `scripts/project-memory-router.py` before `install`:

```python
def merged_guidance(path, block):
    original = path.read_bytes().decode('utf-8') if path.exists() else ''
    newline = '\r\n' if '\r\n' in original else '\n'
    text = original.replace('\r\n', '\n')
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise ValueError(f'Invalid router guidance markers in {path}; inspect personal instructions')
    if BEGIN in text:
        text = text[:text.index(BEGIN)] + block + text[text.index(END) + len(END):]
    else:
        text += ('\n' if text and not text.endswith('\n') else '') + block + '\n'
    return text.replace('\n', newline)
```

In `install`, change the first block sentence to agent-neutral wording:

```python
           'Every coding agent on this machine uses ONE private central SOUL.md identity, USER.md preferences and MEMORY.md general lessons. '
```

Replace the guidance lines inside the agent loop (current lines 180-187) with:

```python
        files[folder/('CLAUDE.md' if agent=='claude' else 'AGENTS.md')]=merged_guidance(
            folder/('CLAUDE.md' if agent=='claude' else 'AGENTS.md'),agent_block)
```

After the agent loop, add:

```python
    for path in args.instructions:
        files[path.expanduser().resolve()]=merged_guidance(path.expanduser().resolve(),block)
```

In `main`, inside `if name == 'install':`:

```python
            command.add_argument('--instructions',type=Path,action='append',default=[],
                                 help="Another agent's instruction file to receive the guidance block")
```

In `scripts/profile_memory.py`, make the wording agent-neutral. `DEFAULT_SOUL` second line:

```python
                'Every coding agent shares this identity across projects and sessions.\n'
```

and in `context`:

```python
            'The same canonical identity and preferences apply to every coding agent. Project vaults supply facts, not another identity.\n'
```

Then search for assertions on the old wording: `git grep -n "Claude and Codex\|Claude Code and Codex" scripts/tests`. Update any match to the new text.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s scripts/tests -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/project-memory-router.py scripts/profile_memory.py scripts/tests/test_central_router.py
git commit -m "feat: install guidance for any agent and keep instruction line endings"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md` ("Where things live", "2. Add your project", "What happens after setup?")
- Modify: `docs/architecture.md` (registry and routing paragraphs)
- Modify: `docs/devices.md` (step 3 and step 4)
- Modify: `docs/maintenance.md` (project commands)
- Modify: `templates/memory-readme.md` (CLI line that assumes `scripts/` in the vault)

- [ ] **Step 1: README layout**

Replace the tree under "Where things live" with:

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

- [ ] **Step 2: README "2. Add your project"**

Replace both command blocks with:

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

Follow with this text: "The vault is a folder of your own. The project repository is not changed, so teammates are unaffected. Working anywhere in MyApp, including its worktrees, loads the vault. To stop using a vault, run `router.py unregister --id myapp`; the files stay."

Then add a subsection:

```markdown
### Team-shared vault (optional)

To share project memory with everyone who clones the repository, put the vault in the repository instead: `setup-vault.py --root /full/path/to/MyApp --name MyApp`, then `register` without `--workspace`. This commits memory scripts, hooks and notes to the repository, and every teammate's agent loads them.
```

- [ ] **Step 3: README "Other agents"**

Add after "What happens after setup?":

```markdown
### Other agents

Claude Code and Codex load memory through hooks. Any other agent that reads an instruction file and can run a shell command can use the same memory: pass its instruction file to `install --instructions PATH` (repeatable). The guidance block tells the agent to run the context command at task start and to record learning through the memory CLI.
```

- [ ] **Step 4: architecture.md**

In "Client routing", add: "A registry entry with `workspaces` is an external vault: `root` is the vault folder and each workspace is a primary Git checkout it serves. Cwd and tool paths select it through the workspace's common Git directory, so worktrees resolve to it, or through a path inside the vault folder. External vaults run the installed engine and contain no scripts or hooks. Context names each workspace `AGENTS.md` without embedding it. `unregister` removes one registry entry, backs up the registry and changes no files."

- [ ] **Step 5: devices.md**

In step 3, add the external form of `register` with `--workspace`. In step 4, add: "External vaults are local folders. To use them on another device, copy or sync the `agent-vaults` folder like the profile, then register each one with that device's paths."

- [ ] **Step 6: maintenance.md and memory-readme.md**

In `docs/maintenance.md`, replace the "Project facts, from its checkout" lines with:

```bash
# Project facts, from any folder:
python3 ~/.config/agent-memory/agent-memory.py --root /full/path/to/agent-vaults/myapp context
python3 ~/.config/agent-memory/agent-memory.py --root /full/path/to/agent-vaults/myapp update --help
```

In `templates/memory-readme.md`, replace "load only this project with `python3 scripts/agent-memory.py context` (`python` on Windows)" with "load only this project with the installed `agent-memory.py --root <this vault> context`".

- [ ] **Step 7: Check links and run the suite**

Run: `python -m unittest discover -s scripts/tests -q`
Expected: all PASS.
Run: `git grep -n "docs/knowledge/memory/README.md\|maintenance.md\|devices.md\|architecture.md\|migration.md" -- "*.md"` and open each target to confirm it exists.

- [ ] **Step 8: Commit**

```bash
git add README.md docs/architecture.md docs/devices.md docs/maintenance.md templates/memory-readme.md
git commit -m "docs: make external project vaults the default setup"
```

---

### Task 7: Move an existing in-repo vault outside its repository (operational)

No code change. Run from the `agent-vault` checkout after Tasks 1 to 6 pass. The example moves project `myapp`, whose vault was committed on a local branch `feat/agent-vault` of `$G/MyApp`, to `$G/agent-vaults/myapp`. Set `G` to the folder that holds your clones.

- [ ] **Step 1: Copy the store with its history**

```bash
vault=$G/agent-vaults/myapp
mkdir -p "$vault/docs/knowledge/memory"
git -C "$G/MyApp" show feat/agent-vault:docs/knowledge/memory/state.json > "$vault/docs/knowledge/memory/state.json"
git -C "$G/MyApp" show feat/agent-vault:MEMORY.md > "$vault/MEMORY.md"
```

- [ ] **Step 2: Complete the vault and verify the facts survived**

```bash
python scripts/setup-vault.py --vault "$G/agent-vaults/myapp" --name myapp
python scripts/agent-memory.py --root "$G/agent-vaults/myapp" status | python -c "import json,sys;d=json.load(sys.stdin);print(d['root'],d['revision'],len(d['entries']))"
```

Expected: the same revision and entry count as the in-repo store.

- [ ] **Step 3: Reinstall the router and switch the registration**

```bash
python scripts/project-memory-router.py install --profile ../agent-profile
python scripts/project-memory-router.py unregister --id myapp
python scripts/project-memory-router.py register --id myapp --name MyApp --root "$G/agent-vaults/myapp" --workspace "$G/MyApp"
```

- [ ] **Step 4: Verify selection**

```bash
R=~/.config/agent-memory/router.py
roots(){ python $R context "$@" | python -c "import json,sys;[print(l) for l in json.load(sys.stdin)['context'].splitlines() if l.startswith('Shared memory root')]"; }
roots --prompt MyApp
roots --cwd "$G/MyApp"
```

Expected: exactly one line each, ending in `agent-vaults/myapp` (`agent-vaults\myapp` on Windows). A linked worktree of `MyApp` selects the same vault.

- [ ] **Step 5: Return the repository to its original state (confirm with the user first)**

Only after Step 4 passes and the user agrees, and only for a branch that was never pushed.

```bash
git -C "$G/MyApp" switch main && git -C "$G/MyApp" branch -D feat/agent-vault
git -C "$G/MyApp" status --porcelain
```

Expected: no vault files remain in the repository.
