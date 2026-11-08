"""Measure selected source bytes separately from optional paired model evidence."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("syntax_benchmark_engine", ROOT / "resources/workflow-kit/common/scripts/syntax-context/engine.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


def score_model_runs(rows):
    """Input contains independently captured actual off/auto model runs, never estimates."""
    required = {"scenario", "size", "cache", "model", "effort", "fixture_sha256", "expected_critical", "off", "auto"}
    groups, quality, run_ids = {}, True, set()
    for row in rows:
        if not required <= row.keys() or row["size"] not in ("large", "small") or row["cache"] not in ("cold", "warm"):
            raise ValueError("Incomplete paired model evidence")
        before, after = row["off"], row["auto"]
        for run in (before, after):
            if (not {"run_id", "input_tokens", "tool_round_trips", "total_seconds", "critical_found", "false_positives", "coverage_complete"} <= run.keys()
                    or run["input_tokens"] <= 0 or run["total_seconds"] <= 0 or run["tool_round_trips"] < 0
                    or run["false_positives"] < 0 or not isinstance(run["run_id"], str) or not run["run_id"]):
                raise ValueError("Model evidence needs actual token/time measurements and independent judgments")
            if run["run_id"] in run_ids:
                raise ValueError("Repeated run identity cannot count as independent evidence")
            run_ids.add(run["run_id"])
        quality &= (set(row["expected_critical"]) <= set(after["critical_found"])
                    and set(before["critical_found"]) <= set(after["critical_found"])
                    and after["false_positives"] <= before["false_positives"]
                    and after["coverage_complete"] is True)
        key = (row["scenario"], row["size"], row["model"], row["effort"], row["fixture_sha256"], row["cache"])
        groups.setdefault(key, []).append((after["input_tokens"] / before["input_tokens"], after["total_seconds"] / before["total_seconds"],
                                          before["tool_round_trips"], after["tool_round_trips"]))
    adequate = (bool(groups) and all(len(samples) >= 3 for samples in groups.values())
                and {key[1] for key in groups} == {"large", "small"}
                and any(not row["expected_critical"] and not row["off"]["critical_found"] for row in rows)
                and all({other[-1] for other in groups if other[:-1] == key[:-1]} == {"cold", "warm"} for key in groups))
    performance = adequate and all(
        statistics.median(sample[1] for sample in samples) <= (0.9 if key[1] == "large" else 1.05)
        and (key[1] != "large" or statistics.median(sample[0] for sample in samples) <= 0.8)
        for key, samples in groups.items())
    comparisons = [{"scenario": key[0], "size": key[1], "model": key[2], "effort": key[3], "fixture_sha256": key[4], "cache": key[5],
                    "paired_runs": len(samples), "input_ratio_median": statistics.median(sample[0] for sample in samples),
                    "total_time_ratio_median": statistics.median(sample[1] for sample in samples),
                    "off_tool_round_trips_median": statistics.median(sample[2] for sample in samples),
                    "auto_tool_round_trips_median": statistics.median(sample[3] for sample in samples)} for key, samples in sorted(groups.items())]
    return {"adequate_paired_runs": adequate, "paired_model_comparisons": comparisons, "model_quality_verified": adequate and quality,
            "end_to_end_performance_verified": performance, "default_enablement_passed": adequate and quality and performance}


def benchmark(repetitions):
    results = []
    for extension, opening, member, closing in (
        ("cs", "class Example {\n", " int Method{n}() {{\n  return {n};\n }}\n", "}\n"),
        ("java", "class Example {\n", " int method{n}() {{\n  return {n};\n }}\n", "}\n"),
        ("js", "", "function method{n}() {{\n return {n};\n}}\n", ""),
        ("ts", "", "function method{n}(): number {{\n return {n};\n}}\n", ""),
    ):
        text = opening + "".join(member.format(n=n) for n in range(500)) + closing
        raw, lines = text.encode(), text.splitlines(keepends=True)
        target = next(i + 1 for i, line in enumerate(lines) if "return 250;" in line)
        cold, warm = [], []
        for _ in range(repetitions):
            began = time.perf_counter()
            analyzer = engine.Engine()
            plan = analyzer.plan(raw, "Example." + extension, [[target, target]])
            cold.append(time.perf_counter() - began)
            began = time.perf_counter()
            analyzer.plan(raw, "Example." + extension, [[target, target]])
            warm.append(time.perf_counter() - began)
            if plan["status"] != "ok":
                raise ValueError(plan)
        selected = sum(len("".join(lines[first - 1:last]).encode()) for first, last in plan["ranges"])
        results.append({"language": plan["language"], "source_sha256": engine.sha(raw), "full_source_bytes": len(raw),
                        "selected_source_bytes": selected, "selected_source_ratio": selected / len(raw),
                        "cold_facts_cache_seconds_median": statistics.median(cold), "warm_facts_cache_seconds_median": statistics.median(warm),
                        "all_changed_lines_selected": any(a <= target <= b for a, b in plan["ranges"])})
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--model-results", type=Path)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 30:
        parser.error("repeat must be 1..30")
    report = {"schema": "SyntaxBenchmark/v1", "engine_sha256": engine.Engine().identity, "repetitions": args.repeat,
              "mechanical": benchmark(args.repeat), "model_tokens": None, "end_to_end_review_seconds": None,
              "model_quality_verified": False, "end_to_end_performance_verified": False, "default_enablement_passed": False,
              "limitation": "Selected source bytes exclude model reasoning, syntax outlines and native framing. Timings compare cold/warm in-memory facts caches; grammar modules and OS caches may be warm. This is not an end-to-end review speed or quality result."}
    if args.model_results:
        model_bytes = args.model_results.read_bytes()
        report.update(score_model_runs(json.loads(model_bytes)))
        report["model_evidence_sha256"] = engine.sha(model_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
