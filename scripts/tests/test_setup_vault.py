"""Setup must preserve existing repo knowledge and work from another device path."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from platform_helpers import home_env, run_hook

SCRIPT = Path(__file__).resolve().parents[1] / 'setup-vault.py'


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'some project'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def setup(self, *extra):
        return subprocess.run([sys.executable, str(SCRIPT), '--root', str(self.root), '--name', 'ExampleApp', *extra],
                              capture_output=True, text=True)

    def test_new_vault_starts_empty_without_repository_identity_and_usable_cli(self):
        result = self.setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads((self.root / 'docs/knowledge/memory/state.json').read_text())
        self.assertFalse((self.root/'SOUL.md').exists())
        self.assertEqual(state['scope'],'project')
        self.assertEqual(state['entries'], [])
        self.assertEqual(state['history'], [])
        self.assertEqual(state['revision'], 0)
        result = subprocess.run([sys.executable, str(self.root / 'scripts/agent-memory.py'), 'context'],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('# ExampleApp project memory', result.stdout)

    def test_unicode_project_path_and_memory_work_without_utf8_locale_default(self):
        destination = self.root.parent / 'Projet café 项目'
        self.root.rename(destination)
        self.root = destination
        self.assertEqual(self.setup().returncode, 0)
        engine = self.root / 'scripts/agent-memory.py'
        result = subprocess.run([sys.executable, str(engine), 'update', '--id', 'unicode', '--kind', 'explicit',
                                 '--text', 'Préférence 测试 😀', '--source', 'user:test', '--agent', 'human',
                                 '--expected-revision', '0'], cwd=self.root, env={**os.environ, 'PYTHONUTF8':'0'},
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable,str(engine),'context'],cwd=self.root,
                                env={**os.environ,'PYTHONUTF8':'0'},capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Préférence 测试 😀',result.stdout)

    def test_existing_instructions_and_settings_are_preserved_and_setup_is_idempotent(self):
        for name, content in [('AGENTS.md', '# Existing rules\nDo not lose me.\n'), ('CLAUDE.md', '# Personal rules\n')]:
            (self.root / name).write_text(content)
        settings = self.root / '.claude/settings.json'
        settings.parent.mkdir()
        settings.write_text(json.dumps({'permissions': {'allow': ['Read']}, 'hooks': {'Stop': [
            {'hooks': [{'type': 'command', 'command': 'existing-hook'}]}]}}))
        result = self.setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / 'AGENTS.md').read_text().startswith('# Existing rules\nDo not lose me.\n'))
        data = json.loads(settings.read_text())
        self.assertEqual(data['permissions'], {'allow': ['Read']})
        self.assertEqual(data['hooks']['Stop'][0]['hooks'][0]['command'], 'existing-hook')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file() and '.git' not in p.parts}
        self.assertEqual(self.setup().returncode, 0)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file() and '.git' not in p.parts}
        self.assertEqual(before, after)

    def test_existing_memory_is_never_reinitialized(self):
        self.assertEqual(self.setup().returncode, 0)
        engine = self.root / 'scripts/agent-memory.py'
        subprocess.run([sys.executable, str(engine), 'update', '--id', 'preserve', '--kind', 'explicit',
                        '--text', 'Keep durable history.', '--source', 'user:test', '--agent', 'human',
                        '--expected-revision', '0'], cwd=self.root, check=True, capture_output=True)
        state = self.root / 'docs/knowledge/memory/state.json'
        before = state.read_bytes()
        self.assertEqual(self.setup().returncode, 0)
        self.assertEqual(state.read_bytes(), before)

    def test_conflicting_script_is_not_overwritten_and_no_partial_setup(self):
        path = self.root / 'scripts/agent-memory.py'
        path.parent.mkdir()
        path.write_text('existing tool\n')
        result = self.setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(path.read_text(), 'existing tool\n')
        self.assertFalse((self.root / 'SOUL.md').exists())
        self.assertFalse((self.root / 'docs/knowledge/memory/state.json').exists())

    def test_invalid_config_is_rejected_before_any_file_changes(self):
        path = self.root / '.claude/settings.json'
        path.parent.mkdir()
        path.write_text('broken')
        self.assertNotEqual(self.setup().returncode, 0)
        self.assertFalse((self.root / 'SOUL.md').exists())
        self.assertEqual(path.read_text(), 'broken')

    def test_optional_codex_hooks_preserve_existing_toml_and_do_not_forge_trust(self):
        destination = self.root.parent / 'Codex café 项目'
        self.root.rename(destination)
        self.root = destination
        config = self.root / '.codex/config.toml'
        config.parent.mkdir()
        config.write_text('model = "keep-existing"\n[features]\nhooks = true\n')
        self.assertEqual(self.setup('--codex-hooks').returncode, 0)
        self.assertEqual(config.read_text(), 'model = "keep-existing"\n[features]\nhooks = true\n')
        handler = json.loads((self.root / '.codex/hooks.json').read_text())['hooks']['SessionStart'][0]['hooks'][0]
        result = run_hook(handler, cwd=self.root, env={**home_env(self.root), 'PYTHONUTF8':'0'},
                                input=json.dumps({'hook_event_name':'SessionStart','cwd':str(self.root)}),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('# ExampleApp project memory', result.stdout)
        self.assertFalse((self.root / '.codex/hook-trust.json').exists())

    def test_conflicting_codex_config_does_not_silently_change_user_settings(self):
        config = self.root / '.codex/config.toml'
        config.parent.mkdir()
        config.write_text('[features]\nhooks = false\n')
        self.assertNotEqual(self.setup('--codex-hooks').returncode, 0)
        self.assertEqual(config.read_text(), '[features]\nhooks = false\n')
        self.assertFalse((self.root / 'SOUL.md').exists())

    def test_codex_header_inside_multiline_instructions_is_not_rewritten(self):
        config = self.root / '.codex/config.toml'
        config.parent.mkdir()
        original = 'developer_instructions = """\nExample configuration:\n[features]\nKeep these instructions intact.\n"""\n'
        config.write_text(original)
        result = self.setup('--codex-hooks')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(config.read_text(), original)
        self.assertFalse((self.root / 'SOUL.md').exists())

    def test_clone_on_other_device_keeps_facts_and_gets_local_registration(self):
        self.assertEqual(self.setup().returncode, 0)
        engine = self.root / 'scripts/agent-memory.py'
        subprocess.run([sys.executable, str(engine), 'update', '--id', 'workflow', '--kind', 'explicit',
                        '--text', 'Shared across devices.', '--source', 'user:test', '--agent', 'human',
                        '--expected-revision', '0'], cwd=self.root, check=True, capture_output=True)
        subprocess.run(['git','-C',str(self.root),'add','AGENTS.md','CLAUDE.md','MEMORY.md','docs','scripts','.claude','.gitignore'],check=True)
        subprocess.run(['git','-C',str(self.root),'-c','user.name=Test','-c','user.email=test@example.test','commit','-qm','vault'],check=True)
        second = self.root.parent / 'other device clone'
        subprocess.run(['git','clone','-q',str(self.root),str(second)],check=True)
        home = self.root.parent / 'other home'
        home.mkdir()
        router = second / 'scripts/project-memory-router.py'
        result = subprocess.run([sys.executable,str(router),'--directory',str(home / '.config/agent-memory'),
                                 'install','--home',str(home),'--id','exampleapp','--name','ExampleApp','--root',str(second)],
                                capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        result = subprocess.run([sys.executable,str(home / '.config/agent-memory/router.py'),'hook'], cwd=home,
                                env=home_env(home),capture_output=True,text=True,input=json.dumps({
                                    'hook_event_name':'UserPromptSubmit','session_id':'second-device','cwd':str(home),'prompt':'Explain ExampleApp'}))
        self.assertEqual(result.returncode,0,result.stderr)
        text=json.loads(result.stdout)['hookSpecificOutput']['additionalContext']
        self.assertIn('Shared across devices.',text)
        self.assertIn(str(second.resolve()),text)


if __name__ == '__main__':
    unittest.main()
