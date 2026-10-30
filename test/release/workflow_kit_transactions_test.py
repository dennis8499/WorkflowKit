"""Production installer previews, trusted upgrades and owned transaction rollback."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tarfile
import unittest
from unittest import mock
import zipfile

import workflow_kit_installer_test as harness

ROOT, ARCHIVE, MARKER = harness.ROOT, harness.ARCHIVE, harness.MARKER

TRUST = json.loads((ROOT / "resources/workflow-kit/trusted-predecessors.json").read_text(encoding="utf-8"))

class TransactionTests(unittest.TestCase):
    # Reuse the real CLI harness without inheriting/rerunning its tests.
    execute = harness.WorkflowKitInstallerTests.execute
    install = harness.WorkflowKitInstallerTests.install
    create_group = harness.WorkflowKitInstallerTests.create_group
    snapshot = harness.WorkflowKitInstallerTests.snapshot
    status = harness.WorkflowKitInstallerTests.status

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kit-transaction-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.group = self.create_group(self.root, wiki="# User Wiki\n")

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
        paths = [ROOT / p for p in (".gitattributes", "VERSION", "README.md", "scripts/build-workflow-kit.py",
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
