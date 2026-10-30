"""Freeze reviewed local sources, or check them without writing any files."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import io
import json
import pprint
import subprocess
import sys
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / 'resources/offline-tools/source-snapshots.json'
REPOS = {'codebase-wiki': 'code-base-llm-wiki',
         'merge-reviewer': 'MergeReviewer', 'release-reviewer': 'ReleaseReviewer',
         'bmad-method': 'BMAD-METHOD'}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_source_text(tool: str, name: str, data: bytes) -> bytes:
    """Normalize checkout line endings except for hash-pinned bundled files."""
    if tool == 'codebase-wiki' and (
        name.startswith('.agents/skills/codebase-wiki/vendor/archify/')
        or name == '.agents/skills/codebase-wiki/vendor/archify-manifest.json'
    ):
        return data
    is_text = Path(name).suffix.lower() in ('.md', '.py', '.yaml', '.yml', '.json', '.txt', '.toml') or Path(name).name == 'VERSION'
    return data.replace(b'\r\n', b'\n') if is_text else data


def archive_root(tool: str, version: str, pin: dict) -> str:
    """Keep the Wiki archive root in step with its upstream version."""
    if tool == 'codebase-wiki':
        return f'codebase-llm-wiki-codex-{version}'
    return pin.get('root', '')


def builder_capabilities(tree: ast.Module) -> list[str]:
    assignment = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'capabilities' for target in node.targets))
    return sorted(ast.literal_eval(assignment.value.args[0]))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def local_entries(tool: str) -> tuple[str, dict[str, bytes]]:
    if tool == 'bmad-method':
        metadata = json.loads((ROOT / 'resources/bmad/source.json').read_text(encoding='utf-8'))
        candidates = (ROOT.parent / REPOS[tool], ROOT / '.tmp' / f"bmad-method-v{metadata['version']}")
        repo = next((candidate for candidate in candidates if candidate.is_dir()), None)
        if repo is None:
            raise ValueError(f'Missing local source: {candidates[0]}')
        info = git_info(repo)
        if info['commit'] != metadata['commit'] or info['dirty']:
            raise ValueError('Pinned BMAD source checkout must match its official commit and have no tracked edits')
        source_archive_path = ROOT / 'resources/offline-tools/sources' / metadata['officialArchive']
        if digest(source_archive_path.read_bytes()) != metadata['officialArchiveSha256']:
            raise ValueError('Official BMAD source archive SHA-256 differs from provenance metadata')
        raw = subprocess.check_output(['git', '-c', f'safe.directory={repo.resolve()}', '-C', str(repo),
                                       'archive', '--format=zip', '--prefix=BMAD-METHOD-6.12.4/', 'HEAD'])
        if raw != source_archive_path.read_bytes():
            raise ValueError('Official BMAD source archive differs from the exact pinned Git tree')
        payload_path = ROOT / 'resources/offline-tools/sources' / metadata['codexArchive']
        if digest(payload_path.read_bytes()) != metadata['codexArchiveSha256']:
            raise ValueError('Official BMAD Codex payload SHA-256 differs from provenance metadata')
        with zipfile.ZipFile(payload_path) as archive:
            payload = {info.filename[len(f"{metadata['codexArchive'][:-4]}/"):]: archive.read(info)
                       for info in archive.infolist() if not info.is_dir() and
                       info.filename.startswith(f"{metadata['codexArchive'][:-4]}/")}
        return metadata['version'], payload
    repo = ROOT.parent / REPOS[tool]
    if tool == 'codebase-wiki':
        release = load_module('wiki_release_sources', repo / 'tools/release.py')
        version = release.read_version(repo)
        return version, dict(release.package_entries(repo, release.package_files(repo, 'codex'), 'codex', version))
    directory = repo / f'skills/{tool}'
    if not directory.is_dir():
        raise ValueError(f'Missing local source: {directory}')
    entries = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Symlink in local source: {path}')
        if not path.is_file() or '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
            continue
        name = path.relative_to(directory).as_posix()
        data = path.read_bytes()
        # Match release source text across platforms while preserving pinned bundle bytes.
        data = normalize_source_text(tool, name, data)
        entries[name] = data
    version_path = repo / f'skills/{tool}/VERSION'
    version = version_path.read_text(encoding='utf-8').strip()
    return version, entries


def git_info(repo: Path) -> dict:
    def git(*args):
        return subprocess.check_output(['git', '-c', f'safe.directory={repo.resolve()}', '-C', str(repo), *args],
                                       text=True, encoding='utf-8').strip()
    return {'commit': git('rev-parse', 'HEAD'), 'dirty': bool(git('status', '--porcelain'))}


def archive_entries(record: dict) -> dict[str, bytes]:
    archive_path = ROOT / 'resources/offline-tools/sources' / record['filename']
    if digest(archive_path.read_bytes()) != record['archiveSha256']:
        raise ValueError(f'Pinned source hash changed: {archive_path.name}')
    prefix = record['entryRoot'] + '/' if record['entryRoot'] else ''
    with zipfile.ZipFile(archive_path) as archive:
        return {info.filename[len(prefix):]: archive.read(info) for info in archive.infolist()
                if not info.is_dir() and info.filename.startswith(prefix)}


def verify_bmad_source(record: dict) -> dict[str, str]:
    metadata = json.loads((ROOT / 'resources/bmad/source.json').read_text(encoding='utf-8'))
    if ((metadata.get('commit'), metadata.get('version'), metadata.get('codexArchive'), metadata.get('codexArchiveSha256'))
            != (record['commit'], record['version'], record['filename'], record['archiveSha256'])):
        raise ValueError('BMAD upstream pin differs from its official provenance record')
    archive_path = ROOT / 'resources/offline-tools/sources' / metadata['officialArchive']
    raw = archive_path.read_bytes()
    if digest(raw) != metadata['officialArchiveSha256']:
        raise ValueError('Official BMAD source archive hash differs from its pin')
    prefix = 'BMAD-METHOD-6.12.4/'
    rows: dict[str, str] = {}
    links = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if not info.filename.startswith(prefix):
                raise ValueError('Official BMAD source contains an entry outside its pinned root')
            relative = info.filename[len(prefix):]
            if not relative or relative in rows:
                raise ValueError('Official BMAD source contains duplicate or empty paths')
            mode = info.external_attr >> 16
            if mode & 0o170000 == 0o120000:
                links.append(relative)
            rows[relative] = digest(archive.read(info))
    if sorted(links) != metadata.get('sourceSymlinks'):
        raise ValueError('Official BMAD source link inventory differs from its pin')
    tree_sha = digest(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode())
    if (tree_sha, len(rows), rows.get('package-lock.json')) != (
            metadata['sourceTreeSha256'], metadata['sourceFileCount'], metadata['lockfileSha256']):
        raise ValueError('Official BMAD source tree or lockfile digest differs from its pin')
    payload_path = ROOT / 'resources/offline-tools/sources' / metadata['codexArchive']
    if digest(payload_path.read_bytes()) != metadata['codexArchiveSha256']:
        raise ValueError('Official BMAD derived Codex archive hash differs from its pin')
    with zipfile.ZipFile(payload_path) as archive:
        payload = {info.filename[len(f"{metadata['codexArchive'][:-4]}/"):]: digest(archive.read(info))
                   for info in archive.infolist() if not info.is_dir() and
                   info.filename.startswith(f"{metadata['codexArchive'][:-4]}/")}
    if (digest(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()) != metadata['codexTreeSha256']
            or len(payload) != metadata['codexFileCount']):
        raise ValueError('Official BMAD derived Codex file manifest differs from its pin')
    return {'sourceArchiveSha256': metadata['officialArchiveSha256'],
            'sourceTreeSha256': metadata['sourceTreeSha256'], 'lockfileSha256': metadata['lockfileSha256']}


def check(compare_local: bool = True) -> dict:
    snapshot = json.loads(SNAPSHOTS.read_text(encoding='utf-8'))
    tree = ast.parse((ROOT / 'scripts/build-workflow-kit.py').read_text(encoding='utf-8'))
    pins = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'PINNED_SOURCES' for target in node.targets))
    pins = {pin['id']: pin for pin in pins}
    capabilities = builder_capabilities(tree)
    if snapshot.get('capabilities') != {'group': capabilities, 'repository': capabilities}:
        raise ValueError('Builder capabilities differ from the reviewed feature inventory')
    results = []
    for tool, record in snapshot['sources'].items():
        archived = archive_entries(record)
        hashes = {name: digest(data) for name, data in sorted(archived.items())}
        if hashes != record['files']:
            raise ValueError(f'{tool}: archive payload differs from frozen source snapshot')
        if digest(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()) != record['treeSha256']:
            raise ValueError(f'{tool}: source tree digest differs')
        bmad_metadata = verify_bmad_source(record) if tool == 'bmad-method' else {}
        if tool == 'bmad-method' and any(record.get(key) != value for key, value in bmad_metadata.items()):
            raise ValueError('BMAD source archive, source tree or package lockfile differs from the snapshot')
        if (pins[tool]['version'], pins[tool]['sha256'], pins[tool]['filename']) != (record['version'], record['archiveSha256'], record['filename']):
            raise ValueError(f'{tool}: builder pins differ from reviewed source snapshot')
        if compare_local:
            version, local = local_entries(tool)
            differences = sorted(name for name in set(local) | set(archived) if local.get(name) != archived.get(name))
            if version != record['version'] or differences:
                raise ValueError(f'{tool}: local source drift (version={version}, files={differences})')
        results.append({'tool': tool, 'version': record['version'], 'files': len(hashes),
                        'sourceDirty': record['dirty'], 'archiveSha256': record['archiveSha256'],
                        **bmad_metadata, 'status': 'PASS'})
    for name, expected in snapshot.get('workspaceFiles', {}).items():
        if digest((ROOT / name).read_bytes()) != expected:
            raise ValueError(f'Workspace overlay or profile drift: {name}')
    return {'ok': True, 'schema': 'GitLabWorkspaceSourceCheck/v1', 'localCompared': compare_local, 'sources': results,
            'workspaceFilesChecked': len(snapshot.get('workspaceFiles', {})), 'capabilities': snapshot['capabilities']}


def freeze(selected_tools: list[str] | None = None) -> dict:
    builder = load_module('kit_sources_builder', ROOT / 'scripts/build-workflow-kit.py')
    selected = set(selected_tools or REPOS)
    if selected - REPOS.keys():
        raise ValueError('Unknown upstream source selection')
    previous = json.loads(SNAPSHOTS.read_text(encoding='utf-8')) if SNAPSHOTS.exists() else {}
    records = dict(previous.get('sources', {})) if selected_tools else {}
    pins = {record['id']: record for record in builder.PINNED_SOURCES}
    for tool, repo_name in REPOS.items():
        if tool not in selected:
            if tool not in records:
                raise ValueError(f'Unselected source has no frozen snapshot: {tool}')
            archive_entries(records[tool])
            continue
        version, entries = local_entries(tool)
        pin = pins[tool]
        filename = pin['filename'] if pin['version'] == version else (
            f'codebase-llm-wiki-codex-{version}.zip' if tool == 'codebase-wiki' else f'{tool}-{version}.zip')
        prefix = archive_root(tool, version, pin) or tool
        archive = ROOT / 'resources/offline-tools/sources' / filename
        # Keep an existing archive byte-for-byte when its reviewed contents match.
        same = False
        if archive.is_file():
            with zipfile.ZipFile(archive) as stream:
                raw_prefix = prefix + '/' if prefix else ''
                existing = {info.filename[len(raw_prefix):]: stream.read(info) for info in stream.infolist()
                            if not info.is_dir() and info.filename.startswith(raw_prefix)}
                same = existing == entries
        if not same:
            builder.make_zip({(prefix + '/' if prefix else '') + name: data for name, data in entries.items()}, archive)
        hashes = {name: digest(data) for name, data in sorted(entries.items())}
        repo = next((candidate for candidate in (ROOT.parent / repo_name, ROOT / '.tmp' / f"bmad-method-v{version}")
                     if candidate.is_dir()), ROOT.parent / repo_name)
        provenance = verify_bmad_source({'commit': 'bab9082c3e884e0d72c759bcd1a6d90bcc01be84',
                                        'version': version, 'filename': filename,
                                        'archiveSha256': digest(archive.read_bytes())}) if tool == 'bmad-method' else {}
        records[tool] = {'repository': repo_name, 'version': version, 'filename': filename, 'entryRoot': prefix,
                         'sourceKind': 'official-cli-snapshot' if tool == 'bmad-method' else 'local-snapshot',
                         **git_info(repo), 'archiveSha256': digest(archive.read_bytes()), **provenance,
                         'treeSha256': digest(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()), 'files': hashes}
        pin.update(version=version, filename=filename, sha256=records[tool]['archiveSha256'],
                   asset='codebase-llm-wiki-codex.zip' if tool == 'codebase-wiki' else filename)
        if tool == 'codebase-wiki':
            pin['root'] = prefix
    builder_path = ROOT / 'scripts/build-workflow-kit.py'
    source = builder_path.read_text(encoding='utf-8')
    lines = source.splitlines(keepends=True)
    assignment = next(node for node in ast.parse(source).body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'PINNED_SOURCES' for target in node.targets))
    lines[assignment.lineno - 1:assignment.end_lineno] = [
        'PINNED_SOURCES = ' + pprint.pformat(tuple(pins.values()), width=110, sort_dicts=False) + '\n']
    builder_path.write_text(''.join(lines), encoding='utf-8', newline='')
    workspace_files = {path.relative_to(ROOT).as_posix(): digest(path.read_bytes())
                       for path in sorted((ROOT / 'resources/workflow-kit').rglob('*'))
                       if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo', '.zip')}
    capabilities = builder_capabilities(ast.parse((ROOT / 'scripts/build-workflow-kit.py').read_text(encoding='utf-8')))
    SNAPSHOTS.write_bytes((json.dumps({'schema': 'GitLabWorkspaceSourceSnapshots/v1', 'sources': records, 'workspaceFiles': workspace_files,
                                     'capabilities': {'group': capabilities, 'repository': capabilities}},
                                    ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8'))
    # A scoped freeze preserves unselected archives; comparing their unrelated
    # live checkouts is a separate explicit source-drift check.
    return check(compare_local=selected_tools is None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', action='store_true', help='Explicitly snapshot reviewed sibling sources.')
    parser.add_argument('--tool', action='append', choices=tuple(REPOS), help='Freeze only these reviewed upstreams; preserve all other frozen source records and archives.')
    parser.add_argument('--archives-only', action='store_true', help='Verify fixed archives without sibling repositories (CI).')
    args = parser.parse_args()
    if args.tool and not args.freeze:
        parser.error('--tool requires --freeze')
    try:
        print(json.dumps(freeze(args.tool) if args.freeze else check(not args.archives_only), ensure_ascii=False, indent=2))
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        raise SystemExit(1)
