"""Real cross-process locks; these tests also execute on native Windows CI."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]


class RuntimeTests(unittest.TestCase):
    def test_contending_writer_times_out_then_acquires_after_release(self):
        with tempfile.TemporaryDirectory() as directory:
            # Use a literal multiline program to exercise the same native lock in separate processes.
            code = 'import sys\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom vault_runtime import file_lock\nwith file_lock(Path(sys.argv[2]),timeout=0.2):\n print("ready",flush=True)\n sys.stdin.readline()\n'
            lock = str(Path(directory) / 'lock')
            args = [sys.executable, '-c', code, str(SCRIPTS), lock]
            holder = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding='utf-8')
            try:
                self.assertEqual(holder.stdout.readline().strip(), 'ready', holder.stderr.read() if holder.poll() is not None else '')
                blocked = subprocess.run(args, input='', capture_output=True, text=True, encoding='utf-8')
                self.assertNotEqual(blocked.returncode, 0)
                self.assertIn('busy', blocked.stderr)
                holder.communicate('\n', timeout=5)
                acquired = subprocess.run(args, input='\n', capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(acquired.returncode, 0, acquired.stderr)
                self.assertEqual(acquired.stdout.strip(), 'ready')
            finally:
                if holder.poll() is None:
                    holder.kill()
                holder.communicate()

    def test_exception_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            code = ('import sys\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\n'
                    'from vault_runtime import file_lock\np=Path(sys.argv[2])\n'
                    'try:\n with file_lock(p):\n  raise ValueError("expected")\n'
                    'except ValueError: pass\nwith file_lock(p,timeout=0.2): print("released")\n')
            result = subprocess.run([sys.executable, '-c', code, str(SCRIPTS), str(Path(directory)/'lock')],
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('released', result.stdout)


if __name__ == '__main__':
    unittest.main()
