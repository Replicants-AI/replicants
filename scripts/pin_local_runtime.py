"""Pin the private local runtime for a release build.

Reads the version in replicants/desktop/runtime_pin.json, looks up that exact Ollama
release through GitHub's API, and records the Windows archive's download URL, size
and SHA-256. The archive is downloaded and hashed here to confirm the published
digest, so the app can verify every byte before it installs anything.

Run on the release builder before freezing the backend:
    python scripts/pin_local_runtime.py
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.request

PIN = Path(__file__).resolve().parents[1] / 'replicants' / 'desktop' / 'runtime_pin.json'


def request(url: str, accept: str = 'application/vnd.github+json'):
    headers = {'Accept': accept, 'User-Agent': 'replicants-release-builder'}
    token = os.environ.get('GITHUB_TOKEN')
    if token and url.startswith('https://api.github.com/'):
        headers['Authorization'] = f'Bearer {token}'
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120)


def main() -> int:
    pin = json.loads(PIN.read_text(encoding='utf-8'))
    version, asset_name = pin['version'], pin['asset']
    with request(f'https://api.github.com/repos/ollama/ollama/releases/tags/v{version}') as response:
        release = json.load(response)
    if release.get('draft') or release.get('prerelease'):
        print(f'v{version} is not a stable release.', file=sys.stderr); return 1
    asset = next((a for a in release.get('assets', []) if a.get('name') == asset_name), None)
    if asset is None:
        print(f'v{version} has no {asset_name}.', file=sys.stderr); return 1
    digest, size = hashlib.sha256(), 0
    with request(asset['browser_download_url'], accept='application/octet-stream') as response:
        while chunk := response.read(1 << 20):
            digest.update(chunk); size += len(chunk)
    sha = digest.hexdigest()
    published = str(asset.get('digest') or '')
    if published and published != f'sha256:{sha}':
        print(f'Downloaded bytes do not match the published digest {published}.', file=sys.stderr); return 1
    if size != asset.get('size'):
        print('Downloaded size does not match the release.', file=sys.stderr); return 1
    pin.update(url=asset['browser_download_url'], sha256=sha, size=size,
               pinned_by=f'scripts/pin_local_runtime.py from the GitHub release v{version}'
                         + (' (published digest confirmed)' if published else ''))
    PIN.write_text(json.dumps(pin, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: pin[k] for k in ('version', 'asset', 'size', 'sha256')}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
