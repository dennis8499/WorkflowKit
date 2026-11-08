"""Deterministic installed-only hooks; all replacement hashes start at upstream."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

NOTICE = '''
## WorkflowKit syntax context

For Ingest, Audit, Functional exploration and Archaeology, after the native
source inventory read `.agents/gitlab-workspace-kit/references/syntax-context.md`.
Use its pinned helper with the inventory SHA and snapshot identity to navigate
complete members. Preserve native file/entrypoint coverage and all unread work.
Normal Query remains Wiki-first. NotebookLM full-source DLP stays unchanged.
'''

BRIDGE = '''"""WorkflowKit installed-only syntax bridge; native evidence rules still apply."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

BUNDLE_SHA256 = __DIGEST__

def rewrite(tool, context, manifest, requests):
    root = Path(__file__).resolve().parents[3] / "gitlab-workspace-kit/scripts/syntax-context"
    for item in (root, *root.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Unsafe WorkflowKit syntax path")
    raw = (root / "bundle.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != BUNDLE_SHA256:
        raise ValueError("WorkflowKit syntax bundle changed; verify installation")
    bundle = json.loads(raw)
    expected_files = set(bundle["files"]) | {"bundle.json"}
    for candidate in root.rglob("*"):
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Unsafe syntax asset")
        if candidate.is_file() and candidate.relative_to(root).as_posix() not in expected_files:
            raise ValueError("Unexpected syntax asset; verify installation")
    for name, digest in bundle["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or "\\\\" in name or ":" in name:
            raise ValueError("Unsafe syntax asset")
        asset = root / relative
        for item in (asset, *asset.parents):
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Unsafe syntax asset")
        if hashlib.sha256(asset.read_bytes()).hexdigest() != digest:
            raise ValueError("WorkflowKit syntax asset changed; verify installation")
    selected = os.environ.get("WORKFLOW_KIT_SYNTAX_CONTEXT", json.loads((root / "acceptance.json").read_text(encoding="utf-8"))["default_mode"])
    if selected not in ("auto", "off"):
        raise ValueError("WORKFLOW_KIT_SYNTAX_CONTEXT must be auto or off")
    if selected == "off":
        return requests
    spec = importlib.util.spec_from_file_location("_workflow_kit_syntax_core", root / "engine.py")
    core = importlib.util.module_from_spec(spec)
    exec(compile((root / "engine.py").read_bytes(), str(root / "engine.py"), "exec"), core.__dict__)
    if not core.supported():
        sys.stderr.write("WorkflowKit syntax: unsupported runtime; retaining original reads.\\n")
        return requests
    if not any(row.get("op", row.get("action")) == "read" and "line_start" not in row
               and Path(row.get("path", "")).suffix.lower() in core.EXTENSIONS for row in requests):
        return requests
    repo_ids = {row["repo"] for row in requests if isinstance(row.get("repo"), str)}
    projected = {**manifest, "repositories": [row for row in manifest["repositories"] if row["id"] in repo_ids]}
    data = json.dumps({"context": str(context), "manifest": projected, "requests": requests}, ensure_ascii=False).encode("utf-8")
    if len(data) > core.MAX_PLAN_INPUT_BYTES:
        sys.stderr.write("WorkflowKit syntax: catalog budget; retaining original reads.\\n")
        return requests
    try:
        process = subprocess.run([sys.executable, "-I", "-B", str(root / "cli.py"), "plan",
                                  "--review-tool", tool, "--native-scripts", str(Path(__file__).parent),
                                  "--expected-engine-sha256", BUNDLE_SHA256],
                                 input=data, capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        sys.stderr.write("WorkflowKit syntax: planner deadline; retaining original reads.\\n")
        return requests
    if process.returncode == 2:
        raise ValueError(process.stderr.decode("utf-8", errors="replace"))
    if process.returncode != 0:
        sys.stderr.write("WorkflowKit syntax: planner unavailable; retaining original reads.\\n")
        return requests
    plan = json.loads(process.stdout)
    if plan.get("engine_sha256") != BUNDLE_SHA256 or plan.get("schema") != "SyntaxReadPlan/v1":
        raise ValueError("Invalid syntax read plan identity")
    states = {}
    for item in plan["files"]:
        states[item["status"]] = states.get(item["status"], 0) + 1
    sys.stderr.write("WorkflowKit syntax: " + json.dumps({"changed_reads": plan["changed_reads"], "states": states}) + "\\n")
    # Store only syntax metadata in the runner-owned sibling, never the source tree.
    runtime = os.environ.get("WORKFLOW_KIT_SYNTAX_RUNTIME")
    if runtime:
        directory = Path(os.path.abspath(runtime))
        if any((item / ".git").exists() for item in (directory, *directory.parents)):
            sys.stderr.write("WorkflowKit syntax: metadata cache disabled inside Git.\\n")
        else:
            try:
                for item in (directory, *directory.parents):
                    if not item.exists() and not item.is_symlink():
                        continue
                    info = item.lstat()
                    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                        raise ValueError("Unsafe syntax runtime")
                directory.mkdir(parents=True, exist_ok=True)
                target = directory / (hashlib.sha256(str(Path(context).resolve()).encode()).hexdigest() + ".json")
                if target.is_symlink():
                    raise ValueError("Unsafe syntax metadata file")
                if not target.exists():
                    with target.open("x", encoding="utf-8") as stream:
                        json.dump(plan, stream, ensure_ascii=False)
            except OSError:
                sys.stderr.write("WorkflowKit syntax: optional metadata cache unavailable.\\n")
    return plan["requests"]
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def modify(files, overlay, name, transform):
    key = "payload/" + name
    original = files[key]
    updated = transform(original.decode("utf-8")).encode("utf-8")
    if updated == original:
        raise ValueError(f"Syntax hook did not apply: {name}")
    files[key] = updated
    overlay["replaced"][name] = {"upstream_sha256": sha(original), "overlay_sha256": sha(updated)}


def once(text, before, after):
    if text.count(before) != 1:
        raise ValueError("Pinned native syntax hook changed")
    return text.replace(before, after)


def apply_reviewers(files, profile):
    root = profile / "common/scripts/syntax-context"
    # Load a verified local bundle and check every asset before packaging.
    import importlib.util
    spec = importlib.util.spec_from_file_location("kit_syntax_build_engine", root / "engine.py")
    module = importlib.util.module_from_spec(spec)
    exec(compile((root / "engine.py").read_bytes(), str(root / "engine.py"), "exec"), module.__dict__)
    bundle, digest = module.bundle()
    if module.supported():
        runtime = module.Engine(digest)
        for name in bundle["languages"]:
            runtime.language(name)
    overlay = {"added": {}, "replaced": {}}
    for tool in ("merge-reviewer", "release-reviewer"):
        name = f".agents/skills/{tool}/scripts/_workflow_kit_syntax.py"
        data = BRIDGE.replace("__DIGEST__", repr(digest)).encode()
        files["payload/" + name] = data
        overlay["added"][name] = sha(data)
    name = ".agents/skills/merge-reviewer/scripts/review_flow.py"
    modify(files, overlay, name, lambda text: once(text,
        "        initial_reads = initial_read_requests(manifest)",
        "        from _workflow_kit_syntax import rewrite as syntax_reads\n"
        "        initial_reads = syntax_reads('merge-reviewer', context, manifest, initial_read_requests(manifest))"))
    name = ".agents/skills/release-reviewer/scripts/review_worklist.py"
    modify(files, overlay, name, lambda text: once(text,
        "    worklist, draft = prepare(manifest)\n    for name, data in",
        "    worklist, draft = prepare(manifest)\n    from _workflow_kit_syntax import rewrite as syntax_reads\n"
        "    worklist['requests'] = syntax_reads('release-reviewer', context, manifest, worklist['requests'])\n    for name, data in"))
    return overlay


def wiki_repository(native):
    name = ".agents/skills/codebase-wiki/SKILL.md"
    original = native[name]
    native[name] = original + NOTICE.encode()
    return {"added": {}, "replaced": {name: {"upstream_sha256": sha(original), "overlay_sha256": sha(native[name])}}}


def wiki_group(files, overlay):
    name = ".agents/skills/codebase-wiki/SKILL.md"
    files["payload/" + name] += NOTICE.encode()
    overlay["replaced"][name]["overlay_sha256"] = sha(files["payload/" + name])
