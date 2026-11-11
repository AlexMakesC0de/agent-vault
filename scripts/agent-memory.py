#!/usr/bin/env python3
"""Shared project memory. Standard library only; no model calls or transcript ingestion."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import unquote
import uuid
import profile_memory as profile

from vault_runtime import configure_io, file_lock, shell_command

LIMIT = 2200
STORE = Path("docs/knowledge/memory/state.json")
CANONICAL = [".agent-vault-profile.json", "SOUL.md", "USER.md", "MEMORY.md", "docs/knowledge/memory/state.json"]
REVIEW_EVERY = 5  # A memory review is due on a session's first prompt and every fifth after it.
SPARSE = 5  # Fewer topic notes than this and the vault is a list, not a graph.
SIMILAR = 0.6  # Share of the shorter entry's content words that marks a new entry as a likely duplicate.
# Installed beside the engine; in the toolkit checkout it sits at the repository root.
SKILL_FILE = next((d / "skills/vault-knowledge/SKILL.md" for d in [Path(__file__).resolve().parent, Path(__file__).resolve().parents[1]]
                   if (d / "skills/vault-knowledge/SKILL.md").is_file()), Path(__file__).resolve().parent / "skills/vault-knowledge/SKILL.md")


def repository(start):
    result = subprocess.run(["git", "-C", str(start), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, encoding="utf-8", check=True)
    common = Path(result.stdout.strip()).resolve()
    root = common.parent
    if not (root / ".git").is_dir():
        raise ValueError("Expected a non-bare project repository with a primary checkout")
    return root


def now():
    return datetime.now(timezone.utc).isoformat()


atomic_write = profile.atomic_write

def runtime(root):
    # A vault outside any Git checkout may sit in a team sync folder; keep locks and receipts per user.
    if (root / ".git").exists() or (root / profile.PROFILE_STORE).exists():
        return root / ".memory-runtime"
    key = hashlib.sha256(os.path.normcase(str(root.resolve())).encode("utf-8")).hexdigest()[:16]
    return Path.home() / ".config/agent-memory/runtime" / key


def locked(root):
    return file_lock(runtime(root) / "write.lock")

def load(root):
    state = json.loads(profile.state_path(root).read_text(encoding="utf-8"))
    if state.get("schema") not in [1, 2] or not isinstance(state.get("revision"), int):
        raise ValueError("Unsupported memory schema; refusing to overwrite it")
    if not isinstance(state.get("entries"), list) or not isinstance(state.get("history"), list):
        raise ValueError("Invalid memory entries/history")
    if (root / profile.PROFILE_STORE).exists() and not profile.is_profile(state):
        raise ValueError("Invalid central profile scope; refusing to guess or reset it")
    if state['schema'] == 2 and state.get('scope') not in ['profile','project']:
        raise ValueError("Invalid memory scope")
    return state


def sync_conflicts(root):
    # Sync clients keep both sides of a concurrent save as a sibling copy, e.g. state-OTHERPC.json.
    copies = []
    for relative in CANONICAL:
        path = root / relative
        if not path.parent.is_dir():
            continue
        pattern = re.compile(re.escape(path.stem) + r"[ (_-].*" + re.escape(path.suffix), re.IGNORECASE)
        copies += sorted(p for p in path.parent.iterdir()
                         if p.is_file() and p.name != path.name and pattern.fullmatch(p.name))
    return copies


def conflict_notice(root):
    copies = sync_conflicts(root)
    if not copies:
        return ""
    command = shell_command([sys.executable, str(Path(__file__).resolve()), "--root", str(root), "conflicts"])
    return ("Sync conflict: another computer saved this memory at the same time and left "
            + ", ".join(str(c) for c in copies) + ". Writes to this store are blocked until it is reconciled. "
            f"List the differences with `{command}`, archive the copies by adding --archive, "
            "then re-apply each missing entry with update, citing the archived copy as source.\n")


def conflicts(root, archive=False):
    with locked(root):
        state = load(root)
        copies = sync_conflicts(root)
        active = {e["id"]: e for e in state["entries"]}
        differences = []
        for copy in copies:
            if copy.suffix.lower() != ".json":
                continue
            try:
                other = [e for e in json.loads(copy.read_text(encoding="utf-8"))["entries"] if isinstance(e, dict)]
            except (ValueError, KeyError, TypeError):
                differences.append({"copy": str(copy), "unreadable": True})
                continue
            differences.append({"copy": str(copy),
                                "only_in_copy": [e for e in other if e.get("id") not in active],
                                "changed_in_copy": [e for e in other if e.get("id") in active and
                                                    (e.get("text"), e.get("status")) !=
                                                    (active[e["id"]]["text"], active[e["id"]]["status"])]})
        archived = None
        if archive and copies:
            target = root / ".sync-conflicts" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            for copy in copies:
                destination = target / copy.relative_to(root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(copy, destination)
            archived = str(target)
    return {"root": str(root), "copies": [str(c) for c in copies], "differences": differences, "archived": archived,
            "next": ("Re-apply each needed entry with update, citing the archived copy as source. "
                     "Compare SOUL.md copies by hand." if archived else
                     "Review the differences, then run conflicts --archive." if copies else "No conflict copies.")}


def render(state, target="memory"):
    if profile.is_profile(state):
        return profile.render(state, target)
    name = state.get("project", "Project")
    if not isinstance(name, str) or not name.strip() or any(c in name for c in ['\n', '\r', '\x00']):
        raise ValueError("Invalid project identity")
    title = f"# {name} shared soul" if state["schema"] == 1 else f"# {name} project memory"
    lines = [title, "", "<!-- Generated by scripts/agent-memory.py; edit through that tool. -->", ""]
    for entry in state["entries"]:
        if entry["status"] == "active" and entry["kind"] != "inferred":
            lines.append("- " + entry["text"])
    lines += ["", "Details and evidence: [shared memory](docs/knowledge/memory/README.md).", ""]
    if state.get('legacy_soul_archive'):
        lines += ['The legacy core differed from its projection; review the exact [archived core]('+state['legacy_soul_archive']+').','']
    if state.get('previous_memory_archive'):
        lines += ['Original project notes: [preserved MEMORY.md]('+state['previous_memory_archive']+').','']
    content = "\n".join(lines)
    if len(content) > LIMIT:
        raise ValueError(f"{profile.projection(state)} would contain {len(content):,} characters; maximum is 2,200. "
                         "Consolidate or retire an entry first; all previous versions remain in history.")
    return content


KNOWLEDGE = Path("docs/knowledge")
# Vault scaffolding, not topic notes: the home map, conventions and memory maintenance.
SCAFFOLD = {"README.md", "CONVENTIONS.md"}
LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")


def topic_notes(root):
    base = root / KNOWLEDGE
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.md")
                  if not any(part.startswith(".") for part in p.relative_to(base).parts)
                  and p.relative_to(base).parts[0] != "memory"
                  and not (p.parent == base and p.name in SCAFFOLD))


def links(note):
    text = re.sub(r"```.*?```|`[^`\n]*`", "", note.read_text(encoding="utf-8"), flags=re.S)
    for target in LINK.findall(text):
        if re.match(r"[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
            continue  # External URL or same-note anchor.
        yield unquote(target.split("#", 1)[0])


def check_knowledge(root):
    """Read-only graph check: every note reachable from the home map, no broken or machine-specific links."""
    base = (root / KNOWLEDGE).resolve()
    home = base / "README.md"
    if not home.is_file():
        raise ValueError(f"No knowledge home at {home}")
    notes = topic_notes(root)
    broken, outside, reached, queue = [], [], {home}, [home]
    while queue:
        note = queue.pop()
        for target in links(note):
            path = (note.parent / target).resolve()
            label = f"{note.relative_to(base).as_posix()} -> {target}"
            if not path.exists():
                broken.append(label)
            elif not path.is_relative_to(root.resolve()):
                outside.append(label)
            elif path.suffix == ".md" and path.is_relative_to(base) and path not in reached:
                reached.add(path)
                queue.append(path)
    for note in notes:  # Unreachable notes still get their links checked.
        if note.resolve() not in reached:
            for target in links(note):
                if not (note.parent / target).resolve().exists():
                    broken.append(f"{note.relative_to(base).as_posix()} -> {target}")
    orphans = [n.relative_to(base).as_posix() for n in notes if n.resolve() not in reached]
    bare = [n.relative_to(base).as_posix() for n in notes
            if not re.match(r"---\r?\n(?:.*\r?\n)*?type:\s*\S+", n.read_text(encoding="utf-8"))]
    return {"root": str(root), "notes": len(notes), "broken_links": sorted(set(broken)), "orphans": orphans,
            "links_outside_vault": sorted(set(outside)), "missing_type_frontmatter": bare,
            "ok": not (broken or orphans or outside)}


def knowledge_pointer(root):
    home = root / KNOWLEDGE / "README.md"
    if not home.is_file():
        return ""
    count = len(topic_notes(root))
    text = (f"Knowledge map: {home}. When the task needs project detail, start there and follow links to only "
            "the notes it needs; notes are uncapped and never loaded automatically.")
    if count < SPARSE:
        text += (f" This vault has only {count} topic note(s). When working on this project, offer to build its "
                 "knowledge graph with the vault-knowledge skill"
                 + (f" ({SKILL_FILE})" if SKILL_FILE.is_file() else "") + ".")
    return text + "\n"


def context(root):
    state = load(root)
    notice = conflict_notice(root)
    if profile.is_profile(state):
        return notice + profile.context(root, state)
    core = render(state)
    projection = root / profile.projection(state)
    if not projection.exists() or projection.read_text(encoding="utf-8") != core:
        print(f"{projection.name} projection is stale; authoritative memory is intact. Run agent-memory.py render.", file=sys.stderr)
    return (f"{notice}Shared memory root: {root}\nMemory revision: {state['revision']}\n{core}{knowledge_pointer(root)}"
            + profile.near_cap([(projection.name, len(core), LIMIT)]))


STOPWORDS = set('the a an and or but of to in on for with by at from as is are was were be been it its this that these those '
                'not no never only use uses used than then so if when while into over under via per each every any all one '
                'first before after them they their there here which what who how why can will would should must may'.split())


def words(text):
    """Content words, lowercased, with a plural s dropped, for comparing two short entries."""
    return {w[:-1] if len(w) > 4 and w.endswith('s') and not w.endswith('ss') else w
            for w in re.findall(r"[a-z0-9][a-z0-9._/-]*[a-z0-9]|[a-z0-9]", text.lower()) if w not in STOPWORDS and len(w) > 2}


def similar_entries(state, text, exclude, target=None):
    """Active entries that share most of their content words with text: likely the same fact twice."""
    mine, found = words(text), []
    for entry in state["entries"]:
        if entry["status"] != "active" or entry["id"] == exclude or (target and entry.get("target", "memory") != target):
            continue
        theirs = words(entry["text"])
        shared = len(mine & theirs)
        if shared >= 4 and shared / max(1, min(len(mine), len(theirs))) >= SIMILAR:
            found.append(entry["id"])
    return found


def change(root, args):
    with locked(root):
        copies = sync_conflicts(root)
        if copies:
            raise ValueError("Sync conflict copies exist (" + ", ".join(c.name for c in copies) +
                             "); reconcile them with the conflicts command before writing")
        state = load(root)
        if state["revision"] != args.expected_revision:
            raise ValueError(f"Stale memory revision {args.expected_revision}; current revision is {state['revision']}. "
                             "Read context and reconcile before retrying.")
        if args.command == "finish-onboarding":
            if not profile.is_profile(state) or state.get("onboarding") != "pending":
                raise ValueError("No pending onboarding interview in this profile")
            if not args.source.strip():
                raise ValueError("Record what was saved or that the user skipped")
            state["onboarding"] = "done"
            state["revision"] += 1
            state["history"].append({"revision": state["revision"], "at": now(), "agent": args.agent,
                                     "action": "finish-onboarding", "source": args.source})
            atomic_write(profile.state_path(root), json.dumps(state, indent=2, ensure_ascii=False) + "\n")
            return {"revision": state["revision"], "root": str(root), "onboarding": "done"}
        if args.command == "set-soul":
            if not args.source.strip():
                raise ValueError("Identity changes require evidence")
            if not profile.is_profile(state):
                raise ValueError("Identity belongs to the central profile, not a project")
            before = (root / "SOUL.md").read_text(encoding="utf-8")
            after = profile.validate_identity(args.text)
            state["revision"] += 1
            state["history"].append({"revision": state["revision"], "at": now(), "agent": args.agent,
                                     "action": "set-soul", "source": args.source, "before": before, "after": after})
            state["soul_sha256"] = hashlib.sha256(after.encode("utf-8")).hexdigest()
            atomic_write(profile.state_path(root), json.dumps(state,indent=2,ensure_ascii=False)+"\n")
            atomic_write(root / "SOUL.md", after)
            return {"revision":state["revision"],"root":str(root),"characters":len(after)}
        existing = next((e for e in state["entries"] if e["id"] == args.id), None)
        before = deepcopy(existing)
        if args.command == "retire":
            if existing is None or existing["status"] != "active":
                raise ValueError("Cannot retire an absent or already-retired entry")
            after = {**existing, "status": "retired", "source": args.source, "updated_at": now()}
        else:
            if not args.text.strip() or any(c in args.text for c in ["\n", "\r", "\x00"]):
                raise ValueError("Memory text must be a non-empty single line")
            after = {"id": args.id, "text": args.text.strip(), "kind": args.kind,
                     "status": "active", "source": args.source, "updated_at": now()}
            if existing is None and not args.allow_similar:
                # A new id for a fact the core already holds wastes the cap and lets the copies drift apart.
                duplicates = similar_entries(state, after["text"], args.id)
                if duplicates:
                    raise ValueError("Similar active entries already exist: " + ", ".join(duplicates) +
                                     ". Update one of those ids instead, retire the older one after merging, "
                                     "or pass --allow-similar if this is a genuinely separate fact.")
        if profile.is_profile(state):
            after["target"] = getattr(args, "target", None) or (existing or {}).get("target", "memory")
        elif getattr(args,"target",None) == "user":
            raise ValueError("User preferences belong in the central profile")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,199}", args.id) or not args.source.strip():
            raise ValueError("Use a stable lowercase entry id and a non-empty evidence source")
        if existing is None:
            state["entries"].append(after)
        else:
            state["entries"][state["entries"].index(existing)] = after
        state["revision"] += 1
        state["history"].append({"revision": state["revision"], "at": now(), "agent": args.agent,
                                 "action": args.command, "before": before, "after": deepcopy(after)})
        core = render(state)  # Validate BEFORE touching persisted state.
        user = render(state, "user") if profile.is_profile(state) else None
        atomic_write(profile.state_path(root), json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        # State is authoritative. A crash here leaves a repairable stale projection, never lost history.
        if profile.is_profile(state):
            atomic_write(root / "USER.md", user)
            atomic_write(root / "MEMORY.md", core)
        else:
            atomic_write(root / profile.projection(state), core)
    result = {"revision": state["revision"], "characters": len(core), "root": str(root)}
    warning = profile.near_cap(([("USER.md", len(user), profile.LIMITS["user"])] if user is not None else [])
                               + [(profile.projection(state), len(core), LIMIT)])
    if warning:
        result["warning"] = warning.strip()
    return result


def session_path(root, session):
    key = hashlib.sha256(session.encode()).hexdigest()
    return runtime(root) / f"session-{key}.json"


def session_state(root, session):
    path = session_path(root, session)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def pending(root, session, renew=False):
    current = session_state(root, session)
    if current.get("token") and not renew:
        return current
    # Keep the revision already shown in this session; only the review receipt renews.
    value = {**current, "token": uuid.uuid4().hex, "reviewed": False, "at": now()}
    atomic_write(session_path(root, session), json.dumps(value) + "\n")
    return value


def remember_shown(root, session, revision):
    value = {**session_state(root, session), "shown": revision}
    atomic_write(session_path(root, session), json.dumps(value) + "\n")


def prompt_context(root, shown):
    """Full context once per session and after any change; a short reminder otherwise."""
    state = load(root)
    if shown != state["revision"]:
        return context(root), state["revision"]
    kind = "Central profile" if profile.is_profile(state) else "Project memory"
    return (conflict_notice(root) + f"{kind} {root} is unchanged at revision {state['revision']}; "
            "it was loaded earlier in this session."), state["revision"]


def review_instruction(root, session, token, agent):
    shell = 'bash' if agent == 'claude' else 'powershell'
    engine = str(Path(__file__).resolve())
    command = shell_command([sys.executable, engine, "--root", str(root), "review",
                             "--session", session, "--token", token], shell=shell)
    update = shell_command([sys.executable, engine, "--root", str(root), "update", "--help"], shell=shell)
    location = ('Put user preferences in USER.md, general lessons in MEMORY.md, and identity changes in SOUL.md through set-soul. '
                + ('Put longer general detail in a note linked from notes/README.md, with a one-line pointer in the core. '
                   if (root / profile.NOTES).is_file() else '')
                if (root/profile.PROFILE_STORE).exists() else
                f'Read {root / "docs/knowledge/CONVENTIONS.md"}. Keep project facts in this vault and user preferences in the central profile. ')
    return ("Before your final response, review the work since your last memory review for durable explicit preferences, corrections, "
            "and verified workflow lessons. " + location + "Update shared memory only when useful; the exact update command is `"
            + update + "`. Keep guesses kind=inferred, and preserve history. "
            "Save technical detail in the appropriate knowledge note instead of the core. "
            "Then record that review, including a no-change review, by running: " + command +
            ". Do not invent a learning to satisfy this check. Do not claim a save without a successful tool result.")


def hook(root, payload, agent):
    event = payload.get("hook_event_name")
    session = payload.get("session_id")
    if event in ["SessionStart", "SubagentStart"]:
        text = context(root)
        # A worker's context is its own; the main conversation has not seen it.
        if event == "SessionStart" and isinstance(session, str) and session and not payload.get("agent_id"):
            with locked(root):
                remember_shown(root, session, load(root)["revision"])
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}
    if event not in ["UserPromptSubmit", "Stop"]:
        return {}
    if not isinstance(session, str) or not session:
        return {"systemMessage": "Project memory review not recorded: hook payload has no session_id."}
    with locked(root):
        if event == "UserPromptSubmit":
            text, revision = prompt_context(root, session_state(root, session).get("shown"))
            remember_shown(root, session, revision)
            current = session_state(root, session)
            prompts = current.get("prompts", 0) + 1
            atomic_write(session_path(root, session), json.dumps({**current, "prompts": prompts}) + "\n")
            if current.get("token") and not current.get("reviewed"):
                state = current  # An earlier review is still owed; its token stays valid.
            elif (prompts - 1) % REVIEW_EVERY == 0:
                state = pending(root, session, renew=True)
            else:
                return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}
            return {"hookSpecificOutput": {"hookEventName": event, "additionalContext":
                    text + "\n" + review_instruction(root, session, state["token"], agent)}}
        state = session_state(root, session) or None
        if state and state.get("reviewed"):
            return {}
        if payload.get("stop_hook_active"):
            return {"systemMessage": "Project memory review not recorded; continuation limit reached. "
                    "Memory was not marked reviewed and no learning was fabricated."}
        state = pending(root, session)
        return {"decision": "block", "reason": review_instruction(root, session, state["token"], agent)}


def main():
    configure_io()
    parser = argparse.ArgumentParser(description=__doc__)
    roots = parser.add_mutually_exclusive_group()
    roots.add_argument("--root", type=Path, help="Explicit project store root")
    roots.add_argument("--profile", type=Path, help="Central shared profile root")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ["context", "status", "render", "init-profile", "check-knowledge"]:
        commands.add_parser(name)
    for name in ["update", "retire", "set-soul", "finish-onboarding"]:
        command = commands.add_parser(name)
        if name in ["update", "retire"]:
            command.add_argument("--id", required=True)
        command.add_argument("--source", required=True)
        command.add_argument("--agent", choices=["codex", "claude", "human", "other"], required=True)
        command.add_argument("--expected-revision", type=int, required=True)
        if name == "set-soul":
            command.add_argument("--text", required=True)
        if name == "update":
            command.add_argument("--target", choices=["user","memory"])
            command.add_argument("--text", required=True)
            command.add_argument("--kind", choices=["identity", "explicit", "observed", "inferred"], required=True)
            command.add_argument("--allow-similar", action="store_true",
                                 help="Add a new entry even though an active entry shares most of its words")
    command = commands.add_parser("review")
    command.add_argument("--session", required=True)
    command.add_argument("--token", required=True)
    command = commands.add_parser("conflicts")
    command.add_argument("--archive", action="store_true")
    command = commands.add_parser("hook")
    command.add_argument("--agent", choices=["codex", "claude"], required=True)
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin) if args.command == "hook" else None
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("Hook payload must be an object")
        start = Path(payload.get("cwd") or Path.cwd()) if payload else Path.cwd()
        root = (args.profile or args.root).resolve() if (args.profile or args.root) else repository(start)
        if args.command == "init-profile":
            if not args.profile:
                raise ValueError("Use --profile ROOT init-profile for an explicit central profile")
            with locked(root):
                state = profile.init(root)
            print(json.dumps({"root":str(root),"revision":state["revision"]}))
            return 0
        if args.profile and not (root / profile.PROFILE_STORE).is_file():
            raise ValueError("Central profile unavailable; initialize or restore it explicitly")
        if args.command == "context":
            print(context(root))
        elif args.command == "check-knowledge":
            result = check_knowledge(root)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result["ok"] else 1
        elif args.command == "status":
            state = load(root)
            core = render(state)
            sizes, limits = {"memory": len(core)}, {"memory": LIMIT}
            if profile.is_profile(state):
                sizes["user"], limits["user"] = len(render(state, "user")), profile.LIMITS["user"]
            warning = profile.near_cap([(name, sizes[name], limits[name]) for name in sizes])
            print(json.dumps({"root": str(root), "revision": state["revision"], "characters": len(core),
                              "sizes": sizes, "limits": limits, "warning": warning.strip() or None,
                              "entries": state["entries"]}, ensure_ascii=False))
        elif args.command == "render":
            with locked(root):
                state = load(root)
                if profile.is_profile(state):
                    for target,name in [("user","USER.md"),("memory","MEMORY.md")]:
                        atomic_write(root/name,render(state,target))
                else:
                    atomic_write(root / profile.projection(state), render(state))
            print("Memory projections repaired from authoritative state; canonical identity preserved")
        elif args.command in ["update", "retire", "set-soul", "finish-onboarding"]:
            print(json.dumps(change(root, args)))
        elif args.command == "conflicts":
            print(json.dumps(conflicts(root, args.archive), ensure_ascii=False))
        elif args.command == "review":
            with locked(root):
                path = session_path(root, args.session)
                state = json.loads(path.read_text(encoding='utf-8'))
                if state["token"] != args.token:
                    raise ValueError("Stale review token: this receipt belongs to another turn")
                state.update(reviewed=True, reviewed_at=now())
                atomic_write(path, json.dumps(state) + "\n")
            print("Memory review recorded; a review alone does not add or change memories")
        else:
            print(json.dumps(hook(root, payload, args.agent), ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"Project memory: {error}", file=sys.stderr)
        if args.command == "hook":
            print(json.dumps({"systemMessage": f"Project shared memory unavailable: {error}. "
                              "Do not claim memory was loaded, learned, or reviewed."}))
            return 0  # Memory maintenance must not trap the user's coding session.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
