"""Real grammar, immutable-review and fail-closed bundle acceptance."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import workflow_kit_installer_test as harness

SOURCE = harness.ROOT / "resources/workflow-kit/common/scripts/syntax-context"
spec = importlib.util.spec_from_file_location("syntax_engine_tests", SOURCE / "engine.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


def fixture(extension, changed=1):
    methods = []
    for number in range(80):
        value = changed if number == 40 else number
        if extension == ".java":
            methods.append(f"  int method{number}() {{\n    return {value};\n  }}")
        elif extension == ".cs":
            methods.append(f"  public int Method{number}() {{\n    return {value};\n  }}")
        else:
            methods.append(f"function method{number}() {{\n  return {value};\n}}")
    text = "\n".join(methods) + "\n"
    return ("class Example {\n" + text + "}\n") if extension in (".cs", ".java") else text


@unittest.skipUnless(engine.supported(), "native syntax runtime is Windows x64 GIL CPython 3.11–3.14")
class SyntaxEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = engine.Engine()

    def test_all_grammars_select_complete_changed_member(self):
        for extension in (".cs", ".java", ".js", ".jsx", ".ts", ".tsx"):
            with self.subTest(extension=extension):
                text = fixture(extension)
                lines = text.splitlines()
                target = next(index + 1 for index, line in enumerate(lines) if "return 1;" in line and index > 100)
                result = self.engine.plan(text.encode(), "Example" + extension, [[target, target]])
                self.assertEqual("ok", result["status"], result.get("reason"))
                self.assertTrue(any(first <= target <= last for first, last in result["ranges"]))
                self.assertLess(sum(last - first + 1 for first, last in result["ranges"]), len(lines) * .2)
                self.assertFalse(result["semantic_reviewed"])
                self.assertTrue(result["unread_ranges"])

    def test_header_changes_require_full_context(self):
        result = self.engine.plan(fixture(".cs").encode(), "Example.cs", [[1, 1]])
        self.assertEqual("fallback", result["status"])

    def test_large_files_and_repeated_native_lifetimes(self):
        text = "class Large {\n" + "".join(f" int F{i}() {{\n return {i};\n }}\n" for i in range(500)) + "}\n"
        for _ in range(3):
            analyzer = engine.Engine()
            result = analyzer.plan(text.encode(), "Large.cs", [[1001, 1001]])
            self.assertEqual("ok", result["status"])
            self.assertTrue(any(first <= 1001 <= last for first, last in result["ranges"]))
            self.assertEqual(501, len(result["symbols"]))

    def test_initialization_and_annotated_overloads_are_retained(self):
        for path, text in [
            ("X.cs", "class X {\n static int counter = 2;\n [Obsolete]\n int F(int x) {\n return x + counter;\n }\n int F(string x) { return 0; }\n}\n"),
            ("X.java", "class X {\n static int counter = 2;\n { counter++; }\n @Deprecated\n int f(int x) {\n return x + counter;\n }\n int f(String x) { return 0; }\n}\n")]:
            with self.subTest(path=path):
                target = next(i + 1 for i, row in enumerate(text.splitlines()) if "return x" in row)
                result = self.engine.plan(text.encode(), path, [[target, target]])
                self.assertEqual("ok", result["status"], result.get("reason"))
                self.assertTrue(any(a <= 2 <= b for a, b in result["ranges"]))
                annotation = next(i + 1 for i, row in enumerate(text.splitlines()) if "Obsolete" in row or "Deprecated" in row)
                self.assertTrue(any(a <= annotation <= b for a, b in result["ranges"]))
        for extension in (".js", ".ts"):
            raw = b'class C {\n constructor() {\n  this.value = 7;\n }\n run() {\n  return this.value;\n }\n skip() { return 0; }\n}\n'
            result = self.engine.plan(raw, "C" + extension, [[6, 6]])
            self.assertEqual("ok", result["status"])
            self.assertTrue(any(first <= 2 and last >= 4 for first, last in result["ranges"]))
            self.assertFalse(any(first <= 8 <= last for first, last in result["ranges"]))
        raw = b'class C {\n int Count { get; }\n  = Initialize();\n int F() {\n  return Count;\n }\n int Skip() { return 0; }\n}\n'
        result = self.engine.plan(raw, "C.cs", [[5, 5]])
        self.assertEqual("ok", result["status"])
        self.assertTrue(any(first <= 2 and last >= 3 for first, last in result["ranges"]))
        self.assertFalse(any(first <= 7 <= last for first, last in result["ranges"]))

    def test_fake_comment_symbols_do_not_become_definitions(self):
        result = self.engine.analyze(b'// function ghost() {}\nfunction real() { return "function fake() {}"; }\n', "x.js")
        self.assertEqual(["real"], [row["name"] for row in result["symbols"]])

    def test_local_declarations_keep_the_complete_function_and_global_initialization(self):
        for extension in (".js", ".ts"):
            raw = b'const state = initialize();\nfunction run() {\n const local = 1;\n return local + state;\n}\nfunction skip() { return 0; }\n'
            result = self.engine.plan(raw, "module" + extension, [[3, 3]])
            self.assertEqual("ok", result["status"])
            self.assertEqual([[1, 5]], result["ranges"])
            raw = b'const run = () => {\n const local = 1;\n return local;\n};\nconst skip = () => 0;\n'
            result = self.engine.plan(raw, "arrows" + extension, [[2, 2]])
            self.assertEqual("ok", result["status"])
            self.assertEqual([[1, 4]], result["ranges"])

    def test_tsx_jsx_and_top_level_initialization(self):
        for path in ("x.tsx", "x.jsx"):
            result = self.engine.plan(b'initialize();\nfunction F() {\n return <div/>;\n}\n', path, [[3, 3]])
            self.assertEqual("ok", result["status"], result.get("reason"))
            self.assertTrue(any(a <= 1 <= b for a, b in result["ranges"]))

    def test_encoding_crlf_and_source_rebinding(self):
        text = "class X {\r\n string F() {\r\n return \"中文\";\r\n }\r\n}\r\n"
        for encoding in ("utf-8-sig", "utf-16", "cp950"):
            raw = text.encode(encoding)
            result = self.engine.plan(raw, "中文.cs", [[3, 3]], {"ref": "first"})
            self.assertEqual("ok", result["status"])
            self.assertEqual(5, result["total_lines"])
            again = self.engine.plan(raw, "中文.cs", [[3, 3]], {"ref": "second"})
            self.assertEqual("second", again["source"]["ref"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), again["source"]["content_sha256"])

    def test_partial_unknown_binary_and_limit_preserve_obligations(self):
        for raw, path, expected in [(b"class X {", "x.cs", "partial"), (b"x", "x.py", "unsupported"),
                                    (b"\0\1", "x.cs", "error"), (b" " * (engine.MAX_BYTES + 1), "x.cs", "limit")]:
            self.assertEqual(expected, self.engine.analyze(raw, path)["status"])

    def test_no_secret_literal_in_syntax_artifact(self):
        result = self.engine.analyze(b'const token = "never-emit-this-secret";\nfunction f() { return token; }', "x.ts")
        self.assertNotIn("never-emit-this-secret", json.dumps(result))

    def test_csharp_file_namespace_and_top_level_initialization(self):
        for prelude in ("namespace Sample;", 'System.Console.WriteLine("initialize");'):
            raw = (prelude + "\npartial class C {\n int F() {\n return 1;\n }\n}\n").encode()
            result = self.engine.plan(raw, "C.cs", [[4, 4]])
            self.assertEqual("ok", result["status"])
            self.assertTrue(any(first <= 1 <= last for first, last in result["ranges"]))

    def test_typescript_member_decorators_follow_their_owners(self):
        raw = b'class C {\n @trace\n // attached comment\n run() {\n return 1;\n }\n @other\n skip() { return 2; }\n}\n'
        result = self.engine.plan(raw, "C.ts", [[5, 5]])
        self.assertEqual("ok", result["status"])
        self.assertTrue(any(first <= 2 <= last for first, last in result["ranges"]))
        self.assertFalse(any(first <= 7 <= last for first, last in result["ranges"]))

    def test_git_hunks_keep_source_specific_deletions_and_literal_changes(self):
        adapter_spec = importlib.util.spec_from_file_location("syntax_adapter_tests", SOURCE / "reviewer_adapter.py")
        adapter = importlib.util.module_from_spec(adapter_spec)
        with patch.dict(sys.modules, {"engine": engine}):
            adapter_spec.loader.exec_module(adapter)
        before, after = adapter.hunk_ranges(b'@@ -2 +2 @@\n- return 1;\n+ return 2;\n@@ -8,2 +8,0 @@\n- // comment\n- removed();\n', 20, 18)
        self.assertEqual([[2, 2], [8, 9]], before)
        self.assertEqual([[2, 2], [9, 9]], after)
        self.assertEqual(([[1, 1]], [[1, 2]]), adapter.hunk_ranges(b'@@ -0,0 +1,2 @@\n', 3, 5))
        self.assertEqual(([], []), adapter.hunk_ranges(b'Binary files differ\n', 3, 3))

    def test_default_enablement_requires_both_acceptance_gates(self):
        original = Path.read_text

        def unverified(path, *args, **kwargs):
            if path.name == "acceptance.json":
                return json.dumps({"schema": "SyntaxAcceptance/v1", "default_mode": "auto", "model_quality_verified": False,
                                   "end_to_end_performance_verified": False})
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", unverified), self.assertRaisesRegex(engine.IntegrityError, "paired quality"):
            engine.Engine()

    def test_wrong_pinned_grammar_abi_falls_back(self):
        analyzer = engine.Engine()
        analyzer.manifest = {**analyzer.manifest, "grammar_abis": {**analyzer.manifest["grammar_abis"], "csharp": 999}}
        analyzer.languages, analyzer.queries = {}, {}
        result = analyzer.analyze(b'class X { int F() { return 1; } }', "X.cs")
        self.assertEqual("unavailable", result["status"])
        self.assertEqual([], result["ranges"])

    def test_cli_output_budget_handles_a_single_giant_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = ("function " + "long_name_" * 4096 + "() { return 1; }\n").encode()
            (root / "large.js").write_bytes(raw)
            result = subprocess.run([sys.executable, "-I", "-B", str(SOURCE / "cli.py"), "analyze", "--root", str(root),
                                     "--path", "large.js", "--expected-source-sha256", hashlib.sha256(raw).hexdigest()],
                                    capture_output=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertLessEqual(len(result.stdout), 24 * 1024)
            self.assertEqual("limit", json.loads(result.stdout)["status"])

    def test_partial_parse_keeps_every_source_line_unread(self):
        result = self.engine.analyze(b'class X {\n int broken(\n', "X.cs")
        self.assertEqual("partial", result["status"])
        self.assertEqual([[1, 2]], result["unread_ranges"])

    def test_bundle_identity_and_query_tampering_are_rejected(self):
        with self.assertRaises(engine.IntegrityError):
            engine.Engine("0" * 64)
        original = Path.read_bytes

        def changed(path):
            return b"changed" if path.name == "java.scm" else original(path)
        with patch.object(Path, "read_bytes", changed), self.assertRaises(engine.IntegrityError):
            engine.Engine()

    def test_unmanaged_siblings_and_bytecode_are_rejected_before_execution(self):
        from importlib._bootstrap_external import _code_to_timestamp_pyc
        for variant in ("bytecode", "stdlib-sibling", "native-sibling"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                helper = root / "helper"
                shutil.copytree(SOURCE, helper)
                sentinel = root / "executed.txt"
                poison = "from pathlib import Path\nPath(" + repr(str(sentinel)) + ").write_text('unexpected execution')\nraise RuntimeError('unmanaged code executed')\n"
                if variant == "bytecode":
                    source = helper / "engine.py"
                    cached = Path(importlib.util.cache_from_source(str(source)))
                    cached.parent.mkdir(parents=True)
                    info = source.stat()
                    cached.write_bytes(_code_to_timestamp_pyc(compile(poison, str(source), "exec"), int(info.st_mtime), info.st_size))
                elif variant == "stdlib-sibling":
                    (helper / "platform.py").write_text(poison, encoding="utf-8")
                else:
                    (helper / "engine.pyd").write_bytes(b"unmanaged native sibling")
                process = subprocess.run([sys.executable, "-I", "-B", str(helper / "cli.py"), "capabilities"],
                                         capture_output=True, timeout=30)
                self.assertEqual(2, process.returncode, process.stderr)
                self.assertIn(b"Unexpected syntax asset", process.stderr)
                self.assertFalse(sentinel.exists())

    def test_source_cli_is_read_only_and_detects_inventory_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = fixture(".cs").encode()
            source = root / "source.cs"
            source.write_bytes(raw)
            command = [sys.executable, "-I", "-B", str(SOURCE / "cli.py"), "analyze", "--root", str(root),
                       "--path", "source.cs", "--expected-source-sha256", hashlib.sha256(raw).hexdigest()]
            result = subprocess.run(command, capture_output=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIsNotNone(json.loads(result.stdout)["next_offset"])
            self.assertEqual([source], list(root.iterdir()))
            source.write_text("changed", encoding="utf-8")
            self.assertEqual(2, subprocess.run(command, capture_output=True, timeout=30).returncode)

    def test_foreign_bytecode_prefix_cannot_replace_managed_wheel_source(self):
        from importlib._bootstrap_external import _code_to_timestamp_pyc
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root / "helper"
            shutil.copytree(SOURCE, helper)
            prefix, sentinel = root / "foreign-cache", root / "executed.txt"
            source = helper / f"vendor/cp{sys.version_info.major}{sys.version_info.minor}/tree_sitter/__init__.py"
            previous = sys.pycache_prefix
            try:
                sys.pycache_prefix = str(prefix)
                cached = Path(importlib.util.cache_from_source(str(source)))
            finally:
                sys.pycache_prefix = previous
            cached.parent.mkdir(parents=True)
            poison = "from pathlib import Path\nPath(" + repr(str(sentinel)) + ").write_text('unexpected execution')\nraise RuntimeError('foreign cache executed')\n"
            info = source.stat()
            cached.write_bytes(_code_to_timestamp_pyc(compile(poison, str(source), "exec"), int(info.st_mtime), info.st_size))
            raw = b'class X { int F() { return 1; } }\n'
            (root / "X.cs").write_bytes(raw)
            process = subprocess.run([sys.executable, "-I", "-B", "-X", f"pycache_prefix={prefix}", str(helper / "cli.py"),
                                      "analyze", "--root", str(root), "--path", "X.cs", "--expected-source-sha256",
                                      hashlib.sha256(raw).hexdigest(), "--worker"], capture_output=True, timeout=30)
            self.assertEqual(0, process.returncode, process.stderr)
            self.assertEqual("ok", json.loads(process.stdout)["status"])
            self.assertFalse(sentinel.exists())


@unittest.skipUnless(engine.supported(), "Windows syntax integration")
class InstalledSyntaxTests(unittest.TestCase):
    install = harness.WorkflowKitInstallerTests.install
    execute = harness.WorkflowKitInstallerTests.execute
    create_group = harness.WorkflowKitInstallerTests.create_group

    def test_installer_rejects_unknown_syntax_files_and_preserves_them(self):
        with tempfile.TemporaryDirectory(prefix="syn-integrity-") as temporary:
            group = self.create_group(Path(temporary))
            result, detail = self.install(group)
            self.assertEqual(0, result.returncode, detail)
            extra = group / ".agents/gitlab-workspace-kit/scripts/syntax-context/platform.py"
            extra.write_bytes(b"raise RuntimeError('unmanaged sibling')\n")
            status, detail = self.execute("status", group, "--expected-version", harness.VERSION)
            self.assertEqual(0, status.returncode, detail)
            self.assertEqual("error", detail["status"])
            self.assertIn("unowned", detail["message"])
            repeated, detail = self.install(group)
            self.assertNotEqual(0, repeated.returncode, detail)
            self.assertEqual(b"raise RuntimeError('unmanaged sibling')\n", extra.read_bytes())

    def test_real_frozen_sessions_use_bounded_reads_and_keep_coverage_unreviewed(self):
        with tempfile.TemporaryDirectory(prefix="syn-") as temporary:
            root = Path(temporary)
            group = self.create_group(root)
            installed, detail = self.install(group)
            self.assertEqual(0, installed.returncode, detail)
            repo = group / "source repo"
            repo.mkdir()
            env = {**os.environ, "WORKFLOW_KIT_SYNTAX_CONTEXT": "auto", "PYTHONPATH": "",
                   "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                   "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.longpaths", "GIT_CONFIG_VALUE_0": "true"}

            def git(*args):
                return subprocess.check_output(["git", "-C", str(repo), *args], env=env).decode().strip()

            git("init", "-b", "base")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "Syntax fixture")
            git("config", "commit.gpgsign", "false")
            git("config", "core.autocrlf", "false")
            for extension in (".cs", ".java", ".js", ".ts"):
                (repo / ("Example" + extension)).write_text(fixture(extension, 1), encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "baseline")
            git("switch", "-c", "feature")
            for extension in (".cs", ".java", ".js", ".ts"):
                (repo / ("Example" + extension)).write_text(fixture(extension, 999), encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "change one member")
            # The planner must read the frozen versions, not this checkout.
            (repo / "Example.cs").write_text("invalid live checkout", encoding="utf-8")
            for tool in ("merge-reviewer", "release-reviewer"):
                runtime = root / ("m" if tool == "merge-reviewer" else "r")
                runner = group / ".agents/gitlab-workspace-kit/run.py"
                script = group / f".agents/skills/{tool}/scripts/review_session.py"

                def run(*args, codes=(0,)):
                    result = subprocess.run([sys.executable, "-B", str(runner), "--", sys.executable, "-X", "utf8", "-B",
                                             str(script), *map(str, args)], env=env, capture_output=True, timeout=120)
                    self.assertIn(result.returncode, codes, (result.stderr or result.stdout).decode(errors="replace"))
                    return json.loads(result.stdout)

                options = ["start", "--workspace", group, "--project", repo, "--base", "base", "--head", "feature", "--runtime-root", runtime]
                if tool == "merge-reviewer":
                    options.append("--no-fetch")
                else:
                    options.append("--prepare-evidence")
                started = run(*options)
                context = Path(started["context_dir"])
                if tool == "merge-reviewer":
                    plan_path = Path(started["initial_reads_file"])
                    requests = json.loads(plan_path.read_text(encoding="utf-8"))
                else:
                    plan_path = context / "review-worklist.json"
                    requests = json.loads(plan_path.read_text(encoding="utf-8"))["requests"]
                    draft = json.loads((context / "review-result-draft.json").read_text(encoding="utf-8"))
                    self.assertTrue(all(row["status"] == "not-reviewed" for row in draft["coverage"]))
                reads = [r for r in requests if r.get("op", r.get("action")) == "read"]
                self.assertTrue(reads)
                self.assertTrue(all("line_start" in row for row in reads), requests)
                self.assertTrue(all(row["line_end"] - row["line_start"] < 12 for row in reads))
                before = plan_path.read_bytes()
                identity = ["--runtime-root", runtime, "--request-id", started["request_id"]]
                run("status", *identity)
                frozen_head = git("rev-parse", "feature")
                git("update-ref", "refs/heads/feature", git("rev-parse", "base"))
                arguments = ["step", *identity, "--requests-file" if tool == "merge-reviewer" else "--worklist", plan_path]
                run(*arguments)
                run(*arguments)  # exact retry reuses saved operation identities
                git("update-ref", "refs/heads/feature", frozen_head)
                run("check", *identity, codes=(0, 3))
                self.assertEqual(before, plan_path.read_bytes())
                self.assertEqual(0, started["network_activity"]["fetch_attempt_count"])
                # This known constant-only fixture authors a complete draft;
                # this tests native publication, not independent model quality.
                manifest = json.loads((context / "manifest.json").read_text(encoding="utf-8"))
                draft_path = Path(started["draft_path"])
                draft = json.loads(draft_path.read_text(encoding="utf-8"))
                draft["summary"] = "Authored fixture: changed one fixed constant in otherwise independent methods."
                citations = []
                for request in reads:
                    if tool == "merge-reviewer":
                        repository_record = next(r for r in manifest["repositories"] if r["id"] == request["repo"])
                        ref = repository_record["sources"][request["source"]]["ref"]
                    else:
                        ref = request["ref"]
                    citations.append({"repo": request["repo"], "source": request["source"], "ref": ref,
                                      "path": request["path"], "line_start": request["line_start"], "line_end": request["line_end"]})
                for row in draft["coverage"]:
                    row.update(status="reviewed", reason="Compared the complete changed member and initialization context.",
                               evidence=[c for c in citations if c["path"] == row["path"]])
                if tool == "release-reviewer":
                    for row in draft["dependency_coverage"]:
                        row.update(status="reviewed", reason="Known literal-only fixture introduces no resources.",
                                   evidence=[c for c in citations if c["source"] == "merge-preview"])
                draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
                run("check", *identity)
                published = run("finish", *identity)
                report = Path(published["report_path"])
                self.assertTrue(report.is_file())
                self.assertTrue(published["review_outcome"]["review_complete"])
                self.assertEqual(str(report), run("finish", *identity)["report_path"])

    def test_merge_parents_delete_and_rename_keep_every_native_obligation(self):
        with tempfile.TemporaryDirectory(prefix="syn-edge-") as temporary:
            root = Path(temporary)
            group = self.create_group(root)
            installed, detail = self.install(group)
            self.assertEqual(0, installed.returncode, detail)
            repo = group / "edge-repo"
            repo.mkdir()
            env = {**os.environ, "WORKFLOW_KIT_SYNTAX_CONTEXT": "auto", "PYTHONPATH": "",
                   "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

            def git(*args):
                return subprocess.check_output(["git", "-C", str(repo), *args], env=env, stderr=subprocess.PIPE).decode().strip()

            git("init", "-b", "base")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "Syntax edge fixture")
            git("config", "commit.gpgsign", "false")
            git("config", "core.autocrlf", "false")
            for path in ("Example.cs", "Deleted.cs", "OldName.java"):
                (repo / path).write_text(fixture(Path(path).suffix), encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "baseline")
            git("switch", "-c", "side")
            (repo / "Example.cs").write_text(fixture(".cs").replace("return 60;", "return 600;"), encoding="utf-8")
            git("commit", "-am", "side member")
            git("switch", "-c", "feature", "base")
            (repo / "Example.cs").write_text(fixture(".cs", 999), encoding="utf-8")
            git("rm", "Deleted.cs")
            git("mv", "OldName.java", "Renamed.java")
            git("commit", "-am", "member delete rename")
            git("merge", "--no-ff", "side", "-m", "merge two changes")
            for tool in ("merge-reviewer", "release-reviewer"):
                runtime = root / ("m" if tool == "merge-reviewer" else "r")
                scripts = group / f".agents/skills/{tool}/scripts"
                runner = group / ".agents/gitlab-workspace-kit/run.py"

                def run(*args):
                    result = subprocess.run([sys.executable, "-B", str(runner), "--", sys.executable, "-X", "utf8", "-B",
                                             str(scripts / "review_session.py"), *map(str, args)], env=env,
                                            capture_output=True, timeout=120)
                    self.assertEqual(0, result.returncode, result.stderr.decode(errors="replace"))
                    return json.loads(result.stdout)

                started = run("start", "--workspace", group, "--project", repo, "--base", "base", "--head", "feature",
                              "--runtime-root", runtime, "--no-fetch" if tool == "merge-reviewer" else "--prepare-evidence")
                context = Path(started["context_dir"])
                manifest_path = context / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertTrue(manifest["required_merge_views"])
                if tool == "merge-reviewer":
                    saved = Path(started["initial_reads_file"])
                    requests = json.loads(saved.read_text(encoding="utf-8"))
                    expression = "__import__('review_flow').initial_read_requests(manifest)"
                else:
                    saved = context / "review-worklist.json"
                    worklist = json.loads(saved.read_text(encoding="utf-8"))
                    requests = worklist["requests"]
                    expression = "__import__('review_worklist').prepare(manifest)[0]['requests']"
                    draft = json.loads((context / "review-result-draft.json").read_text(encoding="utf-8"))
                    self.assertTrue(all(row["status"] == "not-reviewed" for row in draft["merge_parent_review"]))
                code = ("import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
                        "manifest=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'));print(json.dumps(" + expression + "))")
                baseline = json.loads(subprocess.check_output([sys.executable, "-I", "-B", "-c", code, str(scripts), str(manifest_path)], env=env))

                def source_keys(rows):
                    return {(row.get("repo"), row["source"], row.get("ref"), row["path"]) for row in rows
                            if row.get("op", row.get("action")) == "read"}

                self.assertEqual(source_keys(baseline), source_keys(requests))
                reads = [row for row in requests if row.get("op", row.get("action")) == "read"]
                self.assertTrue(any(row["source"].startswith(("parent-", "merge-parent")) for row in reads))
                self.assertTrue(any(row["path"] == "Example.cs" and "line_start" in row for row in reads))
                for path in ("Deleted.cs", "OldName.java", "Renamed.java"):
                    selected = [row for row in reads if row["path"] == path]
                    self.assertTrue(selected, (tool, path, reads))
                    self.assertTrue(all("line_start" not in row for row in selected), (tool, path, selected))
                self.assertEqual([row for row in baseline if row.get("op", row.get("action")) != "read"],
                                 [row for row in requests if row.get("op", row.get("action")) != "read"])
                identity = ["--runtime-root", runtime, "--request-id", started["request_id"]]
                before = saved.read_bytes()
                run("step", *identity, "--requests-file" if tool == "merge-reviewer" else "--worklist", saved)
                self.assertEqual(before, saved.read_bytes())
                self.assertEqual(0, started["network_activity"]["fetch_attempt_count"])
                run("cancel", *identity)
