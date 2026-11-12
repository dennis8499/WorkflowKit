"""Writable runtime routing for installed Skill helper commands."""
from __future__ import annotations

import json
import importlib.util
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest import mock
import unittest

import workflow_kit_installer_test as harness


ROOT = harness.ROOT
RUNNER_SOURCE = ROOT / "resources/workflow-kit/common/run.py"


class WorkflowKitRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="kit-runtime-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.install_root = self.base / "工作區 with spaces"
        self.runner = self.install_root / ".agents/gitlab-workspace-kit/run.py"
        self.runner.parent.mkdir(parents=True)
        shutil.copyfile(RUNNER_SOURCE, self.runner)
        self.project = self.install_root / "服務 A Project"
        self.project.mkdir(parents=True)

    def invoke(self, *arguments, cwd=None, env=None):
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(self.runner), *map(str, arguments)],
            cwd=cwd or self.project,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=90,
        )

    def test_preserves_child_arguments_cwd_output_and_exit_code(self):
        runtime = self.base / "runtime with spaces"
        code = (
            "import json,os,sys; "
            "print(json.dumps({'cwd':os.getcwd(),'args':sys.argv[1:],"
            "'temp':os.environ['TEMP'],'tmp':os.environ['TMP'],'tmpdir':os.environ['TMPDIR'],"
            "'cache':os.environ['UV_CACHE_DIR'],'bytecode':os.environ['PYTHONDONTWRITEBYTECODE']},"
            "ensure_ascii=False))"
        )
        argument = "參數 with spaces"
        original_environment = os.environ.copy()
        result = self.invoke(
            "--runtime-root", runtime, "--", sys.executable, "-X", "utf8", "-B", "-c", code, argument,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(str(self.project), observed["cwd"])
        self.assertEqual([argument], observed["args"])
        self.assertEqual(str(runtime / "tmp"), observed["temp"])
        self.assertEqual(observed["temp"], observed["tmp"])
        self.assertEqual(observed["temp"], observed["tmpdir"])
        self.assertEqual(str(runtime / "uv-cache"), observed["cache"])
        self.assertEqual("1", observed["bytecode"])
        self.assertEqual(original_environment, os.environ.copy())

        default_runtime = self.invoke("--", sys.executable, "-X", "utf8", "-c",
                                      "import os; print(os.environ['TEMP'])")
        self.assertEqual(0, default_runtime.returncode, default_runtime.stderr)
        self.assertEqual(str(self.install_root / ".gitlab-workspace/runtime/tmp"),
                         default_runtime.stdout.strip())
        self.assertTrue((self.install_root / ".gitlab-workspace/runtime/uv-cache").is_dir())

    def test_legacy_auto_environment_does_not_prepare_a_syntax_runtime(self):
        environment = {**os.environ, 'WORKFLOW_KIT_SYNTAX_CONTEXT': 'auto'}
        environment.pop('WORKFLOW_KIT_SYNTAX_RUNTIME', None)
        runtime = self.base / 'ordinary-runtime'
        result = self.invoke('--runtime-root', runtime, '--', sys.executable, '-B', '-c',
            "import os; print(os.environ.get('WORKFLOW_KIT_SYNTAX_RUNTIME', 'absent'))", env=environment)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('absent', result.stdout.strip())
        self.assertFalse((runtime / 'syntax-context').exists())

        exit_code = self.invoke(
            "--runtime-root", runtime, "--", sys.executable, "-c", "raise SystemExit(37)"
        )
        self.assertEqual(37, exit_code.returncode)

    def test_rejects_non_directory_runtime_before_launch(self):
        blocked = self.base / "not a directory"
        blocked.write_text("user file\n", encoding="utf-8")
        result = self.invoke(
            "--runtime-root", blocked, "--", sys.executable, "-c", "raise SystemExit(99)"
        )
        self.assertEqual(2, result.returncode)
        self.assertIn(blocked.name, result.stderr)
        self.assertIn("writable runtime", result.stderr)

    def test_rejects_symlink_runtime_before_launch(self):
        destination = self.base / "real runtime"
        destination.mkdir()
        link = self.base / "runtime link"
        try:
            link.symlink_to(destination, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("This Windows account cannot create symlinks.")
        result = self.invoke(
            "--runtime-root", link, "--", sys.executable, "-c", "raise SystemExit(99)"
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("symlink or junction", result.stderr)

    def test_reviewer_scratch_runtime_is_a_sibling_of_owned_session_runtime(self):
        module_spec = importlib.util.spec_from_file_location("workflowkit_runtime_runner", RUNNER_SOURCE)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        session_root = self.base / "approved reviewer runtime"
        reviewer = self.install_root / ".agents/skills/merge-reviewer/scripts/review_session.py"
        temporary, cache = module.runtime_paths(
            self.install_root, None,
            [sys.executable, str(reviewer), "status", "--runtime-root", str(session_root)],
        )
        self.assertEqual(session_root.with_name(session_root.name + "-workflow-kit") / "tmp", temporary)
        self.assertEqual(session_root.with_name(session_root.name + "-workflow-kit") / "uv-cache", cache)

    def test_reparse_point_attribute_is_rejected(self):
        junction = self.base / "junction"
        junction.mkdir()
        original_lstat = Path.lstat

        def report_junction(path, *args, **kwargs):
            if path == junction:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            return original_lstat(path, *args, **kwargs)

        module_spec = importlib.util.spec_from_file_location("workflowkit_reparse_runner", RUNNER_SOURCE)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        with mock.patch.object(Path, "lstat", new=report_junction):
            with self.assertRaisesRegex(module.RuntimePathError, "symlink or junction"):
                module._check_plain_parents(junction)

    @unittest.skipUnless(shutil.which("uv"), "Pinned uv runtime is installed in release CI.")
    def test_uv_succeeds_when_inherited_temp_and_cache_point_to_a_file(self):
        uv = shutil.which("uv")
        denied_temp = self.base / "not a temporary directory"
        denied_temp.write_text("keep\n", encoding="utf-8")
        inherited = os.environ.copy()
        inherited.update(TEMP=str(denied_temp), TMP=str(denied_temp), TMPDIR=str(denied_temp),
                         UV_CACHE_DIR=str(denied_temp), UV_OFFLINE="1")
        uv_command = [uv, "run", "--no-cache", "python", "-c",
                      "import json,os,sys; print(json.dumps({'python':sys.executable,"
                      "'temp':os.environ['TEMP'],'cache':os.environ['UV_CACHE_DIR'],"
                      "'bytecode':os.environ['PYTHONDONTWRITEBYTECODE']}))"]

        baseline = subprocess.run(uv_command, cwd=self.project, env=inherited, capture_output=True,
                                  text=True, encoding="utf-8", check=False, timeout=90)
        self.assertNotEqual(0, baseline.returncode, baseline.stdout)
        self.assertTrue(denied_temp.is_file())

        runtime = self.base / "runtime with spaces"
        result = self.invoke("--runtime-root", runtime, "--", *uv_command, env=inherited)
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        observed = json.loads(result.stdout)
        self.assertEqual(os.path.normcase(os.path.realpath(sys.executable)),
                         os.path.normcase(os.path.realpath(observed["python"])))
        self.assertEqual(str(runtime / "tmp"), observed["temp"])
        self.assertEqual(str(runtime / "uv-cache"), observed["cache"])
        self.assertEqual("1", observed["bytecode"])
        self.assertTrue(denied_temp.is_file())


class WorkflowKitWikiRuntimeTests(unittest.TestCase):
    execute = harness.WorkflowKitInstallerTests.execute
    create_group = harness.WorkflowKitInstallerTests.create_group

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="kit-wiki-runtime-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.group = self.create_group(self.base, wiki="# Workflow Wiki\n")
        (self.group / "wiki/overview.md").write_text("# Runtime source context\n\nService and storage overview.\n", encoding="utf-8")
        package = harness.ARCHIVE
        installed, data = self.execute(
            "install", package, self.group, harness.VERSION, "bundled", "--format", "tar.xz",
            "--entry-root", "workflow-kit", "--archive-sha256",
            hashlib.sha256(package.read_bytes()).hexdigest(), "--profile", "group",
        )
        self.assertEqual(0, installed.returncode, installed.stderr or installed.stdout)
        self.runner = self.group / ".agents/gitlab-workspace-kit/run.py"
        self.visualizer = self.group / ".agents/skills/codebase-wiki/scripts/wiki-visualize.py"
        self.source = self.group / "app.py"
        self.source.write_text("def service():\n    return 'ready'\n", encoding="utf-8")
        self.environment = {**os.environ, "UV_OFFLINE": "1"}

    def cli(self, *arguments):
        process = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(self.runner), "--",
             sys.executable, "-X", "utf8", "-B", str(self.visualizer), *map(str, arguments)],
            cwd=self.group, env=self.environment, capture_output=True, text=True, encoding="utf-8",
            check=False, timeout=300,
        )
        if process.returncode:
            details = process.stderr or process.stdout
            scratch = self.group / ".gitlab-workspace/runtime/tmp"
            receipts = sorted(scratch.rglob("*.finalize.json")) if scratch.is_dir() else []
            for receipt in receipts:
                details += "\n" + receipt.read_text(encoding="utf-8")[:12000]
            self.fail(details)
        return json.loads(process.stdout)

    def test_prepared_wiki_diagram_resumes_and_publishes_in_a_later_runner_call(self):
        prepared = self.cli(
            "prepare", "--root", self.group, "--type", "architecture", "--slug", "runtime-check",
            "--title", "執行環境架構", "--wiki-page", "wiki/overview.md", "--source", "app.py", "--format", "json",
        )
        plan_path = Path(prepared["plan"])
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        candidate_path = Path(prepared["candidate"])
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        candidate["components"] = [
            {"id": "service", "type": "backend", "label": "服務", "pos": [120, 180], "size": [138, 68]},
            {"id": "storage", "type": "database", "label": "資料庫", "pos": [420, 180], "size": [138, 68]},
        ]
        candidate["connections"] = [{"id": "service-storage", "from": "service", "to": "storage", "label": "資料"}]
        candidate_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        evidence_map = json.loads(Path(prepared["evidence_map"]).read_text(encoding="utf-8"))
        module_spec = importlib.util.spec_from_file_location("workflow_kit_test_visualizer", self.visualizer)
        module = importlib.util.module_from_spec(module_spec)
        sys.path.insert(0, str(self.visualizer.parent))
        try:
            module_spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(self.visualizer.parent))
        evidence_map["claims"] = [
            {"element_id": element, "evidence": [{"path": "app.py", "sha256": source_hash}]}
            for element in sorted(module._semantic_ids(candidate, "architecture"))
        ]
        Path(prepared["evidence_map"]).write_text(
            json.dumps(evidence_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        node = shutil.which("node")
        self.assertIsNotNone(node, "Release CI provides Node.js for Wiki visualization checks.")
        debug_dir = Path(plan["workdir"]) / "direct-finalize"
        debug_dir.mkdir()
        debug_candidate = debug_dir / "candidate.json"
        debug_candidate.write_bytes(candidate_path.read_bytes())
        archify = self.group / ".agents/skills/codebase-wiki/vendor/archify/bin/archify.mjs"

        def finalize():
            return subprocess.run(
                [sys.executable, "-X", "utf8", "-B", str(self.runner), "--", node, str(archify),
                 "finalize", "architecture", str(debug_candidate), str(debug_dir / "diagram.html"),
                 "--quality", "showcase", "--json"],
                cwd=debug_dir, env={**self.environment, "ARCHIFY_UPDATE_CHECK_DISABLED": "1"},
                capture_output=True, text=True, encoding="utf-8", check=False, timeout=300,
            )

        direct = finalize()
        self.assertEqual(0, direct.returncode, direct.stderr or direct.stdout)
        repeated_direct = finalize()
        self.assertEqual(0, repeated_direct.returncode, repeated_direct.stderr or repeated_direct.stdout)

        published = self.cli("publish", "--root", self.group, "--plan", plan_path, "--format", "json")
        self.assertEqual(plan["run_id"], published["run_id"])
        checked = self.cli(
            "verify", "--root", self.group,
            "--run", f"wiki/visualizations/runtime-check/{plan['run_id']}", "--format", "json",
        )
        self.assertTrue(checked["ok"])
        self.assertTrue((self.group / "wiki/visualizations/runtime-check" / plan["run_id"] / "diagram.html").is_file())
        self.assertTrue((self.group / ".gitlab-workspace/runtime/tmp").is_dir())
        self.assertTrue((self.group / ".gitlab-workspace/runtime/uv-cache").is_dir())


if __name__ == "__main__":
    unittest.main(verbosity=2)
