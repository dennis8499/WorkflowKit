"""The real prompt driver must preserve a common supported model effort."""
from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


class ReviewerReliabilityPromptTests(unittest.TestCase):
    def build(self, root, variant, effort):
        engine = root / "engine"
        workspace = engine / "gws/src/workspace"
        webview = engine / "gws/src/webview"
        workspace.mkdir(parents=True, exist_ok=True)
        webview.mkdir(parents=True, exist_ok=True)
        helper = root / "capabilities.py"
        helper.write_text("import json\nprint(json.dumps({'schema':'MergeReviewCapabilities/v1'}))\n", encoding="utf-8")
        (workspace / "installedReviewer.js").write_text(
            "exports.readInstalledReviewerBinding=async()=>(" + json.dumps({"script_path": str(helper)}) + ");\n",
            encoding="utf-8")
        (workspace / "reviewLaunch.js").write_text(
            "exports.saveReviewLaunchRequest=async(request)=>({request});\n", encoding="utf-8")
        (webview / "skillsGuideData.js").write_text(
            "exports.getSkillGuideCard=()=>({id:'merge-repo'});\n"
            "exports.buildSkillGuideContext=()=>'';\n"
            "exports.buildSkillGuidePrompt=(_,inputs)=>JSON.stringify(inputs);\n", encoding="utf-8")
        data = {"engine": str(engine), "workspace": str(root / "workspace"), "project": str(root / "workspace/service"),
                "runtime": str(root / "runtime"), "python": sys.executable, "version": "test", "repositories": [],
                "requestId": "a" * 32, "base": "main", "head": "feature", "variant": variant, "effort": effort}
        source = root / "input.json"
        source.write_text(json.dumps(data), encoding="utf-8")
        result = subprocess.run(["node", str(ROOT / "scripts/reviewer-reliability-prompt.cjs"), str(source)],
                                capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def test_supported_effort_is_identical_in_both_product_prompt_variants(self):
        with tempfile.TemporaryDirectory(prefix="rr-prompt-") as name:
            for variant in ("baseline", "candidate"):
                with self.subTest(variant=variant):
                    result = self.build(Path(name), variant, "max")
                    self.assertEqual("max", result["effort"])
                    self.assertEqual("max", json.loads(result["prompt"])["merge-repo.effort"])

    def test_unsupported_or_missing_effort_uses_product_supported_fallback(self):
        with tempfile.TemporaryDirectory(prefix="rr-prompt-") as name:
            for effort, label in (("ultra", "unsupported"), (None, "missing"), ("max\";exit()", "invalid")):
                with self.subTest(case=label):
                    result = self.build(Path(name), "candidate", effort)
                    self.assertEqual("xhigh", result["effort"])
                    self.assertEqual("xhigh", json.loads(result["prompt"])["merge-repo.effort"])

    def test_trial_rejects_inconsistent_effort_before_any_model_process(self):
        spec = importlib.util.spec_from_file_location("prompt_test_runner", ROOT / "scripts/run-reviewer-reliability.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory(prefix="rr-effort-") as name:
            root = Path(name)
            fixture = root / "source"
            fixture.mkdir()
            workroot = root / "isolated"
            workroot.mkdir()
            args = SimpleNamespace(engine=root / "engine", output=root / "output", effort="ultra", model="test-model")
            source = {"case": "case", "workspace": str(fixture), "base": "main", "head": "feature"}
            built = SimpleNamespace(returncode=0, stdout=json.dumps({"prompt": "fixed", "binding": {}, "effort": "xhigh"}), stderr="")
            with mock.patch.object(runner.tempfile, "mkdtemp", return_value=str(workroot)), \
                 mock.patch.object(runner, "install_fixture"), \
                 mock.patch.object(runner.subprocess, "run", return_value=built), \
                 mock.patch.object(runner.subprocess, "Popen", side_effect=AssertionError("unexpected model process")):
                with self.assertRaisesRegex(ValueError, "Product prompt and CLI effort differ"):
                    runner.run_trial(args, source, 1, Path("unused-codex"), {"variant": "candidate", "kit_version": "test"})
            error = json.loads((root / "output/case/candidate/trial-1/setup-error.json").read_text(encoding="utf-8"))
            self.assertEqual("inconsistent-model-effort", error["code"])
            self.assertEqual(0, error["model_calls"])
            self.assertEqual("ultra", error["requested_effort"])
            self.assertEqual("xhigh", error["product_effort"])


if __name__ == "__main__":
    unittest.main()
