"""Check independent synthetic oracles and reject misleading acceptance results."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("reviewer_reliability_benchmark", ROOT / "scripts/benchmark-reviewer-reliability.py")
BENCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCH)


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

    def test_required_gap_must_not_be_marked_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, oracle, runs = self.records(directory)
            oracle["cases"][0].update(expected_findings=[], expected_complete=False)
            for row in runs:
                row["adjudication"].update(matched_findings=[], review_complete=False)
            self.assertTrue(BENCH.score(manifest, oracle, runs)["accepted"])
            runs[1]["adjudication"]["review_complete"] = True
            self.assertFalse(BENCH.score(manifest, oracle, runs)["accepted"])


if __name__ == "__main__":
    unittest.main()
