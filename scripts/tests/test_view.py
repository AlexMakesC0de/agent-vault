"""The read-only HTML memory page, built from a real profile, an external vault and people notes."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from platform_helpers import home_env
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from profile_memory import LIMITS

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
        self.assertRegex(html, r'USER\.md</span><span>[\d,]+ / ' + f"{LIMITS['user']:,}")

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

    def test_without_setup_names_the_install_command(self):
        result = self.script(SCRIPTS / 'view.py', '--config', self.home / 'empty', check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('project-memory-router.py install --profile', result.stderr)


if __name__ == '__main__':
    unittest.main()
