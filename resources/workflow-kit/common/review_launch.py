"""Validate an installed Reviewer binding and launch its fixed request as argv."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time


SHA = re.compile(r"[a-f0-9]{64}")
ACTIONS = ("start", "status", "view", "check", "finish", "cancel", "preflight", "schema")
TOOLS = {"merge-reviewer": "compact", "release-reviewer": "v3"}
VIEW_OPTIONS = {"--artifact", "--artifact-scope", "--pointer", "--offset", "--page-size",
                "--string-offset", "--requests-file"}
SKIP = {"__pycache__", ".pytest_cache", ".git"}


def plain(value: str | Path, *, file: bool = False) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("Review launch paths must be non-empty path strings.")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("Review launch paths must be absolute.")
    path = Path(os.path.abspath(path))
    for parent in (path, *path.parents):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Review launch paths must not contain links or junctions.")
    if file and not path.is_file():
        raise ValueError(f"Expected an installed ordinary file: {path}")
    return path


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_object(path: Path, *, maximum: int = 256 * 1024) -> dict:
    path = plain(path, file=True)
    if path.stat().st_size > maximum:
        raise ValueError("Review launch metadata exceeds the size limit.")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Expected a review launch JSON object.")
    return value


def payload(directory: Path) -> list[list[str]]:
    rows = []
    for root, dirs, names in os.walk(directory, followlinks=False):
        dirs[:] = [name for name in dirs if name not in SKIP]
        for name in dirs:
            plain(Path(root) / name)
        for name in names:
            if name.endswith(".pyc") or name in SKIP:
                continue
            path = plain(Path(root) / name, file=True)
            rows.append([path.relative_to(directory).as_posix(), sha(path.read_bytes())])
    rows.sort(key=lambda row: row[0].encode("utf-8"))
    return rows


def verify_managed_directory(directory: Path, install_root: Path, files: dict) -> None:
    prefix = directory.relative_to(install_root).as_posix() + "/"
    actual = {prefix + name: digest for name, digest in payload(directory)}
    expected = {name: digest for name, digest in files.items() if name.startswith(prefix)}
    if actual != expected:
        raise ValueError("Installed helper payload differs from the managed manifest.")


def verify_binding(binding: dict, runner: Path) -> Path:
    if not isinstance(binding, dict) or binding.get("schema") != "InstalledReviewerBinding/v1" or binding.get("tool") not in tuple(TOOLS):
        raise ValueError("Review launch needs an installed Reviewer binding.")
    tool = binding["tool"]
    script = plain(binding.get("script_path", ""), file=True)
    directory = script.parent.parent
    if script.name != "review_session.py" or script.parent.name != "scripts" or directory.name != tool:
        raise ValueError("Reviewer entrypoint does not match the bound tool.")
    install_root = runner.parent.parent.parent
    if directory != install_root / ".agents" / "skills" / tool:
        raise ValueError("Reviewer and runner must belong to the same installation.")
    skill = plain(directory / "SKILL.md", file=True)
    version = plain(directory / "VERSION", file=True).read_text(encoding="utf-8").strip()
    if version != binding.get("version"):
        raise ValueError("Installed Reviewer version changed; recreate the launch request.")
    rows = payload(directory)
    actual = {"script_sha256": sha(script.read_bytes()), "skill_sha256": sha(skill.read_bytes()),
              "payload_sha256": sha(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
              "payload_files": len(rows)}
    if any(binding.get(key) != value for key, value in actual.items()):
        raise ValueError("Installed Reviewer payload changed; recreate the launch request.")
    wrapper = binding.get("workflow_kit_runner", {})
    if (not isinstance(wrapper, dict) or plain(wrapper.get("script_path", ""), file=True) != runner
            or wrapper.get("script_sha256") != sha(runner.read_bytes())
            or wrapper.get("review_launch_sha256") != sha(plain(Path(__file__).absolute(), file=True).read_bytes())
            or wrapper.get("review_launch_request") != 1 or wrapper.get("read_only_inspection") is not True):
        raise ValueError("WorkflowKit runner binding changed or lacks review launch support.")
    if tool == "release-reviewer":
        supported = wrapper.get("review_launch_tools")
        if not isinstance(supported, list) or tool not in supported:
            raise ValueError("WorkflowKit runner binding lacks Release Reviewer launch support.")
    return script


def load_request(path: str, expected: str, runner: Path, *, timings: dict | None = None) -> tuple[dict, Path]:
    started = time.perf_counter()
    source = plain(path, file=True)
    with source.open("rb") as stream:
        raw = stream.read(256 * 1024 + 1)
    if not isinstance(expected, str) or not SHA.fullmatch(expected) or len(raw) > 256 * 1024 or sha(raw) != expected:
        raise ValueError("Review launch request SHA-256 differs; use the original request file.")
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Expected a review launch JSON object.")
    allowed = {"schema", "tool", "request_id", "workspace", "project", "base", "head", "runtime_root",
               "workspace_file", "auth_scope", "binding", "draft_format", "refresh", "no_fetch"}
    if set(value) - allowed:
        raise ValueError("Review launch request contains unsupported fields.")
    tool = value.get("tool")
    if value.get("schema") != "ReviewLaunchRequest/v1" or not isinstance(tool, str) or tool not in TOOLS:
        raise ValueError("Unsupported review launch request schema or tool.")
    if not isinstance(value.get("request_id"), str) or not re.fullmatch(r"[a-f0-9]{32}", value["request_id"]):
        raise ValueError("Review launch request_id must be 32 lowercase hexadecimal characters.")
    for key in ("workspace", "project", "runtime_root"):
        if not isinstance(value.get(key), str):
            raise ValueError(f"Review launch requires {key}.")
        plain(value[key])
    for key in ("base", "head"):
        if not isinstance(value.get(key), str) or not value[key].strip() or "\0" in value[key]:
            raise ValueError(f"Review launch requires {key}.")
    if value.get("draft_format") != TOOLS[tool] or tool == "release-reviewer" and "no_fetch" in value:
        raise ValueError("Review launch options do not match the native Reviewer.")
    if "workspace_file" in value:
        plain(value["workspace_file"])
    if "auth_scope" in value and (not isinstance(value["auth_scope"], str) or not value["auth_scope"].strip()):
        raise ValueError("Review launch auth_scope must be non-empty text.")
    for key in ("refresh", "no_fetch"):
        if key in value and not isinstance(value[key], bool):
            raise ValueError(f"Review launch {key} must be boolean.")
    if timings is not None:
        timings["request_seconds"] = time.perf_counter() - started
    started = time.perf_counter()
    binding = value.get("binding")
    if not isinstance(binding, dict) or binding.get("tool") != tool:
        raise ValueError("Review launch tool must match its installed binding.")
    script = verify_binding(binding, runner)
    if timings is not None:
        timings["binding_seconds"] = time.perf_counter() - started
    return value, script


def readonly_environment() -> dict[str, str]:
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def capabilities(command: list[str], tool: str = "merge-reviewer") -> dict:
    result = subprocess.run(command + ["capabilities"], env=readonly_environment(), capture_output=True,
                            text=True, encoding="utf-8", check=False, timeout=30)
    if result.returncode:
        raise ValueError("Installed Reviewer capabilities could not be read.")
    value = json.loads(result.stdout)
    schema = "MergeReviewCapabilities/v1" if tool == "merge-reviewer" else "ReviewCapabilities/v1"
    if (not isinstance(value, dict) or value.get("schema") != schema
            or tool == "release-reviewer" and value.get("tool") != tool):
        raise ValueError("Installed Reviewer capabilities are not supported.")
    return value


def installed_capabilities(script: Path) -> dict | None:
    """Read only an already authenticated payload, never a mutable runtime cache."""
    path = script.parent.parent / "capabilities.json"
    if not path.exists():
        return None  # Historical installations keep their subprocess discovery.
    value = read_object(path)
    if (set(value) != {"schema", "protocol_version", "draft_formats", "features"}
            or value.get("schema") != "MergeReviewCapabilities/v1"
            or type(value.get("protocol_version")) is not int or value["protocol_version"] != 1
            or not isinstance(value.get("draft_formats"), list)
            or not all(isinstance(item, str) for item in value["draft_formats"])
            or not isinstance(value.get("features"), dict)
            or value["features"].get("capability_manifest") is not True):
        raise ValueError("Installed Reviewer capability manifest is invalid.")
    digest = hashlib.sha256()
    for helper in sorted(script.parent.glob("*.py"), key=lambda item: item.name):
        helper = plain(helper, file=True)
        digest.update(helper.name.encode("utf-8") + b"\0" + hashlib.sha256(helper.read_bytes()).digest())
    return {**value, "skill_version": plain(script.parent.parent / "VERSION", file=True).read_text(encoding="utf-8").strip(),
            "helper_sha256": digest.hexdigest(), "python_version": sys.version.split()[0],
            "python_executable": str(Path(sys.executable).resolve()),
            "capabilities_sha256": sha(path.read_bytes())}


def require_features(caps: dict, names: tuple[str, ...]) -> None:
    features = caps.get("features")
    if not isinstance(features, dict) or any(features.get(name) is not True for name in names):
        raise ValueError("Installed Reviewer lacks the required launch/inspection capabilities.")


def view_arguments(arguments: list[str]) -> list[str]:
    if len(arguments) % 2:
        raise ValueError("View accepts documented option/value pairs only.")
    seen = set()
    for index in range(0, len(arguments), 2):
        key, value = arguments[index:index + 2]
        if key not in VIEW_OPTIONS or key in seen or "\0" in value:
            raise ValueError("View arguments cannot override launch identity or execution mode.")
        seen.add(key)
    if ("--artifact" in seen) == ("--requests-file" in seen):
        raise ValueError("View needs exactly one artifact or requests-file.")
    return arguments


def schema_arguments(arguments: list[str]) -> list[str]:
    """Schema inspection has no session overrides or executable command input."""
    if arguments and (len(arguments) != 2 or arguments[0] != "--operation"
                      or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", arguments[1])):
        raise ValueError("Schema accepts only --operation with an operation identifier.")
    return arguments


def launch(argv: list[str], runner: Path, prepare_runtime, child_environment) -> int:
    started = time.perf_counter()
    timings = {}
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--review-request", required=True)
    parser.add_argument("--expected-request-sha256", required=True)
    parser.add_argument("--action", choices=ACTIONS, required=True)
    options, extra = (argv[:argv.index("--")], argv[argv.index("--") + 1:]) if "--" in argv else (argv, [])
    args = parser.parse_args(options)
    request, script = load_request(args.review_request, args.expected_request_sha256, runner, timings=timings)
    tool = request["tool"]
    merge = tool == "merge-reviewer"
    command = [sys.executable, "-X", "utf8", "-B", str(script)]
    phase_started = time.perf_counter()
    caps = installed_capabilities(script)
    capabilities_source = "verified-manifest" if caps is not None else "subprocess"
    if caps is None:
        caps = capabilities(command, tool) if not merge else capabilities(command)
    timings["capabilities_seconds"] = time.perf_counter() - phase_started
    require_features(caps, ("launch_preflight", "read_only_inspection"))
    if merge and "compact" not in caps.get("draft_formats", []):
        raise ValueError("Installed Reviewer does not support compact drafts.")
    if not merge and caps.get("prepare_evidence") is not True:
        raise ValueError("Installed Release Reviewer lacks prepared capture support.")
    if extra and args.action not in ("view", "schema"):
        raise ValueError("Only view or schema accepts documented inspection arguments; review identity is fixed.")
    if args.action == "schema":
        require_features(caps, ("operation_schema",))
        schema_arguments(extra)

    def completed(code):
        timings["total_seconds"] = time.perf_counter() - started
        print(json.dumps({"schema": "ReviewLaunchMetrics/v1", "action": args.action,
                          "returncode": code, "timings": timings,
                          "capabilities_source": capabilities_source}, separators=(",", ":")),
              file=sys.stderr, flush=True)
        return code
    identity = ["--runtime-root", request["runtime_root"], "--request-id", request["request_id"]]
    initial = identity + ["--workspace", request["workspace"], "--project", request["project"],
                          "--base", request["base"], "--head", request["head"]]
    if merge:
        initial += ["--draft-format", request["draft_format"]]
    for key in ("workspace_file", "auth_scope"):
        if key in request:
            initial += ["--" + key.replace("_", "-"), request[key]]
    for key in ("refresh", "no_fetch"):
        if request.get(key):
            initial += ["--" + key.replace("_", "-")]
    job = plain(Path(request["runtime_root"]) / "jobs" / (request["request_id"] + ".json"))
    # Existing sessions validate their saved input digest in native start. Live
    # preflight must not turn a recoverable fixed snapshot into a fresh capture.
    if args.action == "start" and not job.exists():
        phase_started = time.perf_counter()
        inspected = subprocess.run(command + ["preflight"] + initial, env=readonly_environment(),
                                   capture_output=True, text=True, encoding="utf-8", check=False)
        timings["preflight_seconds"] = time.perf_counter() - phase_started
        if inspected.returncode:
            sys.stdout.write(inspected.stdout)
            sys.stderr.write(inspected.stderr)
            return completed(inspected.returncode)
        outcome = json.loads(inspected.stdout)
        expected_schema = "MergeReviewPreflight/v1" if merge else "ReleaseReviewPreflight/v1"
        if outcome.get("schema") != expected_schema or outcome.get("valid") is not True:
            raise ValueError("Native preflight did not validate the fixed launch inputs.")
    arguments = initial if args.action in ("start", "preflight") else identity
    if args.action == "start" and not merge:
        arguments += ["--prepare-evidence"]
    elif args.action == "status":
        arguments += ["--summary"]
    elif args.action == "view":
        options = view_arguments(extra)
        if not merge and "--artifact-scope" in options[::2]:
            raise ValueError("Release Reviewer views use the request's owned evidence context.")
        arguments += (["--read-only"] if merge else []) + options
    elif args.action == "schema":
        arguments = schema_arguments(extra)
    command += [args.action] + arguments
    if args.action in ("status", "view", "preflight", "schema"):
        environment = readonly_environment()
    else:
        temporary, cache = prepare_runtime(runner.parent.parent.parent, None, command)
        environment = child_environment(temporary, cache, command)
    phase_started = time.perf_counter()
    result = subprocess.run(command, env=environment, check=False)
    timings["child_seconds"] = time.perf_counter() - phase_started
    return completed(result.returncode)


def trusted_readonly(command: list[str], runner: Path, marker: dict) -> list[str]:
    """Allow only installed Python inspection helpers with authenticated files."""
    # Preserve Python launcher flags, but reject -c/-m and any foreign executable.
    executable = shutil.which(command[0]) if command else None
    if not executable or Path(executable).resolve() != Path(sys.executable).resolve():
        raise ValueError("Read-only runner requires the current Python executable.")
    index = 1
    while index < len(command) and command[index] in ("-X", "-B", "-I", "-u"):
        if command[index] == "-X":
            if command[index:index + 2] != ["-X", "utf8"]:
                raise ValueError("Read-only runner accepts only -X utf8.")
            index += 2
        else:
            index += 1
    if index >= len(command):
        raise ValueError("Read-only runner requires an installed helper.")
    script = Path(command[index])
    if not script.is_absolute():
        script = Path.cwd() / script
    script = plain(script, file=True)
    install_root = runner.parent.parent.parent
    files = marker.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("Installed manifest requires a managed file map.")
    try:
        relative = script.relative_to(install_root).as_posix()
    except ValueError as error:
        raise ValueError("Read-only helper is outside this installation.") from error
    if files.get(relative) != sha(script.read_bytes()):
        raise ValueError("Read-only helper differs from its installed manifest.")
    helper_args = command[index + 1:]
    if script == install_root / ".agents" / "skills" / "model-routing" / "scripts" / "routing.py":
        directory = script.parent.parent
        verify_managed_directory(directory, install_root, files)
        if len(helper_args) != 7 or helper_args[0] != "status":
            raise ValueError("Read-only routing accepts status with tool, runtime-root and request-id.")
        keys = helper_args[1::2]
        if len(set(keys)) != 3 or set(keys) != {"--tool", "--runtime-root", "--request-id"}:
            raise ValueError("Read-only routing options do not match status.")
        return command
    tool = script.parent.parent.name
    if tool in TOOLS and script == install_root / ".agents" / "skills" / tool / "scripts" / "review_session.py":
        # Verify imported native code as well as the small CLI entrypoint.
        directory = script.parent.parent
        verify_managed_directory(directory, install_root, files)
        if not helper_args:
            raise ValueError("Read-only runner requires an inspection command.")
        action = helper_args[0]
        if tool == "release-reviewer":
            options = helper_args[1:]
            if action in set(ACTIONS) | {"step", "capabilities", "cleanup"} and options == ["--help"]:
                return command
            if action == "capabilities":
                allowed = {"--workspace", "--runtime-root", "--expected-payload-sha256"}
            elif action == "status" and options.count("--summary") == 1:
                allowed = {"--workspace", "--runtime-root", "--request-id", "--summary"}
            elif action == "view":
                allowed = VIEW_OPTIONS - {"--artifact-scope"} | {"--workspace", "--runtime-root", "--request-id"}
            else:
                raise ValueError("Read-only Release Reviewer accepts capabilities, status --summary, or view.")
            return checked_inspection_options(command, options, allowed)
        caps = installed_capabilities(script)
        if caps is None:
            caps = capabilities(command[:index] + [str(script)])
        require_features(caps, ("read_only_inspection",))
        if action == "capabilities" and (len(helper_args) == 1 or
                len(helper_args) == 3 and helper_args[1] == "--workspace" and helper_args[2]):
            return command
        options = helper_args[1:]
        if action == "--help" and not options:
            return command
        if action in set(ACTIONS) | {"step", "capabilities", "cleanup"} and options == ["--help"]:
            return command
        if action == "schema":
            require_features(caps, ("operation_schema",))
            schema_arguments(options)
            return command
        if action == "preflight":
            allowed = {"--workspace", "--project", "--base", "--head", "--workspace-file",
                       "--runtime-root", "--request-id", "--auth-scope", "--draft-format", "--git-timeout",
                       "--no-fetch", "--refresh"}
        elif action == "status" and options.count("--summary") == 1 and "--artifact" not in options:
            allowed = {"--runtime-root", "--request-id", "--workspace", "--summary"}
        elif action == "view" and options.count("--read-only") == 1:
            allowed = VIEW_OPTIONS | {"--runtime-root", "--request-id", "--workspace", "--read-only"}
        else:
            raise ValueError("Read-only runner accepts capabilities, command --help, schema, preflight, status --summary, or view --read-only.")
        return checked_inspection_options(command, options, allowed)
    raise ValueError("This installed helper has no supported read-only inspection contract.")


def checked_inspection_options(command, options, allowed):
    seen = set()
    offset = 0
    while offset < len(options):
        option = options[offset]
        if option not in allowed or option in seen:
            raise ValueError("Unsupported or duplicate read-only helper option.")
        seen.add(option)
        offset += 1 if option in ("--read-only", "--summary", "--no-fetch", "--refresh") else 2
        if offset > len(options):
            raise ValueError("Read-only helper option needs a value.")
    return command
