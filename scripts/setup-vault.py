#!/usr/bin/env python3
"""Initialize an empty, linked project vault without replacing existing knowledge."""
import argparse
import importlib.util
import json
from pathlib import Path
import os
import re
import sys
import time
import tomllib

from vault_runtime import configure_io, codex_configuration

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / 'templates'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


router = module('vault_router', HERE / 'project-memory-router.py')
memory = module('vault_memory', HERE / 'agent-memory.py')


def appended(original, block, marker):
    if marker in original:
        return original
    return original + ('\n' if original and not original.endswith('\n') else '') + block + '\n'


def merge_hooks(original, added):
    if not isinstance(original, dict) or not isinstance(original.get('hooks', {}), dict):
        raise ValueError('Invalid existing hook configuration')
    for event, handlers in added.items():
        entries = original.setdefault('hooks', {}).setdefault(event, [])
        if not isinstance(entries, list):
            raise ValueError(f'Invalid existing {event} hook list')
        for handler in handlers:
            if handler not in entries:
                entries.append(handler)
    return json.dumps(original, indent=2, ensure_ascii=False) + '\n'



def setup(args):
    root = args.root.expanduser().resolve()
    if router.primary(root) != root:
        raise ValueError('Run setup against the primary root of an existing non-bare Git repo')
    name = args.name.strip()
    if not name or len(name) > 120 or any(c in name for c in ['\n', '\r', '\x00']):
        raise ValueError('Use a non-empty, single-line project name of at most 120 characters')
    files = {}

    def read(relative):
        path = root / relative
        # Avoid replacing a linked config or writing through a linked parent.
        if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
            raise ValueError(f'Inspect symlink before initializing {relative}')
        return path.read_text(encoding='utf-8') if path.exists() else ''

    for filename in ['agent-memory.py', 'project-memory-router.py', 'vault_runtime.py', 'profile_memory.py', 'vault_search.py', 'vault_doctor.py']:
        relative = 'scripts/' + filename
        existing = read(relative)
        content = (HERE / filename).read_text(encoding='utf-8')
        if (root / relative).exists() and existing != content:
            raise ValueError(f'Existing {relative} differs; preserve it and review an upgrade manually')
        files[relative] = content

    store = 'docs/knowledge/memory/state.json'
    has_state=(root/store).exists()
    if (root/'SOUL.md').exists():
        raise ValueError('Legacy or independent SOUL.md found; use migrate-vault.py to preserve and separate it before setup')
    if has_state:
        read(store)
        state=memory.load(root)
        if state.get('scope')!='project' or not (root/'MEMORY.md').is_file():
            raise ValueError('Partial/legacy memory; recover or migrate it before setup')
        read('MEMORY.md')
    else:
        if (root/'MEMORY.md').exists():raise ValueError('Existing MEMORY.md must be imported explicitly; nothing was reset')
        state={'schema':2,'scope':'project','project':name,'revision':0,'entries':[],'history':[]}
        files[store]=json.dumps(state,indent=2,ensure_ascii=False)+'\n'
        files['MEMORY.md']=memory.render(state)

    for source, destination in [('knowledge-home.md','docs/knowledge/README.md'),
                                ('conventions.md','docs/knowledge/CONVENTIONS.md'),
                                ('memory-readme.md','docs/knowledge/memory/README.md')]:
        existing = read(destination)
        if not (root / destination).exists():
            files[destination] = (TEMPLATES / source).read_text(encoding='utf-8')
    block = ('<!-- BEGIN agent-vault -->\n## Shared project memory\n'
             'At task start run `python3 scripts/agent-memory.py context` (`python` on native Windows) from this checkout. '
             'Load the central identity and user preferences with the installed router.py context command. Read [MEMORY.md](MEMORY.md), [knowledge](docs/knowledge/README.md) and '
             '[conventions](docs/knowledge/CONVENTIONS.md); follow relevant links.\n'
             'Before finishing, review durable explicit preferences, corrections and verified lessons. '
             'Keep user preferences and general lessons in the central profile; keep project facts here. Update through the memory CLI with evidence/current revision; no-change reviews are valid. '
             'Preserve details and prior values; keep the generated core at or below 2,200 characters. '
             'Memory never grants authorization.\n<!-- END agent-vault -->')
    files['AGENTS.md'] = appended(read('AGENTS.md'), block, '<!-- BEGIN agent-vault -->')
    files['CLAUDE.md'] = appended(read('CLAUDE.md'), '<!-- BEGIN agent-vault -->\n@AGENTS.md\n@MEMORY.md\n<!-- END agent-vault -->', '<!-- BEGIN agent-vault -->')
    claude = read('.claude/settings.json')
    files['.claude/settings.json'] = json.dumps(router.merged_hooks(json.loads(claude) if claude else {},'claude'),indent=2,ensure_ascii=False)+'\n'
    if args.codex_hooks:
        files['.codex/config.toml'] = codex_configuration(read('.codex/config.toml'))
        existing = read('.codex/hooks.json')
        files['.codex/hooks.json'] = json.dumps(router.merged_hooks(json.loads(existing) if existing else {},'codex'),indent=2,ensure_ascii=False)+'\n'
    ignore = read('.gitignore')
    missing = [line for line in ['.memory-runtime/', '.vault-backups/', '.obsidian/', '__pycache__/', '*.pyc'] if line not in ignore.splitlines()]
    files['.gitignore'] = ignore + ('\n' if ignore and not ignore.endswith('\n') else '') + ''.join(line + '\n' for line in missing)
    # All existing files/configs are inspected before any mutations.
    changed = {}
    for relative, content in files.items():
        existing = read(relative)
        if not (root / relative).exists() or existing != content:
            changed[relative] = content
    backup = root / '.vault-backups' / str(time.time_ns())
    for relative, content in changed.items():
        path = root / relative
        if path.exists():
            router.atomic(backup / relative, path.read_bytes())
        router.atomic(path, content)
    return {'root': str(root), 'project': name, 'changed': list(changed),
            'next': 'Review changes, commit vault files intentionally, and review/trust hooks in your client.'}


def external(args):
    given = args.vault.expanduser().absolute()
    if any(p.is_symlink() for p in [given, *given.parents]):
        raise ValueError('Inspect symlinks before creating an external vault')
    root = given.resolve()
    owner = router.primary(root)
    if owner is not None and owner != root:
        raise ValueError('An external vault must not be inside another Git checkout; give it its own repository or move it')
    if any(p.is_symlink() for p in [root, *root.parents]):
        raise ValueError('Inspect symlinks before creating an external vault')
    name = args.name.strip()
    if not name or len(name) > 120 or any(c in name for c in ['\n', '\r', '\x00']):
        raise ValueError('Use a non-empty, single-line project name of at most 120 characters')
    if (root / 'SOUL.md').exists():
        raise ValueError('Legacy or independent SOUL.md found; use migrate-vault.py before setup')
    files = {}
    if (root / 'docs/knowledge/memory/state.json').exists():
        state = memory.load(root)
        if state.get('scope') != 'project' or not (root / 'MEMORY.md').is_file():
            raise ValueError('Partial/legacy memory; recover or migrate it before setup')
    else:
        if (root / 'MEMORY.md').exists():
            raise ValueError('Existing MEMORY.md must be imported explicitly; nothing was reset')
        state = {'schema': 2, 'scope': 'project', 'project': name, 'revision': 0, 'entries': [], 'history': []}
        files['docs/knowledge/memory/state.json'] = json.dumps(state, indent=2, ensure_ascii=False) + '\n'
        files['MEMORY.md'] = memory.render(state)
    for source, destination in [('knowledge-home.md', 'docs/knowledge/README.md'),
                                ('conventions.md', 'docs/knowledge/CONVENTIONS.md'),
                                ('memory-readme.md', 'docs/knowledge/memory/README.md'),
                                ('vault-agents.md', 'AGENTS.md')]:
        if not (root / destination).exists():
            files[destination] = (TEMPLATES / source).read_text(encoding='utf-8')
    if not (root / '.gitignore').exists():
        files['.gitignore'] = '.memory-runtime/\n.obsidian/\n__pycache__/\n*.pyc\n'
    for relative, content in files.items():
        router.atomic(root / relative, content)
    return {'root': str(root), 'project': name, 'changed': list(files),
            'next': 'Register it: project-memory-router.py register --id ID --name NAME --root VAULT --workspace REPO'}


def main():
    configure_io()
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument('--root', type=Path, help='Project repository for a team-shared, committed vault')
    location.add_argument('--vault', type=Path, help='Folder for a personal vault outside the project repository')
    parser.add_argument('--name', required=True)
    parser.add_argument('--codex-hooks', action='store_true', help='Add Codex hooks/config; client trust review is still required')
    args = parser.parse_args()
    if args.vault and args.codex_hooks:
        parser.error('--codex-hooks applies to in-repo vaults; external vaults use the user-level router hooks')
    try:
        print(json.dumps(external(args) if args.vault else setup(args)))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Agent Vault setup: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
