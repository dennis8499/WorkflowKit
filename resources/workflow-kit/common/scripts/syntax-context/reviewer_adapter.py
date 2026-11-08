"""Adapt only immutable native bytes into ordinary native ranged read requests."""
from __future__ import annotations

from pathlib import Path
import re
import sys

from engine import Engine, EXTENSIONS, MAX_BYTES, decode, merge_ranges

HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


def hunk_ranges(patch, before_total, after_total):
    before, after = [], []
    for match in HUNK.finditer(patch):
        for output, start, count, total in ((before, match[1], match[2], before_total),
                                            (after, match[3], match[4], after_total)):
            if total:
                first, length = int(start), int(count) if count is not None else 1
                if length == 0:
                    first = max(1, min(first + 1, total))
                    output.append([first, first])
                else:
                    output.append([first, first + length - 1])
    return before, after


def rewrite(tool, context, manifest, requests, scripts, expected):
    scripts, context = Path(scripts), Path(context)
    if scripts.name != "scripts" or scripts.parent.name != tool:
        raise ValueError("Invalid native syntax adapter binding")
    sys.path.insert(0, str(scripts))
    engine = Engine(expected)
    groups, records, rewritten = {}, [], []
    for index, request in enumerate(requests):
        if (request.get("op", request.get("action")) != "read" or "line_start" in request
                or Path(request["path"]).suffix.lower() not in EXTENSIONS):
            continue
        groups.setdefault((request.get("repo"), request["path"]), []).append((index, request))
    selected_groups = list(groups.values())[:64]

    if tool == "merge-reviewer":
        import review_workspace as native
        import git_review_context as api
        repositories = {repo["id"]: repo for repo in manifest["repositories"]}
        cache = None

        def metadata(request):
            repo = repositories[request["repo"]]
            source = repo["sources"][request["source"]]
            native.safe_path(context, request["path"])
            env = native.source_environment(context, repo, source, api)
            size = int(api.run_git(native.evidence_repository(context, repo),
                                  ["cat-file", "-s", source["ref"] + ":" + request["path"]], env=env))
            return source["ref"], size

        def read(request):
            return cache.read(repositories[request["repo"]], request["source"], request["path"])

        def diff(first, last, before_ref):
            return cache.changed_patch(repositories[last["repo"]], last["source"], before_ref, last["path"]).encode("utf-8")
    elif tool == "release-reviewer":
        import evidence as native

        def metadata(request):
            native.require(native.safe_path(request["path"]), "Unsafe syntax source path")
            ref, env = native.source_version(manifest, context, request["source"], request.get("ref"), request.get("repo"))
            selected = native.repository(manifest, request.get("repo"))
            size = int(native.command({**manifest, "repo": selected["path"]}, ["cat-file", "-s", ref + ":" + request["path"]], env=env))
            return ref, size

        def read(request):
            return native.read_blob(manifest, context, request["source"], request["path"], request.get("ref"), request.get("repo"))

        def diff(first, last, before_ref):
            ref, env = native.source_version(manifest, context, last["source"], last.get("ref"), last.get("repo"))
            selected = native.repository(manifest, last.get("repo"))
            return native.command({**manifest, "repo": selected["path"]},
                                  ["diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--unified=0",
                                   before_ref, ref, "--", last["path"]], env=env)
    else:
        raise ValueError("Unknown reviewer adapter")

    replacements = {}
    for entries in selected_groups:
        metadata_rows = [(index, request, *metadata(request)) for index, request in entries]
        if tool == "merge-reviewer":
            cache = native.FixedSourceCache(context, api)
            cache.prefetch(manifest, [request for _, request, _, size in metadata_rows if size <= MAX_BYTES])
        bodies, spans = [], {}
        for index, request, ref, size in metadata_rows:
            source = {"tool": tool, "repo": request.get("repo"), "source": request["source"], "ref": ref, "path": request["path"]}
            if size > MAX_BYTES:
                records.append({"schema": "SyntaxContext/v1", "engine_sha256": engine.identity, "source": source,
                                "status": "limit", "reason": "source byte budget; original read retained", "semantic_reviewed": False})
                continue
            raw = read(request)
            try:
                lines, _ = decode(raw)
            except (UnicodeError, ValueError):
                lines = None
            bodies.append((index, request, raw, ref, lines))
            spans.setdefault(ref, [])
        by_ref = {}
        for row in bodies:
            by_ref.setdefault(row[3], row)
        unique = list(by_ref.values())
        for i, first in enumerate(unique):
            for last in unique[i + 1:]:
                if first[4] is None or last[4] is None:
                    continue
                before, after = hunk_ranges(diff(first[1], last[1], first[3]), len(first[4]), len(last[4]))
                spans[first[3]].extend(before)
                spans[last[3]].extend(after)
        for index, request, raw, ref, _ in bodies:
            source = {"tool": tool, "repo": request.get("repo"), "source": request["source"], "ref": ref}
            result = engine.plan(raw, request["path"], merge_ranges(spans[ref]), source)
            records.append(result)
            if result["status"] == "ok" and result["ranges"] and result["unread_ranges"]:
                replacement = []
                for position, (first, last) in enumerate(result["ranges"]):
                    row = {**request, "line_start": first, "line_end": last}
                    if "id" in row:
                        row["id"] = row["id"] + f"-syntax-{position:04}"
                    replacement.append(row)
                replacements[index] = replacement
    for index, request in enumerate(requests):
        rewritten.extend(replacements.get(index, [request]))
    return {"schema": "SyntaxReadPlan/v1", "engine_sha256": engine.identity,
            "tool": tool, "context": str(context.resolve()), "requests": rewritten,
            "files": records, "cache_hits": engine.cache_hits,
            "semantic_reviewed": False, "changed_reads": len(replacements)}
