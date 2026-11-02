#!/usr/bin/env python3
"""Prepare, validate, publish, and verify immutable Archify Wiki diagrams."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from typing import Any, Sequence

from bounded_process import ProcessLimitError, run_bounded
from wiki_transaction import WikiConflict, commit, snapshot


SCRIPT = Path(__file__).resolve()
SKILL_ROOT = SCRIPT.parent.parent
VENDOR_ROOT = SKILL_ROOT / "vendor" / "archify"
VENDOR_MANIFEST = SKILL_ROOT / "vendor" / "archify-manifest.json"
MANIFEST_SHA256 = "ce7ba82b274e1847693bbbc75d547c0001b11fd4d4bcccfdea5d9acd7d11a419"
ARCHIVE_SHA256 = "70e210265c59f24dcbdf2a502ff671104b5454e7ee7d3554aecd86bad32384f5"
ARCHIFY_COMMIT = "208acba8d412335185b2056fedf54b3405df43fb"
ARCHIFY_VERSION = "3.2.0"
ARCHIFY_TYPES = (
    "architecture", "workflow", "sequence", "dataflow", "lifecycle",
    "erd", "class", "tree", "timeline", "waterfall",
)
TYPE_ELEMENTS = {
    "architecture": ("components", "boundaries", "connections"),
    "workflow": ("lanes", "phases", "groups", "nodes", "edges"),
    "sequence": ("participants", "messages"),
    "dataflow": ("stages", "nodes", "flows"),
    "lifecycle": ("states", "transitions"),
    "erd": ("entities", "relationships"),
    "class": ("types", "relationships"),
    "tree": ("nodes",),
    "timeline": ("lanes", "events"),
    "waterfall": ("spans",),
}
SENSITIVE_PARTS = {
    ".git", ".venv", "venv", "node_modules", "dist", "build", "cache",
    "logs", ".aws", ".ssh", ".notebooklm", ".archify",
}
MANAGED_START = "<!-- codebase-wiki:visualization-managed:start -->"
MANAGED_END = "<!-- codebase-wiki:visualization-managed:end -->"
NOTES_START = "<!-- codebase-wiki:visualization-notes:start -->"
NOTES_END = "<!-- codebase-wiki:visualization-notes:end -->"


class VisualizeError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


class VisualizeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise VisualizeError(message, 1)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            return bool(os.stat(path, follow_symlinks=False).st_file_attributes & 0x400)
        except FileNotFoundError:
            return False
        except OSError:
            return True
    return False


def repo_root(value: Path) -> Path:
    root = value.absolute()
    if is_reparse(root) or root.resolve() != root:
        raise VisualizeError("repository root must not be a symlink or reparse point", 2)
    if not (root / "wiki").is_dir():
        raise VisualizeError("repository must contain a regular wiki/ directory", 2)
    return root


def safe_repo_file(root: Path, value: str, *, wiki_only: bool = False) -> tuple[str, Path]:
    raw = value.replace("\\", "/")
    pure = PurePosixPath(raw)
    if (not raw or raw != pure.as_posix() or pure.is_absolute() or
        any(part in {".", ".."} or ":" in part for part in pure.parts)):
        raise VisualizeError(f"invalid repository-relative evidence path: {value}")
    relative = pure.as_posix()
    if wiki_only and (not relative.startswith("wiki/") or pure.suffix.lower() != ".md"):
        raise VisualizeError(f"Wiki evidence must be a Markdown file under wiki/: {value}")
    if not wiki_only and relative.startswith("wiki/"):
        raise VisualizeError(f"raw source evidence must not be a Wiki path: {value}")
    if any(part.lower() in SENSITIVE_PARTS for part in pure.parts):
        raise VisualizeError(f"sensitive, generated, or dependency path cannot be evidence: {value}")
    path = root.joinpath(*pure.parts)
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        if is_reparse(cursor):
            raise VisualizeError(f"evidence path contains a link boundary: {value}")
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise VisualizeError(f"evidence path escapes the repository or is missing: {value}") from exc
    if not path.is_file():
        raise VisualizeError(f"evidence path is not a regular file: {value}")
    try:
        path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise VisualizeError(f"evidence must be readable UTF-8 text: {value}") from exc
    return relative, path


def validate_bundle() -> dict[str, Any]:
    try:
        raw = VENDOR_MANIFEST.read_bytes()
    except OSError as exc:
        raise VisualizeError(f"Archify bundle manifest is unavailable: {exc}", 2) from exc
    if sha256_bytes(raw) != MANIFEST_SHA256:
        raise VisualizeError("Archify bundle manifest SHA-256 mismatch", 2)
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VisualizeError("Archify bundle manifest is invalid JSON", 2) from exc
    expected = {
        "schema_version": 1, "tool": "archify", "version": ARCHIFY_VERSION,
        "commit": ARCHIFY_COMMIT, "archive_sha256": ARCHIVE_SHA256,
        "license": "MIT", "node_requirement": ">=18", "file_count": 200,
        "cli": ".agents/skills/codebase-wiki/vendor/archify/bin/archify.mjs",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise VisualizeError(f"Archify bundle manifest mismatch for {key}", 2)
    rows = manifest.get("files")
    if not isinstance(rows, dict) or len(rows) != manifest["file_count"]:
        raise VisualizeError("Archify bundle file inventory is incomplete", 2)
    expected_files: dict[str, str] = {}
    prefix = ".agents/skills/codebase-wiki/vendor/archify/"
    for relative, digest in rows.items():
        pure = PurePosixPath(relative) if isinstance(relative, str) else PurePosixPath(".")
        if (not isinstance(relative, str) or not relative.startswith(prefix) or pure.is_absolute() or
            any(part in {".", ".."} for part in pure.parts) or
            relative[len(prefix):] in expected_files or
            not re.fullmatch(r"[0-9a-f]{64}", str(digest))):
            raise VisualizeError("Archify bundle inventory contains an unsafe or duplicate path", 2)
        expected_files[relative[len(prefix):]] = digest
    actual: dict[str, str] = {}
    if not VENDOR_ROOT.is_dir() or is_reparse(VENDOR_ROOT):
        raise VisualizeError("vendored Archify directory is missing or unsafe", 2)
    for path in sorted(VENDOR_ROOT.rglob("*")):
        if is_reparse(path):
            raise VisualizeError(f"Archify bundle contains a link boundary: {path}", 2)
        if path.is_file():
            actual[path.relative_to(VENDOR_ROOT).as_posix()] = sha256_file(path)
    if set(actual) != set(expected_files):
        raise VisualizeError("Archify bundle file set differs from its pinned manifest", 2)
    for relative, expected_hash in expected_files.items():
        if actual[relative] != expected_hash:
            raise VisualizeError(f"Archify bundle file hash mismatch: {relative}", 2)
    return manifest


def wiki_snapshot(root: Path) -> dict[str, str]:
    try:
        return snapshot(root)
    except (OSError, ValueError) as exc:
        raise VisualizeError(f"unable to snapshot Wiki: {exc}", 2) from exc


def aggregate_snapshot(value: dict[str, str]) -> str:
    return "sha256:" + sha256_bytes(json_bytes(value))


def skeleton(diagram_type: str, title: str, output: str) -> dict[str, Any]:
    schema_path = VENDOR_ROOT / "schemas" / f"{diagram_type}.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VisualizeError(f"missing Archify schema for {diagram_type}: {exc}", 2) from exc
    result: dict[str, Any] = {
        "schema_version": 1,
        "diagram_type": diagram_type,
        "meta": {
            "title": title,
            "locale": "zh-TW",
            "quality_profile": "showcase",
            "animation": "none",
            "output": output,
        },
    }
    meta_required = schema.get("properties", {}).get("meta", {}).get("required", [])
    if "evidence" in meta_required:
        result["meta"]["evidence"] = "observed" if diagram_type == "timeline" else "measured"
    for name in schema.get("required", []):
        if name in result:
            continue
        definition = schema.get("properties", {}).get(name, {})
        if definition.get("type") == "array":
            result[name] = []
        elif definition.get("type") == "object":
            result[name] = {}
    return result


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    root = repo_root(args.root)
    bundle = validate_bundle()
    if args.type not in ARCHIFY_TYPES:
        raise VisualizeError(f"unsupported diagram type: {args.type}")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.slug):
        raise VisualizeError("slug must be lowercase kebab-case")
    if not args.title.strip():
        raise VisualizeError("title must not be empty")
    if args.illustrative and args.type not in {"timeline", "waterfall"}:
        raise VisualizeError("--illustrative is only valid for Timeline or Waterfall")
    if len(args.source) > 5:
        raise VisualizeError("at most five raw source paths may be included in companion frontmatter")
    raw_sources: dict[str, Path] = {}
    wiki_pages: dict[str, Path] = {}
    for value in args.source:
        relative, path = safe_repo_file(root, value)
        if relative in raw_sources:
            raise VisualizeError(f"duplicate source evidence path: {relative}")
        raw_sources[relative] = path
    for value in args.wiki_page:
        relative, path = safe_repo_file(root, value, wiki_only=True)
        if relative in wiki_pages:
            raise VisualizeError(f"duplicate Wiki evidence path: {relative}")
        wiki_pages[relative] = path
    if not raw_sources and not args.wiki_page:
        raise VisualizeError("provide at least one --wiki-page or --source evidence path")

    before = wiki_snapshot(root)
    evidence: list[dict[str, str]] = []
    for path, file_path in sorted((*raw_sources.items(), *wiki_pages.items())):
        evidence.append({
            "path": path,
            "kind": "wiki" if path.startswith("wiki/") else "source",
            "sha256": sha256_file(file_path),
        })
    run_id = str(uuid.uuid4())
    workdir = Path(tempfile.mkdtemp(prefix="codebase-wiki-visualize-")).resolve()
    output_path = workdir / "diagram.html"
    candidate_path = workdir / "candidate.json"
    candidate = skeleton(args.type, args.title.strip(), output_path.name)
    if args.illustrative:
        candidate["meta"]["evidence"] = "illustrative"
    candidate_path.write_bytes(json_bytes(candidate))
    evidence_map_path = workdir / "evidence-map.json"
    evidence_map_path.write_bytes(json_bytes({
        "schema": "codebase-wiki-visualization-evidence/v1",
        "claims": [],
        "gaps": [],
        "instruction": "For each item in the selected type's semantic arrays, cite its element_id as <array>:<id> or <array>[index], with selected evidence path+sha256; otherwise record an element_id gap. Do not invent facts.",
    }))
    plan = {
        "schema": "codebase-wiki-visualization-plan/v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "root": str(root),
        "type": args.type,
        "slug": args.slug,
        "title": args.title.strip(),
        "run_id": run_id,
        "workdir": str(workdir),
        "candidate": str(candidate_path),
        "evidence_map": str(evidence_map_path),
        "output": str(output_path),
        "illustrative": bool(args.illustrative),
        "raw_sources": sorted(raw_sources),
        "wiki_pages": sorted(wiki_pages),
        "evidence": evidence,
        "wiki_snapshot": before,
        "wiki_snapshot_sha256": aggregate_snapshot(before),
        "bundle": {"version": bundle["version"], "manifest_sha256": MANIFEST_SHA256},
    }
    plan_path = workdir / "plan.json"
    plan_path.write_bytes(json_bytes(plan))
    return {
        "ok": True,
        "operation": "prepare",
        "run_id": run_id,
        "plan": str(plan_path),
        "candidate": str(candidate_path),
        "evidence_map": str(evidence_map_path),
        "output": str(output_path),
        "wiki_snapshot_sha256": plan["wiki_snapshot_sha256"],
        "evidence": evidence,
    }


def private_plan(path: Path) -> dict[str, Any]:
    try:
        resolved = path.resolve(strict=True)
        temp = Path(tempfile.gettempdir()).resolve(strict=True)
        workdir = resolved.parent
        workdir.relative_to(temp)
        if not workdir.name.startswith("codebase-wiki-visualize-") or is_reparse(workdir):
            raise ValueError("plan is outside a private visualization work directory")
        if resolved.name != "plan.json" or not resolved.is_file() or is_reparse(resolved):
            raise ValueError("plan path must name the private plan.json file")
        plan = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise VisualizeError(f"cannot read a valid private visualization plan: {exc}", 2) from exc
    if not isinstance(plan, dict) or plan.get("schema") != "codebase-wiki-visualization-plan/v1":
        raise VisualizeError("unsupported visualization plan")
    if Path(plan.get("workdir", "")).resolve() != workdir:
        raise VisualizeError("plan working directory identity mismatch", 2)
    for field in ("candidate", "evidence_map", "output"):
        item = Path(plan.get(field, "")).resolve()
        try:
            item.relative_to(workdir)
        except ValueError as exc:
            raise VisualizeError(f"plan {field} escapes its private work directory", 2) from exc
        if is_reparse(item):
            raise VisualizeError(f"plan {field} is a link boundary", 2)
        plan[field] = str(item)
    if plan.get("type") not in ARCHIFY_TYPES:
        raise VisualizeError("plan contains an unsupported diagram type")
    if not isinstance(plan.get("slug"), str) or not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*", plan["slug"]
    ):
        raise VisualizeError("plan contains an invalid diagram slug")
    try:
        parsed_uuid = uuid.UUID(str(plan.get("run_id", "")))
    except (ValueError, AttributeError) as exc:
        raise VisualizeError("plan contains an invalid run UUID") from exc
    if str(parsed_uuid) != plan["run_id"]:
        raise VisualizeError("plan contains a non-canonical run UUID")
    if not isinstance(plan.get("evidence"), list) or not isinstance(plan.get("wiki_snapshot"), dict):
        raise VisualizeError("plan evidence or Wiki snapshot is invalid")
    plan["_plan_path"] = str(resolved)
    return plan


def verify_plan_fresh(root: Path, plan: dict[str, Any], *, whole_wiki: bool = True) -> None:
    if whole_wiki and wiki_snapshot(root) != plan.get("wiki_snapshot"):
        raise VisualizeError("Wiki snapshot changed after prepare; prepare again to preserve concurrent edits", 2)
    for item in plan.get("evidence", []):
        relative, path = safe_repo_file(root, item["path"], wiki_only=item["kind"] == "wiki")
        actual = sha256_file(path)
        if actual != item["sha256"]:
            raise VisualizeError(f"evidence changed after prepare: {relative}", 2)


def _semantic_ids(candidate: dict[str, Any], diagram_type: str) -> set[str]:
    ids: set[str] = set()
    for key in TYPE_ELEMENTS[diagram_type]:
        value = candidate.get(key, [])
        if not isinstance(value, list):
            raise VisualizeError(f"candidate {key} must be an array")
        for index, row in enumerate(value):
            if not isinstance(row, dict):
                raise VisualizeError(f"every {key} element must be an object for evidence mapping")
            identifier = row.get("id")
            locator = f"{key}:{identifier}" if isinstance(identifier, str) and identifier.strip() else f"{key}[{index}]"
            if locator in ids:
                raise VisualizeError(f"candidate contains a duplicate semantic locator: {locator}")
            ids.add(locator)
    return ids


def validate_evidence_map(candidate: dict[str, Any], mapping: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    if not isinstance(mapping, dict):
        raise VisualizeError("evidence-map.json must contain a JSON object")
    if mapping.get("schema") != "codebase-wiki-visualization-evidence/v1":
        raise VisualizeError("evidence-map.json has an unsupported schema")
    claims = mapping.get("claims")
    gaps = mapping.get("gaps")
    if not isinstance(claims, list) or not isinstance(gaps, list):
        raise VisualizeError("evidence map requires claims and gaps arrays")
    selected = {item["path"]: item["sha256"] for item in plan["evidence"]}
    covered: set[str] = set()
    for claim in claims:
        if (not isinstance(claim, dict) or not isinstance(claim.get("element_id"), str) or
            not claim["element_id"].strip() or not isinstance(claim.get("evidence"), list) or
            not claim["evidence"]):
            raise VisualizeError("each evidence claim requires an element_id and at least one evidence reference")
        element = claim["element_id"]
        if element in covered:
            raise VisualizeError(f"evidence map repeats element_id: {element}")
        covered.add(element)
        for ref in claim["evidence"]:
            if not isinstance(ref, dict) or ref.get("path") not in selected or ref.get("sha256") != selected.get(ref.get("path")):
                raise VisualizeError(f"evidence reference is not bound to selected snapshot: {element}")
    for gap in gaps:
        if not isinstance(gap, dict) or not isinstance(gap.get("description"), str) or not gap["description"].strip():
            raise VisualizeError("each gap requires a non-empty description")
        element = gap.get("element_id")
        if element is not None:
            if not isinstance(element, str) or not element.strip() or element in covered:
                raise VisualizeError("gap element_id must be unique and non-empty")
            covered.add(element)
    ids = _semantic_ids(candidate, plan["type"])
    missing = ids - covered
    unknown = covered - ids
    if missing:
        raise VisualizeError("evidence map must cite every semantic element or record a Gap: " + ", ".join(sorted(missing)))
    if unknown:
        raise VisualizeError("evidence map references ids absent from candidate: " + ", ".join(sorted(unknown)))
    return sorted(missing)


def _path_digest(root: Path, sources: list[str]) -> str:
    records = [(value, sha256_file(root / Path(*PurePosixPath(value).parts))) for value in sorted(sources)]
    digest = hashlib.sha256()
    for path, file_hash in records:
        digest.update(path.encode("utf-8")); digest.update(b"\0")
        digest.update(file_hash.encode("ascii")); digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def _yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _frontmatter(plan: dict[str, Any], root: Path) -> str:
    sources = plan["raw_sources"]
    wiki_pages = sorted(plan["wiki_pages"])
    title = plan["title"]
    lines = [
        "---", f"title: {_yaml_quote(title)}", "type: synthesis",
        f"summary: {_yaml_quote('Evidence-linked Archify visualization: ' + title)}",
        "notebooklm_group: visualizations", "notebooklm_role: exclude", "sources:",
    ]
    if sources:
        lines.extend(f"  - {_yaml_quote(value)}" for value in sources)
    else:
        lines[-1] = "sources: []"
    lines.extend([
        f"source_digest: {_path_digest(root, sources)}" if sources else "source_digest: null",
        "derived_from: " + json.dumps([f"[[{Path(value).stem}]]" for value in wiki_pages], ensure_ascii=False),
        f"last_updated: {dt.date.today().isoformat()}",
        "tags: [visualization, diagram]", "status: active", "---", "",
    ])
    # Empty raw source lists have no content digest by contract.
    if not sources:
        lines = [line for line in lines if line != "source_digest: null"]
    return "\n".join(lines)


def _preserved_notes(existing: str) -> str:
    if NOTES_START in existing and NOTES_END in existing:
        before = existing.split(NOTES_START, 1)[1]
        return NOTES_START + before.split(NOTES_END, 1)[0] + NOTES_END
    return NOTES_START + "\n\n<!-- Add or edit human notes in this block; future runs preserve it. -->\n\n" + NOTES_END


def _managed_history(existing: str) -> list[str]:
    if MANAGED_START not in existing or MANAGED_END not in existing:
        return []
    region = existing.split(MANAGED_START, 1)[1].split(MANAGED_END, 1)[0]
    return re.findall(r"- \[([^\]]+)\]\((\.\./visualizations/[^)]+/diagram\.html)\)", region)


def render_companion(root: Path, plan: dict[str, Any], run_relative: str,
                     manifest: dict[str, Any], evidence_map: dict[str, Any]) -> str:
    page = root / "wiki/synthesis" / f"diagram-{plan['slug']}.md"
    existing = page.read_text(encoding="utf-8") if page.exists() else ""
    if existing and (MANAGED_START not in existing or MANAGED_END not in existing):
        raise VisualizeError(f"existing companion page is not framework-managed; refusing to replace: {page}", 2)
    history = _managed_history(existing)
    history = [(name, location) for name, location in history if run_relative not in location]
    title = plan["title"]
    gates = manifest["validation"]["gates"]
    lines = [MANAGED_START, "", f"# {title}", "",
             f"Latest run: `{plan['run_id']}` · type `{plan['type']}` · quality `showcase`.", "",
             f"- [互動圖表]({run_relative}/diagram.html)",
             f"- [可編輯 JSON]({run_relative}/candidate.json)",
             f"- [證據對照]({run_relative}/evidence-map.json)",
             f"- [Manifest]({run_relative}/manifest.json)", "",
             "## Evidence", ""]
    if manifest["evidence"]:
        for item in manifest["evidence"]:
            lines.append(f"- `{item['path']}` — `{item['sha256']}` ({item['kind']})")
    else:
        lines.append("- No raw source files; evidence is Wiki-only.")
    gaps = evidence_map.get("gaps", [])
    lines.extend(["", "## Gaps", ""])
    if gaps:
        for gap in gaps:
            subject = f"`{gap['element_id']}`: " if gap.get("element_id") else ""
            lines.append(f"- {subject}{gap['description']}")
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Automated validation", ""])
    for gate, result in gates.items():
        lines.append(f"- `{gate}`: {result['status']}")
    lines.extend(["", "## Previous runs", ""])
    if history:
        for old_id, location in history:
            lines.append(f"- [{old_id}]({location})")
    else:
        lines.append("- None.")
    lines.extend(["", MANAGED_END, ""])
    notes = _preserved_notes(existing)
    if existing:
        # The companion page is framework-managed; refresh traceability
        # frontmatter on every run while preserving its explicit notes block.
        return _frontmatter(plan, root) + "\n".join(lines) + "\n" + notes + "\n"
    return _frontmatter(plan, root) + "\n".join(lines) + "\n" + notes + "\n"


def _validate_receipt(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not receipt.get("ok") or receipt.get("status") != "pass":
        raise VisualizeError("Archify finalize did not pass", 1)
    stages = receipt.get("stages", {})
    required = {"validate", "deliver", "check", "browser-check"}
    if not required <= set(stages):
        raise VisualizeError("Archify finalize receipt omitted one or more required gates", 1)
    gates: dict[str, dict[str, Any]] = {}
    validation = stages.get("validate", {})
    delivery = stages.get("deliver", {})
    embedded_validation = (
        isinstance(validation, dict)
        and validation.get("status") == "not-run"
        and validation.get("execution") == "embedded-in-deliver"
        and isinstance(delivery, dict)
        and delivery.get("status") == "pass"
    )
    for name in sorted(required):
        row = stages.get(name)
        passed = isinstance(row, dict) and row.get("status") == "pass"
        if name == "validate" and embedded_validation:
            passed = True
        if not passed:
            raise VisualizeError(f"Archify gate failed: {name}", 1)
        gates[name] = {
            "status": "pass",
            "duration_ms": row.get("durationMs") if isinstance(row, dict) else None,
            **({"execution": "embedded-in-deliver"} if name == "validate" and embedded_validation else {}),
        }
    return gates


def publish(args: argparse.Namespace) -> dict[str, Any]:
    root = repo_root(args.root)
    bundle = validate_bundle()
    plan = private_plan(args.plan)
    if Path(plan["root"]).resolve() != root.resolve():
        raise VisualizeError("plan belongs to a different repository root", 2)
    if plan.get("bundle", {}).get("manifest_sha256") != MANIFEST_SHA256:
        raise VisualizeError("plan was prepared with a different Archify bundle", 2)
    verify_plan_fresh(root, plan)

    candidate_path = Path(plan["candidate"])
    evidence_map_path = Path(plan["evidence_map"])
    output_path = Path(plan["output"])
    if not candidate_path.is_file() or not evidence_map_path.is_file():
        raise VisualizeError("candidate.json or evidence-map.json is missing", 2)
    try:
        candidate_bytes = candidate_path.read_bytes()
        candidate = json.loads(candidate_bytes.decode("utf-8"))
        evidence_map = json.loads(evidence_map_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VisualizeError(f"candidate or evidence map is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(candidate, dict) or candidate.get("schema_version") != 1 or candidate.get("diagram_type") != plan["type"]:
        raise VisualizeError("candidate schema_version or diagram_type does not match the prepared type")
    meta = candidate.get("meta")
    if not isinstance(meta, dict) or meta.get("output") != output_path.name:
        raise VisualizeError("candidate meta.output must remain the prepared diagram.html path")
    if meta.get("locale") != "zh-TW" or meta.get("quality_profile") != "showcase" or meta.get("animation") != "none":
        raise VisualizeError("candidate must retain zh-TW, showcase, and static animation defaults")
    if meta.get("title") != plan["title"]:
        raise VisualizeError("candidate meta.title must match the prepared companion page title")
    if plan["type"] in {"timeline", "waterfall"}:
        expected_evidence = "illustrative" if plan.get("illustrative") else ("observed" if plan["type"] == "timeline" else "measured")
        if meta.get("evidence") != expected_evidence:
            raise VisualizeError(f"candidate meta.evidence must be {expected_evidence!r}")
        if expected_evidence == "illustrative" and not re.search(
            r"(?i)(illustrative|示意|示例)", str(meta.get("subtitle", ""))
        ):
            raise VisualizeError("illustrative Timeline/Waterfall must clearly label its subtitle as illustrative")
    validate_evidence_map(candidate, evidence_map, plan)

    node = shutil.which("node")
    if not node:
        raise VisualizeError("Node.js is unavailable; no Wiki changes were made", 2)
    try:
        node_version = run_bounded([node, "--version"], timeout=10, max_output_bytes=1024, text=True)
    except (OSError, ProcessLimitError) as exc:
        raise VisualizeError(f"Node.js version check failed: {exc}", 2) from exc
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)\s*", node_version.stdout)
    if node_version.returncode or not match or int(match.group(1)) < 18:
        raise VisualizeError("Archify requires Node.js 18 or newer", 2)
    output_path.unlink(missing_ok=True)
    env = os.environ.copy()
    env["ARCHIFY_UPDATE_CHECK_DISABLED"] = "1"
    try:
        result = run_bounded(
            [node, str(VENDOR_ROOT / "bin/archify.mjs"), "finalize", plan["type"],
             str(candidate_path), str(output_path), "--quality", "showcase", "--json"],
            cwd=Path(plan["workdir"]), env=env, timeout=180,
            max_output_bytes=8 * 1024 * 1024, text=False,
        )
    except ProcessLimitError as exc:
        raise VisualizeError(f"Archify finalize stopped at its process limit: {exc}", 2) from exc
    except OSError as exc:
        raise VisualizeError(f"unable to run Archify finalize: {exc}", 2) from exc
    try:
        receipt = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VisualizeError("Archify finalize did not return a JSON receipt", 1) from exc
    if result.returncode != 0:
        failed = receipt.get("failedStage", "unknown") if isinstance(receipt, dict) else "unknown"
        diagnostics = receipt.get("diagnostics", []) if isinstance(receipt, dict) else []
        browser_unavailable = failed == "browser-check" and any(
            isinstance(item, dict) and item.get("code") == "viewer/browser-check-runtime"
            for item in diagnostics
        )
        raise VisualizeError(
            f"Archify finalize failed at {failed}; no Wiki changes were made",
            2 if browser_unavailable else 1,
        )
    # Archify stdout is the compact summary; its original sidecar carries the
    # complete stage receipts that this contract must inspect and preserve.
    full_receipt_path = Path(plan["workdir"]) / f"{Path(plan['output']).stem}.finalize.json"
    if full_receipt_path.is_file():
        try:
            full_receipt = json.loads(full_receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise VisualizeError(f"Archify full finalize receipt is invalid: {exc}", 1) from exc
        if full_receipt.get("ok") is not True or full_receipt.get("status") != "pass":
            raise VisualizeError("Archify full finalize receipt does not record success", 1)
        if full_receipt.get("specification", {}).get("sha256") != sha256_bytes(candidate_bytes):
            raise VisualizeError("Archify finalize receipt is bound to different candidate bytes", 1)
        receipt = full_receipt
    gates = _validate_receipt(receipt)
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise VisualizeError("Archify finalize reported success but did not create diagram.html", 1)

    output_bytes = output_path.read_bytes()
    if receipt.get("artifact", {}).get("sha256") != sha256_bytes(output_bytes):
        raise VisualizeError("Archify finalize receipt is bound to different HTML bytes", 1)
    run_relative = f"wiki/visualizations/{plan['slug']}/{plan['run_id']}"
    receipt_files = {"archify-finalize-stdout.json": result.stdout}
    stem = output_path.stem
    for path in sorted(Path(plan["workdir"]).glob(stem + ".*.json")):
        if path.name in {"candidate.json", "evidence-map.json", "plan.json"}:
            continue
        if path.resolve() == output_path.resolve():
            continue
        receipt_files[path.name] = path.read_bytes()
    receipts = []
    for name, data in sorted(receipt_files.items()):
        receipts.append({"path": f"receipts/{name}", "sha256": sha256_bytes(data), "size": len(data)})
    evidence_items = list(plan["evidence"])
    manifest = {
        "schema": "codebase-wiki-visualization/v1",
        "run_id": plan["run_id"], "slug": plan["slug"], "type": plan["type"],
        "title": plan["title"], "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "runtime": {"tool": "archify", "version": ARCHIFY_VERSION,
                    "commit": ARCHIFY_COMMIT, "archive_sha256": ARCHIVE_SHA256,
                    "bundle_manifest_sha256": MANIFEST_SHA256, "license": "MIT",
                    "node_version": node_version.stdout.strip()},
        "inputs": {
            "candidate": {"sha256": sha256_bytes(candidate_bytes), "size": len(candidate_bytes)},
            "evidence_map": {"sha256": sha256_file(evidence_map_path), "size": evidence_map_path.stat().st_size},
        },
        "evidence": evidence_items,
        "wiki_snapshot": {"sha256": plan["wiki_snapshot_sha256"], "file_count": len(plan["wiki_snapshot"])},
        "artifact": {"path": "diagram.html", "sha256": sha256_bytes(output_bytes), "size": len(output_bytes)},
        "receipts": receipts,
        "validation": {"gates": gates, "update_check": "disabled", "network": "disabled"},
        "provenance_note": "Native Archify receipts retain their original temporary absolute paths. This manifest binds copied bytes into the immutable Wiki run.",
    }
    manifest_bytes = json_bytes(manifest)
    companion_path = f"wiki/synthesis/diagram-{plan['slug']}.md"
    companion = render_companion(root, plan, f"../visualizations/{plan['slug']}/{plan['run_id']}", manifest, evidence_map)
    # Render index against an isolated copy of Wiki plus the pending companion page.
    index_root = Path(plan["workdir"]) / "index-preview"
    index_wiki = index_root / "wiki"
    shutil.copytree(root / "wiki", index_wiki)
    (index_wiki / "synthesis").mkdir(parents=True, exist_ok=True)
    (index_wiki / "synthesis" / f"diagram-{plan['slug']}.md").write_text(companion, encoding="utf-8")
    index_result = run_bounded(
        [sys.executable, "-X", "utf8", str(SKILL_ROOT / "scripts" / "rebuild-index.py"),
         str(index_wiki), "--stdout"], cwd=root, timeout=30,
        max_output_bytes=8 * 1024 * 1024, text=False,
    )
    if index_result.returncode != 0:
        raise VisualizeError("unable to render Wiki index; no Wiki changes were made", 2)
    index_bytes = index_result.stdout
    try:
        index_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise VisualizeError("rebuilt Wiki index is not UTF-8", 2) from exc

    # Recheck everything immediately before the single CAS transaction.
    verify_bundle()
    verify_plan_fresh(root, plan)
    artifact_root = f"wiki/visualizations/{plan['slug']}/{plan['run_id']}"
    artifact_directory = root.joinpath(*PurePosixPath(artifact_root).parts)
    if artifact_directory.exists():
        raise VisualizeError("immutable visualization run already exists; refusing to overwrite it", 2)
    writes: dict[str, bytes] = {
        f"{artifact_root}/candidate.json": candidate_bytes,
        f"{artifact_root}/evidence-map.json": evidence_map_path.read_bytes(),
        f"{artifact_root}/diagram.html": output_bytes,
        f"{artifact_root}/manifest.json": manifest_bytes,
        companion_path: companion.encode("utf-8"),
        "wiki/index.md": index_bytes,
    }
    for name, data in receipt_files.items():
        writes[f"{artifact_root}/receipts/{name}"] = data
    date = dt.date.today().isoformat()
    log_append = (
        f"## [{date}] synthesis | Archify visualization: {plan['title']}\n\n"
        f"- Published immutable run `{plan['run_id']}` under `{artifact_root}/`.\n"
        f"- Affected pages: [[diagram-{plan['slug']}]]."
    ).encode("utf-8")
    try:
        committed = commit(root, writes, plan["wiki_snapshot"], log_append=log_append)
    except (WikiConflict, OSError, ValueError) as exc:
        raise VisualizeError(f"Wiki transaction refused publication: {exc}", 2) from exc
    return {
        "ok": True, "operation": "publish", "run_id": plan["run_id"],
        "companion": companion_path, "artifact": f"{artifact_root}/diagram.html",
        "manifest": f"{artifact_root}/manifest.json", "receipts": receipts,
        "gates": gates, "wiki_files": committed["files"], "snapshot": committed["snapshot"],
    }


def verify_bundle() -> dict[str, Any]:
    manifest = validate_bundle()
    return {"tool": "archify", "version": manifest["version"],
            "files": manifest["file_count"], "manifest_sha256": MANIFEST_SHA256}


def verify_run(args: argparse.Namespace) -> dict[str, Any]:
    root = repo_root(args.root)
    if args.bundle:
        bundle = verify_bundle()
    else:
        bundle = None
    raw = args.run.replace("\\", "/")
    pure = PurePosixPath(raw)
    if pure.is_absolute() or ".." in pure.parts:
        raise VisualizeError("run path must stay under wiki/visualizations")
    relative = pure.as_posix()
    if relative.startswith("wiki/"):
        base = root.joinpath(*pure.parts)
        relative_base = relative
    else:
        base = root / "wiki" / "visualizations" / relative
        relative_base = "wiki/visualizations/" + relative
    try:
        base.resolve(strict=True).relative_to((root / "wiki" / "visualizations").resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise VisualizeError("run directory is missing or outside wiki/visualizations", 2) from exc
    if is_reparse(base) or not base.is_dir():
        raise VisualizeError("run directory must be a regular directory", 2)
    manifest_path = base / "manifest.json"
    if is_reparse(manifest_path) or not manifest_path.is_file():
        raise VisualizeError("run manifest is missing or unsafe", 2)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VisualizeError(f"invalid run manifest: {exc}") from exc
    if manifest.get("schema") != "codebase-wiki-visualization/v1":
        raise VisualizeError("unsupported visualization manifest schema")
    if manifest.get("run_id") != base.name or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        str(manifest.get("run_id", "")), re.IGNORECASE,
    ):
        raise VisualizeError("run UUID does not match its immutable directory")
    if manifest.get("runtime", {}).get("version") != ARCHIFY_VERSION or manifest.get("runtime", {}).get("commit") != ARCHIFY_COMMIT:
        raise VisualizeError("run manifest refers to a different Archify release")
    gates = manifest.get("validation", {}).get("gates", {})
    if set(gates) != {"validate", "deliver", "check", "browser-check"} or any(
        not isinstance(value, dict) or value.get("status") != "pass" for value in gates.values()
    ):
        raise VisualizeError("run manifest does not record four passing Archify gates")
    wiki_snapshot(root)
    checked = []
    entries = [("artifact", manifest.get("artifact", {}))]
    entries.extend((key, item) for key, item in manifest.get("inputs", {}).items())
    entries.extend((None, item) for item in manifest.get("receipts", []))
    for key, item in entries:
        relative_path = item.get("path")
        if relative_path is None and key == "candidate":
            relative_path = "candidate.json"
        elif relative_path is None and key == "evidence_map":
            relative_path = "evidence-map.json"
        if (not isinstance(relative_path, str) or PurePosixPath(relative_path).is_absolute() or
            ".." in PurePosixPath(relative_path).parts or ":" in relative_path or "\\" in relative_path):
            raise VisualizeError("manifest contains an unsafe file path")
        target = base.joinpath(*PurePosixPath(relative_path).parts)
        if is_reparse(target) or not target.is_file():
            raise VisualizeError(f"manifest file is missing or unsafe: {relative_path}")
        actual = sha256_file(target)
        if actual != item.get("sha256") or target.stat().st_size != item.get("size"):
            raise VisualizeError(f"published file hash or size mismatch: {relative_path}")
        checked.append(relative_path)
    stale: list[str] = []
    for item in manifest.get("evidence", []):
        try:
            _, path = safe_repo_file(root, item["path"], wiki_only=item["kind"] == "wiki")
            if sha256_file(path) != item["sha256"]:
                stale.append(item["path"])
        except VisualizeError:
            stale.append(item.get("path", "<invalid>"))
    if stale:
        raise VisualizeError("evidence is stale or unavailable: " + ", ".join(stale), 1)
    return {"ok": True, "operation": "verify", "run": relative_base,
            "run_id": manifest.get("run_id"), "files_checked": sorted(checked),
            "evidence_fresh": True, "bundle": bundle}


def build_parser() -> argparse.ArgumentParser:
    parser = VisualizeArgumentParser(prog="wiki-visualize.py")
    sub = parser.add_subparsers(dest="operation", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--root", type=Path, default=Path("."))
    prep.add_argument("--type", choices=ARCHIFY_TYPES, required=True)
    prep.add_argument("--slug", required=True)
    prep.add_argument("--title", required=True)
    prep.add_argument("--wiki-page", action="append", default=[])
    prep.add_argument("--source", action="append", default=[])
    prep.add_argument("--illustrative", action="store_true", help="allow clearly labeled illustrative Timeline/Waterfall values")
    prep.add_argument("--format", choices=("json",), default="json")
    pub = sub.add_parser("publish")
    pub.add_argument("--root", type=Path, default=Path("."))
    pub.add_argument("--plan", type=Path, required=True)
    pub.add_argument("--format", choices=("json",), default="json")
    ver = sub.add_parser("verify")
    ver.add_argument("--root", type=Path, default=Path("."))
    ver.add_argument("--run")
    ver.add_argument("--bundle", action="store_true")
    ver.add_argument("--format", choices=("json",), default="json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = None
    try:
        args = build_parser().parse_args(argv)
        if args.operation == "prepare":
            payload = prepare(args)
        elif args.operation == "publish":
            payload = publish(args)
        else:
            if not args.bundle and not args.run:
                raise VisualizeError("verify requires --bundle or --run")
            if args.run:
                payload = verify_run(args)
            else:
                payload = {"ok": True, "operation": "verify", "bundle": verify_bundle()}
        emit(payload)
        return 0
    except VisualizeError as exc:
        operation = getattr(args, "operation", argv[0] if argv else "unknown")
        emit({"ok": False, "operation": operation, "error": str(exc), "exit_code": exc.code})
        return exc.code
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, KeyError, ProcessLimitError) as exc:
        operation = getattr(args, "operation", argv[0] if argv else "unknown")
        emit({"ok": False, "operation": operation, "error": str(exc), "exit_code": 2})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
