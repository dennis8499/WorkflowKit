"""Export the installer's read-only status dependency closure for the Extension."""
import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render(installer: Path) -> str:
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
    body.append('''def run():
    parser = argparse.ArgumentParser(description="Verify WorkflowKit installations without modifying them")
    parser.add_argument("action", choices=("status",))
    parser.add_argument("group_root", type=Path)
    parser.add_argument("--expected-version", default=VERSION)
    args = parser.parse_args()
    print(json.dumps(inspect_status(args.group_root, args.expected_version), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())''')
    return '\n\n'.join(body) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/workflow-kit-status.py')
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(ROOT / 'resources/workflow-kit-installer.py'), encoding='utf-8', newline='\n')
    print(args.output)
