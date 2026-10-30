"""Prepare the pinned official BMAD source and Codex runtime snapshots."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT.parent / "BMAD-METHOD"
SOURCE_DIR = ROOT / "resources" / "offline-tools" / "sources"
SOURCE_FILE = SOURCE_DIR / "bmad-method-6.12.4-source.zip"
PAYLOAD_FILE = SOURCE_DIR / "bmad-method-6.12.4-codex.zip"
METADATA_FILE = ROOT / "resources" / "bmad" / "source.json"
VERSION = "6.12.4"
COMMIT = "bab9082c3e884e0d72c759bcd1a6d90bcc01be84"
SOURCE_PREFIX = "BMAD-METHOD-6.12.4/"
PAYLOAD_PREFIX = "bmad-method-6.12.4-codex/"
NORMALIZED_INSTALL_TIME = "2026-10-14T21:19:19.000Z"
MAX_FILES = 12000
MAX_EXPANDED_BYTES = 400 * 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def checked_path(value: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise ValueError(f"Unsafe BMAD archive path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"Unsafe BMAD archive path: {value!r}")
    if any(part[-1:] in (".", " ") or any(char in part for char in '<>:"|?*') for part in path.parts):
        raise ValueError(f"Unsupported Windows path in BMAD source: {value!r}")
    if any(re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part, re.IGNORECASE)
           for part in path.parts):
        raise ValueError(f"Reserved Windows path in BMAD source: {value!r}")
    return path.as_posix()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def make_zip(entries: dict[str, bytes], path: Path, prefix: str) -> bytes:
    if not entries or len(entries) > MAX_FILES or sum(map(len, entries.values())) > MAX_EXPANDED_BYTES:
        raise ValueError("BMAD source snapshot exceeds package limits.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", allowZip64=True) as archive:
        for name, content in sorted(entries.items(), key=lambda item: (PurePosixPath(item[0]).suffix.casefold(), item[0].casefold(), item[0])):
            checked = checked_path(name)
            info = zipfile.ZipInfo(prefix + checked, (2024, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            compressor = zipfile.ZIP_DEFLATED if len(content) > 512 else zipfile.ZIP_STORED
            archive.writestr(info, content, compress_type=compressor, compresslevel=9)
    data = output.getvalue()
    atomic_write(path, data)
    return data


def source_entries(path: Path, expected_prefix: str) -> tuple[dict[str, bytes], set[str]]:
    result: dict[str, bytes] = {}
    links: set[str] = set()
    seen: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if not members or len(members) > MAX_FILES:
            raise ValueError("Official BMAD source archive is empty or too large.")
        for member in members:
            name = checked_path(member.filename.rstrip("/"))
            if member.is_dir():
                continue
            if not name.startswith(expected_prefix):
                raise ValueError(f"Official archive escaped its root: {name}")
            key = name[len(expected_prefix):]
            if not key or key in seen:
                raise ValueError(f"Duplicate or empty BMAD archive path: {name}")
            seen.add(key)
            mode = member.external_attr >> 16
            content = archive.read(member)
            if len(content) != member.file_size:
                raise ValueError(f"Truncated BMAD archive member: {name}")
            if mode & 0o170000 == 0o120000:
                target = content.decode("utf-8")
                if not target or PurePosixPath(target).is_absolute() or "\\" in target or "\x00" in target:
                    raise ValueError(f"Unsafe official BMAD source link: {name}")
                stack = list(PurePosixPath(key).parent.parts)
                for part in PurePosixPath(target).parts:
                    if part == "..":
                        if not stack:
                            raise ValueError(f"Official BMAD source link escapes its root: {name}")
                        stack.pop()
                    elif part not in ("", "."):
                        stack.append(part)
                links.add(key)
            result[key] = content
    return result, links


def source_from_checkout(source_root: Path) -> tuple[dict[str, bytes], set[str], bytes]:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-c", f"safe.directory={source_root.resolve()}", "-C", str(source_root), *args],
                                       text=True, encoding="utf-8", stderr=subprocess.PIPE).strip()

    commit = git("rev-parse", "HEAD")
    if commit != COMMIT:
        raise ValueError(f"Expected BMAD commit {COMMIT}, found {commit}.")
    package = json.loads((source_root / "package.json").read_text(encoding="utf-8"))
    if (package.get("name"), package.get("version"), package.get("license")) != ("bmad-method", VERSION, "MIT"):
        raise ValueError("Official BMAD package metadata differs from the pinned release.")
    raw = subprocess.check_output(["git", "-c", f"safe.directory={source_root.resolve()}", "-C", str(source_root),
                                   "archive", "--format=zip", "--prefix=" + SOURCE_PREFIX, "HEAD"])
    temporary = SOURCE_DIR / f".bmad-source-{os.getpid()}.zip"
    try:
        atomic_write(temporary, raw)
        entries, links = source_entries(temporary, SOURCE_PREFIX)
        return entries, links, raw
    finally:
        temporary.unlink(missing_ok=True)


def normalize_manifest(data: bytes) -> bytes:
    text = data.decode("utf-8")
    text = re.sub(r"(?m)^(\s*(?:installDate|lastUpdated):\s*).+$",
                  lambda match: match.group(1) + NORMALIZED_INSTALL_TIME, text)
    return text.encode("utf-8")


def normalize_config(data: bytes) -> bytes:
    text = data.decode("utf-8")
    for key, value in (("project_name", "WorkflowKitProject"),
                       ("communication_language", "Traditional Chinese")):
        pattern = re.compile(r"(?m)^" + re.escape(key) + r"\s*=\s*.+$")
        if len(pattern.findall(text)) != 1:
            raise ValueError(f"BMAD config must contain exactly one {key} assignment.")
        text = pattern.sub(f'{key} = {json.dumps(value, ensure_ascii=False)}', text)
    return text.encode("utf-8")


def rewrite_files_manifest(data: bytes, files: dict[str, bytes]) -> bytes:
    reader = csv.DictReader(io.StringIO(data.decode("utf-8"), newline=""))
    fields = reader.fieldnames
    if fields != ["type", "name", "module", "path", "hash"]:
        raise ValueError("Unknown official BMAD files-manifest schema.")
    rows = list(reader)
    for row in rows:
        packaged_path = "_bmad/" + row["path"]
        if packaged_path in files:
            row["hash"] = digest(files[packaged_path])
    if not any(row["path"] == "config.toml" for row in rows):
        raise ValueError("Official BMAD files-manifest omits the project config.")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def patch_extended_path_imports(files: dict[str, bytes]) -> None:
    bootstrap = r'''if sys.platform == "win32" and str(Path(__file__).resolve().parent).startswith("\\\\?\\"):
    import importlib.util

    _config_utils_spec = importlib.util.spec_from_file_location(
        "config_utils", Path(__file__).resolve().with_name("config_utils.py")
    )
    if _config_utils_spec is None or _config_utils_spec.loader is None:
        raise RuntimeError("BMAD config_utils.py is missing beside this script")
    _config_utils_module = importlib.util.module_from_spec(_config_utils_spec)
    sys.modules["config_utils"] = _config_utils_module
    _config_utils_spec.loader.exec_module(_config_utils_module)
'''
    anchors = {
        "_bmad/scripts/resolve_config.py": "try:\n    from config_utils import ConfigError, load_central_config\n",
        "_bmad/scripts/render_skill.py": "from config_utils import ConfigError, load_central_config, load_customization, load_toml\n",
        "_bmad/scripts/resolve_customization.py": "try:\n    from config_utils import ConfigError, load_customization\n",
    }
    for path, anchor in anchors.items():
        text = files[path].decode("utf-8")
        newline = "\r\n" if "\r\n" in text else "\n"
        anchor = anchor.replace("\n", newline)
        if text.count(anchor) != 1:
            raise ValueError(f"Pinned BMAD script changed its config_utils import: {path}")
        files[path] = text.replace(anchor, bootstrap.replace("\n", newline) + newline + anchor, 1).encode("utf-8")


def install_bmad(source: dict[str, bytes], source_links: set[str], scratch: Path) -> dict[str, bytes]:
    source_root = scratch / "source"
    project_root = scratch / "project"
    source_root.mkdir(parents=True)
    project_root.mkdir(parents=True)
    for name, content in source.items():
        if name in source_links:
            continue
        target = source_root / checked_path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    lockfile = source_root / "package-lock.json"
    if not lockfile.is_file():
        raise ValueError("Pinned official package-lock.json is missing.")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    node = shutil.which("node")
    if not npm or not node:
        raise ValueError("Maintainer source preparation requires Node.js 20.12+ and npm.")
    npm_args = ["ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund"]
    subprocess.run([npm, *npm_args], cwd=source_root, check=True,
                   shell=os.name == "nt", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                   text=True, encoding="utf-8")
    command = [node, "tools/installer/bmad-cli.js", "install", "--directory", str(project_root),
               "--modules", "bmm", "--tools", "codex", "--user-name", "BMad",
               "--communication-language", "Traditional Chinese", "--document-output-language", "Traditional Chinese",
               "--output-folder", "_bmad-output", "--set", "bmm.project_knowledge=wiki", "--yes", "--no-shims"]
    environment = os.environ.copy()
    environment["NO_COLOR"] = "1"
    subprocess.run(command, cwd=source_root, env=environment, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")

    files: dict[str, bytes] = {}
    for relative_root, target_prefix in ((project_root / "_bmad", "_bmad"),
                                         (project_root / ".agents" / "skills", ".agents/skills")):
        if not relative_root.is_dir() or relative_root.is_symlink():
            raise ValueError(f"Official Codex installation omitted {relative_root.name}.")
        for path in sorted(relative_root.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Generated BMAD installation contains a link: {path}")
            if not path.is_file() or "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
                continue
            relative = path.relative_to(project_root).as_posix()
            if relative in {"_bmad/config.user.toml", "_bmad/custom/config.toml", "_bmad/custom/config.user.toml"}:
                continue
            files[checked_path(relative)] = path.read_bytes()
    license_files = {"LICENSE": "_bmad/_licenses/LICENSE", "TRADEMARK.md": "_bmad/_licenses/TRADEMARK.md"}
    for source_name, destination in license_files.items():
        if source_name not in source:
            raise ValueError(f"Pinned BMAD release omits {source_name}.")
        files[destination] = source[source_name]

    config_path = "_bmad/config.toml"
    metadata_path = "_bmad/_config/manifest.yaml"
    files[config_path] = normalize_config(files[config_path])
    files[metadata_path] = normalize_manifest(files[metadata_path])
    patch_extended_path_imports(files)
    files["_bmad/_config/files-manifest.csv"] = rewrite_files_manifest(
        files["_bmad/_config/files-manifest.csv"], files)
    if "_bmad/_config/bmad-help.csv" not in files:
        raise ValueError("Official BMAD Codex installation omitted its help catalog.")
    skill_names = {PurePosixPath(name).parts[2] for name in files
                   if name.startswith(".agents/skills/") and len(PurePosixPath(name).parts) > 3}
    if len(skill_names) != 29 or not {"bmad-help", "bmad-build", "bmad-project-context"}.issubset(skill_names):
        raise ValueError(f"Expected the 29 non-shim BMAD Core+BMM skills; found {len(skill_names)}.")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT,
                        help="Clean BMAD-METHOD v6.12.4 checkout at the pinned commit")
    args = parser.parse_args()
    try:
        source, source_links, source_archive = source_from_checkout(args.source_root.resolve())
        scratch_root = ROOT / ".tmp"
        scratch_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="bmad-method-source-", dir=scratch_root) as temporary:
            payload = install_bmad(source, source_links, Path(temporary))
        SOURCE_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write(SOURCE_FILE, source_archive)
        payload_archive = make_zip(payload, PAYLOAD_FILE, PAYLOAD_PREFIX)
        hashes = {name: digest(content) for name, content in sorted(source.items())}
        payload_hashes = {name: digest(content) for name, content in sorted(payload.items())}
        source_tree_digest = digest(canonical_json(hashes))
        payload_tree_digest = digest(canonical_json(payload_hashes))
        metadata = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
        if metadata.get("commit") != COMMIT or metadata.get("version") != VERSION:
            raise ValueError("Existing BMAD provenance metadata differs from the pinned release.")
        metadata.update({
            "sourceKind": "official-git-archive",
            "officialArchive": SOURCE_FILE.name,
            "officialArchiveSha256": digest(source_archive),
            "sourceTreeSha256": source_tree_digest,
            "sourceFileCount": len(hashes),
            "sourceSymlinks": sorted(source_links),
            "lockfileSha256": digest(source["package-lock.json"]),
            "codexArchive": PAYLOAD_FILE.name,
            "codexArchiveSha256": digest(payload_archive),
            "codexTreeSha256": payload_tree_digest,
            "codexFileCount": len(payload_hashes),
            "skillCount": 29,
            "normalization": "workflowkit-bmad-codex/v2",
            "compatibilityPatches": ["windows-extended-path-config-utils/v1"],
            "normalizedInstallTime": NORMALIZED_INSTALL_TIME,
            "defaultKnowledgeRoot": "wiki",
            "defaultCommunicationLanguage": "Traditional Chinese",
            "defaultDocumentLanguage": "Traditional Chinese",
        })
        atomic_write(METADATA_FILE, (json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
        print(json.dumps({"ok": True, "sourceFiles": len(hashes), "sourceSha256": digest(source_archive),
                          "codexFiles": len(payload_hashes), "codexSha256": digest(payload_archive),
                          "skills": len({PurePosixPath(name).parts[2] for name in payload if name.startswith(".agents/skills/")})},
                         ensure_ascii=False))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
