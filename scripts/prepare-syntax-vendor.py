"""Maintainer-only, pinned Windows wheels; installed helpers never download packages."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1] / "resources/workflow-kit/common/scripts/syntax-context"
PACKAGES = {"tree-sitter": "0.26.0", "tree-sitter-c-sharp": "0.23.5",
            "tree-sitter-java": "0.23.5", "tree-sitter-javascript": "0.25.0",
            "tree-sitter-typescript": "0.23.2"}
GRAMMAR_ABIS = {"csharp": 15, "java": 14, "javascript": 15, "typescript": 14, "tsx": 14}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def refresh_manifest():
    lock = json.loads((ROOT / "vendor-lock.json").read_text(encoding="utf-8"))
    files = {}
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and path.name != "bundle.json" and "__pycache__" not in path.parts and path.suffix != ".pyc":
            files[path.relative_to(ROOT).as_posix()] = digest(path.read_bytes())
    manifest = {"schema": "SyntaxBundle/v1", "revision": 1, "platform": "win32-x64",
                "python_abis": ["cp311", "cp312", "cp313", "cp314"],
                "languages": ["csharp", "java", "javascript", "typescript", "tsx"],
                "grammar_abis": GRAMMAR_ABIS,
                "core_language_abi": {"minimum": 13, "maximum": 15},
                "queries": {name: {"revision": 1, "sha256": files[f"queries/{name}.scm"],
                                   "origin": "WorkflowKit-owned selectors", "license": "NOASSERTION"}
                            for name in ("csharp", "java", "javascript", "typescript")},
                "packages": lock["packages"], "files": files}
    (ROOT / "bundle.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def prepare():
    packages = []
    for name, version in PACKAGES.items():
        url = f"https://pypi.org/pypi/{name}/{version}/json"
        metadata = json.load(urllib.request.urlopen(url, timeout=45))
        candidates = [item for item in metadata["urls"] if item["filename"].endswith("win_amd64.whl")]
        for abi in (["cp311", "cp312", "cp313", "cp314"] if name == "tree-sitter" else ["shared"]):
            choices = [item for item in candidates if (f"-{abi}-{abi}-" in item["filename"] if abi != "shared" else "-abi3-" in item["filename"])]
            if len(choices) != 1:
                raise ValueError(f"Expected one pinned wheel: {name}/{abi}")
            item = choices[0]
            data = urllib.request.urlopen(item["url"], timeout=60).read()
            if digest(data) != item["digests"]["sha256"]:
                raise ValueError("PyPI wheel hash mismatch")
            destination = ROOT / "vendor" / abi
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in archive.infolist():
                    path = PurePosixPath(member.filename)
                    if path.is_absolute() or ".." in path.parts or "\\" in member.filename or member.file_size > 64 * 1024 * 1024:
                        raise ValueError("Unsafe wheel member")
                    if member.is_dir() or path.suffix == ".pyi" or path.name in ("RECORD", "WHEEL", "INSTALLER"):
                        continue
                    target = destination.joinpath(*path.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(member))
            packages.append({"name": name, "version": version, "abi": abi,
                             "filename": item["filename"], "url": item["url"], "sha256": digest(data),
                             "source": metadata["info"].get("project_urls"), "license": "MIT"})
            print(item["filename"])
    (ROOT / "vendor-lock.json").write_text(json.dumps({"schema": "SyntaxVendor/v1", "packages": packages}, indent=2) + "\n", encoding="utf-8")
    refresh_manifest()


if __name__ == "__main__":
    import sys
    refresh_manifest() if "--manifest-only" in sys.argv else prepare()
