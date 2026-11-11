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
        self.run_script(SETUP, '--vault', str(self.vault), '--name', 'DemoApp')

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

    def test_register_rejects_vault_inside_a_foreign_checkout(self):
        other = self.base / 'other-repo'; other.mkdir()
        self.git('init', '-q', str(other))
        self.vault = other / 'vault'
        self.write_store()
        result = self.register(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must not be inside another Git checkout', result.stderr)
        self.assertFalse((self.config / 'projects.json').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows paths are case-insensitive')
    def test_workspace_path_case_is_ignored_on_windows(self):
        self.make_vault()
        swapped = str(self.app)[0].swapcase() + str(self.app)[1:]
        self.assertNotEqual(swapped, str(self.app))
        self.router('register', '--id', 'demo', '--name', 'DemoApp', '--root', str(self.vault), '--workspace', swapped)

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
        self.assertIn('inside another Git checkout', result.stderr)
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


    def read_hook(self, path):
        return self.hook('PreToolUse', tool_name='Read', tool_input={'file_path': str(path)})

    def test_context_gives_hookless_agents_team_pointer_and_update_command(self):
        import re
        self.create()
        result = self.router('context', '--cwd', str(self.app))
        text = json.loads(result.stdout)['context']
        self.assertIn(str(self.app / 'AGENTS.md'), text)
        commands = re.findall(r'Update command: `([^`]+)`', text)
        self.assertGreaterEqual(len(commands), 2)
        vault_command = next(c for c in commands if self.vault.name in c)
        run = run_review(vault_command, agent='codex', cwd=self.home, env=home_env(self.home),
                         capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('--expected-revision', run.stdout)

    def test_checkout_inside_the_vault_folder_is_not_captured(self):
        self.vault = self.base / 'wide'
        self.create()
        other = self.vault / 'Other'; other.mkdir()
        self.git('init', '-q', str(other))
        (other / 'f.txt').write_text('x', encoding='utf-8')
        self.assertNotIn('Unique DemoApp vault fact.', self.read_hook(other / 'f.txt'))
        context = json.loads(self.router('context', '--cwd', str(other)).stdout)['context']
        self.assertNotIn('Unique DemoApp vault fact.', context)
        (self.vault / 'notes.md').write_text('x', encoding='utf-8')
        self.assertIn('Unique DemoApp vault fact.', self.read_hook(self.vault / 'notes.md'))

    def test_register_refuses_a_workspace_inside_the_vault_folder(self):
        self.vault = self.base / 'wide'
        self.make_vault()
        inner = self.vault / 'Inner'; inner.mkdir()
        self.git('init', '-q', str(inner))
        result = self.router('register', '--id', 'demo', '--name', 'DemoApp', '--root', str(self.vault),
                             '--workspace', str(inner), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('outside the vault folder', result.stderr)

    def test_registry_rejects_nested_or_self_claiming_external_entries(self):
        def entry(key, root, workspaces):
            return {'id': key, 'name': key, 'root': str(root), 'aliases': [key], 'workspaces': [str(w) for w in workspaces]}
        other = self.base / 'repos' / 'Other'
        wide = self.base / 'wide'
        for projects in ([entry('a', self.app, [self.app])],
                         [entry('a', wide, [self.app]), entry('b', wide / 'sub', [other])],
                         [entry('a', self.vault, [self.app]), entry('b', self.base / 'x', [self.vault / 'inner'])]):
            (self.config / 'projects.json').write_text(json.dumps({'schema': 1, 'projects': projects}))
            result = self.router('list', check=False)
            self.assertNotEqual(result.returncode, 0, projects)

    def test_null_workspaces_key_is_rejected(self):
        (self.config / 'projects.json').write_text(json.dumps({'schema': 1, 'projects': [
            {'id': 'a', 'name': 'a', 'root': str(self.vault), 'aliases': ['a'], 'workspaces': None}]}))
        self.assertNotEqual(self.router('list', check=False).returncode, 0)

    def test_overflowing_context_emits_a_runnable_engine_command(self):
        import re
        self.create()
        profile = self.home / 'profile'
        self.run_script(ENGINE, '--profile', str(profile), 'finish-onboarding', '--agent', 'human',
                        '--expected-revision', '0', '--source', 'test')
        (profile / 'SOUL.md').write_text('# Identity\n' + 'Work thoughtfully. ' * 110, encoding='utf-8')
        for target, count in [('user', 3), ('memory', 5)]:
            for i in range(count):
                revision = json.loads((profile / '.agent-vault-profile.json').read_text(encoding='utf-8'))['revision']
                self.run_script(ENGINE, '--profile', str(profile), 'update', '--target', target, '--id', f'{target}{i}',
                                '--kind', 'explicit', '--agent', 'human', '--expected-revision', str(revision),
                                '--source', 'test', '--text', 'Verified preference text. ' * 14)
        for i in range(4):
            self.run_script(ENGINE, '--root', str(self.vault), 'update', '--id', f'big{i}', '--kind', 'explicit',
                            '--agent', 'human', '--expected-revision', str(i + 1), '--source', 'test',
                            '--text', 'Big project fact. ' * 25)
        text = self.hook(prompt='fix the login bug', cwd=str(self.app))
        commands = [c for c in re.findall(r'`([^`]+)`', text) if c.rstrip().endswith(' context') and self.vault.name in c]
        self.assertTrue(commands, text[-1500:])
        run = run_review(commands[0], agent='claude', cwd=self.home, env=home_env(self.home),
                         capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('Unique DemoApp vault fact.', run.stdout)

    def test_codex_hooks_flag_is_refused_with_an_external_vault(self):
        result = self.run_script(SETUP, '--vault', str(self.vault), '--name', 'DemoApp', '--codex-hooks', check=False)
        self.assertEqual(result.returncode, 2)

    def test_reregistering_with_a_new_workspace_replaces_it(self):
        self.create()
        second = self.base / 'repos' / 'DemoApp2'; second.mkdir()
        self.git('init', '-q', str(second))
        self.router('register', '--id', 'demo', '--name', 'DemoApp', '--root', str(self.vault), '--workspace', str(second))
        project = json.loads((self.config / 'projects.json').read_text())['projects'][0]
        self.assertEqual([Path(w) for w in project['workspaces']], [second])

    def test_a_worktree_is_refused_as_a_workspace(self):
        self.make_vault()
        tree = self.base / 'tree'
        self.git('-C', str(self.app), 'worktree', 'add', '-q', str(tree), '-b', 'wt')
        result = self.router('register', '--id', 'demo', '--name', 'DemoApp', '--root', str(self.vault),
                             '--workspace', str(tree), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('primary root', result.stderr)

    def test_symlinked_vault_path_is_refused(self):
        real = self.base / 'real'; real.mkdir()
        link = self.base / 'link'
        try:
            os.symlink(real, link, target_is_directory=True)
        except OSError:
            self.skipTest('symlinks unavailable')
        result = self.run_script(SETUP, '--vault', str(link / 'v'), '--name', 'DemoApp', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('symlinks', result.stderr)

    def test_external_vault_keeps_runtime_out_of_the_shared_folder(self):
        self.create()
        self.hook(prompt='Explain DemoApp')
        self.assertFalse((self.vault / '.memory-runtime').exists())
        receipts = list((self.config / 'runtime').glob('*/session-*.json'))
        self.assertTrue(receipts)
        self.assertTrue(list((self.config / 'runtime').glob('*/write.lock')))

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


TEMP_LENGTH = int(os.environ.get('AGENT_VAULT_TEST_TEMP_LENGTH', '90'))


class LongPathOverflowTests(unittest.TestCase):
    """The overflow fallback must fit even when every path is long, as under macOS /private/var/folders temp dirs."""
    setUp_base = ExternalVaultTests.setUp

    def setUp(self):
        outer = tempfile.TemporaryDirectory(); self.addCleanup(outer.cleanup)
        # About 90 characters: a macOS temp path's length, yet far enough below Windows MAX_PATH for the deepest file.
        deep = Path(outer.name) / ('long-temp-' + 'x' * max(1, TEMP_LENGTH - len(outer.name) - 11))
        deep.mkdir()
        previous = tempfile.tempdir
        tempfile.tempdir = str(deep)
        try:
            self.setUp_base()
        finally:
            tempfile.tempdir = previous

    def test_overflow_fallback_fits_with_long_paths_and_keeps_the_review(self):
        ExternalVaultTests.test_overflowing_context_emits_a_runnable_engine_command(self)
        text = self.hook(prompt='fix the login bug', cwd=str(self.app), session_id='second-session')
        self.assertLessEqual(len(text), 9500)
        self.assertIn('does not authorize edits', text)
        self.assertIn(str(self.vault / 'AGENTS.md'), text)


# Share the fixture helpers without inheriting, and so without rerunning, every ExternalVaultTests test.
for _name, _value in vars(ExternalVaultTests).items():
    if callable(_value) and not _name.startswith(('test', 'setUp', '_')):
        setattr(LongPathOverflowTests, _name, _value)


if __name__ == '__main__':
    unittest.main()
