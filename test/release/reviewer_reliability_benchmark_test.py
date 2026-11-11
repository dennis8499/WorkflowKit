"""Check independent synthetic oracles and reject misleading acceptance results."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("reviewer_reliability_benchmark", ROOT / "scripts/benchmark-reviewer-reliability.py")
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)
RUNNER_SPEC = importlib.util.spec_from_file_location("run_reviewer_reliability", ROOT / "scripts/run-reviewer-reliability.py")
RUNNER = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(RUNNER)


class ReliabilityBenchmarkTests(unittest.TestCase):
    def test_catalog_covers_each_supplied_session_once(self):
        data = json.loads(BENCH.CATALOG.read_text(encoding="utf-8"))
        ids = [row["id"] for row in data["sessions"]]
        self.assertEqual(len(ids), 8)
        self.assertEqual(len(set(ids)), 8)
        self.assertEqual(set(data["semantic_cases"]), set(BENCH.CASES))

    def test_synthetic_oracles_establish_concrete_behavior(self):
        # Only execute these checked-in synthetic source strings, never log content.
        def versions(name):
            modules = []
            for version in ("base", "head"):
                module = {}
                exec(BENCH.CASES[name][version], module)
                modules.append(module)
            return modules
        old, new = versions("date-boundary")
        self.assertTrue(old["active"](10, 10))
        self.assertFalse(new["active"](10, 10))
        old, new = versions("cache-date")
        for version, expected in ((old, [1, 2]), (new, [1, 1])):
            cache = {}
            self.assertEqual([version["positions"](cache, lambda day: day, day, 3) for day in (1, 2)], expected)
        old, new = versions("duplicate-key")
        self.assertEqual(old["index"]([("A", 1), ("A", 2)]), {"A": [1, 2]})
        with self.assertRaises(ValueError):
            new["index"]([("A", 1), ("A", 2)])
        old, new = versions("empty-query")
        self.assertIsNone(old["previous_day"]([]))
        with self.assertRaises(IndexError):
            new["previous_day"]([])
        consumer = {}
        exec(BENCH.CASES["consumer-contract"]["consumer"], consumer)
        old, new = versions("consumer-contract")
        self.assertEqual(consumer["consume"](old["response"](3)), 6)
        with self.assertRaises(KeyError):
            consumer["consume"](new["response"](3))
        old, new = versions("safe-existing")
        self.assertEqual(consumer["consume"](old["response"](3)), consumer["consume"](new["response"](3)))

    def records(self, directory):
        identity = "fixed-source"
        manifest = {"schema": "ReviewerReliabilityMatrix/v1", "cases": [{"case": "case", "source_identity": identity}]}
        oracle = {"schema": "ReviewerReliabilityOracle/v1", "cases": [{"case": "case", "source_identity": identity,
                  "expected_findings": ["defect"], "expected_complete": True}]}
        runs = []
        for trial in range(1, 4):
            for variant in ("baseline", "candidate"):
                trace = Path(directory) / f"synthetic-test-trace-{trial}-{variant}.json"
                trace.write_text(json.dumps({"test_only": True, "trial": trial, "variant": variant}), encoding="utf-8")
                runs.append({"case": "case", "trial": trial, "variant": variant, "source_identity": identity,
                             "execution_id": f"test-only-{variant}-{trial}",
                             "model": "test-model", "effort": "high", "skill_sha256": variant,
                             "prompt_profile": BENCH.PROMPT_PROFILE,
                             "status": "completed", "exit_code": 0, "native_state": "published",
                             "native_outcome": {"review_complete": True}, "source_drift": [],
                             "trace_path": str(trace), "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
                             "prompt_chars": 100 if variant == "baseline" else 40,
                             "tool_calls": 10 if variant == "baseline" else 8,
                             "elapsed_seconds": 10, "first_draft_seconds": 2, "duplicate_document_bytes": 0,
                             "authoring_retries": 0, "tokens": None,
                             "adjudication": {"verified": True, "reviewer": "test-only-adjudicator",
                                              "review_complete": True, "false_positives": 0,
                                              "required_evidence_omitted": 0, "matched_findings": ["defect"]}})
        return manifest, oracle, runs

    def test_absent_runs_are_incomplete_not_a_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, oracle, _ = self.records(directory)
            result = BENCH.score(manifest, oracle, [])
            self.assertEqual(result["status"], "incomplete")
            self.assertFalse(result["accepted"])

    def test_empty_or_duplicate_case_matrix_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, oracle, _ = self.records(directory)
            for value in ([], [manifest["cases"][0], manifest["cases"][0]]):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    BENCH.score({**manifest, "cases": value}, oracle, [])

    def test_reused_execution_or_trace_is_not_an_independent_trial(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, oracle, runs = self.records(directory)
            for field in ("execution_id", "trace_sha256"):
                changed = copy.deepcopy(runs)
                changed[2][field] = changed[0][field]
                with self.subTest(field=field), self.assertRaises(ValueError):
                    BENCH.score(manifest, oracle, changed)

    def test_paired_metrics_do_not_invent_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            result = BENCH.score(*self.records(directory))
            self.assertTrue(result["accepted"])
            self.assertFalse(result["cases"][0]["tokens_observed"])

    def test_quality_failure_wins_over_speed_gain(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, oracle, runs = self.records(directory)
            runs[1]["adjudication"]["matched_findings"] = []
            self.assertFalse(BENCH.score(manifest, oracle, runs)["accepted"])
            runs[1]["adjudication"]["matched_findings"] = ["defect"]
            runs[1]["adjudication"]["required_evidence_omitted"] = 1
            self.assertFalse(BENCH.score(manifest, oracle, runs)["accepted"])

    def test_incompatible_or_unobserved_runs_are_rejected(self):
        mutations = [lambda r: r[1].update(model="another-model"),
                     lambda r: r[1].update(source_identity="new-source"),
                     lambda r: r[1].update(tool_calls=None),
                     lambda r: r[1].update(elapsed_seconds=float("nan")),
                     lambda r: r[1].update(prompt_profile="native-review-with-routing/v1"),
                     lambda r: r[1].update(trace_sha256="wrong"),
                     lambda r: r[1]["adjudication"].update(verified=False),
                     lambda r: r[3].update(skill_sha256="changed-during-run")]
        with tempfile.TemporaryDirectory() as directory:
            manifest, oracle, runs = self.records(directory)
            for mutate in mutations:
                with self.subTest(mutate=mutate):
                    changed = copy.deepcopy(runs)
                    mutate(changed)
                    with self.assertRaises(ValueError):
                        BENCH.score(manifest, oracle, changed)

    def test_execution_and_publication_failures_cannot_pass(self):
        mutations = [lambda row: row.update(status="timed-out"),
                     lambda row: row.update(status="failed"),
                     lambda row: row.update(status="native-incomplete"),
                     lambda row: row.update(exit_code=1),
                     lambda row: row.update(native_state="failed"),
                     lambda row: row.update(native_state=None),
                     lambda row: row.update(native_outcome=None),
                     lambda row: row.pop("native_outcome"),
                     lambda row: row.update(source_drift=["service"]),
                     lambda row: row.update(native_outcome={"review_complete": False})]
        with tempfile.TemporaryDirectory() as directory:
            manifest, oracle, runs = self.records(directory)
            for variant_index in (0, 1):
                for mutate in mutations:
                    with self.subTest(variant=runs[variant_index]["variant"], mutate=mutate):
                        changed = copy.deepcopy(runs)
                        mutate(changed[variant_index])
                        with self.assertRaises(ValueError):
                            BENCH.score(manifest, oracle, changed)

    def test_required_gap_must_not_be_marked_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, oracle, runs = self.records(directory)
            oracle["cases"][0].update(expected_findings=[], expected_complete=False)
            for row in runs:
                row["adjudication"].update(matched_findings=[], review_complete=False)
                row["native_outcome"]["review_complete"] = False
            self.assertTrue(BENCH.score(manifest, oracle, runs)["accepted"])
            runs[1]["adjudication"]["review_complete"] = True
            runs[1]["native_outcome"]["review_complete"] = True
            self.assertFalse(BENCH.score(manifest, oracle, runs)["accepted"])


class EngineFreezeTests(unittest.TestCase):
    def repository(self, root, files):
        root.mkdir(parents=True)
        subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True,
                       text=True, encoding="utf-8")
        for key, value in {"user.name": "Fixture", "user.email": "fixture@example.invalid",
                           "core.longpaths": "true", "gc.auto": "0", "maintenance.auto": "false"}.items():
            subprocess.run(["git", "-C", str(root), "config", key, value], check=True, capture_output=True)
        for name, value in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(value, encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "baseline"], check=True, capture_output=True)
        baseline = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                                  capture_output=True, text=True, encoding="utf-8").stdout.strip()
        return baseline

    def update_repository(self, root, updates):
        for name, value in updates.items():
            (root / name).write_text(value, encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "candidate"], check=True, capture_output=True)
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True, encoding="utf-8").stdout.strip()

    def test_freeze_pins_all_three_repositories_and_checks_every_payload_file(self):
        with tempfile.TemporaryDirectory(prefix="reviewer-engine-freeze-") as directory:
            parent = Path(directory)
            merge = parent / "MergeReviewer"
            kit = parent / "WorkflowKit"
            workspace = parent / "GitlabWorkSpace"
            merge_base = self.repository(merge, {
                "skills/merge-reviewer/VERSION": "0.20.6\n",
                "skills/merge-reviewer/scripts/review_session.py": "# baseline helper\n",
            })
            kit_base = self.repository(kit, {
                "VERSION": "1.7.0\n",
                "resources/workflow-kit/common/profile.md": "baseline workflow\n",
            })
            workspace_base = self.repository(workspace, {
                "package.json": '{"name":"gitlab-workspace","version":"0.47.0"}\n',
                "src/codex/launch.ts": "export const version = 'baseline';\n",
            })
            merge_head = self.update_repository(merge, {
                "skills/merge-reviewer/VERSION": "0.21.1\n",
                "skills/merge-reviewer/scripts/review_session.py": "# candidate helper\n",
            })
            kit_head = self.update_repository(kit, {
                "VERSION": "1.8.0\n",
                "resources/workflow-kit/common/profile.md": "candidate workflow\n",
            })
            workspace_head = self.update_repository(workspace, {
                "package.json": '{"name":"gitlab-workspace","version":"0.48.0"}\n',
                "src/codex/launch.ts": "export const version = 'candidate';\n",
            })
            with mock.patch.object(RUNNER, "ROOT", kit), \
                 mock.patch.object(RUNNER, "PARENT", parent), \
                 mock.patch.object(RUNNER, "transpile_typescript", side_effect=lambda source, _compiler:
                    [(path.with_suffix(".js")).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
                     for path in source.rglob("*.ts")]):
                baseline = SimpleNamespace(variant="baseline", output=parent / "engines/baseline",
                    merge_ref=merge_base, workflowkit_ref=kit_base, gitlab_workspace_ref=workspace_base)
                candidate = SimpleNamespace(variant="candidate", output=parent / "engines/candidate",
                    merge_ref=merge_head, workflowkit_ref=kit_head, gitlab_workspace_ref=workspace_head)
                RUNNER.freeze(baseline)
                RUNNER.freeze(candidate)
                mismatched = SimpleNamespace(variant="baseline", output=parent / "engines/mismatched",
                    merge_ref=merge_base, workflowkit_ref=kit_head, gitlab_workspace_ref=workspace_base)
                with self.assertRaisesRegex(ValueError, "acceptance pair"):
                    RUNNER.freeze(mismatched)
                self.assertFalse(mismatched.output.exists())
                baseline_engine, candidate_engine = baseline.output, candidate.output
                baseline_metadata = RUNNER.load_engine(baseline_engine)
                candidate_metadata = RUNNER.load_engine(candidate_engine)
            self.assertEqual(baseline_metadata["source_revisions"], {
                "merge_reviewer": merge_base, "workflow_kit": kit_base, "gitlab_workspace": workspace_base})
            self.assertEqual(candidate_metadata["source_revisions"], {
                "merge_reviewer": merge_head, "workflow_kit": kit_head, "gitlab_workspace": workspace_head})
            self.assertEqual((baseline_metadata["merge_version"], baseline_metadata["kit_version"],
                              baseline_metadata["gitlab_workspace_version"]), ("0.20.6", "1.7.0", "0.47.0"))
            self.assertEqual((candidate_metadata["merge_version"], candidate_metadata["kit_version"],
                              candidate_metadata["gitlab_workspace_version"]), ("0.21.1", "1.8.0", "0.48.0"))
            self.assertIn("baseline workflow", (baseline_engine / "kit-source/resources/workflow-kit/common/profile.md").read_text(encoding="utf-8"))
            self.assertIn("candidate workflow", (candidate_engine / "kit-source/resources/workflow-kit/common/profile.md").read_text(encoding="utf-8"))
            (candidate_engine / "gws/src/codex/launch.ts").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "payload changed"):
                RUNNER.load_engine(candidate_engine)


if __name__ == "__main__":
    unittest.main()
