"""Filesystem integration tests: run with python3 -m unittest discover -s scripts/tests."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from platform_helpers import home_env, run_hook, run_review


SCRIPT = Path(__file__).resolve().parents[1] / "agent-memory.py"


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".git").mkdir()  # a repository vault keeps its runtime inside the checkout
        self.store = self.root / "docs/knowledge/memory/state.json"
        self.store.parent.mkdir(parents=True)
        self.store.write_text(json.dumps({"schema": 1, "revision": 0, "entries": [], "history": []}))

    def run_cli(self, *args, payload=None):
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args],
                              input=json.dumps(payload) if payload is not None else None,
                              capture_output=True, text=True)

    def update(self, text="The user requires preservation.", revision="0", kind="explicit", key="preserve"):
        return self.run_cli("update", "--id", key, "--text", text, "--source", "user:2026-10-18",
                            "--agent", "codex", "--kind", kind, "--expected-revision", revision)

    def state(self):
        return json.loads(self.store.read_text())

    def knowledge(self, files):
        base = self.root / "docs/knowledge"
        for name, text in files.items():
            (base / name).parent.mkdir(parents=True, exist_ok=True)
            (base / name).write_text(text, encoding="utf-8")
        result = self.run_cli("check-knowledge")
        return result.returncode, json.loads(result.stdout)

    def test_check_knowledge_accepts_a_linked_graph(self):
        note = "---\ntype: reference\n---\n# {0}\nUp: [Backend](README.md)\n"
        code, report = self.knowledge({
            "README.md": "# Home\n- [Backend](backend/README.md)\n- [Docs](https://example.test/x)\n",
            "backend/README.md": "---\ntype: map\n---\n- [Auth](auth-flow.md)\n- [Data](data%20model.md#tables)\n",
            "backend/auth-flow.md": note.format("Auth") + "Uses the [data model](data%20model.md).\n",
            "backend/data model.md": note.format("Data") + "`[not a link](missing.md)`\n",
            "memory/archive.md": "Archived source, not a topic note.\n"})
        self.assertEqual(code, 0, report)
        self.assertEqual((report["notes"], report["broken_links"], report["orphans"]), (3, [], []))

    def test_check_knowledge_reports_broken_orphan_outside_and_bare_notes(self):
        # A sibling temp folder: same drive on Windows; resolved for macOS's /var -> /private/var link.
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        target = Path(other.name).resolve() / "elsewhere.md"
        target.write_text("Outside the vault.\n", encoding="utf-8")
        area = (self.root / "docs/knowledge/area").resolve()
        repo_file = os.path.relpath(target, area).replace(os.sep, "/")
        code, report = self.knowledge({
            "README.md": "# Home\n- [Area](area/README.md)\n",
            "area/README.md": "- [Planned](planned.md)\n- [Repo](" + repo_file + ")\n",
            "area/lonely.md": "---\ntype: lesson\n---\nLinks to [gone](gone.md).\n"})
        self.assertEqual(code, 1)
        self.assertEqual(report["broken_links"], ["area/README.md -> planned.md", "area/lonely.md -> gone.md"])
        self.assertEqual(report["orphans"], ["area/lonely.md"])
        self.assertEqual(len(report["links_outside_vault"]), 1)
        self.assertEqual(report["missing_type_frontmatter"], ["area/README.md"])

    def test_context_points_to_knowledge_map_and_flags_a_sparse_vault(self):
        self.assertEqual(self.update().returncode, 0)
        base = self.root / "docs/knowledge"
        (base / "README.md").write_text("# Home\n", encoding="utf-8")
        text = self.run_cli("context").stdout
        self.assertIn(str(base.resolve() / "README.md"), text)
        self.assertIn("only 0 topic note(s)", text)
        for index in range(5):
            (base / f"topic-{index}.md").write_text("---\ntype: reference\n---\n", encoding="utf-8")
        self.assertNotIn("topic note(s)", self.run_cli("context").stdout)

    def test_update_persists_core_and_evidence(self):
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("The user requires preservation.", (self.root / "SOUL.md").read_text())
        self.assertEqual(self.state()["entries"][0]["source"], "user:2026-10-18")
        self.assertEqual(self.state()["revision"], 1)

    def test_retirement_preserves_previous_content_and_history(self):
        self.assertEqual(self.update().returncode, 0)
        result = self.run_cli("retire", "--id", "preserve", "--source", "user:changed", "--agent", "claude",
                              "--expected-revision", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("The user requires preservation.", (self.root / "SOUL.md").read_text())
        self.assertEqual(self.state()["entries"][0]["text"], "The user requires preservation.")
        self.assertEqual(self.state()["entries"][0]["status"], "retired")
        self.assertEqual(self.state()["history"][-1]["before"]["text"], "The user requires preservation.")

    def test_overflow_leaves_authoritative_state_unchanged(self):
        before = self.store.read_bytes()
        result = self.update("😀" * 2201)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("2,200", result.stderr)
        self.assertEqual(self.store.read_bytes(), before)

    def test_stale_writer_cannot_overwrite_new_learning(self):
        self.assertEqual(self.update().returncode, 0)
        before = self.store.read_bytes()
        result = self.update("Different instruction.")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("revision", result.stderr)
        self.assertEqual(self.store.read_bytes(), before)

    def test_inferences_stay_outside_core(self):
        result = self.update("Maybe The user likes short answers.", kind="inferred")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Maybe The user", (self.root / "SOUL.md").read_text())
        self.assertIn("Maybe The user", self.store.read_text())

    def test_concurrent_writers_do_not_lose_updates_silently(self):
        with concurrent.futures.ThreadPoolExecutor() as pool:
            results = list(pool.map(lambda key: self.update(key=key), ["first", "second"]))
        self.assertEqual(sorted(r.returncode for r in results), [0, 1])
        self.assertEqual(self.state()["revision"], 1)
        self.assertEqual(len(self.state()["history"]), 1)

    def test_context_recovers_from_stale_projection_without_losing_history(self):
        self.assertEqual(self.update().returncode, 0)
        (self.root / "SOUL.md").write_text("stale")
        result = self.run_cli("context")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("The user requires preservation.", result.stdout)
        self.assertIn("projection", result.stderr)
        repair = self.run_cli("render")
        self.assertEqual(repair.returncode, 0, repair.stderr)
        self.assertEqual(len(self.state()["history"]), 1)
        self.assertIn("The user requires preservation.", (self.root / "SOUL.md").read_text())

    def prompt(self, session="session-a"):
        result = self.run_cli("hook", "--agent", "claude", payload={
            "hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": "Do work"})
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    def stop_blocks(self, session="session-a"):
        result = self.run_cli("hook", "--agent", "claude", payload={
            "hook_event_name": "Stop", "session_id": session, "stop_hook_active": False})
        return json.loads(result.stdout).get("decision") == "block"

    def receipt(self):
        return json.loads(next((self.root / ".memory-runtime").glob("session-*.json")).read_text())

    def test_review_is_due_on_the_first_prompt_and_every_fifth_after(self):
        self.assertIn("Before your final response", self.prompt())
        self.assertTrue(self.stop_blocks())
        done = self.run_cli("review", "--session", "session-a", "--token", self.receipt()["token"])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(self.stop_blocks())
        self.assertEqual(self.state()["revision"], 0)
        for _ in range(4):  # Prompts 2-5: context only, no instruction, Stop passes.
            self.assertNotIn("Before your final response", self.prompt())
            self.assertFalse(self.stop_blocks())
        self.assertIn("Before your final response", self.prompt())  # Prompt 6.
        self.assertTrue(self.stop_blocks())

    def test_a_missed_review_stays_due_with_the_same_token(self):
        self.prompt()
        token = self.receipt()["token"]
        self.assertIn(token, self.prompt())
        self.assertTrue(self.stop_blocks())
        self.assertEqual(self.run_cli("review", "--session", "session-a", "--token", token).returncode, 0)

    def test_stop_continuation_does_not_loop_and_reports_missed_review(self):
        result = self.run_cli("hook", "--agent", "codex", payload={
            "hook_event_name": "Stop", "session_id": "session-a", "stop_hook_active": True})
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertNotIn("decision", data)
        self.assertIn("not recorded", data["systemMessage"])

    def test_old_review_token_cannot_mark_a_new_review_window_reviewed(self):
        self.prompt("same-session")
        old_token = self.receipt()["token"]
        self.run_cli("review", "--session", "same-session", "--token", old_token)
        for _ in range(5):
            self.prompt("same-session")
        self.assertNotEqual(self.receipt()["token"], old_token)
        result = self.run_cli("review", "--session", "same-session", "--token", old_token)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.receipt()["reviewed"])

    def test_context_status_and_update_warn_near_the_cap(self):
        self.assertNotIn("move detail to a linked note", self.run_cli("context").stdout)
        long = self.update(text="x" * 1900)
        self.assertEqual(long.returncode, 0, long.stderr)
        self.assertIn("2,200", json.loads(long.stdout)["warning"])
        self.assertIn("Near the cap: SOUL.md ", self.run_cli("context").stdout)
        status = json.loads(self.run_cli("status").stdout)
        self.assertEqual(status["limits"]["memory"], 2200)
        self.assertIn("memory ", status["warning"])

    def test_codex_emitted_review_command_runs_in_native_target_shell(self):
        scripts = self.root / 'scripts'
        scripts.mkdir()
        for name in ['agent-memory.py','vault_runtime.py','profile_memory.py']:
            shutil.copyfile(SCRIPT.with_name(name), scripts / name)
        result = self.run_cli('hook','--agent','codex',payload={
            'hook_event_name':'UserPromptSubmit','session_id':'codex-native'})
        text = json.loads(result.stdout)['hookSpecificOutput']['additionalContext']
        command = text.split('by running: ',1)[1].split('. Do not invent',1)[0]
        result = run_review(command,agent='codex',cwd=self.root,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        output = self.run_cli('hook','--agent','codex',payload={
            'hook_event_name':'Stop','session_id':'codex-native'})
        self.assertEqual(json.loads(output.stdout),{})

    def test_corrupt_state_is_reported_without_resetting_or_claiming_learning(self):
        self.store.write_text("corrupted")
        result = self.run_cli("hook", "--agent", "claude", payload={"hook_event_name": "SessionStart"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("unavailable", json.loads(result.stdout)["systemMessage"])
        self.assertEqual(self.store.read_text(), "corrupted")

    def test_configured_shell_commands_load_memory_from_nested_directory_with_spaces(self):
        # Exercise shipped command paths and payloads, not merely config string contents.
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        scripts = self.root / "scripts"
        scripts.mkdir()
        shutil.copyfile(SCRIPT, scripts / SCRIPT.name)
        shutil.copyfile(SCRIPT.with_name("vault_runtime.py"), scripts / "vault_runtime.py")
        shutil.copyfile(SCRIPT.with_name("profile_memory.py"), scripts / "profile_memory.py")
        nested = self.root / "nested directory" / "child"
        nested.mkdir(parents=True)
        self.assertEqual(self.update().returncode, 0)
        repo = SCRIPT.parents[1]
        for config in [repo / "templates/codex-hooks.json", repo / "templates/claude-settings.json"]:
            handler = json.loads(config.read_text())["hooks"]["SessionStart"][0]["hooks"][0]
            result = run_hook(handler, cwd=nested, text=True, capture_output=True,
                                    env=home_env(self.root),
                                    input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(nested)}))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("The user requires preservation.", json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_session_start_injects_fresh_state_for_both_agents(self):
        self.assertEqual(self.update().returncode, 0)
        for agent in ["claude", "codex"]:
            result = self.run_cli("hook", "--agent", agent, payload={"hook_event_name": "SessionStart"})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("The user requires preservation.", json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_worktree_resolves_same_store_as_primary_checkout(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.test",
                        "commit", "--allow-empty", "-qm", "initial"], check=True)
        worktree = self.root / "separate"
        subprocess.run(["git", "-C", str(self.root), "worktree", "add", "--detach", "-q", str(worktree)], check=True)
        self.assertEqual(self.update().returncode, 0)
        result = subprocess.run([sys.executable, str(SCRIPT), "context"], cwd=worktree, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("The user requires preservation.", result.stdout)
        reported = Path(result.stdout.splitlines()[0].split(': ', 1)[1])
        self.assertTrue(reported.samefile(self.root))


if __name__ == "__main__":
    unittest.main()
