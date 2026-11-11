"""One canonical identity, shared across clients, with independent project knowledge."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'agent-memory.py'


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'private profile café'

    def cli(self, *args, payload=None):
        return subprocess.run([sys.executable, str(SCRIPT), '--profile', str(self.root), *args],
                              input=json.dumps(payload) if payload is not None else None,
                              capture_output=True, text=True, encoding='utf-8',
                              env={**os.environ, 'HOME': self.temp.name, 'USERPROFILE': self.temp.name})

    def init(self):
        result = self.cli('init-profile')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_both_clients_read_the_same_canonical_soul(self):
        self.init()
        (self.root / 'SOUL.md').write_text('# Shared identity\nOne identity for both clients.\n',encoding='utf-8')
        for agent in ['claude','codex']:
            result=self.cli('hook','--agent',agent,payload={'hook_event_name':'SessionStart','session_id':agent})
            self.assertEqual(result.returncode,0,result.stderr)
            text=json.loads(result.stdout)['hookSpecificOutput']['additionalContext']
            self.assertIn('One identity for both clients.',text)
            reported=Path(text.split("Central shared profile: ",1)[1].splitlines()[0])
            self.assertTrue(reported.samefile(self.root))
        self.assertEqual((self.root/'SOUL.md').read_text(encoding='utf-8'),'# Shared identity\nOne identity for both clients.\n')

    def test_user_and_general_learning_have_separate_evidence_and_history(self):
        self.init()
        for revision,target,key,text in [(0,'user','tone','Prefer concise answers.'),(1,'memory','workflow','Use scratch databases.')]:
            result=self.cli('update','--target',target,'--id',key,'--text',text,'--kind','explicit',
                            '--source','user:test','--agent','claude','--expected-revision',str(revision))
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Prefer concise answers.',(self.root/'USER.md').read_text(encoding='utf-8'))
        self.assertNotIn('Use scratch databases.',(self.root/'USER.md').read_text(encoding='utf-8'))
        self.assertIn('Use scratch databases.',(self.root/'MEMORY.md').read_text(encoding='utf-8'))
        state=json.loads((self.root/'.agent-vault-profile.json').read_text(encoding='utf-8'))
        self.assertEqual(state['revision'],2)
        self.assertEqual(len(state['history']),2)
        self.assertEqual(state['entries'][0]['source'],'user:test')

    def test_reinstall_and_render_do_not_reset_authored_identity(self):
        self.init()
        soul=self.root/'SOUL.md'
        soul.write_text('# Custom identity\nPreserve this canonical identity.\n',encoding='utf-8')
        original=soul.read_bytes()
        self.assertEqual(self.cli('init-profile').returncode,0)
        self.assertEqual(self.cli('render').returncode,0)
        self.assertEqual(soul.read_bytes(),original)

    def test_identity_changes_preserve_before_and_after(self):
        self.init()
        before=(self.root/'SOUL.md').read_text(encoding='utf-8')
        result=self.cli('set-soul','--text','# Shared soul\nClear and candid.','--source','user:test',
                        '--agent','human','--expected-revision','0')
        self.assertEqual(result.returncode,0,result.stderr)
        state=json.loads((self.root/'.agent-vault-profile.json').read_text(encoding='utf-8'))
        self.assertEqual(state['history'][-1]['before'],before)
        self.assertIn('Clear and candid.',state['history'][-1]['after'])
        self.assertIn('Clear and candid.',self.cli('context').stdout)

    def test_stale_and_overflow_changes_preserve_all_files(self):
        self.init()
        before={p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        for revision,text in [('9','Changed'),('0','x'*2500)]:
            result=self.cli('update','--target','user','--id','invalid','--text',text,'--kind','explicit',
                            '--source','user:test','--agent','codex','--expected-revision',revision)
            self.assertNotEqual(result.returncode,0)
        after={p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        self.assertEqual(before,after)

    def test_preferences_get_room_and_identity_writes_take_the_tighter_limit(self):
        self.init()
        # Twelve 140-character preferences make USER.md about 1,900 characters: over the former 1,375.
        for i in range(12):
            result=self.cli('update','--target','user','--id',f'pref{i}','--text',f'Preference {i:02d}: '+'concise wording '*8,
                            '--kind','explicit','--source','user:test','--agent','human','--expected-revision',str(i))
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertGreater(len((self.root/'USER.md').read_text(encoding='utf-8')),1375)
        long_identity='# Identity\n'+'Work thoughtfully. '*90  # About 1,700 characters.
        refused=self.cli('set-soul','--text',long_identity,'--source','user:test','--agent','human','--expected-revision','12')
        self.assertEqual(refused.returncode,1)
        self.assertIn('1,500',refused.stderr)

    def test_existing_identity_over_the_new_limit_still_loads_with_a_warning(self):
        self.init()
        (self.root/'SOUL.md').write_text('# Identity\n'+'Work thoughtfully. '*100,encoding='utf-8')  # About 1,900.
        result=self.cli('context')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Work thoughtfully.',result.stdout)
        self.assertIn('Near the cap: SOUL.md',result.stdout)
        (self.root/'SOUL.md').write_text('# Identity\n'+'x'*2300,encoding='utf-8')
        self.assertNotEqual(self.cli('context').returncode,0)

    def test_missing_profile_is_not_initialized_by_context(self):
        result=self.cli('context')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.root/'SOUL.md').exists())

    def test_conflicting_soul_copy_blocks_identity_change(self):
        self.init()
        (self.root / 'SOUL-OTHERPC.md').write_text('# Other identity\n', encoding='utf-8')
        self.assertIn('Sync conflict', self.cli('context').stdout)
        result = self.cli('set-soul', '--text', '# New\n', '--source', 'test', '--agent', 'human', '--expected-revision', '0')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Sync conflict', result.stderr)

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

    def test_context_points_at_central_notes_only_when_they_exist(self):
        self.init()
        self.assertNotIn('Central notes:', self.cli('context').stdout)
        (self.root / 'notes').mkdir()
        (self.root / 'notes' / 'README.md').write_text('# Notes\n', encoding='utf-8')
        self.assertIn('Central notes: ' + str((self.root / 'notes' / 'README.md').resolve()), self.cli('context').stdout)

    def test_user_preferences_warn_before_the_cap_and_fail_at_it(self):
        self.init()
        result = self.cli('update', '--target', 'user', '--id', 'long', '--text', 'y' * 1700, '--kind', 'explicit',
                          '--source', 'user:test', '--agent', 'claude', '--expected-revision', '0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Near the cap: USER.md ', json.loads(result.stdout)['warning'])
        self.assertIn('Near the cap: USER.md ', self.cli('context').stdout)
        full = self.cli('update', '--target', 'user', '--id', 'more', '--text', 'z' * 300, '--kind', 'explicit',
                        '--source', 'user:test', '--agent', 'claude', '--expected-revision', '1')
        self.assertEqual(full.returncode, 1)


if __name__=='__main__':unittest.main()
