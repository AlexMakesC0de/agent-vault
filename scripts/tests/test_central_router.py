"""Actual home-session hooks and installation for both clients and a private profile."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import test_project_memory_router as fixture
from platform_helpers import home_env, run_hook, run_review

SCRIPTS=Path(__file__).resolve().parents[1]


class CentralRouterTests(unittest.TestCase):
    run_cli=fixture.RouterTests.run_cli
    text=fixture.RouterTests.text
    def setUp(self):
        fixture.RouterTests.setUp(self)
        self.home=self.home.resolve();self.config=self.config.resolve()
        self.profile=self.home/'private profile café'
        result=subprocess.run([sys.executable,str(SCRIPTS/'agent-memory.py'),'--profile',str(self.profile),'init-profile'],capture_output=True,text=True,env=home_env(self.home))
        self.assertEqual(result.returncode,0,result.stderr)
        self.identity='# One shared identity\nWork thoughtfully with the user.\n'
        (self.profile/'SOUL.md').write_text(self.identity,encoding='utf-8')
        (self.config/'config.json').write_text(json.dumps({'schema':2,'profile_root':str(self.profile)}))

    def hook(self,event='UserPromptSubmit',agent='claude',**fields):
        result=self.run_cli('hook','--agent',agent,payload={'hook_event_name':event,'session_id':'test-session','cwd':str(self.home),**fields})
        self.assertEqual(result.returncode,0,result.stderr)
        output=json.loads(result.stdout)
        self.assertNotIn('unavailable',output.get('systemMessage',''))
        return output

    def test_both_clients_always_load_the_same_central_soul_from_home(self):
        for agent in ['claude','codex']:
            for event in ['SessionStart','UserPromptSubmit']:
                text=self.text(self.hook(event,agent=agent,prompt='An unrelated question',session_id=agent+event))
                self.assertIn(self.identity,text)
                self.assertIn(str(self.profile/'SOUL.md'),text)
                self.assertNotIn('Unique ExampleApp memory.',text)

    def test_unchanged_profile_is_sent_once_per_session_and_again_after_a_change(self):
        for agent in ['claude','codex']:
            self.assertIn(self.identity,self.text(self.hook('SessionStart',agent=agent)))
            text=self.text(self.hook(agent=agent,prompt='Next question'))
            self.assertNotIn(self.identity,text)
            self.assertIn('unchanged at revision',text)
            self.assertIn('by running: ',text)  # The review receipt still renews every prompt.
            revision=json.loads((self.profile/'.agent-vault-profile.json').read_text(encoding='utf-8'))['revision']
            result=subprocess.run([sys.executable,str(SCRIPTS/'agent-memory.py'),'--root',str(self.profile),'update','--target','memory',
                                   '--id','added-lesson-'+agent,'--kind','explicit','--text','A newly added lesson for '+agent+'.',
                                   '--source','test','--agent','human','--expected-revision',str(revision)],
                                  capture_output=True,text=True,env=home_env(self.home))
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('A newly added lesson for '+agent+'.',self.text(self.hook(agent=agent,prompt='After the change')))
            self.assertIn(self.identity,self.text(self.hook('SessionStart',agent=agent)))  # Compaction re-sends it.

    def test_project_selection_adds_only_owning_vault_without_changing_identity(self):
        for agent in ['claude','codex']:
            text=self.text(self.hook(agent=agent,prompt='Explain ExampleApp'))
            self.assertIn(self.identity,text)
            self.assertIn('Unique ExampleApp memory.',text)
            self.assertNotIn('Unique ProjectX memory.',text)

    def test_central_review_is_required_even_without_selected_project(self):
        for agent in ['claude','codex']:
            text=self.text(self.hook(agent=agent,prompt='No project today'))
            before=list((self.profile/'.memory-runtime').glob('session-*.json'))
            self.assertEqual(self.hook('Stop',agent=agent)['decision'],'block')
            command=text.split('by running: ',1)[1].split('. Do not invent',1)[0]
            result=run_review(command,agent=agent,cwd=self.home,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(self.hook('Stop',agent=agent),{})
            self.assertTrue(before)

    def test_tool_activation_does_not_renew_central_review(self):
        self.hook(prompt='Question')
        receipt=next((self.profile/'.memory-runtime').glob('session-*.json'));before=receipt.read_bytes()
        text=self.text(self.hook('PreToolUse',tool_name='exec_command',tool_input={'cmd':'git status','workdir':str(self.repos['exampleapp'])}))
        self.assertIn('Unique ExampleApp memory.',text)
        self.assertEqual(receipt.read_bytes(),before)

    def test_install_preserves_both_clients_and_native_home_hooks_run(self):
        codex=self.home/'.codex';codex.mkdir()
        (codex/'hooks.json').write_text(json.dumps({'hooks':{'PostToolUse':[{'hooks':[{'type':'command','command':'custom'}]}]}}))
        (codex/'config.toml').write_text('model = "existing"\n[features]\nother = true\n')
        (codex/'AGENTS.md').write_text('# Personal policy\nKeep me.\n')
        args=['install','--home',str(self.home),'--profile',str(self.profile),'--codex-hooks']
        result=self.run_cli(*args);self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue((codex/'AGENTS.md').read_text().startswith('# Personal policy\nKeep me.\n'))
        self.assertIn('other = true',(codex/'config.toml').read_text())
        settings=json.loads((codex/'hooks.json').read_text())
        self.assertEqual(settings['hooks']['PostToolUse'][0]['hooks'][0]['command'],'custom')
        for agent in ['claude','codex']:
            path=self.home/('.'+agent)/('settings.json' if agent=='claude' else 'hooks.json')
            handler=json.loads(path.read_text())['hooks']['UserPromptSubmit'][0]['hooks'][0]
            result=run_hook(handler,cwd=self.home,env=home_env(self.home),capture_output=True,text=True,input=json.dumps({
                'hook_event_name':'UserPromptSubmit','session_id':'shell-'+agent,'cwd':str(self.home),'prompt':'Explain ProjectX'}))
            self.assertEqual(result.returncode,0,result.stderr)
            text=self.text(json.loads(result.stdout));self.assertIn(self.identity,text);self.assertIn('Unique ProjectX memory.',text)
        before={p:p.read_bytes() for p in [codex/'hooks.json',codex/'config.toml',self.home/'.claude/settings.json']}
        self.assertEqual(self.run_cli(*args).returncode,0)
        for p,content in before.items():self.assertEqual(p.read_bytes(),content)
        self.assertFalse((codex/'hook-trust.json').exists())

    def test_install_ships_knowledge_skill_and_replaces_previous_handler(self):
        sys.path.insert(0,str(SCRIPTS));import vault_runtime
        settings=self.home/'.claude'/'settings.json';settings.parent.mkdir(exist_ok=True)
        previous={'hooks':[vault_runtime.hook_handler('claude',subprocess_launch=True)]}
        settings.write_text(json.dumps({'hooks':{'Stop':[previous]}}))
        result=self.run_cli('install','--home',str(self.home),'--profile',str(self.profile))
        self.assertEqual(result.returncode,0,result.stderr)
        source=(SCRIPTS.parent/'skills/vault-knowledge/SKILL.md').read_bytes()
        for path in [self.home/'.claude/skills/vault-knowledge/SKILL.md',self.config/'skills/vault-knowledge/SKILL.md']:
            self.assertEqual(path.read_bytes(),source)
        self.assertIn(str(self.config/'skills/vault-knowledge/SKILL.md'),(self.home/'.claude/CLAUDE.md').read_text(encoding='utf-8'))
        self.assertEqual(json.loads(settings.read_text())['hooks']['Stop'],[{'hooks':[vault_runtime.hook_handler('claude')]}])

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

    def test_clone_profile_to_second_device_and_select_local_path(self):
        subprocess.run(['git','init','-q',str(self.profile)],check=True)
        subprocess.run(['git','-C',str(self.profile),'add','SOUL.md','USER.md','MEMORY.md','.agent-vault-profile.json','.gitattributes'],check=True)
        subprocess.run(['git','-C',str(self.profile),'-c','user.name=Test','-c','user.email=test@example.test','commit','-qm','profile'],check=True)
        second=self.home/'device two profile';subprocess.run(['git','clone','-q',str(self.profile),str(second)],check=True)
        result=self.run_cli('install','--home',str(self.home),'--profile',str(second),'--codex-hooks')
        self.assertEqual(result.returncode,0,result.stderr)
        for agent in ['claude','codex']:
            text=self.text(self.hook('SessionStart',agent=agent))
            self.assertIn(self.identity,text);self.assertIn(str(second),text)
        self.assertEqual((second/'SOUL.md').read_text(encoding='utf-8'),self.identity)

    def test_generated_context_fallback_runs_in_each_clients_native_shell(self):
        result=self.run_cli('install','--home',str(self.home),'--profile',str(self.profile),'--codex-hooks')
        self.assertEqual(result.returncode,0,result.stderr)
        for agent,filename in [('claude','CLAUDE.md'),('codex','AGENTS.md')]:
            guidance=(self.home/('.'+agent)/filename).read_text(encoding='utf-8')
            command=re.search(r'load both with `([^`]+)`',guidance).group(1)
            result=run_review(command,agent=agent,cwd=self.home,env=home_env(self.home),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(self.identity,json.loads(result.stdout)['context'])

    def test_explicitly_disabled_codex_hooks_leave_all_personal_files_unchanged(self):
        codex=self.home/'.codex';codex.mkdir()
        (codex/'config.toml').write_text('[features]\nhooks = false\n')
        result=self.run_cli('install','--home',str(self.home),'--profile',str(self.profile),'--codex-hooks')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.home/'.claude/settings.json').exists())
        self.assertFalse((self.config/'router.py').exists())

    def test_profile_review_names_only_files_the_profile_has(self):
        text=self.text(self.hook(prompt='No project today'))
        self.assertNotIn('README.md',text.split('Before your final response',1)[1])


if __name__=='__main__':unittest.main()
