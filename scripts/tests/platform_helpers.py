"""Run emitted hooks with the real target shell, not a simulated Windows API."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess


def home_env(home):
    return {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home), 'PYTHONUTF8': '1'}


def run_hook(handler, **kwargs):
    if os.name == 'nt' and handler.get('commandWindows'):
        return subprocess.run(handler['commandWindows'], shell=True, encoding='utf-8', **kwargs)
    if os.name == 'nt':
        bash = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Git/bin/bash.exe'
        executable = str(bash) if bash.exists() else shutil.which('bash')
        if not executable:
            raise RuntimeError('Git Bash is required for Claude hook tests on Windows')
        return subprocess.run([executable, '-c', handler['command']], encoding='utf-8', **kwargs)
    return subprocess.run(handler['command'], shell=True, encoding='utf-8', **kwargs)


def run_review(command, agent='claude', **kwargs):
    if os.name == 'nt' and agent == 'claude':
        return run_hook({'command':command}, **kwargs)
    if os.name == 'nt':
        return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                              encoding='utf-8', **kwargs)
    return subprocess.run(shlex.split(command), encoding='utf-8', **kwargs)
