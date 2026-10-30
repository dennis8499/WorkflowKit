"""Bundled and external BMAD ownership across install, update, and rollback."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile

import workflow_kit_installer_test as harness

ROOT = harness.ROOT
spec = importlib.util.spec_from_file_location("bmad_workflow_installer", ROOT / "resources/workflow-kit-installer.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
EXTERNAL_SKILLS = tuple(name for name in harness.SKILLS if not name.startswith("bmad-"))


def bmad_bytes(root):
    result = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if installer.external_bmad_path(relative) or relative == "_bmad-output" or relative.startswith("_bmad-output/"):
            result[relative] = path.read_bytes()
    return result


class BmadWorkflowKitTests(unittest.TestCase):
    execute = harness.WorkflowKitInstallerTests.execute
    snapshot = harness.WorkflowKitInstallerTests.snapshot

    def setUp(self):
        self.original_tempdir = tempfile.tempdir
        temp_root = (ROOT / ".tmp").resolve()
        temp_root.mkdir(parents=True, exist_ok=True)
        tempfile.tempdir = str(temp_root)
        self.addCleanup(setattr, tempfile, "tempdir", self.original_tempdir)
        temporary = tempfile.TemporaryDirectory(prefix="bmad workflow kit ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()

    def target(self, name, *, repository=False):
        root = self.base / name
        root.mkdir(parents=True)
        if repository:
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, capture_output=True)
        return root

    def apply(self, root, profile, env=None):
        return self.execute(
            "install", harness.ARCHIVE, root, harness.VERSION, "bundled",
            "--format", "tar.xz", "--entry-root", "workflow-kit",
            "--archive-sha256", installer.digest(harness.ARCHIVE.read_bytes()),
            "--profile", profile, env=env,
        )

    def rollback(self, root, transaction):
        return self.execute("rollback", root, transaction)

    def write_external(self, root, suffix=""):
        files = {
            "_bmad/config.toml": '[core]\nproject_name = "External"\n',
            "_bmad/scripts/resolve_config.py": "# user runtime\n",
            "_bmad/custom/config.toml": "# team config\n",
            "_bmad/config.user.toml": "# personal config\n",
            "_bmad/render/run/workflow.md": "# render snapshot\n",
            "_bmad/memory/project-context.md": "# user memory\n",
            "_bmad-output/specs/spec-demo/SPEC.md": "# user output\n",
            ".agents/skills/bmad-build/SKILL.md": "# external Codex skill\n",
            ".agents/skills/bmad-build/user-note.md": "# user content\n",
            ".claude/skills/bmad-help/SKILL.md": "# external Claude skill\n",
        }
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + suffix, encoding="utf-8")

    def assert_external_mode(self, root, transaction=None):
        marker = json.loads((root / harness.MARKER).read_text(encoding="utf-8"))
        self.assertEqual("external", marker["bmadMode"])
        self.assertEqual(list(EXTERNAL_SKILLS), [name for name in marker["skills"] if not name.startswith("bmad-")])
        self.assertEqual(4, len(marker["skills"]))
        self.assertNotIn("bmad-method", marker["upstream"])
        self.assertNotIn("bmad-workflow", marker["capabilities"])
        self.assertFalse(any(installer.external_bmad_path(name) for name in marker["files"]))
        if transaction:
            journal = json.loads((root / transaction).read_text(encoding="utf-8"))
            self.assertFalse(any(installer.external_bmad_path(operation["path"])
                                 for operation in journal["operations"]))
            self.assertFalse(any(operation["path"] == "_bmad-output" or operation["path"].startswith("_bmad-output/")
                                 for operation in journal["operations"]))
        ignored = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("/_bmad/", ignored)
        self.assertNotIn("/.agents/skills/bmad-", ignored)

    def test_source_is_fixed_and_payload_has_29_codex_skills(self):
        metadata = json.loads((ROOT / "resources/bmad/source.json").read_text(encoding="utf-8"))
        self.assertEqual("6.12.4", metadata["version"])
        self.assertEqual("bab9082c3e884e0d72c759bcd1a6d90bcc01be84", metadata["commit"])
        self.assertEqual(29, metadata["skillCount"])
        self.assertEqual(metadata["catalogSha256"], installer.digest((ROOT / "resources/bmad/bmad-help.csv").read_bytes()))
        with zipfile.ZipFile(harness.RELEASE_ZIP) as archive:
            self.assertIn("workflow-kit/sources/bmad-method-6.12.4-codex.zip", archive.namelist())
            manifest = json.loads(archive.read("workflow-kit/manifest.json"))
        self.assertEqual("6.12.4", manifest["upstream"]["bmad-method"]["version"])
        for profile in ("group", "repository"):
            self.assertEqual(29, len([name for name in manifest["profiles"][profile]["skills"] if name.startswith("bmad-")]))
            external = manifest["profiles"][profile]["variants"]["external"]
            self.assertNotIn("bmad-workflow", external["capabilities"])
            self.assertFalse(any(name.startswith("_bmad/") or name.startswith(".agents/skills/bmad-")
                                 for name in external["files"]))

    def test_external_install_profile_switch_repeat_and_rollback_preserve_every_byte(self):
        root = self.target("external BMAD", repository=True)
        self.write_external(root)
        before = bmad_bytes(root)
        first, first_data = self.apply(root, "group")
        self.assertEqual(0, first.returncode, first.stderr or first.stdout)
        self.assertEqual("installed", first_data["status"])
        self.assert_external_mode(root, first_data["transaction"])
        self.assertEqual(before, bmad_bytes(root))
        self.assertEqual("external", harness.WorkflowKitInstallerTests.status(self, root)["bmadMode"])

        repeated, repeated_data = self.apply(root, "group")
        self.assertEqual(0, repeated.returncode, repeated.stderr or repeated.stdout)
        self.assertEqual("unchanged", repeated_data["status"])
        self.assertEqual("external", repeated_data["bmadMode"])

        converted, converted_data = self.apply(root, "repository")
        self.assertEqual(0, converted.returncode, converted.stderr or converted.stdout)
        self.assert_external_mode(root, converted_data["transaction"])
        self.assertEqual(before, bmad_bytes(root))
        result, data = self.rollback(root, converted_data["transaction"])
        self.assertEqual(0, result.returncode, data)
        self.assertEqual(before, bmad_bytes(root))
        result, data = self.rollback(root, first_data["transaction"])
        self.assertEqual(0, result.returncode, data)
        self.assertEqual(before, bmad_bytes(root))

    def test_bmad_output_alone_does_not_suppress_the_bundled_component(self):
        root = self.target("output only")
        output = root / "_bmad-output/planning-artifacts/notes.md"
        output.parent.mkdir(parents=True)
        output.write_text("keep this existing output\n", encoding="utf-8")
        before = output.read_bytes()
        blocked_path = self.base / "no-tools"
        blocked_path.mkdir()
        environment = dict(os.environ)
        environment["PATH"] = str(blocked_path)

        result, data = self.apply(root, "group", environment)
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        self.assertEqual("bundled", data["bmadMode"])
        self.assertEqual(33, data["skills"])
        self.assertIn("bmad-workflow", data["capabilities"])
        self.assertTrue(any("uv" in warning for warning in data["warnings"]))
        self.assertEqual(before, output.read_bytes())
        self.assertTrue((root / "_bmad/config.toml").is_file())
        self.assertEqual("installed", harness.WorkflowKitInstallerTests.status(self, root)["status"])
        repeated, unchanged = self.apply(root, "group")
        self.assertEqual(0, repeated.returncode, unchanged)
        self.assertEqual("unchanged", unchanged["status"])

    def test_bundle_defaults_config_render_and_user_state_survive_upgrade_and_rollback(self):
        for profile in ("group", "repository"):
            with self.subTest(profile=profile):
                root = self.target("服務 A Project " + profile, repository=profile == "repository")
                result, data = self.apply(root, profile)
                self.assertEqual(0, result.returncode, result.stderr or result.stdout)
                self.assertEqual("bundled", data["bmadMode"])
                self.assertEqual(33, data["skills"])
                self.assertIn("bmad-method", data["upstreamVersions"])
                self.assertIn("bmad-workflow", data["capabilities"])

                config_path = root / "_bmad/config.toml"
                config = tomllib.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(root.name, config["core"]["project_name"])
                self.assertEqual("Traditional Chinese", config["core"]["communication_language"])
                self.assertEqual("Traditional Chinese", config["core"]["document_output_language"])
                self.assertEqual("_bmad-output", config["core"]["output_folder"])
                self.assertEqual("wiki", config["modules"]["bmm"]["project_knowledge"])
                self.assertEqual("installed", harness.WorkflowKitInstallerTests.status(self, root)["status"])

                resolve = subprocess.run(
                    [sys.executable, str(root / "_bmad/scripts/resolve_config.py"), "--project-root", str(root),
                     "--key", "core.project_name", "--key", "modules.bmm.project_knowledge"],
                    cwd=root, capture_output=True, text=True, encoding="utf-8", check=False,
                )
                self.assertEqual(0, resolve.returncode, resolve.stderr or resolve.stdout)
                resolved = json.loads(resolve.stdout)
                self.assertEqual(root.name, resolved["core.project_name"])
                self.assertEqual("wiki", resolved["modules.bmm.project_knowledge"])

                renderer = subprocess.run(
                    [sys.executable, str(root / "_bmad/scripts/render_skill.py"), "--project-root", str(root),
                     "--skill", str(root / ".agents/skills/bmad-build")],
                    cwd=root, capture_output=True, text=True, encoding="utf-8", check=False,
                )
                self.assertEqual(0, renderer.returncode, renderer.stdout or renderer.stderr)
                self.assertIn("read and follow", renderer.stdout)
                self.assertTrue((root / "_bmad/render/bmad-build").is_dir())

                preserved = {
                    "_bmad/config.user.toml": b'[core]\nuser_name = "Ada"\n',
                    "_bmad/custom/team.toml": b"# team customization\n",
                    "_bmad/memory/project-context.md": b"# User memory\n",
                    "_bmad/render/personal/snapshot.md": b"# Personal render\n",
                    "_bmad-output/planning-artifacts/brief.md": b"# Work output\n",
                }
                for relative, content in preserved.items():
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)

                repeat, unchanged = self.apply(root, profile)
                self.assertEqual(0, repeat.returncode, unchanged)
                self.assertEqual("unchanged", unchanged["status"])
                for relative, content in preserved.items():
                    self.assertEqual(content, (root / relative).read_bytes(), relative)

                rolled, output = self.rollback(root, data["transaction"])
                self.assertEqual(0, rolled.returncode, output)
                for relative, content in preserved.items():
                    self.assertEqual(content, (root / relative).read_bytes(), relative)

    def test_managed_bmad_modification_and_unknown_skill_file_block_without_reclassification(self):
        for relative in ("_bmad/config.toml", ".agents/skills/bmad-build/user-note.md"):
            with self.subTest(relative=relative):
                root = self.target("conflict " + relative.split("/")[-1])
                result, installed = self.apply(root, "group")
                self.assertEqual(0, result.returncode, result.stderr or result.stdout)
                target = root / relative
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((target.read_bytes() if target.exists() else b"") + b"local edit\n")
                before = target.read_bytes()
                status = harness.WorkflowKitInstallerTests.status(self, root)
                self.assertEqual("error", status["status"])
                retry, output = self.apply(root, "group")
                self.assertNotEqual(0, retry.returncode)
                self.assertIn("bundled", json.loads((root / harness.MARKER).read_text(encoding="utf-8"))["bmadMode"])
                self.assertEqual(before, target.read_bytes())

    def test_external_bmad_from_1_1_baselines_remains_byte_identical_after_upgrade(self):
        runner = ROOT / "test/release/frozen_installer_runner.py"
        for version in ("1.1.0", "1.1.1"):
            with self.subTest(version=version):
                root = self.target("legacy " + version)
                self.write_external(root)
                before = bmad_bytes(root)
                old_zip = ROOT / f"dist/gitlab-workspace-kit-{version}.zip"
                old_installer = ROOT / f"test/fixtures/workflow-kit-{version}/installer.py"
                command = [
                    sys.executable, "-X", "utf8", "-B", str(runner), str(old_installer),
                    "install", str(old_zip), str(root), version, "bundled", "--format", "zip",
                    "--entry-root", "workflow-kit",
                    "--archive-sha256", installer.digest(old_zip.read_bytes()), "--profile", "group",
                ]
                legacy = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
                self.assertEqual(0, legacy.returncode, legacy.stderr or legacy.stdout)
                result, updated = self.apply(root, "group")
                self.assertEqual(0, result.returncode, result.stderr or result.stdout)
                self.assertEqual("external", updated["bmadMode"])
                self.assert_external_mode(root, updated["transaction"])
                self.assertEqual(before, bmad_bytes(root))

    def test_1_1_baseline_without_external_bmad_upgrades_to_the_bundle(self):
        version = "1.1.1"
        root = self.target("upgrade default bundle")
        old_zip = ROOT / f"dist/gitlab-workspace-kit-{version}.zip"
        old_installer = ROOT / f"test/fixtures/workflow-kit-{version}/installer.py"
        command = [
            sys.executable, "-X", "utf8", "-B", str(ROOT / "test/release/frozen_installer_runner.py"),
            str(old_installer), "install", str(old_zip), str(root), version, "bundled", "--format", "zip",
            "--entry-root", "workflow-kit", "--archive-sha256", installer.digest(old_zip.read_bytes()),
            "--profile", "group",
        ]
        legacy = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual(0, legacy.returncode, legacy.stderr or legacy.stdout)
        result, updated = self.apply(root, "group")
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        self.assertEqual("bundled", updated["bmadMode"])
        self.assertTrue((root / "_bmad/config.toml").is_file())
        self.assertEqual(33, updated["skills"])

    def test_transaction_paths_allow_only_owned_bundled_runtime_and_skills(self):
        profile = installer.PROFILE_MANIFESTS["group"]
        bundled = {
            "bmadMode": "bundled", "skills": profile["skills"],
            "files": {**profile["bmadFiles"], **profile["files"]},
        }
        allowed = installer.transaction_paths(bundled)
        self.assertIn("_bmad/config.toml", allowed)
        self.assertIn(".agents/skills/bmad-build", allowed)
        self.assertNotIn("_bmad/config.user.toml", allowed)
        self.assertNotIn("_bmad-output", allowed)

        external = {
            "bmadMode": "external", "skills": profile["variants"]["external"]["skills"],
            "files": profile["variants"]["external"]["files"],
        }
        external_allowed = installer.transaction_paths(external)
        self.assertFalse(any(installer.external_bmad_path(path) for path in external_allowed))
        with self.assertRaises(installer.KitError):
            installer.reject_bmad_operations([{"path": "_bmad/config.toml", "kind": "path"}])
        with self.assertRaises(installer.KitError):
            installer.reject_bmad_operations([{"path": "_bmad-output/data.md", "kind": "path"}])

    @unittest.skipUnless(os.name == "nt", "Windows path-length regression")
    def test_bundled_runtime_installs_from_a_long_unicode_windows_path(self):
        current = self.base
        for index in range(4):
            current = current / (f"長路徑區段 {index} " + "x" * 54)
        ordinary_root = current / ("服務 A " + "y" * 72)
        root = Path("\\\\?\\" + str(ordinary_root))
        root.mkdir(parents=True)
        self.assertGreater(len(str(root)), 260)
        self.addCleanup(shutil.rmtree, Path("\\\\?\\" + str(self.base)), ignore_errors=True)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        result, data = self.apply(root, "group")
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        self.assertEqual("bundled", data["bmadMode"])
        self.assertEqual(root.name, tomllib.loads((root / "_bmad/config.toml").read_text(encoding="utf-8"))["core"]["project_name"])
        renderer = subprocess.run(
            [sys.executable, str(root / "_bmad/scripts/render_skill.py"), "--project-root", str(root),
             "--skill", str(root / ".agents/skills/bmad-build")],
            cwd=Path(sys.executable).resolve().parent, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(0, renderer.returncode, renderer.stdout or renderer.stderr)
        self.assertTrue((root / "_bmad/render/bmad-build").is_dir())
        self.assertEqual("installed", harness.WorkflowKitInstallerTests.status(self, root)["status"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
