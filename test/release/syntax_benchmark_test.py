"""Acceptance cannot be inferred from byte reduction or incomplete paired runs."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("syntax_benchmark", Path(__file__).resolve().parents[2] / "scripts/benchmark-syntax.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def evidence():
    rows = []
    for size in ("large", "small"):
        for cache in ("cold", "warm"):
            for repeat in range(3):
                def run(mode):
                    return {"run_id": f"{size}-{cache}-{repeat}-{mode}", "input_tokens": 700 if mode == "auto" else 1000,
                            "tool_round_trips": 4 if mode == "auto" else 8, "total_seconds": 85 if mode == "auto" else 100,
                            "critical_found": ["known-defect"] if size == "large" else [], "false_positives": 0, "coverage_complete": True}
                rows.append({"scenario": size, "size": size, "cache": cache, "model": "fixed-test-model", "effort": "high",
                             "fixture_sha256": "a" * 64, "expected_critical": ["known-defect"] if size == "large" else [], "off": run("off"), "auto": run("auto")})
    return rows


class SyntaxBenchmarkGateTests(unittest.TestCase):
    def test_requires_independent_cold_and_warm_repetitions(self):
        self.assertTrue(benchmark.score_model_runs(evidence())["default_enablement_passed"])
        self.assertFalse(benchmark.score_model_runs([row for row in evidence() if row["cache"] == "cold"])["default_enablement_passed"])
        rows = evidence()
        rows[1]["auto"]["run_id"] = rows[0]["auto"]["run_id"]
        with self.assertRaisesRegex(ValueError, "Repeated run"):
            benchmark.score_model_runs(rows)

    def test_missed_critical_defects_and_false_positives_block_acceptance(self):
        for changes in ({"critical_found": []}, {"false_positives": 1}, {"coverage_complete": False}):
            rows = deepcopy(evidence())
            rows[0]["auto"].update(changes)
            self.assertFalse(benchmark.score_model_runs(rows)["default_enablement_passed"])

    def test_small_case_regression_and_large_input_threshold_are_independent(self):
        for size, field, value in (("small", "total_seconds", 106), ("large", "input_tokens", 801)):
            rows = evidence()
            for row in rows:
                if row["size"] == size:
                    row["auto"][field] = value
            result = benchmark.score_model_runs(rows)
            self.assertTrue(result["model_quality_verified"])
            self.assertFalse(result["end_to_end_performance_verified"])
