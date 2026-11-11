"""Duplicate refusal on update, install provenance, the install guard and doctor, on real temporary homes and repos."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import test_central_profile as profile_fixture
import test_central_router as central
from platform_helpers import home_env

SCRIPTS = Path(__file__).resolve().parents[1]
TOOLKIT = SCRIPTS.parent


class DuplicateEntryTests(unittest.TestCase):
    setUp = profile_fixture.ProfileTests.setUp
    cli = profile_fixture.ProfileTests.cli

    def update(self, key, text, revision, *extra, target='memory'):
        return self.cli('update', '--target', target, '--id', key, '--text', text, '--kind', 'observed',
                        '--source', 'test', '--agent', 'human', '--expected-revision', str(revision), *extra)

    def test_new_entry_restating_an_active_one_is_refused_with_its_id(self):
        self.assertEqual(self.cli('init-profile').returncode, 0)
        first = 'ExampleOrg keeps branches after merge, so a stacked PR never retargets and merges into its dead base.'
        self.assertEqual(self.update('stacked-prs', first, 0).returncode, 0)
        reworded = 'Stacked PRs never retarget in ExampleOrg because branches are kept after merge.'
        refused = self.update('stacked-pr-retarget', reworded, 1)
        self.assertEqual(refused.returncode, 1)
        self.assertIn('stacked-prs', refused.stderr)
        state = json.loads((self.root / '.agent-vault-profile.json').read_text(encoding='utf-8'))
        self.assertEqual((state['revision'], len(state['entries'])), (1, 1))
        # Rewriting the same id, a separate fact, and an explicit override all go through.
        self.assertEqual(self.update('stacked-prs', reworded, 1).returncode, 0)
        self.assertEqual(self.update('pnpm', 'Prefer pnpm over npm for new Next.js repositories.', 2).returncode, 0)
        self.assertEqual(self.update('stacked-pr-retarget', reworded, 3, '--allow-similar').returncode, 0)

    def test_retired_entries_do_not_block_a_replacement(self):
        self.assertEqual(self.cli('init-profile').returncode, 0)
        text = 'Restore Podman Desktop from the fallback steps in the runtime note when Docker fails.'
        self.assertEqual(self.update('podman', text, 0).returncode, 0)
        self.assertEqual(self.cli('retire', '--id', 'podman', '--source', 'test', '--agent', 'human',
                                  '--expected-revision', '1').returncode, 0)
        self.assertEqual(self.update('podman-fallback', text, 2).returncode, 0)


class DoctorTests(unittest.TestCase):
    run_cli = central.CentralRouterTests.run_cli

    def setUp(self):
        central.CentralRouterTests.setUp(self)
        # A real toolkit clone, so provenance, branches and "behind main" come from Git itself.
        self.toolkit = self.home / 'toolkit'
        (self.toolkit / 'scripts').mkdir(parents=True)
        for path in SCRIPTS.glob('*.py'):
            shutil.copyfile(path, self.toolkit / 'scripts' / path.name)
        shutil.copytree(TOOLKIT / 'skills', self.toolkit / 'skills')
        self.git('init', '-q', '-b', 'main')
        self.commit('toolkit')

    def git(self, *args):
        result = subprocess.run(['git', '-C', str(self.toolkit), '-c', 'user.name=t', '-c', 'user.email=t@example.test', *args],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, message):
        self.git('add', '-A')
        self.git('commit', '-qm', message)

    def toolkit_cli(self, *args):
        return subprocess.run([sys.executable, str(self.toolkit / 'scripts/project-memory-router.py'),
                               '--directory', str(self.config), *args], capture_output=True, text=True,
                              encoding='utf-8', cwd=self.home, env=home_env(self.home))

    def install(self, *extra):
        return self.toolkit_cli('install', '--home', str(self.home), '--profile', str(self.profile), *extra)

    def doctor(self):
        result = self.toolkit_cli('doctor', '--home', str(self.home))
        output = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0 if output['ok'] else 1)
        return {item['check']: item for item in output['checks']}

    def change_tool(self, line):
        with open(self.toolkit / 'scripts/vault_runtime.py', 'a', encoding='utf-8') as stream:
            stream.write(f'\n# {line}\n')

    def test_fresh_install_from_main_is_healthy_and_recorded(self):
        self.assertEqual(self.install().returncode, 0)
        record = json.loads((self.config / 'install.json').read_text(encoding='utf-8'))
        self.assertEqual((record['branch'], record['uncommitted']), ('main', False))
        self.assertEqual(record['commit'], self.git('rev-parse', 'HEAD'))
        self.assertIn('vault_doctor.py', record['files'])
        checks = self.doctor()
        for name in ['installed files', 'source', 'registry', 'claude hooks', 'profile']:
            self.assertTrue(checks[name]['ok'], checks[name])

    def test_doctor_reports_edits_behind_main_and_missing_folders(self):
        self.assertEqual(self.install().returncode, 0)
        with open(self.config / 'router.py', 'a', encoding='utf-8') as stream:
            stream.write('\n# local edit\n')
        self.change_tool('newer main')
        self.commit('newer tools')
        shutil.rmtree(self.repos['projectx'])
        checks = self.doctor()
        self.assertIn('router.py', checks['installed files']['detail'])
        self.assertIn('1 tool commit(s) behind main', checks['source']['detail'])
        self.assertIn('projectx', checks['registry']['detail'])

    def test_unmerged_install_is_reported_and_not_silently_replaced(self):
        self.git('switch', '-q', '-c', 'feat/local-only')
        self.change_tool('unmerged work')
        self.commit('unmerged work')
        self.assertEqual(self.install().returncode, 0)
        self.assertIn('never pushed', self.doctor()['source']['detail'])
        self.git('switch', '-q', 'main')
        refused = self.install()
        self.assertEqual(refused.returncode, 1)
        self.assertIn('feat/local-only', refused.stderr)
        self.assertIn('unmerged work', (self.config / 'vault_runtime.py').read_text(encoding='utf-8'))
        self.git('merge', '-q', '--no-edit', 'feat/local-only')
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(self.install('--replace-unmerged').returncode, 0)

    def test_uncommitted_tool_changes_are_flagged(self):
        self.change_tool('work in progress')
        self.assertEqual(self.install().returncode, 0)
        self.assertIn('uncommitted', self.doctor()['source']['detail'])

    def test_install_without_a_record_asks_for_a_reinstall(self):
        self.assertEqual(self.install().returncode, 0)
        (self.config / 'install.json').unlink()
        self.assertFalse(self.doctor()['install record']['ok'])


if __name__ == '__main__':
    unittest.main()
