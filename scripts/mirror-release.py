"""Mirror verified public GitHub Release bytes from an intranet host."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

GITHUB = 'https://api.github.com/repos/dennis8499/WorkflowKit'
GITEA = 'https://tech-sharing.cathaysec.com.tw'
REPOSITORY = '01002903/WorkflowKit'


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        next_request = super().redirect_request(req, fp, code, msg, headers, newurl)
        if next_request and urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
            next_request.remove_header('Authorization')
        return next_request


OPENER = urllib.request.build_opener(SafeRedirect())


def request(url, method='GET', body=None, data=None, content_type='application/json', raw=False):
    headers = {'User-Agent': 'WorkflowKit-mirror', 'Accept': 'application/json'}
    if url.startswith(GITEA + '/'):
        headers['Authorization'] = 'token ' + os.environ['GITEA_TOKEN']
    if body is not None:
        data = json.dumps(body).encode('utf-8')
    if data is not None:
        headers['Content-Type'] = content_type
    with OPENER.open(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=120) as response:
        result = response.read(81 * 1024 * 1024)
    return result if raw else json.loads(result) if result else {}


def optional(url):
    try:
        return request(url)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def mirror(tag):
    if not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise ValueError('Expected a stable vX.Y.Z tag')
    release = request(f'{GITHUB}/releases/tags/{tag}')
    if release['draft'] or release['prerelease'] or release['tag_name'] != tag:
        raise ValueError('Only formal exact-tag releases can be mirrored')
    files = {}
    for asset in release['assets']:
        name = asset['name']
        if Path(name).name != name or name in files or asset['size'] > 80 * 1024 * 1024:
            raise ValueError('Invalid or duplicate asset')
        data = request(asset['browser_download_url'], raw=True)
        if len(data) != asset['size'] or asset.get('digest') != 'sha256:' + hashlib.sha256(data).hexdigest():
            raise ValueError('GitHub release asset digest mismatch')
        files[name] = data
    descriptor = json.loads(files['release.json'])
    expected = {'release.json', 'SHA256SUMS'} | {asset['name'] for asset in descriptor['assets'].values()}
    if set(files) != expected or descriptor['version'] != tag[1:]:
        raise ValueError('Release inventory differs from descriptor')
    rows = dict((name, sha) for sha, name in (line.split('  ') for line in files['SHA256SUMS'].decode('ascii').splitlines()))
    if set(rows) != expected - {'SHA256SUMS'} or any(hashlib.sha256(files[name]).hexdigest() != sha for name, sha in rows.items()):
        raise ValueError('Release checksums differ')
    api = f'{GITEA}/api/v1/repos/{REPOSITORY}'
    if optional(api) is None:
        request(f'{GITEA}/api/v1/repos/migrate', 'POST', body={
            'clone_addr': 'https://github.com/dennis8499/WorkflowKit.git',
            'repo_name': 'WorkflowKit', 'repo_owner': REPOSITORY.split('/')[0],
            'mirror': True, 'private': False, 'description': 'Verified WorkflowKit Release mirror'})
    target = optional(f'{api}/releases/tags/{tag}')
    if target is None:
        target = request(f'{api}/releases', 'POST', body={'tag_name': tag, 'name': tag,
            'draft': True, 'prerelease': False, 'body': release.get('body', '')})
    existing = {asset['name']: asset for asset in request(f"{api}/releases/{target['id']}/assets")}
    for name, data in files.items():
        if name in existing:
            if request(existing[name]['browser_download_url'], raw=True) != data:
                raise ValueError(f'Existing mirrored asset differs: {name}')
            continue
        boundary = 'workflowkit-release-upload'
        payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="attachment"; filename="{name}"\r\n'
                   'Content-Type: application/octet-stream\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
        uploaded = request(f"{api}/releases/{target['id']}/assets?name={urllib.parse.quote(name)}", 'POST',
                           data=payload, content_type=f'multipart/form-data; boundary={boundary}')
        if request(uploaded['browser_download_url'], raw=True) != data:
            raise ValueError('Mirror download differs from the verified GitHub bytes')
    if target['draft']:
        request(f"{api}/releases/{target['id']}", 'PATCH', body={'draft': False})
    print(json.dumps({'ok': True, 'tag': tag, 'repository': REPOSITORY, 'assets': sorted(files)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    mirror(parser.parse_args().tag)
