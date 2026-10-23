from pathlib import Path
import contextlib
import hashlib
import importlib.util
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('workflowkit_mirror', ROOT / 'scripts/mirror-release.py')
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)


class MirrorTests(unittest.TestCase):
    def fixture(self, existing=False, corrupt=False, missing=False, draft=False):
        files = {'kit.zip': b'package', 'installer.py': b'installer'}
        descriptor = {'schema': 'workflowkit-release/v1', 'version': '1.0.0', 'assets': {
            'package': {'name': 'kit.zip'}, 'installer': {'name': 'installer.py'}}}
        files['release.json'] = json.dumps(descriptor).encode()
        files['SHA256SUMS'] = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n' for name, data in files.items()).encode()
        base = 'https://github.com/dennis8499/WorkflowKit/releases/download/v1.0.0/'
        release = {'tag_name': 'v1.0.0', 'draft': False, 'prerelease': False, 'body': 'verified release', 'assets': [
            {'name': name, 'size': len(data), 'digest': 'sha256:' + hashlib.sha256(data).hexdigest(), 'browser_download_url': base + name}
            for name, data in files.items()]}
        calls = []
        uploaded = dict(files) if existing else {}
        if missing:
            uploaded.pop('kit.zip', None)
        if corrupt:
            uploaded['kit.zip'] = b'changed'
        api = f'{mirror.GITEA}/api/v1/repos/{mirror.REPOSITORY}'

        def request(url, method='GET', body=None, data=None, content_type=None, raw=False):
            calls.append((url, method, body))
            if url == mirror.GITHUB + '/releases/tags/v1.0.0':
                return release
            if url.startswith(base):
                return files[url[len(base):]]
            if url == api and method == 'GET':
                if existing:
                    return {'full_name': mirror.REPOSITORY}
                raise urllib.error.HTTPError(url, 404, 'missing', {}, None)
            if url == mirror.GITEA + '/api/v1/repos/migrate' and method == 'POST':
                self.assertEqual('https://github.com/dennis8499/WorkflowKit.git', body['clone_addr'])
                self.assertTrue(body['mirror'])
                self.assertFalse(body['private'])
                return {'full_name': mirror.REPOSITORY}
            if url == api + '/releases/tags/v1.0.0':
                if existing:
                    return {'id': 7, 'tag_name': 'v1.0.0', 'draft': draft, 'prerelease': False}
                raise urllib.error.HTTPError(url, 404, 'missing', {}, None)
            if url == api + '/releases' and method == 'POST':
                self.assertEqual('v1.0.0', body['tag_name'])
                self.assertTrue(body['draft'])
                return {'id': 7, 'draft': True}
            if url == api + '/releases/7/assets' and method == 'GET':
                return [{'name': name, 'browser_download_url': mirror.GITEA + '/attachments/' + name} for name in uploaded]
            if '/releases/7/assets?name=' in url and method == 'POST':
                name = url.split('?name=')[1]
                self.assertIn(files[name], data)
                self.assertTrue(content_type.startswith('multipart/form-data;'))
                uploaded[name] = files[name]
                return {'browser_download_url': mirror.GITEA + '/attachments/' + name}
            if url.startswith(mirror.GITEA + '/attachments/'):
                return uploaded[url.rsplit('/', 1)[1]]
            if url == api + '/releases/7' and method == 'PATCH':
                self.assertEqual({'draft': False}, body)
                self.assertEqual(files, uploaded)
                return {}
            raise AssertionError((url, method))
        return request, calls, files, release

    def run_mirror(self, request):
        with patch.object(mirror, 'request', side_effect=request), contextlib.redirect_stdout(io.StringIO()) as output:
            mirror.mirror('v1.0.0')
        return json.loads(output.getvalue())

    def test_creates_public_git_mirror_and_publishes_only_after_all_attachments_match(self):
        request, calls, files, _ = self.fixture()
        result = self.run_mirror(request)
        self.assertEqual(sorted(files), result['assets'])
        self.assertEqual('PATCH', calls[-1][1])

    def test_identical_formal_release_is_read_only_and_idempotent(self):
        request, calls, _, _ = self.fixture(existing=True)
        self.run_mirror(request)
        self.assertTrue(all(method == 'GET' for _, method, _ in calls))

    def test_conflicting_or_incomplete_formal_release_is_preserved(self):
        for arguments in ({'existing': True, 'corrupt': True}, {'existing': True, 'missing': True}):
            with self.subTest(arguments=arguments):
                request, calls, _, _ = self.fixture(**arguments)
                with self.assertRaises(ValueError):
                    self.run_mirror(request)
                self.assertTrue(all(method == 'GET' for _, method, _ in calls))

    def test_incomplete_draft_resumes_and_is_promoted_after_verification(self):
        request, calls, _, _ = self.fixture(existing=True, missing=True, draft=True)
        self.run_mirror(request)
        self.assertEqual(1, sum(method == 'POST' for _, method, _ in calls))
        self.assertEqual('PATCH', calls[-1][1])

    def test_corrupt_source_asset_is_rejected_before_any_mirror_mutation(self):
        request, calls, _, release = self.fixture()
        release['assets'][0]['digest'] = 'sha256:' + '0' * 64
        with self.assertRaises(ValueError):
            self.run_mirror(request)
        self.assertTrue(all(method == 'GET' for _, method, _ in calls))


if __name__ == '__main__':
    unittest.main()
