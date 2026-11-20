"""Bound launch argv, read-only inspection and compatibility of the kit runner."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "resources/workflow-kit/common"
spec = importlib.util.spec_from_file_location("launch_under_test", COMMON / "review_launch.py")
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)

HELPER = r'''
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
action=args[0]
if action=='capabilities':
 print(json.dumps({'schema':'MergeReviewCapabilities/v1','draft_formats':['v3','compact'],
 'features':{'launch_preflight':True,'read_only_inspection':True,'operation_schema':True}}));sys.exit(0)
if '--help' in args:
 print('fixture help: '+action);sys.exit(0)
if action=='schema':
 print(json.dumps({'schema':'MergeReviewOperationSchema/v1','args':args}));sys.exit(0)
def value(key):
 return args[args.index(key)+1]
root=Path(value('--runtime-root'))
job=root/'jobs'/(value('--request-id')+'.json')
if action=='preflight':
 valid=Path(value('--workspace')).is_dir() and Path(value('--project')).is_dir()
 print(json.dumps({'schema':'MergeReviewPreflight/v1','valid':valid,'errors':[] if valid else ['missing-root']}))
 sys.exit(0 if valid else 3)
if action=='start':
 if not job.exists():
  job.parent.mkdir(parents=True,exist_ok=True);job.write_text('{}')
 print(json.dumps({'action':action,'args':args,'temp':os.environ.get('TEMP')}));sys.exit(0)
print(json.dumps({'action':action,'args':args,'temp':os.environ.get('TEMP')}))
'''


class ReviewLaunchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="review-launch-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.install = self.base / "Workspace with spaces"
        self.runner = self.install / ".agents/gitlab-workspace-kit/run.py"
        self.runner.parent.mkdir(parents=True)
        for name in ("run.py", "review_launch.py", "runner-capabilities.json"):
            shutil.copyfile(COMMON / name, self.runner.parent / name)
        self.skill = self.install / ".agents/skills/merge-reviewer"
        (self.skill / "scripts").mkdir(parents=True)
        self.script = self.skill / "scripts/review_session.py"
        self.script.write_text(HELPER, encoding="utf-8")
        (self.skill / "SKILL.md").write_text("# Fixture\n", encoding="utf-8")
        (self.skill / "VERSION").write_text("0.21.0\n", encoding="utf-8")
        self.project = self.install / "Project with spaces"
        self.project.mkdir()
        self.runtime = self.base / "native"
        self.request = {
            "schema": "ReviewLaunchRequest/v1", "tool": "merge-reviewer", "request_id": "a" * 32,
            "workspace": str(self.install), "project": str(self.project), "base": "origin/main",
            "head": "origin/feature with spaces", "runtime_root": str(self.runtime), "draft_format": "compact",
            "binding": self.binding(),
        }
        self.request_path = self.runtime.with_name("native-workflow-kit") / "launch" / ("a" * 32 + ".json")
        self.request_path.parent.mkdir(parents=True)
        self.save()
        self.marker()

    def binding(self):
        rows = launch.payload(self.skill)
        return {"schema": "InstalledReviewerBinding/v1", "tool": "merge-reviewer", "version": "0.21.0",
                "script_path": str(self.script), "script_sha256": launch.sha(self.script.read_bytes()),
                "skill_sha256": launch.sha((self.skill / "SKILL.md").read_bytes()), "payload_files": len(rows),
                "payload_sha256": launch.sha(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()),
                "workflow_kit_runner": {"script_path": str(self.runner), "script_sha256": launch.sha(self.runner.read_bytes()),
                    "review_launch_sha256": launch.sha((self.runner.parent / "review_launch.py").read_bytes()),
                    "review_launch_request": 1, "read_only_inspection": True}}

    def marker(self):
        value = {"version": "1.8.0", "files": {p.relative_to(self.install).as_posix(): launch.sha(p.read_bytes())
                 for p in self.install.rglob("*") if p.is_file()}}
        path = self.install / ".gitlab-workspace/tool-manifests/workflow-kit.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def save(self):
        raw = json.dumps(self.request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.request_path.write_bytes(raw)
        self.request_sha = launch.sha(raw)

    def invoke(self, action="status", *extra, expected=None):
        return subprocess.run([sys.executable, "-X", "utf8", "-B", str(self.runner),
            "--review-request", str(self.request_path), "--expected-request-sha256", expected or self.request_sha,
            "--action", action, *extra], capture_output=True, text=True, encoding="utf-8", check=False, timeout=30)

    def raw(self, *arguments):
        return subprocess.run([sys.executable, "-X", "utf8", "-B", str(self.runner), "--read-only", "--",
            sys.executable, "-X", "utf8", "-B", str(self.script), *arguments], capture_output=True,
            text=True, encoding="utf-8", check=False, timeout=30)

    def files(self):
        return {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
                for p in self.base.rglob("*") if p.is_file()}

    def test_structured_start_preserves_arguments_and_prepares_separate_scratch(self):
        result = self.invoke("start")
        self.assertEqual(0, result.returncode, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(str(self.project), value["args"][value["args"].index("--project") + 1])
        self.assertEqual("origin/feature with spaces", value["args"][value["args"].index("--head") + 1])
        self.assertEqual("compact", value["args"][value["args"].index("--draft-format") + 1])
        self.assertEqual(str(self.runtime.with_name("native-workflow-kit") / "tmp"), value["temp"])
        self.assertFalse((self.runtime / "tmp").exists())

    def test_release_launch_uses_native_arguments_and_keeps_inspection_readonly(self):
        original = self.skill
        self.skill = original.with_name("release-reviewer")
        shutil.copytree(original, self.skill)
        self.script = self.skill / "scripts/review_session.py"
        source = HELPER.replace("'schema':'MergeReviewCapabilities/v1'",
                                "'schema':'ReviewCapabilities/v1','tool':'release-reviewer','prepare_evidence':True")
        self.script.write_text(source.replace("MergeReviewPreflight/v1", "ReleaseReviewPreflight/v1"), encoding="utf-8")
        binding = self.binding()
        binding["tool"] = "release-reviewer"
        binding["workflow_kit_runner"]["review_launch_tools"] = ["merge-reviewer", "release-reviewer"]
        self.request.update(tool="release-reviewer", draft_format="v3", binding=binding)
        self.save()
        self.marker()
        initial = self.invoke("start")
        self.assertEqual(0, initial.returncode, initial.stderr)
        args = json.loads(initial.stdout)["args"]
        self.assertIn("--prepare-evidence", args)
        self.assertNotIn("--draft-format", args)
        before = self.files()
        status = self.invoke()
        self.assertEqual(0, status.returncode, status.stderr)
        self.assertIn("--summary", json.loads(status.stdout)["args"])
        for run in (self.invoke("view", "--", "--artifact", "b" * 64),
                    self.raw("view", "--runtime-root", str(self.runtime), "--request-id",
                             self.request["request_id"], "--artifact", "b" * 64)):
            self.assertEqual(0, run.returncode, run.stderr)
            self.assertNotIn("--read-only", json.loads(run.stdout)["args"])
        self.assertEqual(before, self.files())

    def test_readonly_actions_create_no_files_and_preserve_mtimes(self):
        before = self.files()
        for action, extra in (("status", ()), ("preflight", ()),
                              ("view", ("--", "--artifact", "b" * 64, "--pointer", "/lines"))):
            result = self.invoke(action, *extra)
            self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(before, self.files())
        self.assertFalse((self.runtime.with_name("native-workflow-kit") / "tmp").exists())

    def test_invalid_preflight_does_not_create_job_or_scratch(self):
        self.request["workspace"] = str(self.base / "wrong")
        self.save()
        before = self.files()
        result = self.invoke("start")
        self.assertEqual(3, result.returncode, result.stderr)
        self.assertFalse(json.loads(result.stdout)["valid"])
        self.assertFalse(self.runtime.exists())
        self.assertEqual(before, self.files())

    def test_existing_job_bypasses_live_preflight(self):
        job = self.runtime / "jobs" / ("a" * 32 + ".json")
        job.parent.mkdir(parents=True)
        job.write_text("{}")
        self.request["workspace"] = str(self.base / "no-longer-present")
        self.save()
        self.assertEqual(0, self.invoke("start").returncode)

    def test_changed_request_fails_before_child_execution(self):
        result = self.invoke(expected="0" * 64)
        self.assertEqual(2, result.returncode)
        self.assertIn("SHA-256 differs", result.stderr)
        self.assertFalse(self.runtime.exists())

    def test_changed_payload_or_launcher_is_rejected(self):
        (self.skill / "SKILL.md").write_text("changed")
        self.assertIn("payload changed", self.invoke().stderr)
        (self.skill / "SKILL.md").write_text("# Fixture\n")
        with (self.runner.parent / "review_launch.py").open("a") as stream:
            stream.write("\nraise RuntimeError('must not execute')\n")
        result = self.invoke()
        self.assertEqual(2, result.returncode)
        self.assertIn("launcher changed", result.stderr)
        self.assertNotIn("RuntimeError", result.stderr)

    def test_view_cannot_override_identity_or_mutation_mode(self):
        for flag in ("--workspace", "--request-id", "--runtime-root", "--draft-format", "--read-only"):
            result = self.invoke("view", "--", "--artifact", "b" * 64, flag, "other")
            self.assertEqual(2, result.returncode, flag)
        self.assertEqual(2, self.invoke("start", "--", "--project", str(self.project)).returncode)

    def test_bound_schema_matches_native_without_runtime_or_writes(self):
        before = self.files()
        inspected = self.invoke("schema", "--", "--operation", "read")
        native = subprocess.run([sys.executable, "-X", "utf8", "-B", str(self.script),
            "schema", "--operation", "read"], capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual(0, inspected.returncode, inspected.stderr)
        self.assertEqual(native.stdout, inspected.stdout)
        self.assertEqual(["schema", "--operation", "read"], json.loads(inspected.stdout)["args"])
        self.assertFalse(self.runtime.exists())
        self.assertEqual(before, self.files())

    def test_schema_rejects_identity_override_and_missing_capability(self):
        for extra in (("--runtime-root", str(self.runtime)), ("--operation", "read", "--operation", "author"),
                      ("--operation", "read;finish"), ("--operation", "--help")):
            with self.subTest(extra=extra):
                result = self.invoke("schema", "--", *extra)
                self.assertEqual(2, result.returncode)
                self.assertFalse(self.runtime.exists())
        self.script.write_text(HELPER.replace("'operation_schema':True", "'operation_schema':False"))
        self.request["binding"] = self.binding()
        self.save()
        result = self.invoke("schema", "--", "--operation", "read")
        self.assertEqual(2, result.returncode)
        self.assertIn("lacks the required", result.stderr)

    def test_action_timings_are_structured_stderr_without_protocol_contamination(self):
        result = self.invoke("status")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("status", json.loads(result.stdout)["action"])
        metrics = json.loads(result.stderr)
        self.assertEqual("ReviewLaunchMetrics/v1", metrics["schema"])
        self.assertEqual(("status", 0), (metrics["action"], metrics["returncode"]))
        required = {"request_seconds", "binding_seconds", "capabilities_seconds", "child_seconds", "total_seconds"}
        self.assertEqual(required, set(metrics["timings"]))
        self.assertTrue(all(value >= 0 for value in metrics["timings"].values()))
        self.assertGreaterEqual(metrics["timings"]["total_seconds"], metrics["timings"]["child_seconds"])
        self.assertNotIn(str(self.install), result.stderr)

    def test_paging_file_path_is_passed_as_one_literal_argument(self):
        requests = self.base / "續讀 狀態.json"
        requests.write_text('{"schema":"MergeReviewPaging/v1","pending":[]}', encoding="utf-8")
        before = self.files()
        result = self.invoke("view", "--", "--requests-file", str(requests))
        self.assertEqual(0, result.returncode, result.stderr)
        args = json.loads(result.stdout)["args"]
        self.assertEqual(str(requests), args[args.index("--requests-file") + 1])
        self.assertEqual(1, args.count("--read-only"))
        self.assertEqual(before, self.files())

    def test_missing_native_feature_fails_without_scratch(self):
        self.script.write_text(HELPER.replace("'launch_preflight':True", "'launch_preflight':False"))
        self.request["binding"] = self.binding()
        self.save()
        result = self.invoke("start")
        self.assertEqual(2, result.returncode)
        self.assertIn("lacks the required", result.stderr)
        self.assertFalse(self.runtime.exists())

    def test_legacy_optional_binding_needs_no_retired_assets_or_request_rewrite(self):
        directory = self.runner.parent / 'scripts/syntax-context'
        self.request['binding']['workflow_kit_runner']['syntax_analysis'] = {
            'schema': 'SyntaxAnalysisBinding/v1', 'script_path': str(directory / 'cli.py'),
            'engine_sha256': 'b' * 64,
            'languages': ['csharp'], 'default_mode': 'off'}
        self.save()
        original_request = self.request_path.read_bytes()
        before = self.files()
        self.assertEqual(0, self.invoke().returncode)
        self.assertEqual(before, self.files())
        result = self.invoke('start')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(directory.exists())
        self.assertEqual(original_request, self.request_path.read_bytes())

    def test_readonly_runner_rejects_retired_helper_before_import(self):
        script = self.runner.parent / 'scripts/syntax-context/cli.py'
        script.parent.mkdir(parents=True)
        script.write_text("raise RuntimeError('retired helper executed')\n")
        self.marker()
        before = self.files()
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(self.runner), '--read-only', '--',
            sys.executable, '-X', 'utf8', '-B', str(script), 'capabilities'], capture_output=True,
            text=True, encoding='utf-8', check=False, timeout=30)
        self.assertEqual(2, result.returncode)
        self.assertNotIn('retired helper executed', result.stderr)
        self.assertEqual(before, self.files())
        self.assertFalse(self.runtime.exists())

    def test_raw_readonly_is_capability_gated_and_rejects_mutating_commands(self):
        before = self.files()
        self.assertEqual(0, self.raw("capabilities").returncode)
        self.assertEqual(0, self.raw("capabilities", "--workspace", str(self.install)).returncode)
        self.assertEqual(2, self.raw("capabilities", "--project", str(self.project)).returncode)
        inspected = self.raw("preflight", "--workspace", str(self.install), "--project", str(self.project),
                             "--base", "main", "--head", "feature", "--runtime-root", str(self.runtime), "--request-id", "a" * 32)
        self.assertEqual(0, inspected.returncode, inspected.stderr)
        result = self.raw("status", "--summary", "--runtime-root", str(self.runtime), "--request-id", "a" * 32)
        self.assertEqual(0, result.returncode, result.stderr)
        for action in ("start", "step", "finish", "cancel", "check"):
            self.assertEqual(2, self.raw(action).returncode, action)
        self.assertEqual(before, self.files())

    def test_raw_readonly_schema_and_exact_subcommand_help(self):
        before = self.files()
        schema = self.raw("schema", "--operation", "author")
        self.assertEqual(0, schema.returncode, schema.stderr)
        self.assertEqual(["schema", "--operation", "author"], json.loads(schema.stdout)["args"])
        for action in ("view", "step", "finish", "cleanup"):
            with self.subTest(action=action):
                result = self.raw(action, "--help")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("fixture help: " + action, result.stdout.strip())
                self.assertEqual(2, self.raw(action, "--help", "--request-id", "a" * 32).returncode)
        self.assertEqual(2, self.raw("schema", "--operation", "author", "--runtime-root", str(self.runtime)).returncode)
        self.assertEqual(before, self.files())

    def test_raw_readonly_rejects_unmanaged_imports_and_legacy_capabilities(self):
        (self.skill / "scripts/extra.py").write_text("raise RuntimeError()")
        self.assertEqual(2, self.raw("capabilities").returncode)
        (self.skill / "scripts/extra.py").unlink()
        self.script.write_text(HELPER.replace("'read_only_inspection':True", "'read_only_inspection':False"))
        self.marker()
        self.assertEqual(2, self.raw("capabilities").returncode)

    def test_unrecognized_request_fields_and_nonboolean_flags_are_rejected(self):
        for key, value in (("model", "other"), ("no_fetch", "false"), ("refresh", 1)):
            self.request[key] = value
            self.save()
            self.assertEqual(2, self.invoke().returncode, key)
            del self.request[key]

    def test_malformed_input_types_are_structured_errors_without_side_effects(self):
        original = json.loads(json.dumps(self.request))
        for key, value in (("request_id", 7), ("workspace", []), ("workspace_file", 7),
                           ("binding", None), ("project", True), ("base", {})):
            self.request = {**original, key: value}
            self.save()
            before = self.files()
            result = self.invoke("start")
            self.assertEqual(2, result.returncode, key)
            self.assertEqual("ReviewLaunchError/v1", json.loads(result.stderr)["schema"])
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(before, self.files())
        self.request = original
        self.request["binding"]["script_path"] = 17
        self.save()
        result = self.invoke("start")
        self.assertEqual(2, result.returncode)
        self.assertNotIn("Traceback", result.stderr)

    def test_legacy_runner_still_runs_general_commands(self):
        result = subprocess.run([sys.executable, "-B", str(self.runner), "--", sys.executable, "-c",
                                 "raise SystemExit(37)", "--review-request", "child-owned-argument"],
                                capture_output=True, timeout=30)
        self.assertEqual(37, result.returncode)

    def install_capability_manifest(self, **features):
        value = {"schema": "MergeReviewCapabilities/v1", "protocol_version": 1,
                 "draft_formats": ["v3", "compact"], "features": {"capability_manifest": True,
                    "launch_preflight": True, "read_only_inspection": True, "operation_schema": True, **features}}
        (self.skill / "capabilities.json").write_text(json.dumps(value), encoding="utf-8")
        self.request["binding"] = self.binding()
        self.save()
        self.marker()
        return value

    def test_verified_manifest_avoids_capability_subprocess_and_pins_python_and_payload(self):
        declared = self.install_capability_manifest()
        with mock.patch.object(launch.subprocess, "run", side_effect=AssertionError("extra capability process")):
            caps = launch.installed_capabilities(self.script)
        self.assertEqual(declared["features"], caps["features"])
        self.assertEqual(sys.version.split()[0], caps["python_version"])
        self.assertEqual(str(Path(sys.executable).resolve()), caps["python_executable"])
        self.assertEqual("0.21.0", caps["skill_version"])
        self.assertEqual(launch.sha((self.skill / "capabilities.json").read_bytes()), caps["capabilities_sha256"])
        before = self.files()
        result = self.invoke("status")
        self.assertEqual(0, result.returncode, result.stderr)
        metric = next(json.loads(line) for line in result.stderr.splitlines() if 'ReviewLaunchMetrics/v1' in line)
        self.assertEqual("verified-manifest", metric["capabilities_source"])
        self.assertEqual(before, self.files())

    def test_manifest_changes_are_rejected_by_original_binding_and_new_unsupported_features_still_fail(self):
        self.install_capability_manifest()
        path = self.skill / "capabilities.json"
        value = json.loads(path.read_text())
        value["features"]["read_only_inspection"] = False
        path.write_text(json.dumps(value))
        denied = self.invoke("status")
        self.assertEqual(2, denied.returncode)
        self.assertIn("payload changed", denied.stderr)
        self.request["binding"] = self.binding()
        self.save()
        self.marker()
        before = self.files()
        denied = self.invoke("status")
        self.assertEqual(2, denied.returncode)
        self.assertIn("lacks the required", denied.stderr)
        self.assertEqual(before, self.files())

    def test_malformed_manifest_cannot_supply_runtime_identity_or_trigger_writes(self):
        self.install_capability_manifest()
        path = self.skill / "capabilities.json"
        value = json.loads(path.read_text())
        value["helper_sha256"] = "0" * 64
        path.write_text(json.dumps(value))
        self.request["binding"] = self.binding()
        self.save()
        before = self.files()
        denied = self.invoke("start")
        self.assertEqual(2, denied.returncode)
        self.assertIn("capability manifest is invalid", denied.stderr)
        self.assertEqual(before, self.files())


if __name__ == "__main__":
    unittest.main()
