"""Verify the exact portable artifacts promoted by CI."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def verify(root=ROOT):
    version = (root / 'VERSION').read_text(encoding='utf-8').strip()
    dist = root / 'dist'
    release = json.loads((dist / 'release.json').read_text(encoding='utf-8'))
    if (release['schema'], release['version'], release['workspaceContract'], release['installerApi']) != ('workflowkit-release/v1', version, 2, 1):
        raise ValueError('Invalid release identity or compatibility contract')
    expected = {'release.json'}
    for asset in release['assets'].values():
        if Path(asset['name']).name != asset['name']:
            raise ValueError('Unsafe release asset name')
        data = (dist / asset['name']).read_bytes()
        if len(data) != asset['size'] or hashlib.sha256(data).hexdigest() != asset['sha256']:
            raise ValueError('Release asset digest or size mismatch')
        expected.add(asset['name'])
    rows = {}
    for line in (dist / 'SHA256SUMS').read_text(encoding='ascii').splitlines():
        sha, name = line.split('  ')
        if name in rows or hashlib.sha256((dist / name).read_bytes()).hexdigest() != sha:
            raise ValueError('Invalid or duplicate checksum entry')
        rows[name] = sha
    if set(rows) != expected:
        raise ValueError('Checksum inventory differs from release assets')
    with zipfile.ZipFile(dist / release['assets']['package']['name']) as archive:
        if archive.testzip():
            raise ValueError('Package CRC verification failed')
        if archive.read('workflow-kit/install.py') != (dist / release['assets']['installer']['name']).read_bytes():
            raise ValueError('Standalone and published installers differ')
        manifest = json.loads(archive.read('workflow-kit/manifest.json'))
        if manifest['version'] != version or manifest['workspaceContract'] != release['workspaceContract']:
            raise ValueError('Package manifest differs from release descriptor')
    spec = importlib.util.spec_from_file_location('verified_workflowkit_installer', dist / release['assets']['installer']['name'])
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    installer.import_package(dist / release['assets']['package']['name'], 'zip', version)
    return release


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    print(json.dumps({'ok': True, 'release': verify()}, ensure_ascii=False))
