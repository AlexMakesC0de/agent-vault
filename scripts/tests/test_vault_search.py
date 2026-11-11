"""Search over real temporary profiles and vaults through the router CLI and the installed copy."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import test_central_router as central
from platform_helpers import home_env


class VaultSearchTests(unittest.TestCase):
    run_cli = central.CentralRouterTests.run_cli

    def setUp(self):
        central.CentralRouterTests.setUp(self)
        self.app = self.repos['exampleapp']
        knowledge = self.app / 'docs/knowledge'
        (knowledge / 'api').mkdir(parents=True)
        (knowledge / 'api/merge-jobs.md').write_text('# Merge jobs\nA merge job copies contacts into the surviving account.\n', encoding='utf-8')
        (knowledge / 'deploy.md').write_text('# Deploy\nUAT deploys run from the release workflow.\n', encoding='utf-8')
        (self.profile / 'notes').mkdir(exist_ok=True)
        (self.profile / 'notes/runtime.md').write_text('# Container runtime\nRestore Podman when Docker fails.\n', encoding='utf-8')

    def search(self, *words, ok=True):
        result = self.run_cli('search', *words)
        if not ok:
            self.assertEqual(result.returncode, 1, result.stdout)
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def titles(self, output):
        return [item['title'] for item in output['results']]

    def test_ranks_notes_from_profile_and_project_vaults(self):
        output = self.search('merge', 'job')
        self.assertEqual(output['matched'], 'all words')
        self.assertEqual(self.titles(output)[0], 'Merge jobs')
        self.assertEqual(output['results'][0]['store'], 'exampleapp')
        self.assertIn('[merge]', output['results'][0]['snippet'].lower())
        restore = self.search('restoring', 'podman')  # Stemming matches "Restore".
        self.assertEqual(restore['results'][0]['store'], 'profile')
        self.assertEqual(restore['results'][0]['title'], 'Container runtime')

    def test_falls_back_to_any_word_when_no_note_has_all(self):
        output = self.search('deploy', 'nonexistentword')
        self.assertEqual(output['matched'], 'any word')
        self.assertEqual(self.titles(output), ['Deploy'])
        self.assertEqual(self.search('nonexistentword')['results'], [])

    def test_project_filter_accepts_id_alias_and_profile(self):
        self.assertEqual({r['store'] for r in self.search('merge', '--project', 'ExampleApp')['results']}, {'exampleapp'})
        self.assertEqual(self.search('merge', '--project', 'projectx')['results'], [])
        self.assertEqual({r['store'] for r in self.search('podman', '--project', 'profile')['results']}, {'profile'})
        self.assertIn("Unknown store 'nope'", self.search('merge', '--project', 'nope', ok=False))
        self.assertIn('at least one search word', self.search('--', '!!', ok=False))

    def test_index_follows_edits_and_deletions_without_a_rebuild(self):
        first = self.search('merge')
        self.assertGreater(first['reindexed'], 0)
        self.assertEqual(self.search('merge')['reindexed'], 0)
        note = self.app / 'docs/knowledge/deploy.md'
        note.write_text('# Deploy\nProduction deploys need a change ticket.\n', encoding='utf-8')
        os.utime(note, ns=(note.stat().st_atime_ns, note.stat().st_mtime_ns + 10**9))
        edited = self.search('ticket')
        self.assertEqual(edited['reindexed'], 1)
        self.assertEqual(self.titles(edited), ['Deploy'])
        self.assertEqual(self.search('release', 'workflow')['results'], [])
        (self.app / 'docs/knowledge/api/merge-jobs.md').unlink()
        gone = self.search('surviving')
        self.assertEqual((gone['removed'], gone['results']), (1, []))

    def test_in_repo_vault_reads_knowledge_but_not_source_or_dependencies(self):
        for relative in ['node_modules/pkg/README.md', 'src/guide.md', 'docs/knowledge/.drafts/hidden.md']:
            path = self.app / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# Secretword\nsecretword\n', encoding='utf-8')
        (self.app / 'docs/knowledge/visible.md').write_text('# Visible\nsecretword\n', encoding='utf-8')
        self.assertEqual(self.titles(self.search('secretword')), ['Visible'])
        self.assertEqual(self.titles(self.search('conventions', '--project', 'exampleapp')), ['ExampleApp rules'])

    def test_damaged_or_discarded_index_is_rebuilt_from_markdown(self):
        self.search('merge')
        (self.config / 'search.sqlite').write_bytes(b'not a database' * 100)
        repaired = self.search('merge')
        self.assertEqual(self.titles(repaired)[0], 'Merge jobs')
        rebuilt = self.search('merge', '--rebuild')
        self.assertEqual(rebuilt['reindexed'], rebuilt['notes'])

    def test_installed_router_searches_and_guidance_names_the_command(self):
        result = self.run_cli('install', '--home', str(self.home), '--profile', str(self.profile))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.config / 'vault_search.py').is_file())
        guidance = (self.home / '.claude/CLAUDE.md').read_text(encoding='utf-8')
        self.assertIn("router.py search", guidance.replace('"', '').replace("'", ''))
        installed = subprocess.run([sys.executable, str(self.config / 'router.py'), '--directory', str(self.config),
                                    'search', 'podman'], capture_output=True, text=True, encoding='utf-8',
                                   cwd=self.home, env=home_env(self.home))
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(json.loads(installed.stdout)['results'][0]['title'], 'Container runtime')


if __name__ == '__main__':
    unittest.main()
