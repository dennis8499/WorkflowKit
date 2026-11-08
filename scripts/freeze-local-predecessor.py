"""Freeze a local predecessor only when its ZIP and installer match committed HEAD."""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def freeze(version):
    def committed(name):
        return subprocess.check_output(["git", "show", "HEAD:" + name], cwd=ROOT)

    if committed("VERSION").decode().strip() != version:
        raise ValueError("Predecessor must be the exact committed HEAD version")
    installer = committed("resources/workflow-kit-installer.py")
    constants = {}
    for node in ast.parse(installer.decode("utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("PROFILE_MANIFESTS", "UPSTREAM"):
                constants[node.targets[0].id] = ast.literal_eval(node.value)
    archive = ROOT / "dist" / f"gitlab-workspace-kit-{version}.zip"
    with zipfile.ZipFile(archive) as stream:
        manifest = json.loads(stream.read("workflow-kit/manifest.json"))
        if stream.read("workflow-kit/install.py") != installer or manifest["profiles"] != constants["PROFILE_MANIFESTS"]:
            raise ValueError("Local predecessor archive differs from committed installer identity")
        for profile_name, prefix in (("group", "payload/"), ("repository", "repository-payload/")):
            import hashlib
            files = {name.removeprefix("workflow-kit/" + prefix): hashlib.sha256(stream.read(name)).hexdigest()
                     for name in stream.namelist() if name.startswith("workflow-kit/" + prefix) and not name.endswith("/")}
            if files != manifest["profiles"][profile_name]["files"]:
                raise ValueError("Predecessor bytes differ from committed profile")
    spec = importlib.util.spec_from_file_location("kit_local_predecessor_manager", ROOT / "scripts/release_manager.py")
    manager = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = manager
    spec.loader.exec_module(manager)
    manager.freeze_predecessor(ROOT, version, subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
                               {archive.name: archive.read_bytes()}, installer)
    print(json.dumps({"version": version, "source": "committed-local-head", "profiles": 4}))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    freeze(parser.parse_args().version)
