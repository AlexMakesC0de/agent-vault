"""Install provenance and health checks for the installed router.

`install` records where the installed tools came from in install.json: the toolkit checkout, its
commit and branch, whether the tool files had uncommitted changes, and a hash of every installed
file. `doctor` compares that record with the files on disk and with the checkout's main branch,
then checks the registry, client hooks and memory caps. It changes nothing.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import time

RECORD = 'install.json'
TOOL_PATHS = ['scripts', 'skills']  # Commits outside these do not change what install ships.
# Running the tools from a checkout writes bytecode beside them; it is never a change to what install ships.
NOT_TOOLS = [':(exclude,glob)**/__pycache__/**', ':(exclude,glob)**/*.pyc']


def digest(content):
    return hashlib.sha256(content.encode('utf-8') if isinstance(content, str) else content).hexdigest()


def git(source, *args):
    result = subprocess.run(['git', '-C', str(source), *args], capture_output=True, text=True,
                            encoding='utf-8', timeout=20)
    return result.stdout.strip() if result.returncode == 0 else None


def checkout_of(script):
    """The toolkit checkout a running script belongs to, or None for an installed copy."""
    folder = Path(script).resolve().parent
    for candidate in [folder, folder.parent]:
        if (candidate / '.git').exists() and (candidate / 'scripts/project-memory-router.py').is_file():
            return candidate
    return None


def provenance(script, files, directory):
    """The install.json content for the files about to be installed into directory."""
    source = checkout_of(script)
    record = {'schema': 1, 'installed_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'source': None,
              'commit': None, 'branch': None, 'uncommitted': None,
              'files': {str(Path(path).relative_to(directory)).replace('\\', '/'): digest(content)
                        for path, content in files.items() if Path(path).is_relative_to(directory)}}
    if source:
        record.update(source=str(source), commit=git(source, 'rev-parse', 'HEAD'),
                      branch=git(source, 'branch', '--show-current') or None,
                      uncommitted=bool(git(source, 'status', '--porcelain', '--', *TOOL_PATHS, *NOT_TOOLS)))
    return record


def check(name, ok, detail, fix=None):
    item = {'check': name, 'ok': ok, 'detail': detail}
    if fix and not ok:
        item['fix'] = fix
    return item


def installed_files(directory, record):
    changed = [name for name, expected in record['files'].items()
               if not (directory / name).is_file() or digest((directory / name).read_bytes()) != expected]
    if changed:
        return check('installed files', False, 'Changed or missing since install: ' + ', '.join(sorted(changed)),
                     'Reinstall from the toolkit checkout; local edits to installed files are overwritten.')
    return check('installed files', True, f'{len(record["files"])} files match the install record')


def source_state(record, fetch):
    source, commit = record.get('source'), record.get('commit')
    if not source or not commit:
        return [check('source', False, 'Installed from a copy without Git history; provenance unknown',
                      'Reinstall from a clone of the toolkit repository.')]
    if not Path(source).is_dir() or git(source, 'rev-parse', '--git-dir') is None:
        return [check('source', False, f'Toolkit checkout {source} is gone', 'Reinstall from a current clone.')]
    results = []
    if fetch:
        fetched = git(source, 'fetch', '--quiet', 'origin')
        results.append(check('fetch', fetched is not None, 'Fetched origin' if fetched is not None
                             else 'Could not fetch origin; comparing with the last fetched main'))
    main = next((ref for ref in ['origin/main', 'main'] if git(source, 'rev-parse', '--verify', '--quiet', ref)), None)
    label = f'{commit[:7]} from branch {record.get("branch") or "(detached)"}'
    if record.get('uncommitted'):
        results.append(check('source', False, f'Installed {label} with uncommitted tool changes',
                             'Commit the changes, merge them, then reinstall from main.'))
    elif main is None:
        results.append(check('source', False, f'Installed {label}; the checkout has no main branch to compare with'))
    elif git(source, 'merge-base', '--is-ancestor', commit, main) is None:
        pushed = git(source, 'branch', '-r', '--contains', commit)
        where = 'pushed but not merged' if pushed else 'never pushed'
        results.append(check('source', False, f'Installed {label}, which is not on {main} ({where}). '
                             'Installing from main now would undo those changes.',
                             'Merge that branch first, then reinstall from main.'))
    else:
        behind = git(source, 'rev-list', '--count', f'{commit}..{main}', '--', *TOOL_PATHS)
        if behind and int(behind):
            results.append(check('source', False, f'Installed {label} is {behind} tool commit(s) behind {main}',
                                 'git switch main && git pull, then run install again.'))
        else:
            results.append(check('source', True, f'Installed {label}, current with {main}'))
    return results


def doctor(directory, home, router_module, fetch=False):
    directory, results = Path(directory), []
    path = directory / RECORD
    if path.is_file():
        record = json.loads(path.read_text(encoding='utf-8'))
        results.append(installed_files(directory, record))
        results += source_state(record, fetch)
    else:
        results.append(check('install record', False, 'No install.json; this install predates provenance records',
                             'Reinstall from the toolkit checkout to record where the tools came from.'))
    config = router_module.configuration(directory)
    projects = router_module.registry(directory)['projects']
    missing = [p['id'] for p in projects if not Path(p['root']).is_dir()]
    missing += [f'{p["id"]} workspace {w}' for p in projects for w in p.get('workspaces', []) if not Path(w).is_dir()]
    results.append(check('registry', not missing, f'{len(projects)} registered project(s)' if not missing
                         else 'Missing folders: ' + ', '.join(missing), 'Restore the folders or unregister the projects.'))
    settings = Path(home) / '.claude/settings.json'
    wanted = router_module.hooks('claude')
    try:
        present = json.loads(settings.read_text(encoding='utf-8')).get('hooks', {}) if settings.is_file() else {}
        hooked = [event for event, handlers in wanted.items() if handlers[0] in present.get(event, [])]
    except (ValueError, AttributeError):
        hooked = []
    results.append(check('claude hooks', len(hooked) == len(wanted), f'{len(hooked)} of {len(wanted)} hook events installed',
                         'Run install again, then restart the client and trust the hooks.'))
    if config.get('profile_root'):
        import profile_memory
        root = Path(config['profile_root'])
        try:
            state = json.loads((root / profile_memory.PROFILE_STORE).read_text(encoding='utf-8'))
            warning = profile_memory.near_cap([(name.upper() + '.md', len(text), profile_memory.LIMITS[name]) for name, text in [
                ('user', (root / 'USER.md').read_text(encoding='utf-8')),
                ('memory', (root / 'MEMORY.md').read_text(encoding='utf-8'))]])
            results.append(check('profile', not warning, f'Revision {state["revision"]}; ' + (warning.strip() or 'cores have room'),
                                 'Move detail into linked notes and shorten the core entries to pointers.'))
        except (OSError, ValueError, KeyError) as error:
            results.append(check('profile', False, f'Cannot read profile at {root}: {error}'))
    return {'ok': all(item['ok'] for item in results), 'checks': results}
