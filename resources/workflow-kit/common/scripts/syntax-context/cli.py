"""Offline syntax navigation. All source paths are explicit; no repository execution."""
from __future__ import annotations

import os
import sys

# Never let an extra sibling shadow stdlib or the declared helper modules.
_directory = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [item for item in sys.path if os.path.abspath(item) != _directory]
sys.dont_write_bytecode = True

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess


def managed_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    # Compile the authenticated source explicitly; never consult a .pyc cache.
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


managed_module("engine", Path(__file__).resolve().with_name("engine.py"))
from engine import Engine, IntegrityError, MAX_BYTES, MAX_PLAN_INPUT_BYTES, MAX_OUTPUT_BYTES, capabilities, plain, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capabilities", "analyze", "plan"))
    parser.add_argument("--expected-engine-sha256")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--path")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--snapshot-id")
    parser.add_argument("--lines", action="append", default=[], help="physical inclusive START:END")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--page-size", type=int, default=32)
    parser.add_argument("--review-tool", choices=("merge-reviewer", "release-reviewer"), help=argparse.SUPPRESS)
    parser.add_argument("--native-scripts", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.command == "capabilities":
        result = capabilities(args.expected_engine_sha256)
    elif args.review_tool:
        from engine import bundle
        bundle(args.expected_engine_sha256)
        rewrite = managed_module("reviewer_adapter", Path(__file__).resolve().with_name("reviewer_adapter.py")).rewrite
        raw_input = sys.stdin.buffer.read(MAX_PLAN_INPUT_BYTES + 1)
        if len(raw_input) > MAX_PLAN_INPUT_BYTES:
            sys.stderr.write("Syntax planner input budget exceeded; retain original reads.\n")
            return 1
        data = json.loads(raw_input)
        result = rewrite(args.review_tool, data["context"], data["manifest"], data["requests"],
                         args.native_scripts, args.expected_engine_sha256)
    else:
        if args.root is None or not args.path or not args.expected_source_sha256:
            parser.error("source operations require --root, --path and --expected-source-sha256 from the native inventory")
        root = plain(args.root).resolve()
        relative = Path(args.path)
        if relative.is_absolute() or ".." in relative.parts:
            parser.error("path must stay within the explicit root")
        path = plain(root / relative)
        if not path.resolve().is_relative_to(root) or not path.is_file():
            parser.error("source path is not a plain file under root")
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            result = {"schema": "SyntaxContext/v1", "status": "limit", "reason": "source byte budget", "semantic_reviewed": False}
        else:
            if sha(raw) != args.expected_source_sha256:
                raise IntegrityError("Source changed since native inventory; rescan before analysis")
            engine = Engine(args.expected_engine_sha256)
            identity = {"snapshot_id": args.snapshot_id, "kind": "working-tree"}
            ranges = [list(map(int, item.split(":"))) for item in args.lines]
            result = engine.plan(raw, args.path, ranges, identity) if args.command == "plan" else engine.analyze(raw, args.path, identity)
        if args.offset < 0 or not 1 <= args.page_size <= 64:
            parser.error("offset must be nonnegative; page-size must be 1..64")
        arrays = {key: value for key, value in result.items() if isinstance(value, list)}
        page_size = args.page_size
        while True:
            end = args.offset + page_size
            page = {**result, **{key: value[args.offset:end] for key, value in arrays.items()},
                    "offset": args.offset, "next_offset": end if any(len(items) > end for items in arrays.values()) else None,
                    "counts": {key: len(value) for key, value in arrays.items()}}
            if len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) < MAX_OUTPUT_BYTES:
                result = page
                break
            if page_size == 1:
                result = {"schema": "SyntaxContext/v1", "engine_sha256": result.get("engine_sha256"),
                          "status": "limit", "reason": "syntax output budget; use native source reads", "semantic_reviewed": False}
                break
            page_size = max(1, page_size // 2)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    try:
        # A process watchdog also bounds a native parser that stops requesting
        # input. Review calls already run under their bridge's 30-second guard.
        if len(sys.argv) > 1 and sys.argv[1] in ("analyze", "plan") and "--worker" not in sys.argv and "--review-tool" not in sys.argv:
            try:
                process = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).resolve()), *sys.argv[1:], "--worker"],
                                         capture_output=True, timeout=10)
                sys.stdout.buffer.write(process.stdout)
                sys.stderr.buffer.write(process.stderr)
                raise SystemExit(process.returncode)
            except subprocess.TimeoutExpired:
                print(json.dumps({"schema": "SyntaxContext/v1", "status": "limit", "reason": "syntax process deadline", "semantic_reviewed": False}))
                raise SystemExit(0)
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        sys.stderr.write(f"Syntax context integrity/input error: {error}\n")
        raise SystemExit(2)
