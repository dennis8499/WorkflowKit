"""Installed session facade smoke; authored fixture decisions do not measure model quality."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import workflow_kit_installer_test as harness


class InstalledReviewerSessionTests(unittest.TestCase):
    execute = harness.WorkflowKitInstallerTests.execute
    install = harness.WorkflowKitInstallerTests.install
    create_group = harness.WorkflowKitInstallerTests.create_group

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='kit-sessions-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.group = self.create_group(self.root)
        installed, data = self.install(self.group)
        self.assertEqual(0, installed.returncode, data)
        self.repo = self.group / 'service'; self.repo.mkdir()
        self.environment = {**os.environ, 'PYTHONPATH': '', 'PYTHONDONTWRITEBYTECODE': '1',
                            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Session fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'core.autocrlf', 'false')
        self.git('config', 'core.longpaths', 'true')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.hooksPath', str(self.root / 'no-hooks'))
        (self.repo / 'app.py').write_text('value = 1\n', encoding='utf-8')
        (self.repo / '.gitignore').write_text('/review-reports/\n', encoding='utf-8')
        self.git('add', '.'); self.git('commit', '-qm', 'base')
        self.git('switch', '-qc', 'feature')
        (self.repo / 'app.py').write_text('value = 2\n', encoding='utf-8')
        self.git('add', '.'); self.git('commit', '-qm', 'constant update')
        (self.repo / 'app.py').write_text('uncommitted = True\n', encoding='utf-8')

    def git(self, *args):
        process = subprocess.run(['git', '-C', str(self.repo), *args], env=self.environment,
                                 capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(0, process.returncode, process.stderr)
        return process.stdout.strip()

    def cli(self, tool, command, *args, code=0, deny_report_write=False):
        script = self.group / '.agents/skills' / tool / 'scripts/review_session.py'
        runner = self.group / '.agents/gitlab-workspace-kit/run.py'
        invocation = [str(script), command, *map(str, args)]
        if deny_report_write:
            # Inject only a staging-file permission failure in the installed
            # process; the facade, runner and frozen validation remain real.
            injection = '''import errno, runpy, sys
from pathlib import Path
from unittest.mock import patch
original = Path.open
def denied(path, *args, **kwargs):
    mode = args[0] if args else kwargs.get("mode", "r")
    if path.parent.name == "review-reports" and path.name.startswith((".merge-review-", ".release-report-")) and any(flag in mode for flag in "wx"):
        raise PermissionError(errno.EACCES, "fixture report output unavailable", str(path))
    return original(path, *args, **kwargs)
sys.argv = sys.argv[1:]
sys.path.insert(0, str(Path(sys.argv[0]).parent))
with patch.object(Path, "open", denied):
    runpy.run_path(sys.argv[0], run_name="__main__")
'''
            invocation = ['-c', injection, *invocation]
        process = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(runner), '--',
                                  sys.executable, '-X', 'utf8', '-B', *invocation],
            cwd=self.repo, env=self.environment, capture_output=True, text=True, encoding='utf-8', timeout=90)
        self.assertIn(process.returncode, (code,) if isinstance(code, int) else code,
                      process.stderr or process.stdout)
        if command == 'view':
            self.assertLessEqual(len(process.stdout.encode('utf-8')), 24 * 1024)
        return json.loads(process.stdout)

    def routing(self, tool, command, runtime, identifier, *args):
        script = self.group / '.agents/skills/model-routing/scripts/routing.py'
        process = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(script), command,
            '--tool', tool, '--runtime-root', str(runtime), '--request-id', identifier, *map(str, args)],
            cwd=self.repo, env=self.environment, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(0, process.returncode, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def test_bound_launch_uses_real_native_preflight_resume_and_readonly_inspection(self):
        tool = 'merge-reviewer'
        skill = self.group / '.agents/skills' / tool
        script = skill / 'scripts/review_session.py'
        runner = self.group / '.agents/gitlab-workspace-kit/run.py'
        launch_script = runner.with_name('review_launch.py')
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        rows = [[path.relative_to(skill).as_posix(), digest(path)] for path in skill.rglob('*')
                if path.is_file() and not any(part in ('__pycache__', '.pytest_cache', '.git') for part in path.parts)
                and path.suffix != '.pyc']
        rows.sort(key=lambda row: row[0].encode('utf-8'))
        binding = {'schema': 'InstalledReviewerBinding/v1', 'tool': tool,
            'version': (skill / 'VERSION').read_text(encoding='utf-8').strip(),
            'script_path': str(script), 'script_sha256': digest(script), 'skill_sha256': digest(skill / 'SKILL.md'),
            'payload_sha256': hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest(),
            'payload_files': len(rows), 'workflow_kit_runner': {'script_path': str(runner),
                'script_sha256': digest(runner), 'review_launch_sha256': digest(launch_script),
                'review_launch_request': 1, 'read_only_inspection': True}}
        runtime = self.root / 'bound-runtime'
        identifier = 'd' * 32
        request = {'schema': 'ReviewLaunchRequest/v1', 'tool': tool, 'request_id': identifier,
                   'workspace': str(self.repo), 'project': str(self.repo), 'base': 'main', 'head': 'feature',
                   'runtime_root': str(runtime), 'binding': binding, 'draft_format': 'compact', 'no_fetch': True}
        path = runtime.with_name(runtime.name + '-workflow-kit') / 'launch' / (identifier + '.json')
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
        request_hash = digest(path)

        def invoke(action, *extra, code=0):
            process = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(runner), '--review-request', str(path),
                '--expected-request-sha256', request_hash, '--action', action, *map(str, extra)],
                cwd=self.repo, env=self.environment, capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(code, process.returncode, process.stderr or process.stdout)
            return json.loads(process.stdout)

        def snapshot():
            return {str(item): (item.stat().st_mtime_ns, digest(item)) for item in self.root.rglob('*') if item.is_file()}

        before = snapshot()
        self.assertTrue(invoke('preflight')['valid'])
        self.assertEqual(before, snapshot())
        self.assertFalse(runtime.exists())
        started = invoke('start')
        context = Path(started['context_dir'])
        self.assertEqual('merge-reviewer-authoring/v1', json.loads((context / 'draft.json').read_text(encoding='utf-8'))['schema'])
        self.assertEqual(str(context), invoke('start')['context_dir'])
        self.assertEqual(1, len(list((runtime / 'jobs').glob('*.json'))))
        request_file = self.root / 'read-evidence.json'
        request_file.write_text(json.dumps([{'id': 'bound-read', 'op': 'read', 'repo': started['selected_repo'],
                                            'source': 'head', 'path': 'app.py'}]), encoding='utf-8')
        stepped = self.cli(tool, 'step', '--runtime-root', runtime, '--request-id', identifier,
                           '--requests-file', request_file)
        before = snapshot()
        self.assertEqual('MergeReviewStatusSummary/v1', invoke('status')['schema'])
        viewed = invoke('view', '--', '--artifact', stepped['operations'][0]['artifact'])
        self.assertTrue(viewed)
        self.assertEqual(before, snapshot())
        self.assertFalse(invoke('check', code=3)['expected_outcome']['review_complete'])
        invoke('cancel')

    def test_both_installed_facades_check_resume_publish_retry_and_cancel_independently(self):
        before = self.git('status', '--porcelain')
        outputs = []
        identifier = 'a' * 32
        for tool, job_schema in (('merge-reviewer', 'MergeReviewSession/v1'),
                                 ('release-reviewer', 'ReleaseReviewSession/v1')):
            with self.subTest(tool=tool):
                capabilities = self.cli(tool, 'capabilities')
                self.assertEqual(harness.CURRENT_SOURCES[tool]['version'], capabilities['skill_version'])
                self.assertTrue(capabilities['features']['publication_retry'])
                draft_arguments = []
                if tool == 'merge-reviewer':
                    self.assertIn('compact', capabilities['draft_formats'])
                    self.assertTrue(capabilities['features']['read_only_artifact_view'])
                    self.assertTrue(capabilities['features']['batch_artifact_view'])
                    self.assertTrue(capabilities['features']['validation_progress'])
                    draft_arguments = ['--draft-format', 'compact']
                else:
                    self.assertTrue(capabilities['features']['runtime_paths'])
                    self.assertTrue(capabilities['features']['read_only_batch_view'])
                    self.assertTrue(capabilities['features']['base_final_review'])
                    skill = self.group / '.agents/skills' / tool
                    rows = [[path.relative_to(skill).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()]
                            for path in skill.rglob('*') if path.is_file() and '__pycache__' not in path.parts
                            and path.suffix != '.pyc']
                    rows.sort(key=lambda row: row[0].encode('utf-8'))
                    installed_sha = hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
                    self.assertEqual(installed_sha, capabilities['payload_sha256'])
                runtime = self.root / tool
                start = self.cli(tool, 'start', '--workspace', self.repo, '--project', self.repo,
                    '--base', 'main', '--head', 'feature', '--runtime-root', runtime, '--request-id', identifier,
                    *draft_arguments)
                self.assertEqual(0, start['network_activity']['fetch_attempt_count'])
                context = Path(start['context_dir'])
                route = self.routing(tool, 'bind', runtime, identifier, '--effort', 'high')
                self.assertEqual('high', route['effort'])
                self.assertEqual('reviewing', route['phase'])
                if tool == 'merge-reviewer':
                    draft = json.loads(Path(start['draft_path']).read_text(encoding='utf-8'))
                    self.assertEqual('merge-reviewer-authoring/v1', draft['schema'])
                self.assertEqual(job_schema, json.loads((runtime / 'jobs' / (identifier + '.json')).read_text(encoding='utf-8'))['schema'])
                manifest = json.loads((context / 'manifest.json').read_text(encoding='utf-8'))
                arguments = ['--runtime-root', runtime, '--request-id', identifier]
                self.assertEqual('ready', self.cli(tool, 'status', *arguments)['state'])
                check = self.cli(tool, 'check', *arguments, code=3 if tool == 'merge-reviewer' else 0)
                self.assertFalse(check['evidence_verified'])
                self.assertEqual(0, check['git_commands'])
                if tool == 'release-reviewer':
                    self.assertEqual(['app.py'], check['remaining']['changes'])
                    self.assertEqual({'config', 'db', 'ftp', 'sftp', 'redis', 'kafka', 'other'}, set(check['remaining']['dependencies']))
                selected = start.get('selected_repo', 'entry')
                operations = [{'id': source, 'op': 'read', 'repo': selected, 'source': source, 'path': 'app.py',
                               'line_start': 1, 'line_end': 1} for source in ('base', 'head', 'merge-preview')]
                requests = context / 'installed-round.json'
                requests.write_text(json.dumps(operations), encoding='utf-8')
                first_step = self.cli(tool, 'step', *arguments, '--requests-file', requests)
                self.assertTrue(first_step['complete'])
                if tool == 'merge-reviewer':
                    scripts = self.group / '.agents/skills/merge-reviewer/scripts'
                    spec = importlib.util.spec_from_file_location(
                        'workflow_kit_test_merge_runtime', scripts / 'review_runtime.py')
                    runtime_module = importlib.util.module_from_spec(spec)
                    sys.path.insert(0, str(scripts))
                    try:
                        spec.loader.exec_module(runtime_module)
                        artifact = runtime_module.store_view(
                            context, {'operations': [{'id': 'saved-result', 'result': {'text': 'fixed evidence'}}]})
                    finally:
                        sys.path.remove(str(scripts))
                    manifest_path = context / 'manifest.json'
                    before_view = manifest_path.read_bytes()
                    viewed = self.cli(tool, 'view', *arguments, '--artifact-scope', 'context',
                                      '--artifact', artifact, '--pointer', '/operations', '--offset', '0',
                                      '--page-size', '1')
                    self.assertEqual('context', viewed['scope'])
                    self.assertEqual(artifact, viewed['artifact'])
                    self.assertTrue(viewed['view_complete'])
                    self.assertEqual(before_view, manifest_path.read_bytes())
                for malformed in (None, '{broken'):
                    if malformed is None:
                        requests.unlink()
                    else:
                        requests.write_text(malformed, encoding='utf-8')
                    repair = self.cli(tool, 'step', *arguments, '--requests-file', requests, code=3)
                    self.assertFalse(repair['terminal'])
                    self.assertTrue(repair['recoverable'])
                    self.assertTrue(repair['context_retained'])
                    errors = repair.get('errors', [repair])
                    self.assertTrue(any(row['code'] == 'authoring.invalid-requests-file' and
                                        row['pointer'] == '/requests_file' for row in errors))
                    waiting = self.cli(tool, 'status', *arguments)
                    self.assertEqual('reviewing', waiting['state'])
                    self.assertEqual('input-repair', waiting['phase'])
                    self.assertTrue(context.is_dir())
                    requests.write_text(json.dumps(operations), encoding='utf-8')
                    repaired = self.cli(tool, 'step', *arguments, '--requests-file', requests)
                    self.assertTrue(repaired['complete'])
                    for original, replayed in zip(first_step['operations'], repaired['operations'], strict=True):
                        self.assertEqual(original['id'], replayed['id'])
                        self.assertEqual(original['result'], replayed['result'])
                        self.assertTrue(replayed.get('reused') is True or replayed.get('artifact') == original['artifact'])
                resumed = self.cli(tool, 'status', *arguments)
                self.assertEqual(identifier, resumed['request_id'])
                self.assertIn('resume', resumed)
                draft_path = Path(start['draft_path'])
                draft = json.loads(draft_path.read_text(encoding='utf-8'))
                draft['summary'] = 'Authored fixture: only the fixed constant changes; no product claim.'
                if tool == 'merge-reviewer':
                    seed = next(row for row in manifest['repositories'] if row['id'] == selected)
                    evidence = [{'repo': selected, 'source': source, 'ref': seed['sources'][source]['ref'],
                                 'path': 'app.py', 'line_start': 1, 'line_end': 1}
                                for source in ('base', 'head', 'merge-preview')]
                else:
                    evidence = [{'repo': 'entry', 'source': 'head', 'ref': manifest['head_sha'], 'path': 'app.py', 'line_start': 1, 'line_end': 1},
                                {'repo': 'entry', 'source': 'merge-preview', 'ref': manifest['merge_preview']['tree_sha'], 'path': 'app.py', 'line_start': 1, 'line_end': 1}]
                    for row in draft['dependency_coverage']:
                        row.update(status='reviewed', reason='Fixed constant update introduces no resource use.', evidence=evidence)
                for row in draft['coverage']:
                    row.update(status='reviewed', reason='Compared both fixed constant values and the final tree.', evidence=evidence)
                draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
                self.cli(tool, 'check', *arguments)
                frozen_manifest = (context / 'manifest.json').read_bytes()
                failed = self.cli(tool, 'finish', *arguments, code=3, deny_report_write=True)
                self.assertTrue(failed['recoverable'])
                self.assertTrue(failed['context_retained'])
                self.assertEqual('publication.output-unavailable' if tool == 'merge-reviewer' else 'publication.io',
                                 failed['errors'][0]['code'])
                self.assertEqual(frozen_manifest, (context / 'manifest.json').read_bytes())
                retry_status = self.cli(tool, 'status', *arguments)
                self.assertEqual(identifier, retry_status['request_id'])
                self.assertEqual(0, retry_status['network_activity']['fetch_attempt_count'])
                self.assertEqual(draft, json.loads(draft_path.read_text(encoding='utf-8')))
                published = self.cli(tool, 'finish', *arguments)
                route = self.routing(tool, 'complete', runtime, identifier, '--revision', route['revision'])
                self.assertEqual('complete', route['phase'])
                self.assertEqual(route['snapshot_hash'], self.routing(tool, 'status', runtime, identifier)['snapshot_hash'])
                report = Path(published['report_path']); outputs.append(report)
                body = report.read_text(encoding='utf-8')
                self.assertEqual(['## ' + heading for heading in ('審查結論', '問題總攬', '問題詳情（工程師參考）', '範圍與限制', '技術審查紀錄（工程師參考）')],
                                 [line for line in body.splitlines() if line.startswith('## ')])
                self.assertFalse(context.exists())
                self.assertTrue(published['review_outcome']['review_complete'])
                self.assertTrue(self.cli(tool, 'status', *arguments)['review_outcome']['review_complete'])
                if tool == 'merge-reviewer':
                    progress = self.cli(tool, 'status', *arguments, '--summary')['progress']
                    self.assertIn('validation', progress)
                    self.assertIn('validation_updated_at', progress)
                self.assertEqual(str(report), self.cli(tool, 'finish', *arguments)['report_path'])
                self.assertEqual(body, report.read_text(encoding='utf-8'))
                cancelled_id = 'b' * 32
                cancel_start = self.cli(tool, 'start', '--workspace', self.repo, '--project', self.repo,
                    '--base', 'main', '--head', 'feature', '--runtime-root', runtime, '--request-id', cancelled_id)
                cancelled = self.cli(tool, 'cancel', '--runtime-root', runtime, '--request-id', cancelled_id)
                self.assertEqual('cancelled', cancelled['state'])
                self.assertFalse(Path(cancel_start['context_dir']).exists())
        self.assertEqual(2, len(outputs), 'Both installed reviewers must publish successfully')
        self.assertNotEqual(outputs[0], outputs[1])
        self.assertEqual(2, len(list((self.repo / 'review-reports').glob('*.md'))))
        self.assertEqual(before, self.git('status', '--porcelain'))

    def test_installed_batch_views_keep_batch_and_page_continuations_read_only(self):
        for tool in ('merge-reviewer', 'release-reviewer'):
            with self.subTest(tool=tool):
                runtime, identifier = self.root / tool, 'e' * 32
                start = self.cli(tool, 'start', '--workspace', self.repo, '--project', self.repo,
                    '--base', 'main', '--head', 'feature', '--runtime-root', runtime, '--request-id', identifier)
                context = Path(start['context_dir'])
                arguments = ['--runtime-root', runtime, '--request-id', identifier]
                values = ['中文字' * 40 for _ in range(100)]
                fixture = self.root / (tool + '-artifact.json')
                fixture.write_text(json.dumps(values, ensure_ascii=False), encoding='utf-8')
                scripts = self.group / '.agents/skills' / tool / 'scripts'
                store = subprocess.run([sys.executable, '-X', 'utf8', '-B',
                    str(self.group / '.agents/gitlab-workspace-kit/run.py'), '--',
                    sys.executable, '-X', 'utf8', '-B', '-c',
                    'import json,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                    'import review_runtime; print(review_runtime.store_view(Path(sys.argv[2]), '
                    'json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))))',
                    str(scripts), str(context), str(fixture)], cwd=self.repo, env=self.environment,
                    capture_output=True, text=True, encoding='utf-8', timeout=30)
                self.assertEqual(0, store.returncode, store.stderr or store.stdout)
                artifact = store.stdout.strip()
                requests = self.root / (tool + '-views.json')
                requests.write_text(json.dumps([{'id': f'page-{n}', 'artifact': artifact} for n in range(4)]),
                                    encoding='utf-8')
                before = {p.relative_to(context): p.read_bytes() for p in context.rglob('*') if p.is_file()}
                offset, identifiers, first_page, batches = 0, [], None, 0
                while True:
                    # Merge uses exit 3 for a valid unfinished batch; Release
                    # returns exit 0 with its separate continuation marker.
                    result = self.cli(tool, 'view', *arguments, '--requests-file', requests, '--offset', offset,
                                      code=(0, 3) if tool == 'merge-reviewer' else 0)
                    batches += 1
                    identifiers.extend(row['id'] for row in result['results'])
                    for row in result['results']:
                        page = row['result']
                        self.assertEqual(len(values), page['total'])
                        self.assertIn('continue', page)
                        if first_page is None:
                            first_page = page
                    if result['complete']:
                        break
                    self.assertGreater(result['next_index'], offset)
                    offset = result['next_index']
                self.assertGreater(batches, 1)
                self.assertEqual([f'page-{n}' for n in range(4)], identifiers)
                observed = list(first_page['items'])
                offset = first_page['next_offset']
                while offset is not None:
                    page = self.cli(tool, 'view', *arguments, '--artifact', artifact, '--offset', offset)
                    observed.extend(page['items'])
                    following = page['next_offset']
                    self.assertTrue(following is None or following > offset)
                    offset = following
                self.assertEqual(values, observed)
                self.assertEqual(before, {p.relative_to(context): p.read_bytes()
                                         for p in context.rglob('*') if p.is_file()})
                self.assertEqual('cancelled', self.cli(tool, 'cancel', *arguments)['state'])

    def test_published_incomplete_outcomes_survive_cleanup_retry_and_legacy_metadata_is_unknown(self):
        before = self.git('status', '--porcelain')
        for tool in ('merge-reviewer', 'release-reviewer'):
            with self.subTest(tool=tool):
                runtime = self.root / tool
                identifier = 'c' * 32
                start = self.cli(tool, 'start', '--workspace', self.repo, '--project', self.repo,
                    '--base', 'main', '--head', 'feature', '--runtime-root', runtime, '--request-id', identifier)
                draft_path = Path(start['draft_path'])
                draft = json.loads(draft_path.read_text(encoding='utf-8'))
                draft['summary'] = 'Installed fixture intentionally leaves review coverage incomplete.'
                draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
                arguments = ['--runtime-root', runtime, '--request-id', identifier]
                published = self.cli(tool, 'finish', *arguments)
                self.assertEqual('published', published['state'])
                self.assertFalse(Path(start['context_dir']).exists())
                outcome = published['review_outcome']
                self.assertTrue(outcome['outcome_available'])
                self.assertFalse(outcome['review_complete'])
                self.assertTrue(outcome['gaps'])
                self.assertTrue(outcome['remaining']['changes'])
                report = Path(published['report_path'])
                body = report.read_bytes()
                self.assertEqual(outcome, self.cli(tool, 'status', *arguments)['review_outcome'])
                checked = self.cli(tool, 'check', *arguments, code=3)
                self.assertEqual(outcome, checked['review_outcome'])
                self.assertFalse(checked['review_complete'])
                self.assertTrue(checked['gaps'])
                self.assertFalse(checked['evidence_verified'])
                self.assertEqual(0, checked['git_commands'])
                self.assertEqual(outcome, self.cli(tool, 'finish', *arguments)['review_outcome'])
                self.assertEqual(body, report.read_bytes())
                # Simulate a genuine old publication record, without inspecting the Markdown.
                job_path = runtime / 'jobs' / (identifier + '.json')
                job = json.loads(job_path.read_text(encoding='utf-8'))
                job.pop('review_outcome', None)
                if isinstance(job.get('report_receipt'), dict):
                    job['report_receipt'].pop('review_outcome', None)
                job_path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
                legacy = self.cli(tool, 'status', *arguments)['review_outcome']
                self.assertFalse(legacy['outcome_available'])
                self.assertIsNone(legacy['review_complete'])
                self.assertEqual('unknown', legacy['review_status'])
                self.assertTrue(legacy['gaps'])
                checked_legacy = self.cli(tool, 'check', *arguments, code=3)
                self.assertIsNone(checked_legacy['review_complete'])
                self.assertTrue(checked_legacy['gaps'])
                self.assertEqual(0, checked_legacy['git_commands'])
        self.assertEqual(2, len(list((self.repo / 'review-reports').glob('*.md'))))
        self.assertEqual(before, self.git('status', '--porcelain'))

    def test_installed_merge_check_rejects_own_impact_source_mismatch_and_preserves_the_request(self):
        peer = self.group / 'consumer'; peer.mkdir()
        for args in (('init', '-q', '-b', 'main'),
                     ('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                      '-c', 'commit.gpgsign=false', 'commit', '-q', '--allow-empty', '-m', 'peer')):
            process = subprocess.run(['git', '-C', str(peer), *args], env=self.environment,
                                     capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(0, process.returncode, process.stderr)
        runtime, identifier = self.root / 'merge-group', 'd' * 32
        start = self.cli('merge-reviewer', 'start', '--workspace', self.group, '--project', self.repo,
            '--base', 'main', '--head', 'feature', '--runtime-root', runtime, '--request-id', identifier)
        context = Path(start['context_dir'])
        arguments = ['--runtime-root', runtime, '--request-id', identifier]
        manifest = json.loads((context / 'manifest.json').read_text(encoding='utf-8'))
        self.assertTrue(manifest['extension_enabled'])
        selected = start['selected_repo']
        seed = next(row for row in manifest['repositories'] if row['id'] == selected)
        root = next(row for row in manifest['required_coverage'] if row['path'] == 'app.py')
        evidence = {'repo': selected, 'source': 'head', 'path': 'app.py',
                    'ref': seed['sources']['head']['ref'], 'line_start': 1, 'line_end': 1}
        contract = {'id': 'C-001', 'root': root, 'kind': 'behavior', 'symbol': 'value', 'evidence': evidence,
                    'search_terms': [{'query': value, 'reason': 'Fixed constant name and complete changed line.'}
                                     for value in ('value', 'value = 2')]}
        requests = context / 'contract-round.json'
        requests.write_text(json.dumps([{'id': 'contract', 'op': 'register-contract', 'contract': contract}]), encoding='utf-8')
        self.assertTrue(self.cli('merge-reviewer', 'step', *arguments, '--requests-file', requests)['complete'])
        draft_path = Path(start['draft_path'])
        draft = json.loads(draft_path.read_text(encoding='utf-8'))
        draft['summary'] = 'Installed diagnostic fixture leaves supporting review explicitly incomplete.'
        draft['impact_coverage'] = [{'id': 'I-001', 'repo': selected, 'source': 'merge-base', 'path': 'app.py',
            'status': 'reviewed', 'reason': 'Compare the fixed own path.', 'contract_ids': ['C-001'],
            'related_to': [], 'evidence': [evidence]}]
        own_error = 'authoring.impact-evidence-must-cover-its-own-fixed-path-source'
        draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
        checked = self.cli('merge-reviewer', 'check', *arguments, code=3)
        self.assertEqual(['/impact_coverage/0/evidence'],
                         [row['pointer'] for row in checked['errors'] if row['code'] == own_error])
        self.assertEqual(0, checked['git_commands'])
        self.assertFalse(checked['evidence_verified'])
        draft['impact_coverage'][0]['source'] = 'head'
        draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
        repaired = self.cli('merge-reviewer', 'check', *arguments, code=3)
        self.assertFalse(any(row['code'] == own_error for row in repaired['errors']))
        self.assertEqual(0, repaired['git_commands'])
        self.assertEqual(identifier, self.cli('merge-reviewer', 'status', *arguments)['request_id'])
        self.assertTrue(context.is_dir())
        self.assertEqual('cancelled', self.cli('merge-reviewer', 'cancel', *arguments)['state'])
        self.assertFalse(context.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
