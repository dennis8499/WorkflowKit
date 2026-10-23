"""Run the standalone package's release and migration regressions."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    for command in (
        ['scripts/build-workflow-kit.py'],
        ['scripts/verify-release.py'],
        ['-m', 'unittest', 'discover', '-s', 'test/release', '-p', '*_test.py', '-v'],
        ['scripts/test_release_ci.py', '-v'],
    ):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', *command], cwd=ROOT)
        if result.returncode:
            raise SystemExit(result.returncode)
