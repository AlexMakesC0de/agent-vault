"""Lossless transfer between private profile and project stores, including replay."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS=Path(__file__).resolve().parents[1]


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.project=self.base/'project café';self.project.mkdir()
        subprocess.run(['git','init','-q',str(self.project)],check=True)
        self.profile=self.base/'private profile'
        result=subprocess.run([sys.executable,str(SCRIPTS/'agent-memory.py'),'--profile',str(self.profile),'init-profile'],capture_output=True,text=True,encoding='utf-8',env={**os.environ,'HOME':self.temp.name,'USERPROFILE':self.temp.name})
        self.assertEqual(result.returncode,0,result.stderr)
        self.state=self.project/'docs/knowledge/memory/state.json';self.state.parent.mkdir(parents=True)
        entries=[{'id':'preference','text':'Prefer concise answers.','kind':'explicit','status':'active','source':'docs/evidence.md#preference','updated_at':'2026-10-18'},
                 {'id':'project-fact','text':'ExampleApp uses SQLite.','kind':'observed','status':'active','source':'test:verified','updated_at':'2026-10-18'}]
        state={'schema':1,'revision':2,'entries':entries,'history':[{'revision':i+1,'action':'update','before':None,'after':entry} for i,entry in enumerate(entries)]}
        self.state.write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8')
        (self.project/'docs/evidence.md').write_text('# Evidence\nDirect user preference.\n',encoding='utf-8')
        (self.project/'SOUL.md').write_bytes(b'# Exact legacy core\r\nKeep these bytes.\r\n')
        (self.project/'AGENTS.md').write_text('# Existing rules\nRead [SOUL.md](SOUL.md).\nNever drop original detail.\n',encoding='utf-8')
        (self.project/'CLAUDE.md').write_text('@AGENTS.md\n@SOUL.md\n',encoding='utf-8')
        (self.project/'scripts').mkdir()
        (self.project/'scripts/agent-memory.py').write_text('# old owned engine\n',encoding='utf-8')
        self.original={name:(self.project/name).read_bytes() for name in ['docs/knowledge/memory/state.json','SOUL.md','AGENTS.md','CLAUDE.md','scripts/agent-memory.py','docs/evidence.md']}

    def migrate(self,*extra,apply=True):
        args=[sys.executable,str(SCRIPTS/'migrate-vault.py'),'--project',str(self.project),'--profile',str(self.profile),
              '--id','example','--name','ExampleApp','--move-user','preference','--expected-project-revision','2',
              '--expected-profile-revision','0','--upgrade-tools',*extra]
        if apply:args.append('--apply')
        return subprocess.run(args,capture_output=True,text=True,encoding='utf-8')

    def test_preview_does_not_change_source_or_profile(self):
        before=(self.profile/'.agent-vault-profile.json').read_bytes()
        result=self.migrate(apply=False)
        self.assertEqual(result.returncode,0,result.stderr)
        for name,content in self.original.items():self.assertEqual((self.project/name).read_bytes(),content)
        self.assertEqual((self.profile/'.agent-vault-profile.json').read_bytes(),before)
        self.assertNotIn('Prefer concise answers.',(self.profile/'USER.md').read_text(encoding='utf-8'))

    def test_every_original_entry_history_and_affected_file_is_preserved(self):
        result=self.migrate();self.assertEqual(result.returncode,0,result.stderr)
        original=json.loads(self.original['docs/knowledge/memory/state.json'])
        current=json.loads(self.state.read_text(encoding='utf-8'))
        self.assertEqual(current['history'][:2],original['history'])
        self.assertEqual([e['text'] for e in current['entries']],[e['text'] for e in original['entries']])
        self.assertEqual(current['entries'][0]['status'],'migrated')
        self.assertFalse((self.project/'SOUL.md').exists())
        self.assertNotIn('Prefer concise answers.',(self.project/'MEMORY.md').read_text(encoding='utf-8'))
        self.assertIn('ExampleApp uses SQLite.',(self.project/'MEMORY.md').read_text(encoding='utf-8'))
        self.assertIn('Prefer concise answers.',(self.profile/'USER.md').read_text(encoding='utf-8'))
        self.assertNotIn('ExampleApp uses SQLite.',(self.profile/'USER.md').read_text(encoding='utf-8'))
        receipt=json.loads((self.project/'docs/knowledge/memory/MIGRATION-v2.json').read_text(encoding='utf-8'))
        for name,content in self.original.items():
            record=receipt['originals'][name]
            self.assertEqual(record['sha256'],hashlib.sha256(content).hexdigest())
            self.assertEqual((self.project/record['archive']).read_bytes(),content)
        self.assertEqual((self.profile/'imports/example/source-state.json').read_bytes(),self.original['docs/knowledge/memory/state.json'])
        self.assertEqual((self.profile/'imports/example/evidence/docs/evidence.md').read_bytes(),self.original['docs/evidence.md'])
        self.assertNotIn('@SOUL.md',(self.project/'CLAUDE.md').read_text(encoding='utf-8'))

    def test_replay_is_idempotent_and_never_duplicates_preferences(self):
        self.assertEqual(self.migrate().returncode,0)
        profile=(self.profile/'.agent-vault-profile.json').read_bytes();project=self.state.read_bytes()
        self.assertEqual(self.migrate().returncode,0)
        self.assertEqual((self.profile/'.agent-vault-profile.json').read_bytes(),profile)
        self.assertEqual(self.state.read_bytes(),project)

    def test_resume_after_destination_commit_preserves_originals_and_does_not_reimport(self):
        self.assertEqual(self.migrate().returncode,0)
        before=(self.profile/'.agent-vault-profile.json').read_bytes()
        # Restore the source preimage to emulate interruption before its commit.
        for name,content in self.original.items():(self.project/name).write_bytes(content)
        result=self.migrate();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((self.profile/'.agent-vault-profile.json').read_bytes(),before)
        self.assertFalse((self.project/'SOUL.md').exists())
        self.assertEqual(json.loads(self.state.read_text(encoding='utf-8'))['schema'],2)

    def test_resume_after_partial_instruction_and_tool_rewrites(self):
        self.assertEqual(self.migrate().returncode,0)
        before=(self.profile/'.agent-vault-profile.json').read_bytes()
        self.state.write_bytes(self.original['docs/knowledge/memory/state.json'])
        (self.project/'SOUL.md').write_bytes(self.original['SOUL.md'])
        result=self.migrate();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((self.profile/'.agent-vault-profile.json').read_bytes(),before)
        self.assertFalse((self.project/'SOUL.md').exists())

    def test_resume_after_project_state_commit_finishes_legacy_core_removal(self):
        self.assertEqual(self.migrate().returncode,0)
        (self.project/'SOUL.md').write_bytes(self.original['SOUL.md'])
        result=self.migrate();self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((self.project/'SOUL.md').exists())

    def test_existing_memory_is_archived_and_linked(self):
        content=b'# Hand authored project memory\r\nUnique original fact.\r\n'
        (self.project/'MEMORY.md').write_bytes(content)
        result=self.migrate();self.assertEqual(result.returncode,0,result.stderr)
        receipt=json.loads((self.project/'docs/knowledge/memory/MIGRATION-v2.json').read_text())
        self.assertEqual((self.project/receipt['originals']['MEMORY.md']['archive']).read_bytes(),content)
        self.assertIn('preserved MEMORY.md',(self.project/'MEMORY.md').read_text())

    def test_completed_state_recovery_preview_never_removes_core(self):
        self.assertEqual(self.migrate().returncode,0)
        (self.project/'SOUL.md').write_bytes(self.original['SOUL.md'])
        receipt=self.project/'docs/knowledge/memory/MIGRATION-v2.json'
        before=receipt.read_bytes()
        result=self.migrate(apply=False);self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(receipt.read_bytes(),before)
        self.assertEqual((self.project/'SOUL.md').read_bytes(),self.original['SOUL.md'])

    def test_root_evidence_is_available_in_profile_clone(self):
        evidence=b'# Root evidence\nPreference requested here.\n'
        (self.project/'evidence.md').write_bytes(evidence)
        state=json.loads(self.state.read_text());state['entries'][0]['source']='evidence.md#preference'
        self.state.write_text(json.dumps(state))
        result=self.migrate();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((self.profile/'imports/example/evidence/evidence.md').read_bytes(),evidence)

    @unittest.skipIf(sys.platform=='win32','Windows symlink privileges vary')
    def test_symlinked_output_is_rejected_before_changes(self):
        other=self.base/'other.md';other.write_text('Do not touch')
        (self.project/'MEMORY.md').symlink_to(other)
        result=self.migrate();self.assertNotEqual(result.returncode,0)
        self.assertEqual(other.read_text(),'Do not touch')
        self.assertTrue((self.project/'SOUL.md').exists())

    def test_resume_after_profile_state_before_derived_user_projection(self):
        before=(self.profile/'USER.md').read_bytes()
        self.assertEqual(self.migrate().returncode,0)
        self.state.write_bytes(self.original['docs/knowledge/memory/state.json'])
        (self.project/'SOUL.md').write_bytes(self.original['SOUL.md'])
        (self.profile/'USER.md').write_bytes(before)
        result=self.migrate();self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Prefer concise answers.',(self.profile/'USER.md').read_text())

    def test_resume_refuses_new_manual_memory_instead_of_overwriting_it(self):
        self.assertEqual(self.migrate().returncode,0)
        self.state.write_bytes(self.original['docs/knowledge/memory/state.json'])
        (self.project/'SOUL.md').write_bytes(self.original['SOUL.md'])
        content=b'# Important manual note after interruption\nKeep this original.\n'
        (self.project/'MEMORY.md').write_bytes(content)
        result=self.migrate();self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.project/'MEMORY.md').read_bytes(),content)

    def test_windows_style_git_clone_preserves_exact_archive_bytes(self):
        self.assertEqual(self.migrate().returncode,0)
        subprocess.run(['git','-C',str(self.project),'-c','core.autocrlf=true','add','.gitattributes','MEMORY.md','docs'],check=True,capture_output=True)
        subprocess.run(['git','-C',str(self.project),'-c','user.name=Test','-c','user.email=test@example.test','commit','-qm','migration'],check=True,capture_output=True)
        clone=self.base/'windows clone'
        subprocess.run(['git','-c','core.autocrlf=true','clone','-q',str(self.project),str(clone)],check=True,capture_output=True)
        receipt=json.loads((clone/'docs/knowledge/memory/MIGRATION-v2.json').read_text())
        for name,content in self.original.items():
            self.assertEqual((clone/receipt['originals'][name]['archive']).read_bytes(),content)

    def test_stale_source_revision_refuses_without_mutating_either_store(self):
        current=json.loads(self.state.read_text(encoding='utf-8'));current['revision']=3
        self.state.write_text(json.dumps(current),encoding='utf-8')
        before=self.state.read_bytes();target=(self.profile/'.agent-vault-profile.json').read_bytes()
        self.assertNotEqual(self.migrate().returncode,0)
        self.assertEqual(self.state.read_bytes(),before)
        self.assertEqual((self.profile/'.agent-vault-profile.json').read_bytes(),target)

    def test_overflow_does_not_remove_or_move_source_information(self):
        current=json.loads(self.state.read_text(encoding='utf-8'));current['entries'][0]['text']='x'*2300
        self.state.write_text(json.dumps(current),encoding='utf-8')
        before=self.state.read_bytes();target=(self.profile/'.agent-vault-profile.json').read_bytes()
        self.assertNotEqual(self.migrate().returncode,0)
        self.assertEqual(self.state.read_bytes(),before)
        self.assertEqual((self.profile/'.agent-vault-profile.json').read_bytes(),target)
        self.assertTrue((self.project/'SOUL.md').exists())


if __name__=='__main__':unittest.main()
