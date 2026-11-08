"""Bounded, offline syntax facts. Syntax is navigation, never semantic coverage."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import sys
import time

ROOT = Path(__file__).resolve().parent
MAX_BYTES = 4 * 1024 * 1024
MAX_FACTS = 4096
MAX_SECONDS = 2.0
MAX_PLAN_INPUT_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 24 * 1024
EXTENSIONS = {".cs": "csharp", ".java": "java", ".js": "javascript", ".jsx": "javascript",
              ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript", ".mts": "typescript",
              ".cts": "typescript", ".tsx": "tsx"}
MODULES = {"csharp": "tree_sitter_c_sharp", "java": "tree_sitter_java",
           "javascript": "tree_sitter_javascript", "typescript": "tree_sitter_typescript", "tsx": "tree_sitter_typescript"}
_RUNTIMES = {}  # Keep native Language/Query lifetimes together for this process.


class IntegrityError(ValueError):
    """A declared managed asset is missing, replaced, or unsafe."""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def plain(path):
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError as error:
            raise IntegrityError(f"Missing syntax asset: {path.name}") from error
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise IntegrityError("Syntax asset path contains a link or junction")
    return path


def bundle(expected=None):
    path = plain(ROOT / "bundle.json")
    raw = path.read_bytes()
    identity = sha(raw)
    if expected is not None and identity != expected:
        raise IntegrityError("Syntax bundle changed; check installation and copy a fresh task")
    value = json.loads(raw)
    if value.get("schema") != "SyntaxBundle/v1" or not isinstance(value.get("files"), dict):
        raise IntegrityError("Unknown syntax bundle")
    expected_files = set(value["files"]) | {"bundle.json"}
    for candidate in ROOT.rglob("*"):
        plain(candidate)
        if candidate.is_file() and candidate.relative_to(ROOT).as_posix() not in expected_files:
            raise IntegrityError("Unexpected syntax asset; verify installation")
    for name, digest in value["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
            raise IntegrityError("Unsafe syntax asset path")
        asset = plain(ROOT / relative)
        if not asset.is_file() or sha(asset.read_bytes()) != digest:
            raise IntegrityError(f"Syntax asset hash mismatch: {name}")
    acceptance = json.loads((ROOT / "acceptance.json").read_text(encoding="utf-8"))
    if acceptance.get("schema") != "SyntaxAcceptance/v1" or acceptance.get("default_mode") not in ("auto", "off"):
        raise IntegrityError("Invalid syntax acceptance mode")
    if acceptance["default_mode"] == "auto" and not (
            acceptance.get("model_quality_verified") is True and acceptance.get("end_to_end_performance_verified") is True):
        raise IntegrityError("Default syntax enablement requires paired quality and end-to-end acceptance")
    return value, identity


def mode():
    chosen = os.environ.get("WORKFLOW_KIT_SYNTAX_CONTEXT")
    if chosen is None:
        chosen = json.loads((ROOT / "acceptance.json").read_text(encoding="utf-8"))["default_mode"]
    if chosen not in ("auto", "off"):
        raise ValueError("WORKFLOW_KIT_SYNTAX_CONTEXT must be auto or off")
    return chosen


def supported():
    return (sys.platform == "win32" and platform.machine().lower() in ("amd64", "x86_64")
            and sys.implementation.name == "cpython" and (3, 11) <= sys.version_info[:2] <= (3, 14)
            and not sysconfig_free_threaded())


def sysconfig_free_threaded():
    import sysconfig
    return bool(sysconfig.get_config_var("Py_GIL_DISABLED"))


def capabilities(expected=None):
    data, identity = bundle(expected)
    return {"schema": "SyntaxCapabilities/v1", "engine_sha256": identity, "available": supported(),
            "default_mode": mode(), "languages": data["languages"], "python_abis": data["python_abis"],
            "grammar_abis": data["grammar_abis"],
            "limits": {"source_bytes": MAX_BYTES, "facts": MAX_FACTS, "parse_seconds": MAX_SECONDS,
                       "planner_input_bytes": MAX_PLAN_INPUT_BYTES, "output_bytes": MAX_OUTPUT_BYTES},
            "semantic_resolution": False}


def decode(raw):
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text, encoding = raw.decode("utf-16"), "utf-16"
    else:
        encoding = "utf-8-sig"
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            text, encoding = raw.decode("cp950"), "cp950"
        if "\0" in text:
            raise ValueError("binary source")
    sample = raw[:8192]
    if encoding != "utf-16" and sample and sum(byte < 9 or 13 < byte < 32 for byte in sample) / len(sample) > 0.05:
        raise ValueError("binary source")
    # Use physical lines, preserving evidence line numbers through transcoding.
    lines = re.split(r"\r\n|\n|\r", text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines, encoding


def merge_ranges(ranges):
    result = []
    for first, last in sorted(ranges):
        if result and first <= result[-1][1] + 1:
            result[-1][1] = max(last, result[-1][1])
        else:
            result.append([first, last])
    return result


def complement(ranges, total):
    result, next_line = [], 1
    for first, last in merge_ranges(ranges):
        if next_line < first:
            result.append([next_line, first - 1])
        next_line = last + 1
    if next_line <= total:
        result.append([next_line, total])
    return result


class Engine:
    def __init__(self, expected=None):
        self.manifest, self.identity = bundle(expected)
        self.cache = {}
        self.languages, self.queries = _RUNTIMES.setdefault(self.identity, ({}, {}))
        self.cache_hits = 0

    def language(self, name):
        if name in self.languages:
            return self.languages[name]
        paths = [ROOT / "vendor" / f"cp{sys.version_info.major}{sys.version_info.minor}", ROOT / "vendor/shared"]
        for module_name in ("tree_sitter", MODULES[name]):
            existing = sys.modules.get(module_name)
            if existing is not None and not Path(existing.__file__).resolve().is_relative_to(ROOT / "vendor"):
                raise IntegrityError("Refusing an ambient Tree-sitter package")
        sys.path[:0] = [str(path) for path in paths]
        previous_bytecode = sys.dont_write_bytecode
        previous_prefix = sys.pycache_prefix
        sys.dont_write_bytecode = True
        sys.pycache_prefix = None
        try:
            binding = importlib.import_module("tree_sitter")
            grammar = importlib.import_module(MODULES[name])
            if self.manifest["core_language_abi"] != {"minimum": binding.MIN_COMPATIBLE_LANGUAGE_VERSION,
                                                       "maximum": binding.LANGUAGE_VERSION}:
                raise RuntimeError("Pinned Tree-sitter ABI mismatch")
            capsule = grammar.language_tsx() if name == "tsx" else grammar.language_typescript() if name == "typescript" else grammar.language()
            language = binding.Language(capsule)
            if not binding.MIN_COMPATIBLE_LANGUAGE_VERSION <= language.abi_version <= binding.LANGUAGE_VERSION:
                raise RuntimeError("Unsupported grammar ABI")
            if language.abi_version != self.manifest["grammar_abis"][name]:
                raise RuntimeError("Pinned grammar ABI mismatch")
            query_name = "typescript" if name == "tsx" else name
            query = binding.Query(language, (ROOT / "queries" / f"{query_name}.scm").read_text(encoding="utf-8"))
            self.languages[name], self.queries[name] = (binding, language), query
        finally:
            del sys.path[:len(paths)]
            sys.dont_write_bytecode = previous_bytecode
            sys.pycache_prefix = previous_prefix
        return self.languages[name]

    def analyze(self, raw, path, source=None):
        language = EXTENSIONS.get(Path(path).suffix.lower())
        base = {"schema": "SyntaxContext/v1", "engine_sha256": self.identity,
                "source": {**(source or {}), "path": path, "content_sha256": sha(raw)},
                "language": language, "status": "unsupported", "symbols": [], "imports": [], "calls": [], "decorators": [],
                "ranges": [], "unread_ranges": [], "semantic_reviewed": False}
        if language is None:
            return base
        if not supported():
            return {**base, "status": "unavailable", "reason": "Windows x64 GIL CPython 3.11–3.14 required"}
        if len(raw) > MAX_BYTES:
            return {**base, "status": "limit", "reason": "source byte budget"}
        try:
            lines, encoding = decode(raw)
        except (UnicodeError, ValueError):
            return {**base, "status": "error", "reason": "binary or undecodable source"}
        base.update(encoding=encoding, total_lines=len(lines), unread_ranges=[[1, len(lines)]] if lines else [])
        key = (sha(raw), language, encoding, self.identity)
        if key in self.cache:
            self.cache_hits += 1
            return {**self.cache[key], "source": base["source"]}
        deadline = time.monotonic() + MAX_SECONDS
        try:
            binding, lang = self.language(language)
            parser = binding.Parser(lang)
            normalized = "\n".join(lines).encode("utf-8")
            # Avoid callback lifetime/progress faults in the pinned Windows
            # wheels. An external process watchdog bounds native parsing; the
            # byte cap and post-parse deadline reject over-budget results.
            tree = parser.parse(normalized)
            if tree is None or time.monotonic() >= deadline:
                return {**base, "status": "limit", "reason": "parse deadline"}
            if tree.root_node.has_error:
                return {**base, "status": "partial", "reason": "ERROR or MISSING syntax; use original reads"}
            # Keep the cursor alive while inspecting its captured native nodes.
            cursor = binding.QueryCursor(self.queries[language], match_limit=MAX_FACTS)
            captures = cursor.captures(tree.root_node)
            if sum(len(nodes) for nodes in captures.values()) > MAX_FACTS or time.monotonic() >= deadline:
                return {**base, "status": "limit", "reason": "syntax fact budget"}
            for role, nodes in captures.items():
                for node in nodes:
                    actual_role = role
                    if node.type == "property_declaration" and node.child_by_field_name("value") is not None:
                        actual_role = "initializer"
                    if node.type in ("lexical_declaration", "variable_declaration"):
                        parent = node.parent
                        if parent is not None and parent.type == "export_statement":
                            parent = parent.parent
                        if parent is None or not (parent.type == "program" or (
                                parent.type == "statement_block" and parent.parent is not None
                                and parent.parent.type == "internal_module")):
                            # A local declaration is part of its enclosing complete
                            # function, not a smaller independently readable member.
                            continue
                        values = [item.child_by_field_name("value") for item in node.named_children
                                  if item.type == "variable_declarator"]
                        if not values or any(item is None or item.type not in (
                                "arrow_function", "function_expression", "generator_function") for item in values):
                            actual_role = "initializer"
                    if role in ("class_block", "top_level"):
                        expected_parent = "class_body" if role == "class_block" else "program"
                        if node.parent is None or node.parent.type != expected_parent:
                            continue
                        actual_role = "initializer"
                    start_point, end_point = node.start_point, node.end_point
                    first, last = start_point[0] + 1, end_point[0] + (end_point[1] != 0)
                    last = max(first, last)
                    name_node = node.child_by_field_name("name")
                    if name_node is None and role == "call":
                        name_node = node.child_by_field_name("function") or node.child_by_field_name("expression")
                        if name_node is not None:
                            name_node = (name_node.child_by_field_name("name") or name_node.child_by_field_name("property")
                                         or (name_node if name_node.type == "identifier" else None))
                    name = normalized[name_node.start_byte:name_node.end_byte].decode("utf-8") if name_node is not None else ""
                    # No literal/string contents or raw source in syntax artifacts.
                    if not re.fullmatch(r"[\w@$]+", name, re.UNICODE):
                        name = ""
                    fact = {"kind": node.type, "name": name, "line_start": first, "line_end": last, "role": actual_role}
                    if role == "decorator":
                        owner = node.parent
                        if owner is not None and owner.type in ("class_body", "program"):
                            owner = node.next_named_sibling
                            while owner is not None and owner.type in ("decorator", "comment"):
                                owner = owner.next_named_sibling
                        if owner is not None:
                            owner_start, owner_end = owner.start_point, owner.end_point
                            fact["owner_range"] = [owner_start[0] + 1, owner_end[0] + (owner_end[1] != 0)]
                    if role == "export":
                        declaration = node.child_by_field_name("declaration") or node.child_by_field_name("value")
                        if declaration is not None:
                            declaration_point = declaration.start_point
                            fact["line_end"] = declaration_point[0] + 1
                        fact["role"] = "import"
                    if role == "container":
                        body = node.child_by_field_name("body")
                        body_point = body.start_point if body is not None else None
                        fact["header_end"] = body_point[0] + 1 if body_point is not None else last
                    if role == "call":
                        base["calls"].append(fact)
                    elif role == "decorator":
                        base["decorators"].append(fact)
                    elif role in ("import", "export"):
                        base["imports"].append(fact)
                    else:
                        base["symbols"].append(fact)
            for name in ("symbols", "imports", "calls", "decorators"):
                base[name].sort(key=lambda row: (row["line_start"], row["line_end"], row["kind"]))
            base.update(status="ok", unread_ranges=[[1, len(lines)]] if lines else [])
            self.cache[key] = {**base, "source": {}}
            return base
        except IntegrityError:
            raise
        except (ImportError, OSError, ValueError, RuntimeError) as error:
            return {**base, "status": "unavailable", "reason": f"parser/grammar unavailable: {type(error).__name__}"}

    def plan(self, raw, path, changed_ranges, source=None):
        result = self.analyze(raw, path, source)
        if result["status"] != "ok":
            return result
        total = result["total_lines"]
        selected, ranges = [], []
        for first, last in changed_ranges:
            if not (1 <= first <= last <= total):
                return {**result, "status": "fallback", "reason": "unmapped diff hunk"}
            candidates = [s for s in result["symbols"] if s["role"] != "container"
                          and s["line_start"] <= first <= last <= s["line_end"]]
            if not candidates:
                return {**result, "status": "fallback", "reason": "container/header/top-level change requires full context"}
            selected.append(min(candidates, key=lambda s: s["line_end"] - s["line_start"]))
        if not selected:
            return {**result, "status": "fallback", "reason": "no reliable source-specific hunks"}
        for symbol in selected:
            first = symbol["line_start"]
            lines, _ = decode(raw)
            while first > 1 and symbol["line_start"] - first < 16 and lines[first - 2].lstrip().startswith(("//", "/*", "*")):
                first -= 1
            ranges.append([first, symbol["line_end"]])
            for container in result["symbols"]:
                if container["role"] == "container" and container["line_start"] <= symbol["line_start"] <= container["line_end"]:
                    ranges.append([container["line_start"], container["header_end"]])
        for symbol in result["symbols"]:
            if (symbol["role"] == "initializer" or "constructor" in symbol["kind"]
                    or symbol["kind"] == "method_definition" and symbol["name"] == "constructor"):
                ranges.append([symbol["line_start"], symbol["line_end"]])
        ranges.extend([item["line_start"], item["line_end"]] for item in result["imports"])
        for item in result["decorators"]:
            owner = item.get("owner_range")
            if owner is None or any(first <= owner[1] and owner[0] <= last for first, last in ranges):
                ranges.append([item["line_start"], item["line_end"]])
        ranges = merge_ranges(ranges)
        return {**result, "ranges": ranges, "unread_ranges": complement(ranges, total),
                "selection": "complete members, enclosing headers, imports and initializers"}
