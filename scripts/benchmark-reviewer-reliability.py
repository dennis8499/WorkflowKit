"""Prepare blind, source-only fixtures and score independently adjudicated paired runs.

This does not fabricate model reviews or infer model usage from helper timing.
The oracle is outside the workspace and must not be sent to the reviewer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "test/fixtures/reviewer-reliability-cases.json"
DATE = "2026-11-10T00:00:00+00:00"
PROMPT_PROFILE = "native-review-no-routing/v2"

CASES = {
    "date-boundary": {
        "base": "def active(expiry, day):\n    return expiry >= day\n",
        "head": "def active(expiry, day):\n    return expiry > day\n",
        "contract": "Positions remain active through their expiry date, including that day.",
        "finding": "expiry-day-excluded", "expected_complete": True,
        "oracle": "active(10, 10) changes from True to False, violating the inclusive expiry contract."},
    "cache-date": {
        "base": "def positions(cache, query, trade_date, today):\n    key = trade_date\n    if key not in cache:\n        cache[key] = query(trade_date)\n    return cache[key]\n",
        "head": "def positions(cache, query, trade_date, today):\n    key = today\n    if key not in cache:\n        cache[key] = query(trade_date)\n    return cache[key]\n",
        "contract": "Historical requests for distinct trade dates must return the positions for each requested date.",
        "finding": "historical-cache-collision", "expected_complete": True,
        "oracle": "Two requested trade dates sharing today reuse the first date's positions."},
    "duplicate-key": {
        "base": "def index(rows):\n    result = {}\n    for key, value in rows:\n        result.setdefault(key, []).append(value)\n    return result\n",
        "head": "def index(rows):\n    result = {}\n    for key, value in rows:\n        if key in result:\n            raise ValueError('duplicate key')\n        result[key] = [value]\n    return result\n",
        "contract": "Each product may have multiple underlying rows; export must include all rows.",
        "finding": "valid-duplicate-rejected", "expected_complete": True,
        "oracle": "index([('A', 1), ('A', 2)]) was valid and now raises ValueError."},
    "empty-query": {
        "base": "def previous_day(rows):\n    return rows[0] if rows else None\n",
        "head": "def previous_day(rows):\n    return rows[0]\n",
        "contract": "No prior trading date is a valid query result, represented by None.",
        "finding": "empty-query-crash", "expected_complete": True,
        "oracle": "previous_day([]) now raises IndexError instead of returning None."},
    "consumer-contract": {
        "base": "def response(value):\n    return {'amount': value}\n",
        "head": "def response(value):\n    return {'total': value}\n",
        "consumer": "def consume(payload):\n    return payload['amount'] * 2\n",
        "contract": "The reports consumer calls response and reads the amount field; no translation layer exists.",
        "finding": "consumer-field-removed", "expected_complete": True,
        "oracle": "The fixed peer consumer raises KeyError after the response rename."},
    "safe-existing": {
        "base": "def response(value):\n    return {'amount': value}\n\ndef legacy_first(rows):\n    return rows[0]\n",
        "head": "def response(value):\n    return {'amount': value, 'total': value}\n\ndef legacy_first(rows):\n    return rows[0]\n",
        "consumer": "def consume(payload):\n    return payload['amount'] * 2\n",
        "contract": "The API allows additional fields. Only the fixed reports consumer uses it. legacy_first is unchanged.",
        "finding": None, "expected_complete": True,
        "oracle": "Compatible additive field; do not report unchanged empty-list behavior or invent outside-scope consumers."},
    "required-consumer-gap": {
        "base": "def response(value):\n    return {'amount': value}\n",
        "head": "def response(value):\n    return {'total': value}\n",
        "contract": "A required settlement consumer reads this response. Its implementation was not supplied. It must be checked before compatibility can be established.",
        "finding": None, "expected_complete": False,
        "oracle": "Preserve a required-consumer evidence gap. A concrete consumer runtime defect is not established."},
}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(repo, *args):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_AUTHOR_DATE": DATE, "GIT_COMMITTER_DATE": DATE}
    return subprocess.run(["git", "-c", "core.longpaths=true", "-C", str(repo), *map(str, args)],
                          env=env, check=True, capture_output=True, text=True, encoding="utf-8", timeout=30).stdout.strip()


def initialize(repo, files):
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    for key, value in {"user.name": "Synthetic Review", "user.email": "review@example.invalid",
                       "commit.gpgsign": "false", "core.autocrlf": "false", "core.hooksPath": str(repo / "no-hooks")}.items():
        git(repo, "config", key, value)
    for name, content in files.items():
        (repo / name).write_text(content, encoding="utf-8", newline="\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "fixed baseline")


def prepare(destination, selected=None, changed_files=None):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Use a fresh output directory; existing results are never overwritten")
    chosen = list(selected or CASES)
    if not chosen or any(name not in CASES for name in chosen) or len(chosen) != len(set(chosen)):
        raise ValueError("Choose unique supported cases")
    destination.mkdir(parents=True)
    fixtures, oracles = [], []
    plans = [(name, size) for name in chosen for size in (changed_files or [1])]
    if any(size not in (1, 6, 7, 11, 20) for _, size in plans):
        raise ValueError('Changed-file sizes must match the observed 1/6/7/11/20-file shapes.')
    for source_case, size in plans:
        name = source_case if changed_files is None else f'{source_case}-files-{size}'
        case = CASES[source_case]
        workspace = destination / name / "Project" / "review workspace"
        project = workspace / "service"
        additional = {f'local_{i:02}.py': f'def calculate_{i}(value):\n    return value * 2\n' for i in range(1, size)}
        initialize(project, {"app.py": case["base"], "CONTRACT.md": case["contract"] + "\n", **additional})
        base = git(project, "rev-parse", "HEAD")
        git(project, "switch", "-c", "feature/review")
        (project / "app.py").write_text(case["head"], encoding="utf-8", newline="\n")
        for filename, content in additional.items():
            (project / filename).write_text(content.replace('return value * 2', 'return (value * 2)'), encoding='utf-8', newline='\n')
        git(project, "add", ".")
        git(project, "commit", "-m", "comparison change")
        peers = []
        for index in range(15):
            peer = workspace / ("reports-consumer" if index == 0 else f"unrelated-{index:02}")
            files = {"README.md": "Unrelated fixed peer; no service API usage.\n"}
            if index == 0 and "consumer" in case:
                files = {"consumer.py": case["consumer"], "README.md": "Calls the service response API directly.\n"}
            initialize(peer, files)
            peers.append({"name": peer.name, "sha": git(peer, "rev-parse", "HEAD")})
        source = {"base_sha": base, "head_sha": git(project, "rev-parse", "HEAD"), "peers": peers}
        identity = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
        fixture = {"case": name, "schema": "ReviewerReliabilitySource/v1", "source_only": True, "changed_files": size,
                   "workspace": str(workspace), "project": str(project), "base": "main", "head": "feature/review",
                   "source_identity": identity, **source}
        save(destination / name / "source.json", fixture)
        fixtures.append(fixture)
        oracles.append({"case": name, "source_identity": identity,
                        "expected_findings": [case["finding"]] if case["finding"] else [],
                        "expected_complete": case["expected_complete"], "rationale": case["oracle"]})
    save(destination / "manifest.json", {"schema": "ReviewerReliabilityMatrix/v1", "cases": fixtures,
                                        "minimum_pairs": 3, "model_runs": "not-run"})
    save(destination / "oracle-parent-only.json", {"schema": "ReviewerReliabilityOracle/v1", "cases": oracles})
    return {"output": str(destination), "cases": len(fixtures), "repos_per_case": 16, "model_runs": "not-run"}


def number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be an observed nonnegative finite number")
    return value


def score(manifest, oracle, runs):
    if manifest.get("schema") != "ReviewerReliabilityMatrix/v1" or oracle.get("schema") != "ReviewerReliabilityOracle/v1":
        raise ValueError("Unsupported fixture or oracle schema")
    if (not manifest.get("cases") or not oracle.get("cases")
            or len({row["case"] for row in manifest["cases"]}) != len(manifest["cases"])
            or len({row["case"] for row in oracle["cases"]}) != len(oracle["cases"])):
        raise ValueError("A nonempty set of unique fixture and oracle cases is required")
    expected = {row["case"]: row for row in oracle["cases"]}
    sources = {row["case"]: row["source_identity"] for row in manifest["cases"]}
    if set(expected) != set(sources) or any(expected[k]["source_identity"] != v for k, v in sources.items()):
        raise ValueError("Oracle does not match the fixed sources")
    groups, executions, traces = {}, set(), set()
    for row in runs:
        case, variant, trial = row.get("case"), row.get("variant"), row.get("trial")
        if case not in expected or variant not in ("baseline", "candidate") or type(trial) is not int or trial < 1:
            raise ValueError("Invalid case, variant or trial")
        key = (case, trial)
        if variant in groups.setdefault(key, {}):
            raise ValueError("Duplicate paired run")
        if row.get("source_identity") != sources[case]:
            raise ValueError("Run source identity differs")
        if not all(isinstance(row.get(field), str) and row[field] for field in ("model", "effort", "skill_sha256", "execution_id", "trace_path", "trace_sha256")):
            raise ValueError("Model, effort, skill identity and trace path are required")
        if row.get("prompt_profile") != PROMPT_PROFILE:
            raise ValueError("Run does not use the frozen native-review prompt profile")
        if row["execution_id"] in executions or row["trace_sha256"] in traces:
            raise ValueError("Each run needs an independent execution and raw trace; reused observations are not pairs")
        executions.add(row["execution_id"])
        traces.add(row["trace_sha256"])
        if not Path(row["trace_path"]).is_file():
            raise ValueError("Observed trace is missing")
        if hashlib.sha256(Path(row["trace_path"]).read_bytes()).hexdigest() != row["trace_sha256"]:
            raise ValueError("Observed trace hash differs")
        review = row.get("adjudication", {})
        if review.get("verified") is not True or not review.get("reviewer"):
            raise ValueError("Independent adjudication is required; ungraded model output is not acceptance")
        if type(review.get("review_complete")) is not bool or type(review.get("false_positives")) is not int or review["false_positives"] < 0:
            raise ValueError("Invalid adjudicated completeness or false positives")
        if type(review.get("required_evidence_omitted")) is not int or review["required_evidence_omitted"] < 0:
            raise ValueError("Adjudicated omitted evidence count is required")
        if not isinstance(review.get("matched_findings"), list) or not all(isinstance(x, str) for x in review["matched_findings"]):
            raise ValueError("Adjudicated finding identifiers are required")
        if row.get("status") != "completed" or type(row.get("exit_code")) is not int or row["exit_code"] != 0:
            raise ValueError(f"{variant} execution did not complete successfully")
        if row.get("native_state") != "published":
            raise ValueError(f"{variant} native review was not published")
        drift = row.get("source_drift")
        if not isinstance(drift, list) or any(not isinstance(name, str) for name in drift) or drift:
            raise ValueError(f"{variant} frozen sources are missing or changed")
        native_outcome = row.get("native_outcome")
        if not isinstance(native_outcome, dict) or type(native_outcome.get("review_complete")) is not bool:
            raise ValueError(f"{variant} native review outcome is missing or invalid")
        if native_outcome["review_complete"] != review["review_complete"]:
            raise ValueError(f"{variant} native outcome differs from independent adjudication")
        for field in ("prompt_chars", "tool_calls", "elapsed_seconds", "first_draft_seconds", "duplicate_document_bytes", "authoring_retries"):
            number(row.get(field), field)
        if row.get("tokens") is not None:
            number(row["tokens"], "tokens")
        groups[key][variant] = row
    missing = [f"{case}: at least 3 complete pairs required" for case in expected
               if sum(k[0] == case and set(v) == {"baseline", "candidate"} for k, v in groups.items()) < 3]
    if any(set(pair) != {"baseline", "candidate"} for pair in groups.values()):
        missing.append("Unpaired run")
    if missing:
        return {"schema": "ReviewerReliabilityScore/v1", "status": "incomplete", "missing": missing, "accepted": False}
    failures, per_case = [], []
    for case in expected:
        pairs = [pair for (name, _), pair in groups.items() if name == case]
        if len({(p[v]["model"], p[v]["effort"]) for p in pairs for v in p}) != 1:
            raise ValueError("Do not mix model or effort settings across a case's trials")
        for variant in ("baseline", "candidate"):
            if len({p[variant]["skill_sha256"] for p in pairs}) != 1:
                raise ValueError("Freeze each variant's skill before all trials")
        for pair in pairs:
            baseline, candidate = pair["baseline"], pair["candidate"]
            if (baseline["model"], baseline["effort"]) != (candidate["model"], candidate["effort"]):
                raise ValueError("Paired runs must use the same model and effort")
            wanted = set(expected[case]["expected_findings"])
            bq, cq = baseline["adjudication"], candidate["adjudication"]
            if (set(cq["matched_findings"]) != wanted or cq["false_positives"] != 0
                    or cq["review_complete"] != expected[case]["expected_complete"] or cq["required_evidence_omitted"] != 0):
                failures.append(f"{case}: candidate violates independent oracle")
            if (len(wanted - set(cq["matched_findings"])) > len(wanted - set(bq["matched_findings"]))
                    or cq["false_positives"] > bq["false_positives"]):
                failures.append(f"{case}: quality regression")
        ratios = {}
        changed_files = next(row.get('changed_files', 1) for row in manifest['cases'] if row['case'] == case)
        for field, limit in (("prompt_chars", None), ("tool_calls", None), ("elapsed_seconds", .5 if changed_files >= 6 else 1.0)):
            before = statistics.median(pair["baseline"][field] for pair in pairs)
            after = statistics.median(pair["candidate"][field] for pair in pairs)
            ratio = after / before if before else (1.0 if after == 0 else None)
            ratios[field] = ratio
            if limit is not None and (ratio is None or (before > 0 and ratio > limit)):
                failures.append(f"{case}: {field} target missed")
        per_case.append({"case": case, "pairs": len(pairs), "ratios": ratios,
                         "tokens_observed": all(p[v].get("tokens") is not None for p in pairs for v in p)})
    return {"schema": "ReviewerReliabilityScore/v1", "status": "failed" if failures else "passed",
            "accepted": not failures, "failures": sorted(set(failures)), "cases": per_case}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--case", choices=tuple(CASES), action="append")
    grade = sub.add_parser("score")
    for name in ("manifest", "oracle", "runs", "output"):
        grade.add_argument("--" + name, type=Path, required=True)
    prep.add_argument('--changed-files', action='append', type=int, choices=(1, 6, 7, 11, 20))
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.output, args.case, args.changed_files)
    else:
        read = lambda p: json.loads(p.read_text(encoding="utf-8"))
        result = score(read(args.manifest), read(args.oracle), read(args.runs))
        save(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("accepted", args.command == "prepare") else 3


if __name__ == "__main__":
    raise SystemExit(main())
