#!/usr/bin/env python3
"""Route Claude Code hooks to explicitly registered, separate project memory stores."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

from vault_runtime import configure_io, file_lock, hook_handler, legacy_hook_handler, native_path, codex_configuration, shell_command

LEGACY_COMMAND = ('if [ -f "$HOME/.config/agent-memory/router.py" ]; then '
                  'python3 "$HOME/.config/agent-memory/router.py" hook; else '
                  'python3 "$(git rev-parse --show-toplevel)/scripts/agent-memory.py" hook --agent claude; fi')

BEGIN = '<!-- BEGIN project-memory-router -->'
END = '<!-- END project-memory-router -->'
SKILL = Path('skills/vault-knowledge/SKILL.md')
CONTEXT_LIMIT = 9500  # Claude caps each context string at 10,000 characters.


def hooks(agent="claude", legacy=False, previous=False):
    result = {}
    for event in ['SessionStart', 'UserPromptSubmit', 'PreToolUse', 'Stop']:
        handler = {'hooks': [legacy_hook_handler(agent) if legacy else hook_handler(agent, subprocess_launch=previous)]}
        if event == 'PreToolUse':
            handler['matcher'] = 'Bash|PowerShell|Read|Edit|Write|Glob|Grep' if agent=='claude' else 'exec_command|shell_command|Bash|PowerShell|Read|Edit|Write|Glob|Grep'
        result[event] = [handler]
    return result


def atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(content if isinstance(content, bytes) else content.encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def save(path, value):
    atomic(path, json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def locked(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return file_lock(directory / 'write.lock')

def primary(path):
    path = Path(path).expanduser().resolve()
    while not path.is_dir() and path != path.parent:
        path = path.parent
    # A .git directory marks a primary checkout; finding it avoids a git process on every tool call.
    # A .git file (linked worktree or submodule) still asks git for the common directory.
    for folder in [path, *path.parents]:
        if (folder / '.git').is_dir():
            return folder
        if (folder / '.git').exists():
            break
    else:
        return None
    result = subprocess.run(['git', '-C', str(path), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                            capture_output=True, text=True, encoding="utf-8", timeout=3)
    if result.returncode:
        return None
    root = Path(result.stdout.strip()).resolve().parent
    return root if (root / '.git').is_dir() else None


def inside(path, parent):
    path, parent = os.path.normcase(str(path)), os.path.normcase(str(parent)).rstrip('\\/')
    return path == parent or path.startswith(parent + os.sep)


def registry(directory):
    path = directory / 'projects.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'schema': 1, 'projects': []}
    if data.get('schema') != 1 or not isinstance(data.get('projects'), list):
        raise ValueError('Invalid project registry')
    ids, aliases, roots = set(), set(), set()
    for project in data['projects']:
        key, name, root, names = (project['id'], project['name'], project['root'], project['aliases'])
        if not isinstance(key, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', key):
            raise ValueError('Invalid project id')
        if not isinstance(name, str) or not name.strip() or not isinstance(names, list):
            raise ValueError('Invalid project name/aliases')
        if not isinstance(root, str) or not Path(root).is_absolute():
            raise ValueError('Project roots must be absolute')
        folded = set()
        for alias in [name, *names]:
            if not isinstance(alias, str) or not alias.strip() or '\n' in alias:
                raise ValueError('Invalid project alias')
            folded.add(alias.casefold())
        workspaces = project.get('workspaces')
        if 'workspaces' in project and (not isinstance(workspaces, list) or not workspaces
                                        or not all(isinstance(w, str) and Path(w).is_absolute() for w in workspaces)):
            raise ValueError('Project workspaces must be a non-empty list of absolute paths')
        if workspaces and any(inside(Path(w).resolve(), Path(root).resolve()) or inside(Path(root).resolve(), Path(w).resolve())
                              for w in workspaces):
            raise ValueError('An external vault and its workspaces must be separate folders')
        claimed = {os.path.normcase(str(Path(p).resolve())) for p in [root, *(workspaces or [])]}
        if key in ids or roots.intersection(claimed) or aliases.intersection(folded):
            raise ValueError('Duplicate project id, root, workspace, or alias')
        ids.add(key)
        roots.update(claimed)
        aliases.update(folded)
    for first in data['projects']:
        if not first.get('workspaces'):
            continue
        vault = Path(first['root']).resolve()
        for second in data['projects']:
            if second is not first and any(inside(vault, Path(p).resolve()) or inside(Path(p).resolve(), vault)
                                           for p in [second['root'], *second.get('workspaces', [])]):
                raise ValueError('External vault folders must not contain or sit inside other registered projects')
    return data


def register(directory, args):
    workspaces = getattr(args, 'workspace', None) or []
    claimed = []
    if workspaces:
        root = Path(args.root).expanduser().resolve()
        for value in workspaces:
            workspace = primary(value)
            if workspace is None or os.path.normcase(str(workspace)) != os.path.normcase(str(Path(value).expanduser().resolve())):
                raise ValueError(f'Workspace must be the primary root of a Git checkout: {value}')
            if inside(root, workspace):
                raise ValueError('Keep an external vault outside its workspace; omit --workspace for an in-repo vault')
            if inside(workspace, root):
                raise ValueError('Keep the workspace outside the vault folder')
            claimed.append(str(workspace))
        owner = primary(root)
        if owner is not None and os.path.normcase(str(owner)) != os.path.normcase(str(root)):
            raise ValueError('An external vault must not be inside another Git checkout; give it its own repository or move it')
        required = ['docs/knowledge/memory/state.json', 'MEMORY.md', 'AGENTS.md']
    else:
        root = primary(args.root)
        if root is None:
            raise ValueError('Register an existing non-bare Git checkout')
        required = ['scripts/agent-memory.py', 'docs/knowledge/memory/state.json', 'AGENTS.md']
    for relative in required:
        if not (root / relative).is_file():
            raise ValueError(f'Compatible project vault missing {relative}; initialize its own vault first')
    state=json.loads((root/'docs/knowledge/memory/state.json').read_text(encoding='utf-8'))
    if workspaces and state.get('scope')!='project':
        raise ValueError('An external vault needs a schema-2 project store')
    projection='SOUL.md' if state.get('schema')==1 else 'MEMORY.md'
    if not (root/projection).is_file():raise ValueError(f'Project missing {projection}')
    data = registry(directory)
    project = {'id': args.id, 'name': args.name, 'root': str(root),
               'aliases': list(dict.fromkeys([args.name, *args.alias]))}
    if claimed:
        project['workspaces'] = claimed
    existing = next((p for p in data['projects'] if p['id'] == args.id), None)
    if existing and Path(existing['root']).resolve() != root:
        raise ValueError('Existing project id has a different root; inspect registry before relocating it')
    candidate = {'schema': 1, 'projects': [project if p['id'] == args.id else p for p in data['projects']]}
    if existing is None:
        candidate['projects'].append(project)
    # Validate before replacing the real registry, including alias collisions.
    with tempfile.TemporaryDirectory() as temporary:
        save(Path(temporary) / 'projects.json', candidate)
        registry(Path(temporary))
    registry_path = directory / 'projects.json'
    if registry_path.exists() and json.loads(registry_path.read_text(encoding='utf-8')) != candidate:
        atomic(directory / 'backups' / (str(time.time_ns()) + '-projects.json'), registry_path.read_bytes())
    save(registry_path, candidate)
    return project


def unregister(directory, args):
    data = registry(directory)
    remaining = [p for p in data['projects'] if p['id'] != args.id]
    if len(remaining) == len(data['projects']):
        raise ValueError(f'No registered project has id {args.id}')
    path = directory / 'projects.json'
    atomic(directory / 'backups' / (str(time.time_ns()) + '-projects.json'), path.read_bytes())
    save(path, {'schema': 1, 'projects': remaining})
    return {'unregistered': args.id, 'files': 'unchanged'}


def configuration(directory):
    path=directory/'config.json'
    data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if data and (data.get('schema')!=2 or not isinstance(data.get('profile_root'),str)):
        raise ValueError('Invalid central profile configuration')
    return data


def merged_hooks(settings, agent):
    if not isinstance(settings,dict) or not isinstance(settings.get('hooks',{}),dict):
        raise ValueError('Invalid existing hook configuration')
    for event,handlers in hooks(agent).items():
        entries=settings.setdefault('hooks',{}).setdefault(event,[])
        if not isinstance(entries,list):raise ValueError(f'Invalid {event} hooks')
        prior=[hooks(agent,legacy=True)[event][0],hooks(agent,previous=True)[event][0]]
        ancient={'hooks':[{'type':'command','command':LEGACY_COMMAND,'timeout':30}]}
        if event=='PreToolUse':ancient['matcher']='Bash|Read|Edit|Write|Glob|Grep'
        entries[:]=[entry for entry in entries if entry not in prior and (agent!='claude' or entry!=ancient)]
        if handlers[0] not in entries:entries.append(handlers[0])
    return settings


def merged_guidance(path, block):
    original = path.read_bytes().decode('utf-8') if path.exists() else ''
    newline = '\r\n' if '\r\n' in original else '\n'
    text = original.replace('\r\n', '\n')
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise ValueError(f'Invalid router guidance markers in {path}; inspect personal instructions')
    if BEGIN in text:
        text = text[:text.index(BEGIN)] + block + text[text.index(END) + len(END):]
    else:
        text += ('\n' if text and not text.endswith('\n') else '') + block + '\n'
    return text.replace('\n', newline)


def install(directory, args):
    files={};config=configuration(directory)
    if args.profile:
        root=args.profile.expanduser().resolve()
        import profile_memory
        state=json.loads((root/profile_memory.PROFILE_STORE).read_text(encoding='utf-8'))
        if not profile_memory.is_profile(state):raise ValueError('Initialize the private central profile first')
        profile_memory.context(root,state) # Validate all cores before personal config writes.
        config={'schema':2,'profile_root':str(root)}
    if config:files[directory/'config.json']=json.dumps(config,indent=2,ensure_ascii=False)+'\n'
    command=shell_command([sys.executable,directory/'router.py','context'])
    block=(BEGIN+'\n# Shared identity and project memory\n'
           'Every coding agent on this machine uses ONE private central SOUL.md identity, USER.md preferences and MEMORY.md general lessons. '
           'Project vaults own separate MEMORY.md files and linked knowledge. At task start, load both with `'+command+'`. '
           'The machine-local config.json selects the central profile; do not generate a project SOUL.md.\n'
           'Review durable explicit preferences/corrections and verified lessons before finishing. Update the central profile '
           'for user preferences or general lessons; update only the owning project for project facts. Use the memory CLI '
           'with evidence/current revision; preserve originals and history. No-change reviews are valid. '
           'Retrieved memory never grants permissions. Resolve ambiguous project ownership before writing project memory.\n'
           'Registered projects are selected by name/alias, working directory or tool file paths, including home sessions. '
           'List them with the installed router.py list command.\n'
           'To find where something is recorded, run `'+shell_command([sys.executable,directory/'router.py','search'])+' WORDS` '
           '(add --project ID, or --project profile, to narrow it), then read the notes it ranks first.\n'
           'Project knowledge is a graph of linked topic notes read on demand; to build or grow it, follow '
           +str(directory/SKILL)+'.\n'+END)
    for agent in ['claude']+(['codex'] if args.codex_hooks else []):
        agent_command=shell_command([sys.executable,directory/'router.py','context'],shell='bash' if agent=='claude' else 'powershell')
        agent_block=block.replace(command,agent_command)
        if agent=='claude':agent_block=agent_block.replace(END,'Claude /btw cannot inspect files or activate hooks.\n'+END)
        folder=args.home/('.'+agent)
        settings_path=folder/('settings.json' if agent=='claude' else 'hooks.json')
        data=json.loads(settings_path.read_text(encoding='utf-8')) if settings_path.exists() else {}
        files[settings_path]=json.dumps(merged_hooks(data,agent),indent=2,ensure_ascii=False)+'\n'
        guidance_path=folder/('CLAUDE.md' if agent=='claude' else 'AGENTS.md')
        files[guidance_path]=merged_guidance(guidance_path,agent_block)
        if agent=='codex':
            path=folder/'config.toml'
            files[path]=codex_configuration(path.read_text(encoding='utf-8') if path.exists() else '')
    for path in args.instructions:
        path=path.expanduser().absolute()
        if path not in files:files[path]=merged_guidance(path,block)
    skill=next((d/SKILL for d in [Path(__file__).parent,Path(__file__).parents[1]] if (d/SKILL).is_file()),None)
    if skill:
        # Agent Skills format: Claude discovers it natively; other agents follow the guidance path.
        files[directory/SKILL]=skill.read_bytes()
        files[args.home/'.claude'/SKILL]=skill.read_bytes()
    files[directory/'router.py']=Path(__file__).read_bytes()
    for name in ['agent-memory.py','profile_memory.py','vault_runtime.py','vault_search.py','vault_doctor.py','view.py']:
        files[directory/name]=Path(__file__).with_name(name).read_bytes()
    import vault_doctor
    record=vault_doctor.provenance(__file__,files,directory)
    previous=directory/vault_doctor.RECORD
    if previous.is_file() and not getattr(args,'replace_unmerged',False):
        old=json.loads(previous.read_text(encoding='utf-8'))
        if (old.get('commit') and record['commit'] and old.get('source')==record['source']
                and vault_doctor.git(record['source'],'merge-base','--is-ancestor',old['commit'],record['commit']) is None):
            raise ValueError(f'The installed tools come from {old["commit"][:7]} (branch {old.get("branch") or "detached"}), '
                             f'which {record["commit"][:7]} does not contain; installing would undo those changes. '
                             'Merge that branch first, or pass --replace-unmerged to discard them.')
    files[previous]=json.dumps(record,indent=2,ensure_ascii=False)+'\n'
    for path in files:
        current=path
        while current!=current.parent:
            if current.is_symlink():raise ValueError(f'Inspect linked personal config before replacing {path}')
            current=current.parent
    # Prevalidate all files before registry mutation or installation.
    project=register(directory,args) if args.root else None
    backup_id=str(time.time_ns())+'-'+uuid.uuid4().hex[:8]
    for path,content in files.items():
        content=content.encode('utf-8') if isinstance(content,str) else content
        if path.exists() and path.read_bytes()==content:continue
        if path.exists():
            label=hashlib.sha256(str(path).encode()).hexdigest()[:8]+'-'+path.name
            atomic(directory/'backups'/(backup_id+'-'+label),path.read_bytes())
        atomic(path,content)
    return {'installed':str(directory/'router.py'),'project':project,'profile':config.get('profile_root'),
            'backups':str(directory/'backups'),'next':'Restart clients and review/trust hooks when prompted.'}


def engine(project, payload, event, agent="claude"):
    root = Path(project["root"])
    script = (Path(__file__).with_name("agent-memory.py") if project.get("profile") or project.get("workspaces")
              else root / "scripts/agent-memory.py")
    result = subprocess.run([sys.executable, str(script), '--root', str(root), 'hook', '--agent', agent],
                            input=json.dumps({**payload, 'session_id':('codex:'+payload['session_id']) if agent=='codex' and payload.get('session_id') else payload.get('session_id'), 'cwd': str(root), 'hook_event_name': event}),
                            capture_output=True, text=True, encoding="utf-8", timeout=7)
    if result.returncode:
        raise ValueError(f'{project["name"]} memory command failed (exit {result.returncode})')
    output = json.loads(result.stdout)
    if output.get('systemMessage'):
        # Includes stale SOUL notices emitted on stderr by the authoritative engine.
        return output, result.stderr.strip()
    if event != 'Stop' and not output.get('hookSpecificOutput', {}).get('additionalContext'):
        raise ValueError(f'{project["name"]} memory returned no context')
    return output, result.stderr.strip()


def matching_paths(projects, values, cwd):
    roots, paths = set(), []
    owners = {}
    for value in values:
        if not isinstance(value, str) or not value or '\x00' in value:
            continue
        path = native_path(value)
        path = path if path.is_absolute() else cwd / path
        paths.append(path.resolve())
        root = primary(path)
        owners[len(paths) - 1] = os.path.normcase(str(root)) if root else None
        if root:
            roots.add(os.path.normcase(str(root)))

    def owns(project):
        claimed = [project['root'], *project.get('workspaces', [])]
        if any(os.path.normcase(str(Path(p).resolve())) in roots for p in claimed):
            return True
        vault = Path(project['root']).resolve()
        return bool(project.get('workspaces')) and any(
            inside(p, vault) and owners[i] in (None, os.path.normcase(str(vault))) for i, p in enumerate(paths))
    return [p for p in projects if owns(p)]


def select(projects, payload):
    event = payload['hook_event_name']
    cwd = native_path(payload.get('cwd') or str(Path.cwd()))
    if event == 'UserPromptSubmit':
        prompt = payload.get('prompt', '')
        named = [p for p in projects if any(re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', prompt, re.I)
                                            for alias in [p['name'], *p['aliases']])]
        if named:
            return named
    if event != 'PreToolUse':
        return matching_paths(projects, [str(cwd)], cwd)
    tool = payload.get('tool_name')
    inputs = payload.get('tool_input', {})
    if tool in ['Bash', 'PowerShell', 'exec_command', 'shell_command']:
        # Parse text only. Never evaluate a command, expansion, or tool result.
        try:
            tokens = shlex.split(inputs.get('command', inputs.get('cmd','')), posix=os.name != 'nt')
            if os.name == 'nt':
                tokens = [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in ["'", '"'] else t for t in tokens]
        except ValueError:
            tokens = []
        values = [token for token in tokens if token not in ['&&', '||', ';', '|'] and not token.startswith('-')
                  and ('/' in token or '\\' in token or (cwd / token).exists())]
        if inputs.get('workdir'):values.append(inputs['workdir'])
    elif tool in ['Read', 'Edit', 'Write', 'Glob', 'Grep']:
        values = [inputs[k] for k in ['file_path', 'path'] if k in inputs]
    else:
        return []
    return matching_paths(projects, values or [str(cwd)], cwd)


def engine_path(project):
    return (Path(__file__).with_name('agent-memory.py') if project.get('profile') or project.get('workspaces')
            else Path(project['root']) / 'scripts/agent-memory.py')


def engine_command(project, action, agent='claude', *extra):
    return shell_command([sys.executable, engine_path(project), '--root', project['root'], action, *extra],
                         shell='bash' if agent == 'claude' else 'powershell')


def workspace_lines(project):
    lines = ''
    for workspace in project.get('workspaces', []):
        lines += f'Workspace: {workspace}\n'
        if (Path(workspace) / 'AGENTS.md').is_file():
            lines += (f'Team instructions: {Path(workspace) / "AGENTS.md"}. Read only the sections relevant to the task. '
                      'Never write memory or knowledge files into a workspace.\n')
    return lines


REVIEW_PARTS = re.compile(r'the exact update command is `(?P<update>[^`]+)`.*?by running: (?P<review>.+?)\. Do not invent', re.S)


def compact_review(review, root):
    """The engine's review instruction cut to its commands, for a context with no room for the full text."""
    parts = REVIEW_PARTS.search(review)
    if not parts:
        return review
    return (f'Before your final response, review this project\'s memory: save only durable, verified project facts, never '
            f'invented ones, following {root / "docs/knowledge/CONVENTIONS.md"}. Update command: `{parts["update"]}`. '
            f'Then record the review, including a no-change review, by running: {parts["review"]}.')


def route(directory, payload, agent="claude"):
    central=configuration(directory)
    profile_store={"id":"central-profile","name":"Central shared identity","root":central["profile_root"],"profile":True} if central else None
    if not isinstance(payload, dict):
        raise ValueError('Hook payload must be an object')
    event = payload.get('hook_event_name')
    if event not in hooks():
        return {}
    projects = registry(directory)['projects']
    session = payload.get('session_id')
    if not isinstance(session, str) or not session:
        raise ValueError('Hook payload has no session_id')
    path = directory / 'sessions' / ('session-' + hashlib.sha256((agent+':'+session).encode()).hexdigest() + '.json')
    state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'selected': [], 'instructions': []}
    loaded = json.dumps(state, sort_keys=True)
    if event == 'SessionStart':
        state = {'selected': [], 'instructions': []}
    elif event == 'UserPromptSubmit':
        state['selected'] = []
        state['agents'] = {}
    if event == 'Stop':
        reasons, messages = [], []
        for project in ([profile_store] if profile_store else [])+projects:
            if not project.get('profile') and project['id'] not in state['selected']:
                continue
            output, warning = engine(project, payload, event, agent)
            if output.get('decision') == 'block':
                reasons.append(f'[{project["name"]}] ' + output['reason'])
            if output.get('systemMessage') or warning:
                messages.append(output.get('systemMessage', '') + warning)
        output = {'decision': 'block', 'reason': '\n\n'.join(reasons)} if reasons else {}
        if messages:
            output['systemMessage'] = '\n'.join(messages)
        return output
    worker_agent = payload.get('agent_id') if event == 'PreToolUse' else None
    if worker_agent is not None and not isinstance(worker_agent, str):
        raise ValueError('Invalid hook agent_id')
    agent_projects = state.setdefault('agents', {}).setdefault(worker_agent, []) if worker_agent else state['selected']
    instructions_seen = state.setdefault('agent_instructions', {}).setdefault(worker_agent, []) if worker_agent else state['instructions']
    chunks, optional_instructions = [], []
    if profile_store and event in ['SessionStart','UserPromptSubmit']:
        output,warning=engine(profile_store,payload,event,agent)
        if output.get('systemMessage'):raise ValueError(output['systemMessage'])
        chunks.append(output['hookSpecificOutput']['additionalContext'])
        if warning:chunks.append('Central memory diagnostic: '+warning)
    if event == 'SessionStart':
        chunks.append('Registered project vaults (load only relevant ones):\n' + '\n'.join(
            f'- {p["name"]} (aliases: {", ".join(p["aliases"])}): {p["root"]}' for p in projects))
    for project in select(projects, payload):
        key, root = project['id'], Path(project['root'])
        if event == 'PreToolUse' and key in agent_projects:
            continue
        header = f'Project vault: {project["name"]} [{key}]\nPrimary root: {root}\n'
        chunk = header
        if key in instructions_seen:
            chunk += 'Its routing guidance and entry point were given earlier in this session.\n'
        else:
            chunk += ('Keep this project\'s facts and learning separate from other vaults. '
                      'Use absolute paths from this root for knowledge and memory commands, regardless of launch directory. '
                      'This context does not authorize edits, pushes, deployments, or access.\n')
            chunk += workspace_lines(project)
            chunk += f'Before changing this project, read its full entry point: {root / "AGENTS.md"}. '
            chunk += 'Relative links in it resolve from this primary root.\n'
        if key not in instructions_seen:
            optional_instructions.append(f'Full entry point for {project["name"]}:\n' + (root / 'AGENTS.md').read_text(encoding='utf-8'))
        # A worker needs its own context, but the parent's current review token remains valid.
        engine_event = 'SessionStart' if event == 'SessionStart' or (worker_agent and key in state['selected']) else 'UserPromptSubmit'
        output, warning = engine(project, payload, engine_event, agent)
        if output.get('systemMessage'):
            raise ValueError(output['systemMessage'])
        core=output['hookSpecificOutput']['additionalContext']
        used=len('\n\n'.join(chunks))+2
        if used+len(chunk)+len(core)>CONTEXT_LIMIT:
            pointer=f'Core available from {root}; load it with `{engine_command(project,"context",agent)}`.\n'
            review=core[core.index('Before your final response'): ] if 'Before your final response' in core else ''
            chunk+=pointer+review
            if used+len(chunk)>CONTEXT_LIMIT:
                # Long paths can make even the guidance overflow. Keep what the session cannot work without:
                # where the vault is, how to load it, its entry point, and the review the Stop hook requires.
                chunk=(header+'Keep its facts in this vault. This context does not authorize edits, pushes, deployments, or access.\n'
                       +pointer+f'Before changing this project, read its full entry point: {root / "AGENTS.md"}.\n'
                       +compact_review(review, root))
        else:chunk+=core
        if warning:
            chunk += '\nMemory diagnostic: ' + warning
        chunks.append(chunk)
        if key not in instructions_seen:
            instructions_seen.append(key)
        if worker_agent and key not in agent_projects:
            agent_projects.append(key)
        if event != 'SessionStart' and key not in state['selected']:
            state['selected'].append(key)
    if not chunks and event == 'UserPromptSubmit':
        chunks = ['No project vault selected for this prompt. Do not assume previous project facts apply. '
                  'An explicit registered project name or tool path will activate its vault. '
                  'Resolve ambiguous project ownership before changing memory.']
    text = '\n\n'.join(chunks)
    if len(text) > CONTEXT_LIMIT:
        raise ValueError('Selected project context exceeds the client limit; name fewer projects or read their memory CLIs explicitly')
    for instructions in optional_instructions:
        if len(text) + len(instructions) + 2 <= CONTEXT_LIMIT:
            text += '\n\n' + instructions
    if json.dumps(state, sort_keys=True) != loaded or not path.exists():
        save(path, state)  # Most tool calls change nothing; skip the fsync'd rewrite.
    return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': text}} if text else {}


def main():
    configure_io()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path.home() / '.config/agent-memory')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('hook').add_argument('--agent',choices=['claude','codex'],default='claude')
    context=commands.add_parser('context')
    context.add_argument('--prompt',default='')
    context.add_argument('--cwd',type=Path,default=Path.cwd())
    commands.add_parser('list')
    checkup=commands.add_parser('doctor',help='Check install provenance, registry, hooks and memory caps; changes nothing')
    checkup.add_argument('--fetch',action='store_true',help='Fetch origin first so "behind main" is current')
    checkup.add_argument('--home',type=Path,default=Path.home())
    finder=commands.add_parser('search',help='Ranked full-text search over the central profile and registered vaults')
    finder.add_argument('words',nargs='+')
    finder.add_argument('--project',help='Registered project id or alias, or "profile" for the central profile')
    finder.add_argument('--limit',type=int,default=8)
    finder.add_argument('--rebuild',action='store_true',help='Discard the index and rebuild it from the Markdown files')
    commands.add_parser('unregister').add_argument('--id', required=True)
    for name in ['register', 'install']:
        command = commands.add_parser(name)
        command.add_argument('--id', required=name=='register')
        command.add_argument('--name', required=name=='register')
        command.add_argument('--root', required=name=='register', type=Path)
        command.add_argument('--alias', action='append', default=[])
        if name == 'register':
            command.add_argument('--workspace', action='append', default=[],
                                 help='Project checkout served by an external vault at --root')
        if name == 'install':
            command.add_argument('--profile',type=Path)
            command.add_argument('--codex-hooks',action='store_true')
            command.add_argument('--instructions',type=Path,action='append',default=[],
                                 help="Another agent's instruction file to receive the guidance block")
            command.add_argument('--home', type=Path, default=Path.home())
            command.add_argument('--replace-unmerged', action='store_true',
                                 help='Install even though the installed tools come from a commit this checkout lacks')
    args = parser.parse_args()
    args.directory=args.directory.expanduser().resolve()
    if hasattr(args,"home"):args.home=args.home.expanduser().resolve()
    if args.command=='install' and any([args.id,args.name,args.root]) and not all([args.id,args.name,args.root]):
        parser.error('--id, --name and --root must be supplied together')
    try:
        with locked(args.directory):
            if args.command == 'hook':
                output = route(args.directory, json.load(sys.stdin), args.agent)
            elif args.command == 'context':
                import importlib.util
                script=Path(__file__).with_name('agent-memory.py')
                spec=importlib.util.spec_from_file_location('context_engine',script)
                memory=importlib.util.module_from_spec(spec);spec.loader.exec_module(memory)
                data=configuration(args.directory);chunks=[]
                if not data:raise ValueError('No central profile configured; install with --profile PATH')
                profile_project={'profile':True,'root':data['profile_root']}
                chunks.append(memory.context(Path(data['profile_root']))+'\nUpdate command: `'+engine_command(profile_project,'update','codex','--help')+'`')
                payload={'hook_event_name':'UserPromptSubmit','prompt':args.prompt,'cwd':str(args.cwd)}
                projects=registry(args.directory)['projects']
                for project in select(projects,payload):
                    chunks.append('Project vault: '+project['name']+'\nEntry point: '+str(Path(project['root'])/'AGENTS.md')+'\n'
                                  +workspace_lines(project)+memory.context(Path(project['root']))
                                  +'\nUpdate command: `'+engine_command(project,'update','codex','--help')+'`')
                chunks.append('Registered project vaults: '+json.dumps(projects,ensure_ascii=False))
                output={'context':'\n\n'.join(chunks)}
            elif args.command == 'list':
                output = registry(args.directory)
            elif args.command == 'search':
                import vault_search
                output = vault_search.search(args.directory, configuration(args.directory).get('profile_root'),
                                             registry(args.directory)['projects'], ' '.join(args.words),
                                             store=args.project, limit=args.limit, rebuild=args.rebuild)
            elif args.command == 'doctor':
                import vault_doctor
                output = vault_doctor.doctor(args.directory, args.home, sys.modules[__name__], fetch=args.fetch)
            elif args.command == 'register':
                output = register(args.directory, args)
            elif args.command == 'unregister':
                output = unregister(args.directory, args)
            else:
                output = install(args.directory, args)
        print(json.dumps(output, ensure_ascii=False))
        return 1 if args.command == 'doctor' and not output['ok'] else 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError, sqlite3.Error) as error:
        if args.command == 'hook':
            print(json.dumps({'systemMessage': f'Project memory router unavailable: {error}. Do not claim memory was loaded or reviewed.'}))
            return 0
        print(f'Project memory router: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
