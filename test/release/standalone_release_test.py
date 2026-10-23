from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


class StandaloneReleaseTests(unittest.TestCase):
    def test_unpacked_release_installs_without_extension_or_original_archive(self):
        with tempfile.TemporaryDirectory(prefix='wk-standalone-') as temporary:
            directory = Path(temporary)
            with zipfile.ZipFile(ROOT / f'dist/gitlab-workspace-kit-{VERSION}.zip') as archive:
                archive.extractall(directory / 'download')
            installer = directory / 'download/workflow-kit/install.py'
            for profile in ('group', 'repository'):
                with self.subTest(profile=profile):
                    target = directory / profile
                    target.mkdir()
                    if profile == 'repository':
                        subprocess.run(['git', 'init', '-q', str(target)], check=True, capture_output=True)
                    command = [sys.executable, '-X', 'utf8', '-B', str(installer), '--target', str(target)]
                    preview = subprocess.run(command + ['--dry-run'], capture_output=True, text=True, encoding='utf-8')
                    self.assertEqual(0, preview.returncode, preview.stdout + preview.stderr)
                    self.assertFalse((target / '.agents').exists())
                    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    receipt = json.loads(result.stdout)
                    self.assertEqual(profile, receipt['profile'])
                    self.assertEqual(VERSION, receipt['version'])
                    again = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
                    self.assertEqual(0, again.returncode, again.stdout + again.stderr)
                    self.assertEqual('unchanged', json.loads(again.stdout)['status'])

    def test_release_descriptor_authenticates_zip_and_both_installer_copies(self):
        release = json.loads((ROOT / 'dist/release.json').read_text(encoding='utf-8'))
        self.assertEqual(VERSION, release['version'])
        self.assertEqual('0.33.0', release['minimumExtensionVersion'])
        for asset in release['assets'].values():
            content = (ROOT / 'dist' / asset['name']).read_bytes()
            self.assertEqual(asset['size'], len(content))
            self.assertEqual(asset['sha256'], hashlib.sha256(content).hexdigest())
        with zipfile.ZipFile(ROOT / 'dist' / release['assets']['package']['name']) as archive:
            self.assertEqual(archive.read('workflow-kit/install.py'), (ROOT / 'dist' / release['assets']['installer']['name']).read_bytes())


if __name__ == '__main__':
    unittest.main()
