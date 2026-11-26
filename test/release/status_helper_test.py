"""Exercise the packaged read-only adapter with an authenticated historical API fixture."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MARKER = '.gitlab-workspace/tool-manifests/workflow-kit.json'
LEGACY = b'''import json

VERSION = '1.7.0'

def read_regular(file):
    return file.read_bytes()

def inspect_status(root, expected_version):
    file = root / '.gitlab-workspace/tool-manifests/workflow-kit.json'
    raw = json.loads(read_regular(file))
    return {'ok': True, 'status': 'installed', 'integrity': 'verified', 'statusContract': 1,
            'source': raw['source'], 'version': expected_version}

if __name__ == '__main__':
    raise AssertionError('Only the read-only status entry should run')
'''


class ExportedStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix='workflow-kit-status-')
        cls.addClassCleanup(directory.cleanup)
        cls.helper = Path(directory.name) / 'workflow-kit-status.py'
        subprocess.run([sys.executable, '-X', 'utf8', '-B', str(ROOT / 'scripts/export-status-helper.py'),
                        '--output', str(cls.helper)], capture_output=True, check=True, timeout=120)

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='workflow-kit-status-case-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.cached = self.root / 'installer.py'

    def status(self, *options):
        completed = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(self.helper), 'status',
                                    str(self.project), *options], capture_output=True, encoding='utf-8',
                                   check=True, timeout=30)
        return json.loads(completed.stdout)

    def cached_options(self, source):
        self.cached.write_bytes(source)
        return ('--expected-version', '1.7.0', '--cached-installer', str(self.cached),
                '--cached-installer-size', str(len(source)), '--cached-installer-sha256', hashlib.sha256(source).hexdigest())

    def manifest(self):
        marker = self.project / MARKER
        marker.parent.mkdir(parents=True)
        content = b'{\r\n  "version": "1.7.0", "source": "github"\r\n}\r\n'
        marker.write_bytes(content)
        return marker, content

    def test_cached_legacy_status_attests_the_bytes_read_by_the_verifier(self):
        marker, content = self.manifest()
        options = self.cached_options(LEGACY)
        result = self.status(*options)
        self.assertEqual('installed', result['status'])
        self.assertEqual('1.7.0', result['version'])
        self.assertEqual('github', result['source'])
        self.assertEqual(hashlib.sha256(content).hexdigest(), result['installedManifestSha256'])
        self.assertEqual(content, marker.read_bytes())
        self.assertEqual(LEGACY, self.cached.read_bytes())

    def test_cached_status_rejects_replaced_installer_bytes(self):
        options = self.cached_options(LEGACY)
        self.cached.write_bytes(LEGACY.replace(b"'installed'", b"'replaced!'"))
        self.assertEqual(len(LEGACY), self.cached.stat().st_size)
        result = self.status(*options)
        self.assertEqual('error', result['status'])
        self.assertIn('摘要不符', result['message'])
        self.assertNotIn('installedManifestSha256', result)

    def test_cached_legacy_status_rejects_an_unobserved_manifest(self):
        self.manifest()
        options = self.cached_options(LEGACY.replace(b'json.loads(read_regular(file))', b'json.loads(file.read_bytes())'))
        result = self.status(*options)
        self.assertEqual('error', result['status'])
        self.assertIn('無法確認舊版檢查器驗證', result['message'])
        self.assertNotIn('installedManifestSha256', result)

    def test_embedded_status_keeps_an_uninstalled_root_read_only(self):
        result = self.status()
        self.assertEqual('missing', result['status'])
        self.assertEqual([], list(self.project.iterdir()))
        catalog = json.loads(self.helper.with_suffix('.json').read_bytes())
        self.assertIn(catalog['version'], catalog['versions'])

    def identity_markers(self):
        helper = runpy.run_path(str(self.helper))
        profile = helper['PROFILE_MANIFESTS']['repository']
        marker = self.project / MARKER
        marker.parent.mkdir(parents=True)
        managed = '.agents/skills/merge-reviewer/SKILL.md'
        file = self.project / managed
        file.parent.mkdir(parents=True)
        file.write_bytes(b'Managed fixture bytes')
        upstream = {name: {key: item for key, item in data.items() if key != 'root'}
                    for name, data in helper['UPSTREAM'].items()}
        known = {'schema': 'gitlab-workspace-kit-installed/v1', 'package': helper['PACKAGE'],
                 'version': helper['VERSION'], 'source': 'github', 'workspaceContract': helper['WORKSPACE_CONTRACT'],
                 'profile': 'repository', 'bmadMode': 'bundled', 'upstream': upstream,
                 'overlays': profile['overlays'], 'payloadSha256': profile['payloadSha256'],
                 'files': {managed: hashlib.sha256(file.read_bytes()).hexdigest()}}
        return marker, known, {**known, 'payloadSha256': 'f' * 64}

    def test_embedded_status_classifies_only_unknown_package_identity(self):
        marker, known, unknown = self.identity_markers()
        marker.write_text(json.dumps(unknown), encoding='utf-8')
        result = self.status()
        self.assertEqual(('error', 'unverified', 1, 'unknown-package-identity'),
                         (result['status'], result['integrity'], result['statusContract'], result['errorCode']))
        self.assertNotIn('installedManifestSha256', result)

        marker.write_text(json.dumps(known), encoding='utf-8')
        result = self.status()
        self.assertEqual('error', result['status'])
        self.assertIn('Installed Skill hashes differ', result['message'])
        self.assertNotIn('errorCode', result)

        marker.write_text(json.dumps(unknown), encoding='utf-8')
        stage = self.project / '.gitlab-workspace/tool-installs' / ('kit-' + 'a' * 32)
        stage.mkdir(parents=True)
        owner = {'package': unknown['package'], 'group_root': str(self.project.resolve())}
        (stage / 'owner.json').write_text(json.dumps(owner), encoding='utf-8')
        result = self.status()
        self.assertEqual('error', result['status'])
        self.assertIn('未完成', result['message'])
        self.assertNotIn('errorCode', result)

    def test_embedded_status_reports_record_and_path_errors_before_fallback(self):
        marker, _, unknown = self.identity_markers()
        managed, digest = next(iter(unknown['files'].items()))
        directory = self.project / 'managed-directory'
        directory.mkdir()
        cases = (
            ('missing upstream', {'upstream': None}, 'Installed upstream manifest'),
            ('invalid upstream record', {'upstream': {'tool': []}}, 'Installed upstream manifest'),
            ('invalid overlay record', {'overlays': {'tool': None}}, 'Installed overlay manifest'),
            ('empty file map', {'files': {}}, '缺少安裝檔案摘要'),
            ('bad file digest', {'files': {managed: 'invalid'}}, '安裝摘要格式無效'),
            ('escaping relative path', {'files': {'../outside.txt': digest}}, '路徑超出允許範圍'),
            ('missing file', {'files': {'missing-managed.txt': digest}}, 'missing-managed.txt'),
            ('directory instead of file', {'files': {directory.name: digest}}, '檔案不是安全的一般檔案'),
        )
        for case, changes, message in cases:
            with self.subTest(case=case):
                marker.write_text(json.dumps({**unknown, **changes}), encoding='utf-8')
                result = self.status()
                self.assertEqual(('error', 'unverified', 1), (result['status'], result['integrity'], result['statusContract']))
                self.assertIn(message, result['message'])
                self.assertNotIn('errorCode', result)
                self.assertNotIn('installedManifestSha256', result)

    def test_safe_path_rejects_links_before_resolving_the_candidate(self):
        helper = runpy.run_path(str(self.helper))
        parent = self.project / 'managed'
        parent.mkdir()
        link = parent / 'linked'
        original_resolve, original_lstat = Path.resolve, Path.lstat
        calls = []

        def resolve(path, *args, **kwargs):
            calls.append(('resolve', path))
            return original_resolve(path, *args, **kwargs)

        def lstat(path, *args, **kwargs):
            calls.append(('lstat', path))
            if path == link:
                return SimpleNamespace(st_mode=stat.S_IFLNK)
            return original_lstat(path, *args, **kwargs)

        for case, candidate, allow_missing in (
                ('directory link', link / 'child.txt', True),
                ('file link', link, False)):
            with self.subTest(case=case):
                calls.clear()
                relative = candidate.relative_to(self.project).as_posix()
                with mock.patch.object(Path, 'resolve', new=resolve), mock.patch.object(Path, 'lstat', new=lstat):
                    with self.assertRaisesRegex(helper['KitError'], 'symbolic link'):
                        helper['assert_safe'](self.project, relative, allow_missing=allow_missing)
                self.assertEqual([('resolve', self.project), ('lstat', parent), ('lstat', link)], calls)

    def test_safe_path_rejects_invalid_names_before_filesystem_checks(self):
        helper = runpy.run_path(str(self.helper))
        for case, relative in (('parent traversal', '../outside.txt'), ('absolute path', '/outside.txt'),
                               ('drive path', 'C:/outside.txt'), ('backslash', r'managed\outside.txt')):
            with self.subTest(case=case):
                with (mock.patch.object(Path, 'resolve', side_effect=AssertionError('unexpected resolution')) as resolve,
                      mock.patch.object(Path, 'lstat', side_effect=AssertionError('unexpected metadata check')) as lstat):
                    with self.assertRaises(helper['KitError']):
                        helper['assert_safe'](self.project, relative, allow_missing=True)
                    resolve.assert_not_called()
                    lstat.assert_not_called()

    def test_safe_path_can_name_a_file_under_a_missing_directory(self):
        helper = runpy.run_path(str(self.helper))
        parent = self.project / 'managed'
        parent.mkdir()
        missing = parent / 'not-created'
        target = missing / 'file.txt'
        with mock.patch.object(Path, 'lstat', autospec=True, side_effect=Path.lstat) as lstat:
            self.assertEqual(target, helper['assert_safe'](self.project, 'managed/not-created/file.txt', allow_missing=True))
        self.assertEqual([mock.call(parent), mock.call(missing)], lstat.call_args_list)
        self.assertFalse(missing.exists())

    def test_embedded_status_rejects_a_managed_link_before_fallback(self):
        marker, _, unknown = self.identity_markers()
        managed, digest = next(iter(unknown['files'].items()))
        target = self.project / managed
        linked = self.project / 'linked-managed'
        if os.name == 'nt':
            from _winapi import CreateJunction
            CreateJunction(str(target.parent), str(linked))
        else:
            linked.symlink_to(target.parent, target_is_directory=True)
        relative = (linked / target.name).relative_to(self.project).as_posix()
        marker.write_text(json.dumps({**unknown, 'files': {relative: digest}}), encoding='utf-8')
        result = self.status()
        self.assertEqual('error', result['status'])
        self.assertIn('symbolic link', result['message'])
        self.assertNotIn('errorCode', result)
