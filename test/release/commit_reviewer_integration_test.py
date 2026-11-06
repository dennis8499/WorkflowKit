"""Exercise CommitReviewer from installed profiles and the official 1.4 predecessor."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import workflow_kit_installer_test as harness


class CommitReviewerIntegrationTests(unittest.TestCase):
    execute = harness.WorkflowKitInstallerTests.execute
    install = harness.WorkflowKitInstallerTests.install
    create_group = harness.WorkflowKitInstallerTests.create_group
    status = harness.WorkflowKitInstallerTests.status

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='kit-commit-reviewer-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.env = dict(os.environ, GIT_AUTHOR_NAME='Developer', GIT_AUTHOR_EMAIL='dev@example.test',
                        GIT_COMMITTER_NAME='Developer', GIT_COMMITTER_EMAIL='dev@example.test')

    def git(self, repo, *args):
        result = subprocess.run(['git', '-C', str(repo), '-c', 'core.hooksPath=', '-c', 'commit.gpgsign=false', *args],
                                env=self.env, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout.strip()

    def helper(self, install, *args):
        return subprocess.run([sys.executable, '-X', 'utf8', '-B',
            str(install / '.agents/gitlab-workspace-kit/run.py'), '--', sys.executable, '-X', 'utf8', '-B',
            str(install / '.agents/skills/commit-reviewer/scripts/commit_review.py'), *map(str, args)],
            env=self.env, capture_output=True, text=True, encoding='utf-8')

    def test_both_profiles_run_both_native_modes_with_saved_report_exit_codes(self):
        for profile in ('group', 'repository'):
            with self.subTest(profile=profile):
                base = self.root / profile
                base.mkdir()
                target = self.create_group(base)
                repo = target / 'service' if profile == 'group' else target
                repo.mkdir(exist_ok=True)
                self.git(repo, 'init', '-b', 'main')
                self.git(repo, 'config', 'user.email', 'dev@example.test')
                (repo / 'feature.txt').write_text('base\n', encoding='utf-8')
                self.git(repo, 'add', 'feature.txt')
                self.git(repo, 'commit', '-m', 'feat: baseline\n\nRefs: #1')
                remote = base / 'remote.git'
                self.git(repo, 'clone', '--bare', str(repo), str(remote))
                self.git(repo, 'remote', 'add', 'origin', str(remote))
                self.git(repo, 'switch', '-c', 'feature/test')
                installed, data = self.install(target, profile=profile)
                self.assertEqual(0, installed.returncode, data)
                self.assertTrue({'commit-draft', 'mr-precheck'} <= set(self.status(target)['capabilities']))
                for mode in ('commit', 'mr'):
                    (repo / 'feature.txt').write_text('staged\n', encoding='utf-8')
                    self.git(repo, 'add', 'feature.txt')
                    if mode == 'mr':
                        self.git(repo, 'commit', '-m', 'feat: update\n\nRefs: #123')
                    (repo / 'feature.txt').write_text('unstaged\n', encoding='utf-8')
                    before = self.git(repo, 'diff', '--cached', '--binary')
                    evidence = base / ('evidence-' + mode)
                    args = ['inspect', '--repo', repo, '--mode', mode, '--output-dir', evidence]
                    args += ['--issue', '#123'] if mode == 'commit' else ['--remote', 'origin', '--target', 'main']
                    inspected = self.helper(target, *args)
                    self.assertEqual(0, inspected.returncode, inspected.stderr)
                    captured = json.loads(inspected.stdout)
                    pending = self.helper(target, 'report', '--snapshot', captured['snapshot'], '--analysis', captured['analysis'])
                    self.assertEqual(3, pending.returncode, pending.stderr)
                    self.assertTrue(Path(json.loads(pending.stdout)['report']).is_file())
                    analysis_path = Path(captured['analysis'])
                    analysis = json.loads(analysis_path.read_text(encoding='utf-8'))
                    analysis.update(summary='Update the staged feature.', diff_reviewed=True, commit_message='feat: update\n\nRefs: #123')
                    analysis_path.write_text(json.dumps(analysis), encoding='utf-8')
                    report = self.helper(target, 'report', '--snapshot', captured['snapshot'], '--analysis', analysis_path)
                    self.assertEqual(0, report.returncode, report.stderr or report.stdout)
                    result = json.loads(report.stdout)
                    self.assertEqual('pass', result['status'])
                    self.assertEqual(repo / 'review-reports', Path(result['report']).parent)
                    self.assertNotIn('+unstaged', Path(captured['patch']).read_text(encoding='utf-8'))
                    self.assertEqual(before, self.git(repo, 'diff', '--cached', '--binary'))

    def test_official_140_upgrade_and_rollback_preserve_user_content_in_both_profiles(self):
        fixture = harness.ROOT / 'test/fixtures/workflow-kit-1.4.0'
        for profile in ('group', 'repository'):
            with self.subTest(profile=profile):
                base = self.root / profile
                base.mkdir()
                target = self.create_group(base, wiki='# Personal Wiki\n')
                if profile == 'repository':
                    self.git(target, 'init', '-b', 'main')
                with mock.patch.object(harness, 'INSTALLER', fixture / 'installer.py'):
                    old, output = self.install(target, archive=fixture / 'workflow-kit.tar.xz', version='1.4.0', profile=profile)
                self.assertEqual(0, old.returncode, output)
                previous = (target / harness.MARKER).read_bytes()
                updated, output = self.install(target, profile=profile)
                self.assertEqual(0, updated.returncode, output)
                self.assertTrue((target / '.agents/skills/commit-reviewer/VERSION').is_file())
                reverted, receipt = self.execute('rollback', target, output['transaction'])
                self.assertEqual(0, reverted.returncode, receipt)
                self.assertEqual(previous, (target / harness.MARKER).read_bytes())
                self.assertFalse((target / '.agents/skills/commit-reviewer').exists())
                self.assertEqual('# Personal Wiki\n', (target / 'wiki/index.md').read_text(encoding='utf-8'))
                self.assertIn('Keep this user text.', (target / 'AGENTS.md').read_text(encoding='utf-8'))
                self.assertEqual('old report\n', (target / 'review-reports/previous/report.md').read_text(encoding='utf-8'))
