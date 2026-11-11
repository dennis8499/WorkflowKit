"""Production installer previews, trusted upgrades and owned transaction rollback."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tarfile
import unittest
from unittest import mock
import zipfile

import workflow_kit_installer_test as harness

ROOT, ARCHIVE, MARKER = harness.ROOT, harness.ARCHIVE, harness.MARKER

TRUST = json.loads((ROOT / "resources/workflow-kit/trusted-predecessors.json").read_text(encoding="utf-8"))
installer_spec = importlib.util.spec_from_file_location("workflow_kit_predecessor_installer", ROOT / "resources/workflow-kit-installer.py")
installer = importlib.util.module_from_spec(installer_spec)
assert installer_spec and installer_spec.loader
installer_spec.loader.exec_module(installer)

class TransactionTests(unittest.TestCase):
    # Reuse the real CLI harness without inheriting/rerunning its tests.
    execute = harness.WorkflowKitInstallerTests.execute
    install = harness.WorkflowKitInstallerTests.install
    create_group = harness.WorkflowKitInstallerTests.create_group
    snapshot = harness.WorkflowKitInstallerTests.snapshot
    status = harness.WorkflowKitInstallerTests.status

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kit-transaction-")
        owned_root = Path(temporary.name).resolve()
        def cleanup():
            if Path(temporary.name).resolve() != owned_root:
                raise AssertionError('Test temporary root changed; preserving it.')
            if os.name == 'nt' and owned_root.drive and not str(owned_root).startswith('\\\\'):
                # Transaction backups retain long vendor license paths.
                temporary.name = "\\\\?\\" + str(owned_root)
            for attempt in range(20):
                try:
                    temporary.cleanup()
                    return
                except OSError as error:
                    if os.name != 'nt' or getattr(error, 'winerror', None) not in (32, 145) or attempt == 19:
                        raise
                    time.sleep(.15)
        self.addCleanup(cleanup)
        self.root = owned_root
        self.group = self.create_group(self.root, wiki="# User Wiki\n")
        self.predecessor_assets = {}

    def assets_for_predecessor(self, version):
        if version != "1.3.4":
            fixture = ROOT / f"test/fixtures/workflow-kit-{version}"
            return fixture / f"gitlab-workspace-kit-{version}.zip", fixture / "installer.py"

        if version not in self.predecessor_assets:
            source = self.root / "predecessors" / version
            source.mkdir(parents=True)
            archive = source / "source.zip"
            exported = subprocess.run(
                ["git", "archive", "--format=zip", f"--output={archive}", f"v{version}"],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(0, exported.returncode, exported.stderr or exported.stdout)
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(source)
            build = subprocess.run(
                [sys.executable, "-X", "utf8", "-B", str(source / "scripts/build-workflow-kit.py")],
                cwd=source, capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(0, build.returncode, build.stderr or build.stdout)
            self.predecessor_assets[version] = (
                source / "dist/gitlab-workspace-kit-1.3.4.zip",
                source / "dist/workflowkit-installer-1.3.4.py",
            )
        return self.predecessor_assets[version]

    def test_1_2_and_1_3_predecessors_are_trusted_for_each_profile_and_bmad_mode(self):
        rows = [row for row in TRUST["packages"] if row["version"] in ("1.2.0", "1.2.1", "1.3.0", "1.3.3", "1.3.4", "1.3.5", "1.3.6")]
        self.assertEqual(28, len(rows))
        identities = set()
        for row in rows:
            with self.subTest(version=row["version"], profile=row["profile"], bmadMode=row["bmadMode"]):
                raw = {
                    "version": row["version"],
                    "profile": row["profile"],
                    "bmadMode": row["bmadMode"],
                    "installedRoot": str(self.group.resolve()),
                    "payloadSha256": row["payloadSha256"],
                    "upstream": row["upstream"],
                    "overlays": row["overlays"],
                    "skills": row["skills"],
                    "files": {**row["files"], **row["wikiFiles"]},
                }
                if row["bmadMode"] == "bundled":
                    raw["files"].update(installer.legacy_bmad_identity(raw, row))
                selected = installer.trusted_package(raw)
                self.assertEqual(row["payloadSha256"], selected["payloadSha256"])
                self.assertEqual(row["capabilities"], selected["capabilities"])
                identities.add((row["version"], row["profile"], row["bmadMode"]))
        self.assertEqual(28, len(identities))

    def test_real_predecessors_upgrade_repeat_and_rollback_from_versioned_fixtures(self):
        cases = (
            ("1.2.0", "group", "bundled"),
            ("1.2.1", "repository", "external"),
            ("1.3.0", "group", "bundled"),
            ("1.3.0", "group", "external"),
            ("1.3.0", "repository", "bundled"),
            ("1.3.0", "repository", "external"),
            ("1.3.3", "group", "bundled"),
            ("1.3.3", "group", "external"),
            ("1.3.3", "repository", "bundled"),
            ("1.3.3", "repository", "external"),
            ("1.3.4", "group", "bundled"),
            ("1.3.4", "group", "external"),
            ("1.3.4", "repository", "bundled"),
            ("1.3.4", "repository", "external"),
            ("1.3.5", "group", "bundled"),
            ("1.3.5", "group", "external"),
            ("1.3.5", "repository", "bundled"),
            ("1.3.5", "repository", "external"),
            ("1.3.6", "group", "bundled"),
            ("1.3.6", "group", "external"),
            ("1.3.6", "repository", "bundled"),
            ("1.3.6", "repository", "external"),
            ("1.5.0", "group", "bundled"),
            ("1.5.0", "group", "external"),
            ("1.5.0", "repository", "bundled"),
            ("1.5.0", "repository", "external"),
            ("1.6.0", "group", "bundled"),
            ("1.6.0", "group", "external"),
            ("1.6.0", "repository", "bundled"),
            ("1.6.0", "repository", "external"),
            ("1.8.0", "group", "bundled"),
            ("1.8.0", "group", "external"),
            ("1.8.0", "repository", "bundled"),
            ("1.8.0", "repository", "external"),
        )
        selected_version = os.environ.get("WORKFLOW_KIT_TEST_PREDECESSOR_VERSION")
        if selected_version:
            cases = tuple(case for case in cases if case[0] == selected_version)
            self.assertTrue(cases, f"No real predecessor cases found for {selected_version}.")
        selected_profile = os.environ.get("WORKFLOW_KIT_TEST_PREDECESSOR_PROFILE")
        if selected_profile:
            self.assertIn(selected_profile, ("group", "repository"))
            cases = tuple(case for case in cases if case[1] == selected_profile)
            self.assertTrue(cases, f"No real predecessor cases found for {selected_profile}.")
        for version, profile, bmad_mode in cases:
            with self.subTest(version=version, profile=profile, bmad_mode=bmad_mode):
                target = self.create_group(self.root / f"{version}-{profile}-{bmad_mode}", wiki="# User Wiki\n")
                prior_diagram = target / "wiki/visualizations/prior-run/diagram.html"
                prior_diagram.parent.mkdir(parents=True)
                prior_diagram.write_bytes(b"user-owned earlier visualization\n")
                if profile == "repository":
                    initialized = subprocess.run(
                        ["git", "init", "--quiet", "-b", "main", str(target)],
                        capture_output=True, text=True, encoding="utf-8", check=False,
                    )
                    self.assertEqual(0, initialized.returncode, initialized.stderr)
                if bmad_mode == "external":
                    custom = target / "_bmad/custom/external.md"
                    custom.parent.mkdir(parents=True, exist_ok=True)
                    custom.write_text("External BMAD configuration stays.\n", encoding="utf-8")

                report = target / "review-reports/previous/merge-review-prior.md"
                report.write_text("Prior review report stays.\n", encoding="utf-8")
                package, old_installer = self.assets_for_predecessor(version)
                archive_hash = hashlib.sha256(package.read_bytes()).hexdigest()
                legacy = subprocess.run(
                    [sys.executable, "-X", "utf8", "-B", str(ROOT / "test/release/frozen_installer_runner.py"),
                     str(old_installer), "install", str(package), str(target),
                     version, "bundled", "--format", "zip", "--entry-root", "workflow-kit",
                     "--archive-sha256", archive_hash, "--profile", profile],
                    capture_output=True, text=True, encoding="utf-8", check=False,
                )
                self.assertEqual(0, legacy.returncode, legacy.stderr or legacy.stdout)
                legacy_manifest = json.loads((target / MARKER).read_text(encoding="utf-8"))
                self.assertEqual((version, profile, bmad_mode),
                                 (legacy_manifest["version"], legacy_manifest["profile"], legacy_manifest["bmadMode"]))
                source_wiki_version = {"1.3.0": "0.7.0", "1.3.3": "0.7.1", "1.3.4": "0.7.2", "1.3.5": "0.7.2", "1.3.6": "0.7.2", "1.5.0": "0.7.2", "1.6.0": "0.7.2", "1.8.0": "0.7.2"}.get(version, "0.6.4")
                self.assertEqual(source_wiki_version, legacy_manifest["upstream"]["codebase-wiki"]["version"])
                custom = target / "_bmad/custom/user-choice.md"
                if bmad_mode == "bundled":
                    custom.parent.mkdir(parents=True, exist_ok=True)
                    custom.write_text("User BMAD custom content stays.\n", encoding="utf-8")
                if version == '1.8.0':
                    for name in ('routing/merge-reviewer/prior.json', 'sessions/prior/draft.json', 'jobs/prior.json'):
                        path = target / '.review-runtime' / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(b'{"historical":"preserve without rewriting"}\n')
                audit = {path.relative_to(target).as_posix(): path.read_bytes()
                         for path in (target / '.review-runtime').rglob('*.json')}
                previous = self.snapshot(target)

                upgraded, data = self.install(target, profile=profile)
                self.assertEqual(0, upgraded.returncode, upgraded.stderr or upgraded.stdout)
                self.assertEqual(harness.VERSION, data["version"])
                self.assertEqual(bmad_mode, data["bmadMode"])
                status = self.status(target)
                self.assertEqual("installed", status.get("status"), status)
                self.assertEqual("0.7.2", status["upstreamVersions"]["codebase-wiki"])
                self.assertEqual(harness.CURRENT_SOURCES["merge-reviewer"]["version"],
                                 status["upstreamVersions"]["merge-reviewer"])
                self.assertEqual("0.12.0", status["upstreamVersions"]["release-reviewer"])
                self.assertIn("visualize", status["capabilities"])
                self.assertNotIn("model-routing", status["capabilities"])
                self.assertFalse((target / '.agents/skills/model-routing').exists())
                self.assertEqual(audit, {path.relative_to(target).as_posix(): path.read_bytes()
                                        for path in (target / '.review-runtime').rglob('*.json')})
                self.assertEqual(b"user-owned earlier visualization\n", prior_diagram.read_bytes())
                self.assertEqual("Prior review report stays.\n", report.read_text(encoding="utf-8"))
                if bmad_mode == "bundled":
                    self.assertEqual("User BMAD custom content stays.\n", custom.read_text(encoding="utf-8"))
                if bmad_mode == "external":
                    self.assertEqual("External BMAD configuration stays.\n",
                                     (target / "_bmad/custom/external.md").read_text(encoding="utf-8"))

                after_upgrade = self.snapshot(target)
                repeated, repeated_data = self.install(target, profile=profile)
                self.assertEqual(0, repeated.returncode, repeated.stderr or repeated.stdout)
                self.assertFalse(repeated_data["applied"])
                self.assertEqual("unchanged", repeated_data["status"])
                self.assertEqual(after_upgrade, self.snapshot(target))

                rolled_back, rollback_data = self.execute("rollback", target, data["transaction"])
                self.assertEqual(0, rolled_back.returncode, rollback_data)
                self.assertEqual(previous, self.snapshot(target))
                restored = self.status(target, expected_version=version)
                self.assertEqual(version, restored["version"])
                self.assertEqual(source_wiki_version, restored["upstreamVersions"]["codebase-wiki"])
                self.assertEqual("# User Wiki\n", (target / "wiki/index.md").read_text(encoding="utf-8"))
                self.assertEqual("Prior review report stays.\n", report.read_text(encoding="utf-8"))
                if bmad_mode == "bundled":
                    self.assertEqual("User BMAD custom content stays.\n", custom.read_text(encoding="utf-8"))
                if bmad_mode == "external":
                    self.assertEqual("External BMAD configuration stays.\n",
                                     (target / "_bmad/custom/external.md").read_text(encoding="utf-8"))

    def test_user_modified_retired_router_is_preserved_and_upgrade_is_rejected(self):
        package, old_installer = self.assets_for_predecessor('1.8.0')
        target = self.create_group(self.root / 'modified-router')
        legacy = subprocess.run([sys.executable, '-X', 'utf8', '-B',
            str(ROOT / 'test/release/frozen_installer_runner.py'), str(old_installer), 'install', str(package),
            str(target), '1.8.0', 'bundled', '--format', 'zip', '--entry-root', 'workflow-kit',
            '--archive-sha256', hashlib.sha256(package.read_bytes()).hexdigest(), '--profile', 'group'],
            capture_output=True, text=True, encoding='utf-8', check=False)
        self.assertEqual(0, legacy.returncode, legacy.stdout + legacy.stderr)
        modified = target / '.agents/skills/model-routing/references/execution.md'
        modified.write_bytes(modified.read_bytes() + b'\nUser-owned routing customization.\n')
        before = self.snapshot(target)
        upgraded, data = self.install(target)
        self.assertNotEqual(0, upgraded.returncode, data)
        self.assertEqual(before, self.snapshot(target))

    def test_1_8_native_review_resume_survives_router_retirement(self):
        package, old_installer = self.assets_for_predecessor('1.8.0')
        for profile in ('group', 'repository'):
            with self.subTest(profile=profile):
                target = self.create_group(self.root / ('native-' + profile))
                custom = target / '_bmad/custom/user.md'; custom.parent.mkdir(parents=True)
                custom.write_text('External BMAD stays.\n', encoding='utf-8')
                repo = target / 'service' if profile == 'group' else target
                repo.mkdir(exist_ok=True)
                def git(*arguments):
                    result = subprocess.run(['git', '-C', str(repo), *arguments], capture_output=True,
                                            text=True, encoding='utf-8', check=False)
                    self.assertEqual(0, result.returncode, result.stderr)
                git('init', '-q', '-b', 'main')
                for key, value in (('user.name', 'Native upgrade'), ('user.email', 'fixture@example.invalid'),
                                   ('core.longpaths', 'true'), ('core.autocrlf', 'false'), ('commit.gpgsign', 'false')):
                    git('config', key, value)
                (repo / 'app.py').write_text('value = 1\n', encoding='utf-8')
                git('add', 'app.py'); git('commit', '-qm', 'base'); git('switch', '-qc', 'feature')
                (repo / 'app.py').write_text('value = 2\n', encoding='utf-8')
                git('add', 'app.py'); git('commit', '-qm', 'head')
                installed = subprocess.run([sys.executable, '-X', 'utf8', '-B',
                    str(ROOT / 'test/release/frozen_installer_runner.py'), str(old_installer), 'install', str(package),
                    str(target), '1.8.0', 'bundled', '--format', 'zip', '--entry-root', 'workflow-kit',
                    '--archive-sha256', hashlib.sha256(package.read_bytes()).hexdigest(), '--profile', profile],
                    capture_output=True, text=True, encoding='utf-8', check=False)
                self.assertEqual(0, installed.returncode, installed.stdout + installed.stderr)
                runtime, identifier = self.root / ('native-runtime-' + profile), 'f' * 32
                runner = target / '.agents/gitlab-workspace-kit/run.py'
                helper = target / '.agents/skills/merge-reviewer/scripts/review_session.py'
                def native(action, *arguments):
                    result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(runner), '--',
                        sys.executable, '-X', 'utf8', '-B', str(helper), action, *map(str, arguments)],
                        cwd=repo, capture_output=True, text=True, encoding='utf-8', check=False, timeout=90)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    return json.loads(result.stdout)
                arguments = ['--workspace', target, '--project', repo, '--base', 'main', '--head', 'feature',
                             '--runtime-root', runtime, '--request-id', identifier, '--draft-format', 'compact', '--no-fetch']
                started = native('start', *arguments); context = Path(started['context_dir'])
                operations = [{'id': 'read-before-upgrade', 'op': 'read', 'repo': started['selected_repo'],
                               'source': 'head', 'path': 'app.py'}]
                requests = context / 'prior-operations.json'; requests.write_text(json.dumps(operations), encoding='utf-8')
                first = native('step', '--runtime-root', runtime, '--request-id', identifier, '--requests-file', requests)
                self.assertTrue(first['complete'])
                job_path = runtime / 'jobs' / (identifier + '.json')
                prior_job = json.loads(job_path.read_text(encoding='utf-8'))
                draft = (context / 'draft.json').read_bytes()
                manifest = json.loads((context / 'manifest.json').read_text(encoding='utf-8'))
                route = runtime / 'routing/merge-reviewer' / (identifier + '.json')
                route.parent.mkdir(parents=True)
                route.write_bytes(b'{"historical":"read-only route audit"}\n')
                routing_bytes = route.read_bytes()
                upgraded, data = self.install(target, profile=profile)
                self.assertEqual(0, upgraded.returncode, data)
                resumed = native('start', *arguments)
                self.assertEqual(started['context_dir'], resumed['context_dir'])
                self.assertEqual(draft, (context / 'draft.json').read_bytes())
                resumed_job = json.loads(job_path.read_text(encoding='utf-8'))
                self.assertEqual(prior_job['input_digest'], resumed_job['input_digest'])
                self.assertEqual(prior_job['started_at'], resumed_job['started_at'])
                resumed_manifest = json.loads((context / 'manifest.json').read_text(encoding='utf-8'))
                self.assertEqual({row['id']: row['sources'] for row in manifest['repositories']},
                                 {row['id']: row['sources'] for row in resumed_manifest['repositories']})
                self.assertEqual(manifest['operations'], resumed_manifest['operations'])
                replayed = native('step', '--runtime-root', runtime, '--request-id', identifier, '--requests-file', requests)
                self.assertTrue(replayed['operations'][0]['reused'])
                self.assertEqual(first['operations'][0]['result'], replayed['operations'][0]['result'])
                self.assertEqual(routing_bytes, route.read_bytes())
                self.assertFalse((target / '.agents/skills/model-routing').exists())
                self.assertEqual(1, len(list((runtime / 'jobs').glob('*.json'))))
                native('cancel', '--runtime-root', runtime, '--request-id', identifier)

    def preview(self):
        return self.execute("install", ARCHIVE, self.group, harness.VERSION, "bundled",
            "--format", "tar.xz", "--entry-root", "workflow-kit",
            "--archive-sha256", hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(), "--dry-run")

    def apply(self):
        result, data = self.install(self.group)
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        return data

    def test_dry_run_leaves_group_bytes_and_directories_unchanged(self):
        before = self.snapshot(self.group)
        directories = {p.relative_to(self.group).as_posix() for p in self.group.rglob("*") if p.is_dir()}
        result, data = self.preview()
        self.assertEqual(0, result.returncode, data)
        self.assertFalse(data["applied"])
        self.assertEqual("ready", data["status"])
        self.assertTrue(data["changed_paths"])
        self.assertEqual(before, self.snapshot(self.group))
        self.assertEqual(directories, {p.relative_to(self.group).as_posix() for p in self.group.rglob("*") if p.is_dir()})

    def test_repeated_install_is_byte_identical_and_keeps_original_journal(self):
        first = self.apply()
        before = self.snapshot(self.group)
        second = self.apply()
        self.assertFalse(second["applied"])
        self.assertEqual("unchanged", second["status"])
        self.assertEqual([], second["changed_paths"])
        self.assertEqual(before, self.snapshot(self.group))
        self.assertTrue((self.group / first["transaction"]).is_file())

    def test_fresh_rollback_preserves_user_files(self):
        before = self.snapshot(self.group)
        installed = self.apply()
        result, data = self.execute("rollback", self.group, installed["transaction"])
        self.assertEqual(0, result.returncode, data)
        self.assertEqual(before, self.snapshot(self.group))
        result, _ = self.execute("rollback", self.group, installed["transaction"])
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, self.snapshot(self.group))

    def test_unknown_predecessor_rejected_even_with_self_consistent_file_hashes(self):
        self.apply()
        path = self.group / MARKER
        marker = json.loads(path.read_text(encoding="utf-8"))
        for mutation in ({"payloadSha256": "0" * 64}, {"workspaceContract": 1, "payloadSha256": "0" * 64},
                         {"local_update": {"schema": "workflow-overlay-install/v1", "version": "unknown"}}):
            value = {**marker, **mutation}
            path.write_text(json.dumps(value), encoding="utf-8")
            before = self.snapshot(self.group)
            result, _ = self.install(self.group)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, self.snapshot(self.group))

    def test_self_rehashed_profile_is_not_a_trusted_predecessor(self):
        self.apply()
        relative = ".agents/gitlab-workspace-kit/profile.md"
        target = self.group / relative
        target.write_bytes(target.read_bytes() + b"unreviewed profile\n")
        path = self.group / MARKER
        marker = json.loads(path.read_text(encoding="utf-8"))
        marker["files"][relative] = hashlib.sha256(target.read_bytes()).hexdigest()
        path.write_text(json.dumps(marker), encoding="utf-8")
        before = self.snapshot(self.group)
        result, _ = self.install(self.group)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, self.snapshot(self.group))

    def test_rollback_rejects_later_edits_before_changing_any_file(self):
        installed = self.apply()
        target = self.group / "AGENTS.md"
        target.write_text(target.read_text(encoding="utf-8") + "Later user decision\n", encoding="utf-8")
        before = self.snapshot(self.group)
        result, _ = self.execute("rollback", self.group, installed["transaction"])
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, self.snapshot(self.group))

    def test_interrupted_recovery_checks_identity_and_all_edits_before_restoring(self):
        environment = {**os.environ, "GITLAB_WORKSPACE_KIT_TESTING": "1", "GITLAB_WORKSPACE_KIT_TEST_CRASH_AFTER": "4"}
        result, _ = self.install(self.group, env=environment)
        self.assertEqual(86, result.returncode)
        path = next((self.group / ".gitlab-workspace/tool-installs").glob("kit-*/transaction.json"))
        journal = json.loads(path.read_text(encoding="utf-8"))
        journal["id"] = "kit-" + "0" * 32
        path.write_text(json.dumps(journal), encoding="utf-8")
        before = self.snapshot(self.group)
        self.assertEqual("error", self.status(self.group)["status"])
        self.assertEqual({p: hashlib.sha256(v).hexdigest() for p, v in before.items()},
                         {p: hashlib.sha256(v).hexdigest() for p, v in self.snapshot(self.group).items()})
        journal["id"] = path.parent.name
        path.write_text(json.dumps(journal), encoding="utf-8")
        # Crash injection counts actual operations; installed Skill ordering can
        # change when the reviewed bundle gains tools. Tamper with a protected
        # entry point that the interrupted transaction really wrote.
        written = sorted(relative for relative in journal["installed_manifest"]["files"]
                         if relative.startswith(".agents/skills/") and relative.endswith("/SKILL.md")
                         and (self.group / relative).is_file())
        self.assertTrue(written, "The interrupted install must have written a protected Skill entry point")
        target = self.group / written[0]
        original = target.read_bytes()
        target.write_bytes(original + b"later edit\n")
        before = self.snapshot(self.group)
        self.assertEqual("error", self.status(self.group)["status"])
        self.assertEqual({p: hashlib.sha256(v).hexdigest() for p, v in before.items()},
                         {p: hashlib.sha256(v).hexdigest() for p, v in self.snapshot(self.group).items()})
        target.write_bytes(original)
        self.assertEqual("error", self.status(self.group)["status"])
        result, _ = self.install(self.group)
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        self.assertEqual("installed", self.status(self.group)["status"])

    def test_changed_archive_rejected_even_when_caller_rehashes_it(self):
        from workflow_kit_installer_test import RELEASE_ZIP
        archive = self.root / "changed.zip"
        with zipfile.ZipFile(RELEASE_ZIP) as source, zipfile.ZipFile(archive, "w") as target:
            for info in source.infolist():
                raw = source.read(info)
                if info.filename.endswith("/merge-reviewer/SKILL.md"):
                    raw += b"changed source\n"
                target.writestr(info, raw)
        before = self.snapshot(self.group)
        result, _ = self.install(self.group, archive=archive, archive_format="zip")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, self.snapshot(self.group))

    def test_windows_checkout_and_git_archive_have_identical_bundle_digests(self):
        source = self.root / "source"
        source.mkdir()
        paths = [ROOT / p for p in (".gitattributes", "VERSION", "README.md", "scripts/build-workflow-kit.py", "scripts/syntax-overlay.py",
                                    "resources/workflow-kit-installer.py")]
        paths.extend(p for p in (ROOT / "resources/workflow-kit").rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
        paths.extend(p for p in (ROOT / "resources/bmad").rglob("*") if p.is_file())
        sources = {record['filename'] for record in harness.CURRENT_SOURCES.values()}
        bmad_provenance = json.loads((ROOT / "resources/bmad/source.json").read_text(encoding="utf-8"))
        sources.add(bmad_provenance["officialArchive"])
        paths.extend(ROOT / 'resources/offline-tools/sources' / name for name in sorted(sources))
        paths.extend((ROOT / "scripts/workflow-kit-sources.py", ROOT / "resources/offline-tools/source-snapshots.json"))
        for path in paths:
            target = source / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)

        def git(*args):
            result = subprocess.run(["git", *map(str, args)], capture_output=True, check=False)
            self.assertEqual(0, result.returncode, result.stderr.decode("utf-8", errors="replace"))
        git("init", source)
        git("-C", source, "config", "user.name", "Fixture")
        git("-C", source, "config", "user.email", "fixture@example.invalid")
        git("-C", source, "config", "core.autocrlf", "true")
        git("-C", source, "add", ".")
        git("-C", source, "commit", "-m", "frozen build inputs")
        checkout = self.root / "Windows checkout"
        git("-c", "core.autocrlf=true", "clone", "--no-hardlinks", source, checkout)
        archive = self.root / "source.zip"
        git("-C", source, "archive", "--format=zip", "--output=" + str(archive), "HEAD")
        exported = self.root / "Git archive"
        exported.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                target = exported / info.filename
                self.assertTrue(target.resolve().is_relative_to(exported))
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bundle.read(info))
        expected = json.loads((ROOT / "resources/offline-tools/manifest.json").read_text(encoding="utf-8"))
        for tree in (checkout, exported):
            result = subprocess.run([sys.executable, "-X", "utf8", "-B", "scripts/build-workflow-kit.py"],
                                    cwd=tree, capture_output=True, text=True, encoding="utf-8", check=False)
            self.assertEqual(0, result.returncode, result.stderr or result.stdout)
            actual = json.loads((tree / "resources/offline-tools/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(expected["payloadSha256"], actual["payloadSha256"])
            self.assertEqual(expected["archiveSha256"], actual["archiveSha256"])
            self.assertEqual(expected["releaseZipSha256"], actual["releaseZipSha256"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
