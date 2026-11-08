#!/usr/bin/env python3
"""Run WorkflowKit Skill helpers with temp and package caches in a writable root."""
from __future__ import annotations

import os
from pathlib import Path
import contextlib
import stat
import subprocess
import sys
import uuid


class RuntimePathError(OSError):
    """The selected WorkflowKit runtime is not safe and writable."""


def _split_arguments(argv: list[str]) -> tuple[Path | None, list[str]]:
    try:
        separator = argv.index("--")
    except ValueError as error:
        raise ValueError("Usage: run.py [--runtime-root PATH] -- COMMAND [ARG ...]") from error
    options, command = argv[:separator], argv[separator + 1 :]
    if not command:
        raise ValueError("A command must follow `--`.")
    runtime = None
    index = 0
    while index < len(options):
        option = options[index]
        if option == "--runtime-root" and index + 1 < len(options):
            if runtime is not None:
                raise ValueError("Specify --runtime-root only once.")
            if not options[index + 1].strip():
                raise ValueError("--runtime-root must name a writable directory.")
            runtime = Path(options[index + 1])
            index += 2
        elif option.startswith("--runtime-root="):
            if runtime is not None:
                raise ValueError("Specify --runtime-root only once.")
            value = option.partition("=")[2]
            if not value.strip():
                raise ValueError("--runtime-root must name a writable directory.")
            runtime = Path(value)
            index += 1
        else:
            raise ValueError(f"Unknown runner option: {option}")
    return runtime, command


def _is_reparse_point(path: Path) -> bool:
    try:
        information = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(information.st_mode):
        return True
    attributes = getattr(information, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _check_plain_parents(path: Path) -> None:
    probe = path
    while probe != probe.parent:
        if _is_reparse_point(probe):
            raise RuntimePathError(f"runtime path contains a symlink or junction: {probe}")
        probe = probe.parent


def _check_writable_directory(path: Path) -> Path:
    _check_plain_parents(path)
    path.mkdir(parents=True, exist_ok=True)
    _check_plain_parents(path)
    if not path.is_dir():
        raise RuntimePathError(f"runtime path is not a directory: {path}")
    resolved = path.resolve(strict=True)
    if not os.path.samefile(path, resolved):
        raise RuntimePathError(f"runtime path does not resolve to itself: {path}")
    source = path / f".workflow-kit-probe-{uuid.uuid4().hex}"
    destination = path / f".workflow-kit-probe-{uuid.uuid4().hex}"
    try:
        with source.open("xb") as stream:
            stream.write(b"WorkflowKit writable runtime probe\n")
        os.replace(source, destination)
        if destination.read_bytes() != b"WorkflowKit writable runtime probe\n":
            raise RuntimePathError(f"runtime write probe did not preserve its contents: {path}")
    finally:
        with contextlib.suppress(OSError):
            source.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            destination.unlink(missing_ok=True)
    return resolved


def _session_runtime(command: list[str]) -> Path | None:
    """Give Reviewer caches a stable sibling that never enters their owned runtime."""
    script_index = next(
        (index for index, argument in enumerate(command)
         if Path(argument).name.casefold() == "review_session.py"),
        None,
    )
    if script_index is None:
        return None
    for index, argument in enumerate(command[script_index + 1 :], script_index + 1):
        if argument == "--runtime-root" and index + 1 < len(command):
            session_root = Path(command[index + 1]).expanduser()
            return session_root.with_name(session_root.name + "-workflow-kit")
        if argument.startswith("--runtime-root="):
            session_root = Path(argument.partition("=")[2]).expanduser()
            return session_root.with_name(session_root.name + "-workflow-kit")
    return None


def runtime_paths(install_root: Path, requested: Path | None, command: list[str]) -> tuple[Path, Path]:
    if requested is not None:
        root = requested.expanduser()
    else:
        root = _session_runtime(command) or install_root / ".gitlab-workspace" / "runtime"
    if not root.is_absolute():
        root = Path.cwd() / root
    root = Path(os.path.abspath(root))
    runtime = _check_writable_directory(root)
    temporary = _check_writable_directory(root / "tmp")
    cache = _check_writable_directory(root / "uv-cache")
    return temporary, cache


def child_environment(temporary: Path, cache: Path, command: list[str]) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        TEMP=str(temporary),
        TMP=str(temporary),
        TMPDIR=str(temporary),
        UV_CACHE_DIR=str(cache),
        PYTHONDONTWRITEBYTECODE="1",
        WORKFLOW_KIT_SYNTAX_RUNTIME=str(temporary.parent / "syntax-context"),
    )
    if Path(command[0]).name.casefold() in {"uv", "uv.exe"}:
        environment.update(
            UV_NO_PROJECT="1",
            UV_PYTHON=sys.executable,
            UV_PYTHON_DOWNLOADS="never",
        )
    return environment


def main(argv: list[str] | None = None) -> int:
    try:
        requested, command = _split_arguments(list(sys.argv[1:] if argv is None else argv))
        # run.py is installed under <workspace>/.agents/gitlab-workspace-kit/.
        install_root = Path(__file__).resolve().parents[2]
        temporary, cache = runtime_paths(install_root, requested, command)
    except (OSError, ValueError) as error:
        detail = str(error)
        if isinstance(error, OSError) and getattr(error, "winerror", None) == 5:
            detail = f"access denied (WinError 5): {detail}"
        sys.stderr.write(
            "WorkflowKit runner could not prepare a writable runtime. "
            f"{detail}. Choose a writable --runtime-root and invoke the command again.\n"
        )
        return 2
    try:
        return subprocess.run(command, env=child_environment(temporary, cache, command), check=False).returncode
    except OSError as error:
        sys.stderr.write(f"WorkflowKit runner could not launch child command {command[0]!r}: {error}\n")
        return 127 if isinstance(error, FileNotFoundError) else 126


if __name__ == "__main__":
    raise SystemExit(main())
