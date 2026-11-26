"""Export the installer's read-only status dependency closure for the Extension."""
import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render_with_support(installer: Path) -> tuple[str, dict]:
    source = installer.read_text(encoding='utf-8')
    tree = ast.parse(source)
    definitions = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            definitions[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    definitions[target.id] = node
    names = {'inspect_status', 'VERSION'}
    pending = list(names)
    while pending:
        node = definitions.get(pending.pop())
        if node is None:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and child.id in definitions and child.id not in names:
                names.add(child.id)
                pending.append(child.id)
    selected = {id(definitions[name]) for name in names if name in definitions}
    body = ['"""Generated from the verified WorkflowKit installer; status CLI only."""']
    body.extend(ast.get_source_segment(source, node) for node in tree.body
                if isinstance(node, (ast.Import, ast.ImportFrom)) or id(node) in selected)
    body.append('''def inspect_cached_status(root_value, expected_version, installer, size, sha256):
    try:
        if not installer.is_absolute() or not 0 < size <= 16 * 1024 * 1024 or not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise ValueError("快取的 WorkflowKit 檢查器資訊無效。")
        info = installer.lstat()
        if not stat.S_ISREG(info.st_mode) or _is_reparse_point(installer, info) or info.st_size != size:
            raise ValueError("快取的 WorkflowKit 檢查器檔案或大小不符。")
        with installer.open("rb") as stream:
            code = stream.read(size + 1)
        if len(code) != size or digest(code) != sha256:
            raise ValueError("快取的 WorkflowKit 檢查器摘要不符。")

        root = checked_root(root_value)
        scope = {"__name__": "workflowkit_cached_installer", "__file__": str(installer)}
        exec(compile(code, str(installer), "exec", dont_inherit=True), scope)
        inspect = scope.get("inspect_status")
        if scope.get("VERSION") != expected_version or not callable(inspect):
            raise ValueError("快取的 WorkflowKit 檢查器版本或唯讀入口不符。")

        marker = root / MARKER
        observed = set()
        read = scope.get("read_regular")
        if callable(read):
            def capture(file, *args, **kwargs):
                content = read(file, *args, **kwargs)
                if file == marker:
                    observed.add(digest(content))
                return content
            scope["read_regular"] = capture

        status = inspect(root, expected_version)
        if not isinstance(status, dict):
            raise ValueError("WorkflowKit 狀態回應無效。")
        if status.get("ok") is True and status.get("status") in ("installed", "update-available"):
            if status.get("statusContract") != 1 or status.get("integrity") != "verified":
                raise ValueError("快取的 WorkflowKit 檢查器未確認安裝驗證。")
            if "installedManifestSha256" not in status:
                if len(observed) != 1:
                    raise ValueError("無法確認舊版檢查器驗證的 WorkflowKit 安裝紀錄。")
                status = {**status, "installedManifestSha256": next(iter(observed))}
            else:
                marker_sha = status["installedManifestSha256"]
                if not isinstance(marker_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", marker_sha) or (observed and observed != {marker_sha}):
                    raise ValueError("WorkflowKit 檢查器回傳的安裝紀錄摘要不符。")
        return status
    except (KitError, OSError, ValueError, TypeError, SyntaxError) as error:
        return {"ok": True, "status": "error", "statusContract": 1, "integrity": "unverified", "message": str(error)}


def run():
    parser = argparse.ArgumentParser(description="Verify WorkflowKit installations without modifying them")
    parser.add_argument("action", choices=("status",))
    parser.add_argument("group_root", type=Path)
    parser.add_argument("--expected-version", default=VERSION)
    parser.add_argument("--cached-installer", type=Path)
    parser.add_argument("--cached-installer-size", type=int)
    parser.add_argument("--cached-installer-sha256")
    args = parser.parse_args()
    cached = (args.cached_installer, args.cached_installer_size, args.cached_installer_sha256)
    if all(item is None for item in cached):
        status = inspect_status(args.group_root, args.expected_version)
    elif any(item is None for item in cached):
        parser.error("The cached installer requires its path, size and SHA-256.")
    else:
        status = inspect_cached_status(args.group_root, args.expected_version, *cached)
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())''')
    version = ast.literal_eval(definitions['VERSION'].value)
    predecessors = ast.literal_eval(definitions['TRUSTED_PREDECESSORS'].value)
    support = {'schema': 'WorkflowKitStatusSupport/v1', 'version': version,
               'versions': sorted({version, *(row['version'] for row in predecessors['packages'])})}
    return '\n\n'.join(body) + '\n', support


def render(installer: Path) -> str:
    return render_with_support(installer)[0]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/workflow-kit-status.py')
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    script, support = render_with_support(ROOT / 'resources/workflow-kit-installer.py')
    args.output.write_text(script, encoding='utf-8', newline='\n')
    args.output.with_suffix('.json').write_text(json.dumps(support, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(args.output)
