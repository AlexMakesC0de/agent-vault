"""Real filesystem/CLI tests for project-aware routing and additive installation."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest
from platform_helpers import home_env, run_hook, run_review

SCRIPT = Path(__file__).resolve().parents[1] / "project-memory-router.py"
ENGINE = SCRIPT.with_name("agent-memory.py")


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home directory"
        self.home.mkdir()
        self.config = self.home / ".config/agent-memory"
        self.config.mkdir(parents=True)
        self.repos = {}
        projects = []
        for key, name in [("exampleapp", "ExampleApp"), ("projectx", "ProjectX")]:
            root = self.home / "repos" / name
            root.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "scripts").mkdir()
            shutil.copyfile(ENGINE, root / "scripts/agent-memory.py")
            shutil.copyfile(ENGINE.with_name("vault_runtime.py"), root / "scripts/vault_runtime.py")
            shutil.copyfile(ENGINE.with_name("profile_memory.py"), root / "scripts/profile_memory.py")
            (root / "AGENTS.md").write_text(f"# {name} rules\nUse {name} conventions.\n")
            store = root / "docs/knowledge/memory/state.json"
            store.parent.mkdir(parents=True)
            store.write_text(json.dumps({"schema": 1, "revision": 0, "entries": [{
                "id": "identity", "text": f"Unique {name} memory.", "kind": "explicit", "status": "active",
                "source": "user:test", "updated_at": "2026-10-19"}], "history": []}))
            subprocess.run([sys.executable, str(ENGINE), "--root", str(root), "render"], check=True, capture_output=True)
            self.repos[key] = root
            projects.append({"id": key, "name": name, "root": str(root), "aliases": [name]})
        (self.config / "projects.json").write_text(json.dumps({"schema": 1, "projects": projects}))

    def run_cli(self, *args, payload=None, config=None):
        return subprocess.run([sys.executable, str(SCRIPT), "--directory", str(config or self.config), *args],
                              input=json.dumps(payload) if payload else None, capture_output=True, text=True, encoding="utf-8",
                              cwd=self.home, env=home_env(self.home))

    def hook(self, event="UserPromptSubmit", **fields):
        result = self.run_cli("hook", payload={"hook_event_name": event, "session_id": "test-session",
                                               "cwd": str(self.home), **fields})
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def text(self, output):
        return output.get("hookSpecificOutput", {}).get("additionalContext", "")

    def test_name_selects_only_owning_vault_from_home(self):
        text = self.text(self.hook(prompt="How does ExampleApp handle sync?"))
        self.assertIn("Unique ExampleApp memory.", text)
        self.assertNotIn("Unique ProjectX memory.", text)
        self.assertIn("Use ExampleApp conventions.", text)

    def test_unrelated_prompt_resets_selection_without_keyword_substring_matches(self):
        self.hook(prompt="Work on ExampleApp")
        text = self.text(self.hook(prompt="Explain exampleappian mythology"))
        self.assertNotIn("Unique ExampleApp memory.", text)
        self.assertEqual(self.hook("Stop"), {})

    def test_comparison_loads_separately_labelled_vaults(self):
        text = self.text(self.hook(prompt="Compare ExampleApp and ProjectX"))
        self.assertIn("Unique ExampleApp memory.", text)
        self.assertIn("Unique ProjectX memory.", text)
        self.assertIn("exampleapp", text.lower())
        self.assertIn("projectx", text.lower())

    def test_absolute_file_path_activates_project_before_tool(self):
        self.hook(prompt="Read the file")
        path = self.repos["exampleapp"] / "lib/not-created-yet.ts"
        text = self.text(self.hook("PreToolUse", tool_name="Read", tool_input={"file_path": str(path)}))
        self.assertIn("Unique ExampleApp memory.", text)
        self.assertEqual(self.hook("Stop")["decision"], "block")

    def test_repeated_tool_access_does_not_duplicate_core_or_review_token(self):
        self.hook(prompt="Work on ExampleApp")
        store = next((self.repos["exampleapp"] / ".memory-runtime").glob("session-*.json"))
        before = store.read_bytes()
        output = self.hook("PreToolUse", tool_name="Read", tool_input={"file_path": str(self.repos["exampleapp"] / "AGENTS.md")})
        self.assertEqual(output, {})
        self.assertEqual(store.read_bytes(), before)

    def test_subagent_gets_own_context_without_renewing_parent_review(self):
        self.hook(prompt="Work on ExampleApp")
        store = next((self.repos["exampleapp"] / ".memory-runtime").glob("session-*.json"))
        before = store.read_bytes()
        fields = {"agent_id": "explorer-a", "tool_name": "Read", "tool_input": {
            "file_path": str(self.repos["exampleapp"] / "AGENTS.md")}}
        text = self.text(self.hook("PreToolUse", **fields))
        self.assertIn("Unique ExampleApp memory.", text)
        self.assertEqual(store.read_bytes(), before)
        self.assertEqual(self.hook("PreToolUse", **fields), {})

    def test_review_receipt_allows_stop_and_continuation_never_loops(self):
        self.hook(prompt="Work on ExampleApp")
        receipt = next((self.repos["exampleapp"] / ".memory-runtime").glob("session-*.json"))
        token = json.loads(receipt.read_text())["token"]
        self.assertEqual(self.hook("Stop")["decision"], "block")
        result = subprocess.run([sys.executable, str(ENGINE), "--root", str(self.repos["exampleapp"]), "review",
                                 "--session", "test-session", "--token", token], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.hook("Stop"), {})
        self.hook(prompt="ExampleApp follow-up")
        self.assertNotIn("decision", self.hook("Stop", stop_hook_active=True))

    def test_worktree_cwd_routes_to_primary_store(self):
        root = self.repos["projectx"]
        subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.test",
                        "commit", "--allow-empty", "-qm", "initial"], check=True)
        worktree = self.home / "isolated worktree"
        subprocess.run(["git", "-C", str(root), "worktree", "add", "--detach", "-q", str(worktree)], check=True)
        text = self.text(self.hook(prompt="Fix the tests", cwd=str(worktree)))
        self.assertIn("Unique ProjectX memory.", text)
        self.assertIn(str(root), text)

    def test_bash_cd_path_routes_without_running_shell_input(self):
        self.hook(prompt="Check the repository")
        command = f"cd '{self.repos['projectx']}' && touch SHOULD_NOT_EXIST"
        text = self.text(self.hook("PreToolUse", tool_name="Bash", tool_input={"command": command}))
        self.assertIn("Unique ProjectX memory.", text)
        self.assertFalse((self.repos["projectx"] / "SHOULD_NOT_EXIST").exists())

    @unittest.skipUnless(os.name == 'nt', 'Native Windows path parsing')
    def test_native_powershell_and_git_bash_drive_paths_activate_without_execution(self):
        root = self.repos['projectx']
        for tool, command in [('PowerShell', f"Set-Location '{root}'; New-Item SHOULD_NOT_EXIST"),
                              ('Bash', f'cd {str(root).replace(" ", "_")}')]:
            # Quoted paths with native backslashes and Git Bash drive syntax are both supported.
            if tool == 'Bash':
                path = '/' + root.drive[0].lower() + root.as_posix()[2:]
                command = f"cd '{path}' && touch SHOULD_NOT_EXIST"
            # One session per tool: a session shows an unchanged core only once.
            self.hook(prompt='Check repository', session_id='native-' + tool)
            text = self.text(self.hook('PreToolUse', session_id='native-' + tool, tool_name=tool, tool_input={'command':command}))
            self.assertIn('Unique ProjectX memory.', text)
            self.assertFalse((root / 'SHOULD_NOT_EXIST').exists())

    def test_bash_slashless_relative_repo_path_activates_vault(self):
        parent = self.repos["exampleapp"].parent
        for command in ["cd ExampleApp && pwd", "git -C ExampleApp status"]:
            self.hook(prompt="Check repository", cwd=str(parent), session_id=command)
            text = self.text(self.hook("PreToolUse", cwd=str(parent), session_id=command, tool_name="Bash", tool_input={"command": command}))
            self.assertIn("Unique ExampleApp memory.", text)

    def test_large_entry_points_keep_cores_and_review_commands_within_client_cap(self):
        for root in self.repos.values():
            (root / "AGENTS.md").write_text("# Rules\n" + "Large full project policy.\n" * 700)
        text = self.text(self.hook(prompt="Compare ExampleApp and ProjectX"))
        self.assertLessEqual(len(text), 10000)
        self.assertIn("Unique ExampleApp memory.", text)
        self.assertIn("Unique ProjectX memory.", text)
        self.assertIn(str(self.repos["exampleapp"] / "AGENTS.md"), text)
        self.assertEqual(text.count('by running: '), 2)

    def test_installer_preserves_settings_and_exact_backups_and_is_idempotent(self):
        settings = self.home / ".claude/settings.json"
        settings.parent.mkdir()
        original = '{"env":{"EXISTING":"keep"},"permissions":{"allow":["Read"]},"hooks":{"Stop":[{"hooks":[{"type":"command","command":"existing-hook"}]}]}}\n'
        settings.write_text(original)
        instructions = self.home / ".claude/CLAUDE.md"
        instructions.write_text("# Existing personal guidance\nKeep this.\n")
        args = ["install", "--home", str(self.home), "--id", "exampleapp", "--name", "ExampleApp", "--root", str(self.repos["exampleapp"]), "--alias", "ExampleAlias"]
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(settings.read_text())
        self.assertEqual(data["env"], {"EXISTING": "keep"})
        self.assertEqual(data["permissions"], {"allow": ["Read"]})
        self.assertEqual(data["hooks"]["Stop"][0]["hooks"][0]["command"], "existing-hook")
        self.assertTrue(any(p.read_text() == original for p in (self.config / "backups").glob("*settings.json")))
        self.assertTrue(instructions.read_text().startswith("# Existing personal guidance\nKeep this.\n"))
        before = settings.read_bytes()
        self.assertEqual(self.run_cli(*args).returncode, 0)
        self.assertEqual(settings.read_bytes(), before)
        self.assertTrue((self.config / "router.py").is_file())

    def test_duplicate_alias_registration_is_rejected_without_changing_registry(self):
        before = (self.config / "projects.json").read_bytes()
        result = self.run_cli("register", "--id", "third", "--name", "Third", "--root", str(self.repos["projectx"]), "--alias", "ExampleApp")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.config / "projects.json").read_bytes(), before)

    def test_upgrade_replaces_only_old_owned_handlers_without_duplicate_reviews(self):
        settings = self.home / '.claude/settings.json'
        settings.parent.mkdir()
        legacy = ('if [ -f "$HOME/.config/agent-memory/router.py" ]; then '
                  'python3 "$HOME/.config/agent-memory/router.py" hook; else '
                  'python3 "$(git rev-parse --show-toplevel)/scripts/agent-memory.py" hook --agent claude; fi')
        custom = {'hooks':[{'type':'command','command':'existing-hook'}]}
        settings.write_text(json.dumps({'hooks':{'UserPromptSubmit':[custom,{'hooks':[{
            'type':'command','command':legacy,'timeout':30}]}]}}))
        result=self.run_cli('install','--home',str(self.home),'--id','exampleapp','--name','ExampleApp',
                            '--root',str(self.repos['exampleapp']))
        self.assertEqual(result.returncode,0,result.stderr)
        handlers=json.loads(settings.read_text())['hooks']['UserPromptSubmit']
        self.assertEqual(len(handlers),2)
        self.assertEqual(handlers[0],custom)
        self.assertNotEqual(handlers[1]['hooks'][0]['command'],legacy)

    def test_corrupt_registry_never_falls_back_to_a_guessed_project(self):
        (self.config / "projects.json").write_text("broken")
        output = self.hook(prompt="Work on ExampleApp")
        self.assertIn("unavailable", output["systemMessage"])
        self.assertNotIn("hookSpecificOutput", output)

    def test_injected_review_command_runs_unchanged_from_home(self):
        text = self.text(self.hook(prompt="Work on ExampleApp"))
        command = text.split("by running: ", 1)[1].split(". Do not invent", 1)[0]
        result = run_review(command, cwd=self.home, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.hook("Stop"), {})

    def test_installed_shell_hook_works_from_home_and_matches_repository_handler(self):
        result = self.run_cli("install", "--home", str(self.home), "--id", "exampleapp", "--name", "ExampleApp",
                              "--root", str(self.repos["exampleapp"]), "--alias", "ExampleAlias")
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads((self.home / ".claude/settings.json").read_text())
        repo_settings = json.loads((SCRIPT.parents[1] / "templates/claude-settings.json").read_text())
        self.assertEqual(settings["hooks"], repo_settings["hooks"])
        handler = settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        result = run_hook(handler, cwd=self.home, capture_output=True, text=True,
                                env=home_env(self.home), input=json.dumps({
                                    "hook_event_name": "UserPromptSubmit", "session_id": "shell-test",
                                    "cwd": str(self.home), "prompt": "Work on ExampleAlias"}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Unique ExampleApp memory.", self.text(json.loads(result.stdout)))

    def test_similar_directory_name_does_not_activate_vault(self):
        path = self.repos["exampleapp"].with_name("ExampleApp-copy") / "README.md"
        self.assertEqual(self.hook("PreToolUse", tool_name="Read", tool_input={"file_path": str(path)}), {})

    def test_explicit_other_project_takes_precedence_over_cwd(self):
        text = self.text(self.hook(prompt="Explain ProjectX", cwd=str(self.repos["exampleapp"])))
        self.assertIn("Unique ProjectX memory.", text)
        self.assertNotIn("Unique ExampleApp memory.", text)

    def test_bash_command_words_do_not_select_unrelated_cwd_vault(self):
        fields = {"cwd": str(self.repos["exampleapp"])}
        self.hook(prompt="Explain ProjectX", **fields)
        output = self.hook("PreToolUse", tool_name="Bash", tool_input={"command":
            f"python3 '{self.repos['projectx']}/scripts/agent-memory.py' context"}, **fields)
        self.assertEqual(output, {})

    def test_unrelated_home_start_only_lists_discovery_pointers(self):
        text = self.text(self.hook("SessionStart"))
        self.assertIn(str(self.repos["exampleapp"]), text)
        self.assertNotIn("Unique ExampleApp memory.", text)
        self.assertNotIn("Unique ProjectX memory.", text)

    def test_corrupt_settings_do_not_replace_existing_instructions(self):
        settings = self.home / ".claude/settings.json"
        settings.parent.mkdir()
        settings.write_text("corrupt")
        result = self.run_cli("install", "--home", str(self.home), "--id", "exampleapp", "--name", "ExampleApp",
                              "--root", str(self.repos["exampleapp"]))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(settings.read_text(), "corrupt")
        self.assertFalse((self.config / "router.py").exists())


if __name__ == "__main__":
    unittest.main()
