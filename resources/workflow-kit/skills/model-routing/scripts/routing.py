#!/usr/bin/env python3
"""Persist model/effort routing against a native frozen review; no Git or model calls."""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import sys
import uuid

MODEL = "gpt-6-luna"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
SCHEMA_V2 = "ReviewModelRouting/v2"


def model_settings(model, efforts):
    if (not isinstance(model, str) or not model.strip() or len(model) > 200
            or any(ord(char) < 32 for char in model)
            or not isinstance(efforts, list) or not 1 <= len(efforts) <= 32
            or any(not isinstance(item, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", item)
                   or item == "auto" for item in efforts) or len(set(efforts)) != len(efforts)):
        raise ValueError("Invalid model or supported reasoning efforts.")
    return model, efforts


def select_effort(recommended, supported):
    if recommended not in EFFORT_ORDER or any(item not in EFFORT_ORDER for item in supported):
        raise ValueError("Auto cannot order these efforts; choose a manual effort.")
    choices = [item for item in EFFORT_ORDER if item in supported]
    selected = next((item for item in choices if EFFORT_ORDER.index(item) >= EFFORT_ORDER.index(recommended)), choices[-1])
    return selected, EFFORT_ORDER.index(selected) < EFFORT_ORDER.index(recommended)
TOOLS = {"merge-reviewer": ("MergeReviewRuntime/v1", "MergeReviewSession/v1"),
         "release-reviewer": ("ReleaseReviewRuntime/v1", "ReleaseReviewSession/v1")}
SCHEMA = "ReviewModelRouting/v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def plain(path):
    path = Path(os.path.abspath(path))
    for probe in (path, *path.parents):
        try:
            info = probe.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Routing paths must not contain links or junctions.")
    return path


def read(path):
    path = plain(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Routing input exceeds the size limit.")
    with path.open(encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object.")
    return value


@contextlib.contextmanager
def locked(path):
    path = plain(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"\0"); stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError("Routing is busy; reload status before retrying.") from exc
            try:
                yield
            finally:
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError("Routing is busy; reload status before retrying.") from exc
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def atomic(path, value):
    temporary = plain(path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp"))
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def identity(job, context):
    # Ledger/coverage/manifest hashes change during evidence reads. Only fixed
    # source anchors belong in the routing identity.
    manifest_path = context / "manifest.json"
    # Native manifests may be large: bounded routing JSON limits don't apply.
    with plain(manifest_path).open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    repositories = []
    for repo in manifest["repositories"]:
        sources = {name: source.get("ref") for name, source in repo.get("sources", {}).items()
                   if isinstance(source, dict)}
        snapshot = repo.get("snapshot") or {}
        repositories.append({"id": repo["id"], "sources": sources,
                             "snapshot_sources": sorted(snapshot.get("sources", {}))})
    result = {"input_digest": job["input_digest"], "repositories": repositories}
    for key in ("base_sha", "head_sha", "merge_base", "diff_base", "selected_repo", "entry_repo"):
        if key in manifest:
            result[key] = manifest[key]
    return result


def session(root, tool, identifier):
    root = plain(Path(root).expanduser()).resolve()
    marker = read(root / ("." + tool + "-runtime.json"))
    if marker.get("schema") != TOOLS[tool][0] or Path(marker.get("directory", "")).resolve() != root:
        raise ValueError("Native runtime ownership does not match.")
    job = read(root / "jobs" / (identifier + ".json"))
    if (job.get("schema") != TOOLS[tool][1] or job.get("request_id") != identifier
            or Path(job.get("runtime_root", "")).resolve() != root):
        raise ValueError("Native review identity does not match.")
    if not job.get("context_dir") or not job.get("draft_path"):
        raise ValueError("Native capture has not completed.")
    context = plain(job["context_dir"])
    if context != root / "sessions" / identifier:
        raise ValueError("Native context does not belong to this request.")
    return root, job, context


def validate(record, root, tool, identifier, job, context):
    dynamic = record.get("schema") == SCHEMA_V2
    model, efforts = model_settings(record.get("model"), record.get("supported_efforts") if dynamic else list(EFFORTS))
    if (record.get("schema") not in (SCHEMA, SCHEMA_V2) or not dynamic and model != MODEL or record.get("tool") != tool
            or record.get("request_id") != identifier or record.get("runtime_root") != str(root)
            or record.get("context_dir") != str(context)
            or record.get("requested_effort") not in ("auto", *efforts)
            or record.get("effort") not in (None, *efforts)
            or record.get("phase") not in ("routing", "reviewing", "complete")
            or not isinstance(record.get("revision"), int) or record["revision"] < 0
            or record.get("input_digest") != job.get("input_digest")):
        raise ValueError("Routing record does not match the native review.")
    if dynamic and record["requested_effort"] == "auto" and record["effort"] is not None:
        selected, capped = select_effort(record.get("recommended_effort"), efforts)
        if selected != record["effort"] or capped != record.get("capped"):
            raise ValueError("Saved auto effort does not match model capabilities.")
    if record["requested_effort"] != "auto" and record["effort"] != record["requested_effort"]:
        raise ValueError("Manual effort is fixed for this request.")
    if context.exists():
        if digest(identity(job, context)) != record.get("snapshot_hash"):
            raise ValueError("Frozen source identity changed; routing cannot resume.")
    elif job.get("state") not in ("published", "cancelled", "failed"):
        raise ValueError("Active native evidence is missing.")
    if digest(record.get("fixed_sources")) != record.get("snapshot_hash"):
        raise ValueError("Saved routing source identity is corrupt.")


def operate(args):
    identifier = uuid.UUID(args.request_id).hex
    root, job, context = session(args.runtime_root, args.tool, identifier)
    path = plain(root / "routing" / args.tool / (identifier + ".json"))
    if args.command == "status":
        record = read(path)
        validate(record, root, args.tool, identifier, job, context)
        return record
    with locked(path.with_suffix(".lock")):
        existing = read(path) if path.exists() else None
        if existing:
            validate(existing, root, args.tool, identifier, job, context)
        if args.command == "bind" and existing:
            if job.get("state") not in ("ready", "reviewing", "validating", "published"):
                raise ValueError("Native review is not resumable; preserve its diagnostics.")
            if existing["requested_effort"] != args.effort:
                raise ValueError("This request already has a different effort setting.")
            if getattr(args, "model", None) is not None or getattr(args, "supported_efforts", None) is not None:
                model, efforts = model_settings(args.model, args.supported_efforts.split(",") if isinstance(args.supported_efforts, str) else args.supported_efforts)
                if existing["model"] != model or existing.get("supported_efforts", list(EFFORTS)) != efforts:
                    raise ValueError("This request already has different model capabilities.")
            return existing
        if job.get("state") not in ("ready", "reviewing", "validating", "published"):
            raise ValueError("Native review is not resumable; preserve its diagnostics.")
        if args.command == "bind":
            if job.get("state") == "published":
                raise ValueError("Return the existing report; a published review needs no new routing.")
            fixed = identity(job, context)
            dynamic = getattr(args, "model", None) is not None or getattr(args, "supported_efforts", None) is not None
            model, efforts = model_settings(getattr(args, "model", None) if dynamic else MODEL,
                args.supported_efforts.split(",") if dynamic and isinstance(getattr(args, "supported_efforts", None), str)
                else getattr(args, "supported_efforts", None) if dynamic else list(EFFORTS))
            if args.effort not in ("auto", *efforts):
                raise ValueError("Requested effort is not supported by this model.")
            if args.effort == "auto":
                select_effort("high", efforts)
            selected = None if args.effort == "auto" else args.effort
            record = {"schema": SCHEMA_V2 if dynamic else SCHEMA, "tool": args.tool, "request_id": identifier,
                      "runtime_root": str(root), "context_dir": str(context), "draft_path": job["draft_path"],
                      "input_digest": job["input_digest"], "fixed_sources": fixed, "snapshot_hash": digest(fixed),
                      "requested_effort": args.effort, "model": model, "effort": selected,
                      "phase": "routing" if selected is None else "reviewing", "reason": "" if selected is None else "User-selected effort.",
                      "evidence": [], "checkpoint": "", "history": [], "revision": 0}
            if dynamic:
                record["supported_efforts"] = efforts
            record['files'] = {key: str(context / name) for key, name in (
                ('manifest', 'manifest.json'), ('native_start', 'start.json'),
                ('initial_reads', 'initial-reads.json'), ('worklist', 'review-worklist.json'))
                if plain(context / name).is_file()}
            if selected:
                record["history"].append({"effort": selected, "reason": record["reason"], "evidence": [], "kind": "manual"})
        else:
            if not existing:
                raise ValueError("Bind the native session before changing routing.")
            record = existing
            decision = read(args.decision_file) if args.command != "complete" else {}
            operation_hash = digest({"command": args.command, "revision": args.revision, "decision": decision})
            if record.get("last_operation") == operation_hash:
                return record
            if args.revision != record["revision"]:
                raise ValueError("Routing revision conflict; reload status and reconcile.")
            if args.command == "complete":
                if job.get("state") != "published" or not job.get("report_path"):
                    raise ValueError("Only a published native review can complete routing.")
                if record["phase"] != "reviewing":
                    raise ValueError("A routing assessment cannot complete semantic review.")
                record.update(phase="complete", report_path=job["report_path"],
                              review_outcome=job.get("review_outcome") or job.get("report_receipt", {}).get("review_outcome"))
            else:
                effort, reason, evidence = decision.get("effort"), decision.get("reason"), decision.get("evidence")
                checkpoint = decision.get("checkpoint", "")
                dynamic = record["schema"] == SCHEMA_V2
                if (effort not in (EFFORT_ORDER if dynamic else EFFORTS) or not isinstance(reason, str) or not reason.strip() or len(reason) > 4000
                        or not isinstance(checkpoint, str) or len(checkpoint) > 16000
                        or not isinstance(evidence, list) or len(evidence) > 100
                        or any(not isinstance(item, str) or not item.strip() or len(item) > 2000 for item in evidence)):
                    raise ValueError("Decision needs a supported effort, reason and evidence array.")
                if record["requested_effort"] != "auto":
                    raise ValueError("Manual effort is fixed for this request.")
                if args.command == "decide" and record["phase"] != "routing":
                    raise ValueError("The initial routing decision is already saved.")
                recommended = effort
                effort, capped = select_effort(recommended, record["supported_efforts"]) if dynamic else (effort, False)
                at_limit = dynamic and capped and record["effort"] == effort and args.command == "escalate"
                if args.command == "escalate":
                    if (record["phase"] != "reviewing" or not at_limit and EFFORT_ORDER.index(effort) <= EFFORT_ORDER.index(record["effort"])
                            or not isinstance(decision.get("checkpoint"), str) or not decision["checkpoint"].strip()
                            or len(decision["checkpoint"]) > 16000 or not evidence):
                        raise ValueError("Escalation needs a strictly higher effort, evidence and a saved-work checkpoint.")
                    if not plain(record["draft_path"]).is_file():
                        raise ValueError("Save the native draft before escalating.")
                if capped:
                    reason = reason.strip() + f" Recommended {recommended}; using this model's highest supported effort {effort}."
                if dynamic:
                    record.update(recommended_effort=recommended, capped=capped)
                record.update(effort=effort, reason=reason.strip(), evidence=evidence, phase="reviewing",
                              checkpoint=decision.get("checkpoint", ""))
                entry = {"effort": effort, "reason": reason.strip(), "evidence": evidence,
                         "checkpoint": record["checkpoint"], "kind": args.command}
                if dynamic:
                    entry.update(recommended_effort=recommended, capped=capped)
                if at_limit:
                    record["limit_decision"] = entry
                else:
                    record["history"].append(entry)
            record["revision"] += 1
            record["last_operation"] = operation_hash
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        record["state_path"] = str(path)
        atomic(path, record)
        return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("bind", "status", "decide", "escalate", "complete"):
        sub = commands.add_parser(command)
        sub.add_argument("--tool", choices=tuple(TOOLS), required=True)
        sub.add_argument("--runtime-root", required=True)
        sub.add_argument("--request-id", required=True)
        if command == "bind":
            sub.add_argument("--effort", default="auto")
            sub.add_argument("--model")
            sub.add_argument("--supported-efforts", help="Comma-separated model/list reasoning efforts; frozen for this request")
        elif command != "status":
            sub.add_argument("--revision", type=int, required=True)
            if command != "complete":
                sub.add_argument("--decision-file", required=True)
    try:
        result = operate(parser.parse_args(argv))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
