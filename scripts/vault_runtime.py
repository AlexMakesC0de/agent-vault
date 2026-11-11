"""Platform support shared by installed engines and the user router (stdlib only)."""
from contextlib import contextmanager
import base64
import errno
import os
from pathlib import Path
import shlex
import sys
import time
import re
import tomllib

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


def configure_io():
    for stream in [sys.stdin, sys.stdout, sys.stderr]:
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')


@contextmanager
def file_lock(path, timeout=5):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b'\0')
                stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in [errno.EACCES, errno.EAGAIN, errno.EDEADLK]:
                    raise
                if time.monotonic() >= deadline:
                    raise ValueError('Shared memory is busy; retry after the current writer finishes') from error
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def shell_command(args, shell='powershell'):
    if os.name == 'nt' and shell != 'bash':
        # These commands are displayed to the agent/user for native PowerShell.
        return '& ' + ' '.join("'" + str(arg).replace("'", "''") + "'" for arg in args)
    return shlex.join([str(arg).replace('\\', '/') if os.name == 'nt' else str(arg) for arg in args])


def legacy_hook_code(agent):
    # No payload is evaluated: only a fixed local script is launched with inherited stdin.
    prefix = 'import pathlib,subprocess,sys;'
    local = ('p=pathlib.Path(subprocess.check_output(["git","rev-parse","--show-toplevel"],'
             'text=True,encoding="utf-8").strip())/"scripts/agent-memory.py";')
    if agent == 'claude':
        return (prefix + 'r=pathlib.Path.home()/".config/agent-memory/router.py";'
                'p=r if r.is_file() else pathlib.Path(subprocess.check_output(["git","rev-parse","--show-toplevel"],'
                'text=True,encoding="utf-8").strip())/"scripts/agent-memory.py";'
                'a=["hook"] if r.is_file() else ["hook","--agent","claude"];'
                'sys.exit(subprocess.call([sys.executable,str(p),*a]))')
    return prefix + local + 'sys.exit(subprocess.call([sys.executable,str(p),"hook","--agent","codex"]))'


def legacy_hook_handler(agent):
    code = legacy_hook_code(agent)
    command = ('if command -v python >/dev/null 2>&1; then av_python=python; else av_python=python3; fi; '
               '"$av_python" -c ' + shlex.quote(code))
    handler = {'type': 'command', 'command': command, 'timeout': 30}
    if agent == 'claude':
        handler['shell'] = 'bash'  # Git Bash on native Windows; never WSL.
    else:
        script = ("$utf8 = New-Object System.Text.UTF8Encoding($false)\n"
                  "[Console]::InputEncoding = $utf8\n[Console]::OutputEncoding = $utf8\n$OutputEncoding = $utf8\n"
                  "$projectRoot = & git rev-parse --show-toplevel\n"
                  "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n"
                  "& python (Join-Path $projectRoot 'scripts/agent-memory.py') hook --agent codex\n"
                  "exit $LASTEXITCODE")
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        handler['commandWindows'] = 'powershell.exe -NoProfile -NonInteractive -EncodedCommand ' + encoded
    return handler


def hook_code(agent, subprocess_launch=False):
    if agent not in ['claude','codex']:raise ValueError('Unknown agent')
    locate=('import pathlib,subprocess,sys;r=pathlib.Path.home()/".config/agent-memory/router.py";'
            'p=r if r.is_file() else pathlib.Path(subprocess.check_output(["git","rev-parse","--show-toplevel"],'
            'text=True,encoding="utf-8").strip())/"scripts/agent-memory.py";')
    if subprocess_launch:
        # Previous handler, kept so install can recognise and replace it.
        return locate+f'sys.exit(subprocess.call([sys.executable,str(p),"hook","--agent","{agent}"]))'
    # Run the fixed local script in this interpreter: a second Python start costs every tool call.
    return (locate+'import runpy;sys.path.insert(0,str(p.parent));'
            f'sys.argv=[str(p),"hook","--agent","{agent}"];runpy.run_path(str(p),run_name="__main__")')


def hook_handler(agent, subprocess_launch=False):
    code=hook_code(agent, subprocess_launch)
    handler={'type':'command','command':
             'if command -v python >/dev/null 2>&1; then av_python=python; else av_python=python3; fi; '
             +'"$av_python" -c '+shlex.quote(code),'timeout':30}
    if agent=='claude':handler['shell']='bash'
    else:
        # Windows PowerShell 5.1 strips embedded double quotes in native argv.
        # The -c wrapper contains only single-quoted ASCII base64, never source quotes.
        wrapper="import base64;exec(base64.b64decode('"+base64.b64encode(code.encode('utf-8')).decode('ascii')+"'))"
        script=("$utf8 = New-Object System.Text.UTF8Encoding($false)\n"
                "[Console]::InputEncoding = $utf8\n[Console]::OutputEncoding = $utf8\n$OutputEncoding = $utf8\n"
                "& python -c '"+wrapper.replace("'","''")+"'\nexit $LASTEXITCODE")
        handler['commandWindows']='powershell.exe -NoProfile -NonInteractive -EncodedCommand '+base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return handler


def native_path(value):
    # Git Bash reports drive paths as /c/...; pathlib on native Windows expects C:/...
    if os.name == 'nt' and len(value) >= 3 and value[0] == '/' and value[1].isalpha() and value[2] == '/':
        value = value[1].upper() + ':' + value[2:]
    return Path(value).expanduser()


def codex_configuration(text):
    data = tomllib.loads(text)
    features = data.get('features', {})
    if not isinstance(features, dict):
        raise ValueError('Invalid existing Codex features')
    if features.get('hooks') is True:
        return text
    if 'hooks' in features:
        raise ValueError('Codex hooks are explicitly disabled; enable them yourself after reviewing the hooks')
    match = re.search(r'^\[features\][ \t]*(?:#[^\n]*)?$', text, re.M)
    if match:
        candidate = text[:match.end()] + '\nhooks = true' + text[match.end():]
    elif 'features' in data:
        raise ValueError('Enable features.hooks = true in existing Codex config manually')
    else:
        candidate = text + ('\n' if text and not text.endswith('\n') else '') + '[features]\nhooks = true\n'
    expected = {**data, 'features': {**features, 'hooks': True}}
    if tomllib.loads(candidate) != expected:
        raise ValueError('Cannot amend Codex config without changing existing values; enable features.hooks manually')
    return candidate
