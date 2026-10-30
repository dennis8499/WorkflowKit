"""Fixed remaining upstream packages match their local source distributions."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('workflow_kit_sources_tests', ROOT / 'scripts/workflow-kit-sources.py')
sources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sources)


class SourceSummaryTests(unittest.TestCase):
    def test_codebase_wiki_archive_root_tracks_the_upstream_version(self):
        self.assertEqual(
            'codebase-llm-wiki-codex-0.7.0',
            sources.archive_root('codebase-wiki', '0.7.0', {'root': 'codebase-llm-wiki-codex-0.6.4'}),
        )

    def test_vendor_bytes_keep_release_line_endings(self):
        data = b'line one\r\nline two\n'
        self.assertEqual(data, sources.normalize_source_text(
            'codebase-wiki', '.agents/skills/codebase-wiki/vendor/archify/SKILL.md', data,
        ))
        self.assertEqual(data, sources.normalize_source_text(
            'codebase-wiki', '.agents/skills/codebase-wiki/vendor/archify-manifest.json', data,
        ))
        self.assertEqual(b'line one\nline two\n', sources.normalize_source_text(
            'codebase-wiki', '.agents/skills/codebase-wiki/references/intent-routing.md', data,
        ))

    def test_source_notes_follow_each_new_pin_instead_of_a_historical_version(self):
        spec = importlib.util.spec_from_file_location('workflow_kit_summary_test', ROOT / 'scripts/build-workflow-kit.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        versions = {'codebase-wiki': '91.2.3',
                    'merge-reviewer': '93.4.5', 'release-reviewer': '94.5.6',
                    'bmad-method': '96.7.8'}
        notes = builder.source_summary({tool: {'version': version} for tool, version in versions.items()})
        self.assertEqual(4, len(notes))
        for note, tool, label in zip(notes, versions, ('Codebase LLM Wiki', 'MergeReviewer', 'ReleaseReviewer', 'BMAD Method')):
            prefix = f'Official {label} {versions[tool]} ' if tool == 'bmad-method' else f'Native {label} {versions[tool]} '
            self.assertTrue(note.startswith(prefix), note)


class SourcePackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='kit-upstream-source-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.workspace = self.base / 'GitlabWorkSpace'
        self.reviewer = self.base / 'MergeReviewer'
        (self.workspace / 'scripts').mkdir(parents=True)
        shutil.copyfile(ROOT / 'scripts/build-workflow-kit.py', self.workspace / 'scripts/build-workflow-kit.py')
        shutil.copyfile(ROOT / 'VERSION', self.workspace / 'VERSION')
        snapshot = json.loads((ROOT / 'resources/offline-tools/source-snapshots.json').read_text(encoding='utf-8'))
        snapshot['sources'] = {'merge-reviewer': snapshot['sources']['merge-reviewer']}
        snapshot['workspaceFiles'] = {}
        directory = self.workspace / 'resources/offline-tools'
        (directory / 'sources').mkdir(parents=True)
        self.snapshot = directory / 'source-snapshots.json'
        self.snapshot.write_text(json.dumps(snapshot), encoding='utf-8')
        archive = snapshot['sources']['merge-reviewer']['filename']
        shutil.copyfile(ROOT / 'resources/offline-tools/sources' / archive, directory / 'sources' / archive)
        with zipfile.ZipFile(directory / 'sources' / archive) as stream:
            for item in stream.infolist():
                if item.is_dir():
                    continue
                name = Path(item.filename)
                self.assertEqual(name.parts[0], 'merge-reviewer')
                target = self.reviewer / 'skills' / name
                self.assertTrue(target.resolve().is_relative_to(self.reviewer))
                data = stream.read(item)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(sources, 'ROOT', self.workspace).start()
        mock.patch.object(sources, 'SNAPSHOTS', self.snapshot).start()

    def test_complete_reviewer_package_matches_local_distribution(self):
        result = sources.check(compare_local=True)
        self.assertTrue(result['ok'])
        record = json.loads(self.snapshot.read_text(encoding='utf-8'))['sources']['merge-reviewer']
        self.assertTrue({'SKILL.md', 'VERSION'} <= set(record['files']))
        self.assertIn('scripts/review_workspace.py', record['files'])

    def test_package_document_and_version_drift_are_rejected(self):
        for name in ('SKILL.md', 'VERSION'):
            with self.subTest(name=name):
                path = self.reviewer / 'skills/merge-reviewer' / name
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b'changed\n')
                    with self.assertRaisesRegex(ValueError, 'local source drift'):
                        sources.check(compare_local=True)
                finally:
                    path.write_bytes(original)

    def test_windows_text_line_endings_match_without_changing_archive_identity(self):
        before = self.snapshot.read_bytes()
        directory = self.reviewer / 'skills/merge-reviewer'
        for path in directory.rglob('*'):
            if path.is_file() and (path.suffix.lower() in ('.md', '.py', '.yaml', '.yml', '.json', '.txt', '.toml') or path.name == 'VERSION'):
                path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
        self.assertTrue(sources.check(compare_local=True)['ok'])
        self.assertEqual(before, self.snapshot.read_bytes())

    def test_binary_source_bytes_are_not_normalized(self):
        target = self.reviewer / 'skills/merge-reviewer/payload.bin'
        target.write_bytes(b'a\r\nb')
        _, entries = sources.local_entries('merge-reviewer')
        self.assertEqual(b'a\r\nb', entries['payload.bin'])
        with self.assertRaisesRegex(ValueError, 'local source drift'):
            sources.check(compare_local=True)

    def test_scoped_freeze_preserves_unselected_source_without_reading_its_live_checkout(self):
        snapshot = json.loads(self.snapshot.read_text(encoding='utf-8'))
        release = json.loads((ROOT / 'resources/offline-tools/source-snapshots.json').read_text(encoding='utf-8'))['sources']['release-reviewer']
        snapshot['sources']['release-reviewer'] = release
        self.snapshot.write_text(json.dumps(snapshot), encoding='utf-8')
        archive = self.workspace / 'resources/offline-tools/sources' / release['filename']
        shutil.copyfile(ROOT / 'resources/offline-tools/sources' / release['filename'], archive)
        before = archive.read_bytes()
        read = sources.local_entries
        with mock.patch.object(sources, 'REPOS', {'merge-reviewer': 'MergeReviewer', 'release-reviewer': 'ReleaseReviewer'}), \
             mock.patch.object(sources, 'git_info', return_value={'commit': 'a' * 40, 'dirty': False}), \
             mock.patch.object(sources, 'local_entries', side_effect=lambda tool: read(tool) if tool == 'merge-reviewer' else self.fail('Read unselected source')):
            result = sources.freeze(['merge-reviewer'])
        self.assertTrue(result['ok'])
        self.assertFalse(result['localCompared'])
        self.assertEqual(release, json.loads(self.snapshot.read_text(encoding='utf-8'))['sources']['release-reviewer'])
        self.assertEqual(before, archive.read_bytes())


class WikiFreezeRegressionTests(unittest.TestCase):
    def test_wiki_freeze_uses_new_root_is_stable_and_preserves_other_sources(self):
        with tempfile.TemporaryDirectory(prefix='kit-wiki-freeze-') as temporary:
            base = Path(temporary).resolve()
            workspace = base / 'GitlabWorkSpace'
            (workspace / 'scripts').mkdir(parents=True)
            (workspace / 'resources/offline-tools/sources').mkdir(parents=True)
            (workspace / 'resources/workflow-kit').mkdir(parents=True)
            shutil.copyfile(ROOT / 'scripts/build-workflow-kit.py', workspace / 'scripts/build-workflow-kit.py')
            shutil.copyfile(ROOT / 'VERSION', workspace / 'VERSION')

            original = json.loads((ROOT / 'resources/offline-tools/source-snapshots.json').read_text(encoding='utf-8'))
            unselected_record = original['sources']['merge-reviewer']
            snapshots = workspace / 'resources/offline-tools/source-snapshots.json'
            snapshots.write_text(json.dumps({
                'schema': original['schema'],
                'sources': {'merge-reviewer': unselected_record},
                'workspaceFiles': {},
                'capabilities': original['capabilities'],
            }), encoding='utf-8')
            untouched_archive = workspace / 'resources/offline-tools/sources' / unselected_record['filename']
            shutil.copyfile(ROOT / 'resources/offline-tools/sources' / unselected_record['filename'], untouched_archive)
            untouched_before = untouched_archive.read_bytes()

            wiki_entries = {
                'VERSION': b'0.7.0\n',
                'SKILL.md': b'# Wiki 0.7.0\r\n',
                '.agents/skills/codebase-wiki/vendor/archify/SKILL.md': b'upstream\r\nbytes\n',
                '.agents/skills/codebase-wiki/vendor/archify-manifest.json': b'{"line":"one\\r\\ntwo"}\r\n',
            }
            mocker = mock.patch.multiple(
                sources,
                ROOT=workspace,
                SNAPSHOTS=snapshots,
            )
            mocker.start()
            self.addCleanup(mocker.stop)
            repos_patch = mock.patch.object(
                sources, 'REPOS', {'codebase-wiki': 'code-base-llm-wiki', 'merge-reviewer': 'MergeReviewer'}
            )
            repos_patch.start()
            self.addCleanup(repos_patch.stop)
            entries_patch = mock.patch.object(sources, 'local_entries', return_value=('0.7.0', wiki_entries))
            entries_patch.start()
            self.addCleanup(entries_patch.stop)
            git_patch = mock.patch.object(sources, 'git_info', return_value={
                'commit': 'ed2c1d709994abbf41044fa10ccbfcf441c735ba', 'dirty': False,
            })
            git_patch.start()
            self.addCleanup(git_patch.stop)

            first = sources.freeze(['codebase-wiki'])
            self.assertTrue(first['ok'])
            record = json.loads(snapshots.read_text(encoding='utf-8'))['sources']['codebase-wiki']
            self.assertEqual('codebase-llm-wiki-codex-0.7.0', record['entryRoot'])
            self.assertEqual('ed2c1d709994abbf41044fa10ccbfcf441c735ba', record['commit'])
            self.assertFalse(record['dirty'])
            archive = workspace / 'resources/offline-tools/sources' / record['filename']
            frozen_bytes = archive.read_bytes()
            with zipfile.ZipFile(archive) as stream:
                names = [name for name in stream.namelist() if not name.endswith('/')]
                self.assertTrue(names)
                self.assertTrue(all(name.startswith('codebase-llm-wiki-codex-0.7.0/') for name in names))
                self.assertFalse(any('0.6.4' in name for name in names))
                self.assertEqual(
                    wiki_entries['.agents/skills/codebase-wiki/vendor/archify/SKILL.md'],
                    stream.read('codebase-llm-wiki-codex-0.7.0/.agents/skills/codebase-wiki/vendor/archify/SKILL.md'),
                )
                self.assertEqual(
                    wiki_entries['.agents/skills/codebase-wiki/vendor/archify-manifest.json'],
                    stream.read('codebase-llm-wiki-codex-0.7.0/.agents/skills/codebase-wiki/vendor/archify-manifest.json'),
                )
            first_snapshot = snapshots.read_bytes()

            second = sources.freeze(['codebase-wiki'])
            self.assertTrue(second['ok'])
            self.assertEqual(frozen_bytes, archive.read_bytes())
            self.assertEqual(first_snapshot, snapshots.read_bytes())
            self.assertEqual(untouched_before, untouched_archive.read_bytes())
            self.assertEqual(unselected_record,
                             json.loads(snapshots.read_text(encoding='utf-8'))['sources']['merge-reviewer'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
