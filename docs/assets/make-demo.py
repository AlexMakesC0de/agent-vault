#!/usr/bin/env python3
"""Build the memory viewer page from synthetic data, for README screenshots.

Creates a throwaway home folder with a profile, two project vaults and two people notes, all invented,
installs the tools into it, and writes the viewer page to the path given. The temporary folder is replaced
by "~" in the page, so a screenshot never shows a real machine path.

    python docs/assets/make-demo.py demo.html
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
PROFILE_ENTRIES = [
    ('user', 'short-answers', 'explicit', 'Lead with the answer; detail only when asked.'),
    ('user', 'branch-per-change', 'explicit', 'Never commit to main: one feat/ or fix/ branch and a pull request per change.'),
    ('user', 'verify-first', 'explicit', 'Run the command and show its output before saying something works.'),
    ('user', 'tabs-maybe', 'inferred', 'Probably prefers tabs over spaces in new files.'),
    ('memory', 'windows-git-bash', 'observed', 'Git Bash rewrites paths in docker run -v; set MSYS_NO_PATHCONV=1.'),
    ('memory', 'lockfile-ci', 'observed', 'CI installs from the lockfile; update it in the same commit as the manifest.'),
]
VAULTS = {
    'shopfront': ('Shopfront', [
        ('stack', 'explicit', 'Next.js frontend and FastAPI backend; one Dev Container for local and CI.'),
        ('auth', 'observed', 'Sign-in uses the company identity provider; tests use a local stub, never real accounts.'),
        ('checkout-flag', 'explicit', 'New checkout ships behind the checkout-v2 flag until finance signs off.'),
    ]),
    'data-pipeline': ('Data pipeline', [
        ('schedule', 'explicit', 'Nightly load runs at 02:00 UTC; reruns are safe because every step is idempotent.'),
        ('schema', 'observed', 'Add columns at the end of a table; downstream reports read by position.'),
    ]),
}
PEOPLE = {
    'sam-rivera': ('Sam Rivera', 'Product owner, Shopfront', 'Decides scope for Shopfront', 'sam@example.com',
                   ['2026-09-02: asked for the checkout flag.', '2026-10-14: approved the new basket layout.']),
    'priya-shah': ('Priya Shah', 'Data engineer, Analytics', 'Owns the nightly pipeline', 'priya@example.com',
                   ['2026-10-01: moved the load to 02:00 UTC.']),
}


def run(home, *args):
    # The throwaway home stands in for the real one, so nothing is read from or written to the user's own setup.
    env = {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home), 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, encoding='utf-8',
                            cwd=home, env=env)
    if result.returncode:
        raise SystemExit(f'{args[0]} failed: {result.stderr}')
    return result.stdout


def update(home, flag, root, key, kind, text, target=None):
    revision = json.loads(run(home, SCRIPTS / 'agent-memory.py', flag, root, 'status'))['revision']
    run(home, SCRIPTS / 'agent-memory.py', flag, root, 'update', '--id', key, '--kind', kind, '--text', text,
        '--source', 'demo data', '--agent', 'human', '--expected-revision', revision,
        *(['--target', target] if target else []))


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    output = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp).resolve() / 'home'
        (home / '.claude').mkdir(parents=True)
        profile, config = home / 'agent-profile', home / '.config/agent-memory'
        run(home, SCRIPTS / 'agent-memory.py', '--profile', profile, 'init-profile')
        run(home, SCRIPTS / 'agent-memory.py', '--profile', profile, 'finish-onboarding', '--agent', 'human',
            '--expected-revision', '0', '--source', 'demo data')
        run(home, SCRIPTS / 'project-memory-router.py', 'install', '--profile', profile)
        for target, key, kind, text in PROFILE_ENTRIES:
            update(home, '--profile', profile, key, kind, text, target)
        for key, (name, entries) in VAULTS.items():
            workspace, vault = home / 'code' / key, home / 'agent-vaults' / key
            workspace.mkdir(parents=True)
            subprocess.run(['git', 'init', '-q', str(workspace)], check=True)
            run(home, SCRIPTS / 'setup-vault.py', '--vault', vault, '--name', name)
            run(home, SCRIPTS / 'project-memory-router.py', 'register', '--id', key, '--name', name,
                '--root', vault, '--workspace', workspace)
            for entry, kind, text in entries:
                update(home, '--root', vault, entry, kind, text)
        people = profile / 'notes/people'
        people.mkdir(parents=True)
        (people / 'README.md').write_text('# People\n', encoding='utf-8')
        for key, (name, role, relation, contact, history) in PEOPLE.items():
            (people / f'{key}.md').write_text(
                f'# {name}\n\n- **Role:** {role}\n- **Relationship to me:** {relation}\n- **Work contact:** {contact}\n\n'
                '## History\n\n' + ''.join(f'- {line}\n' for line in history), encoding='utf-8')
        page = Path(temp) / 'view.html'
        run(home, config / 'view.py', '--output', page)
        html = page.read_text(encoding='utf-8')
        for spelling in {str(home), str(home).replace('\\', '/'), home.as_posix()}:
            html = html.replace(spelling, '~')
        output.write_text(html, encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
