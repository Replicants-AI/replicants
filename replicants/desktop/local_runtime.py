"""A private local inference runtime the app installs and runs itself.

People who have never installed developer tools should not have to install Ollama.
The release build pins one exact Ollama release and its SHA-256 (see
scripts/pin_local_runtime.py). On first setup the app downloads that archive,
verifies it, unpacks it under its own data folder, and runs it on a private
localhost port with its own model folder. It never touches a system Ollama.

A build without a verified pin refuses to download anything; setup then falls
back to an Ollama the person installed themselves.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from typing import Callable

import aiohttp
import psutil

from replicants.desktop import settings

PORT = 11535
URL = f'http://127.0.0.1:{PORT}'
PIN_FILE = Path(__file__).with_name('runtime_pin.json')
MAX_ARCHIVE_BYTES = 6 * 1024 ** 3


class RuntimeUnavailable(ValueError):
    pass


def pin() -> dict:
    data = json.loads(PIN_FILE.read_text(encoding='utf-8'))
    for key in ('version', 'url', 'executable'):
        if not isinstance(data.get(key), str) or not data[key]:
            raise RuntimeUnavailable('The local runtime pin is incomplete.')
    return data


def verified_build() -> bool:
    try:
        p = pin()
    except (OSError, ValueError):
        return False
    return isinstance(p.get('sha256'), str) and len(p['sha256']) == 64 and isinstance(p.get('size'), int)


def root() -> Path:
    return settings.data_home() / 'runtime'


def install_dir() -> Path:
    return root() / f"ollama-{pin()['version']}"


def executable() -> Path:
    return install_dir() / pin()['executable']


def models_dir() -> Path:
    return settings.data_home() / 'models'


def installed() -> bool:
    try:
        marker = install_dir() / '.verified'
        return executable().is_file() and marker.is_file() and marker.read_text().strip() == pin().get('sha256')
    except (OSError, ValueError):
        return False


def status() -> dict:
    try:
        version = pin()['version']
    except (OSError, ValueError):
        version = None
    return {'version': version, 'verified_build': verified_build(), 'installed': installed(), 'url': URL,
            'supported_platform': os.name == 'nt'}


# Install --------------------------------------------------------------------

def _safe_extract(archive: Path, target: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            parts = PurePosixPath(info.filename.replace('\\', '/')).parts
            if (not parts or info.filename.startswith(('/', '\\')) or '..' in parts or ':' in info.filename
                    or (info.external_attr >> 16) & 0o170000 == 0o120000):
                raise RuntimeUnavailable('The runtime archive contains an unsafe path.')
        bundle.extractall(target)


async def install(emit: Callable[[dict], None], *, session: aiohttp.ClientSession | None = None) -> None:
    """Download, verify, and unpack the pinned runtime. Safe to interrupt and repeat."""
    p = pin()
    if not verified_build():
        raise RuntimeUnavailable('This build has no verified local runtime. Install Ollama yourself, '
                                 'then choose Check again.')
    if installed():
        return
    root().mkdir(parents=True, exist_ok=True)
    part = root() / f"{p['asset']}.{uuid.uuid4().hex}.part"
    digest, received = hashlib.sha256(), 0
    owned = session is None
    session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=120))
    try:
        async with session.get(p['url']) as response:
            response.raise_for_status()
            with part.open('xb') as stream:
                async for chunk in response.content.iter_chunked(1 << 20):
                    received += len(chunk)
                    if received > min(p['size'], MAX_ARCHIVE_BYTES):
                        raise RuntimeUnavailable('The runtime download is larger than expected.')
                    digest.update(chunk)
                    stream.write(chunk)
                    emit({'stage': 'runtime', 'status': 'downloading', 'completed': received, 'total': p['size']})
        if received != p['size'] or digest.hexdigest() != p['sha256']:
            raise RuntimeUnavailable('The runtime download did not match its verified checksum. Nothing was installed.')
        emit({'stage': 'runtime', 'status': 'unpacking'})
        staging = root() / f'.staging-{uuid.uuid4().hex}'
        try:
            await asyncio.to_thread(_safe_extract, part, staging)
            if not (staging / p['executable']).is_file():
                raise RuntimeUnavailable('The runtime archive does not contain the expected program.')
            (staging / '.verified').write_text(p['sha256'])
            if install_dir().exists():
                shutil.rmtree(install_dir())
            os.replace(staging, install_dir())
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        emit({'stage': 'runtime', 'status': 'installed'})
    finally:
        part.unlink(missing_ok=True)
        if owned:
            await session.close()


# Process --------------------------------------------------------------------

def _state_path() -> Path:
    return root() / 'state.json'


def _owned_process() -> psutil.Process | None:
    """Only a process this app started, from this app's runtime folder, is ever stopped."""
    try:
        state = json.loads(_state_path().read_text(encoding='utf-8'))
        process = psutil.Process(int(state['pid']))
        expected = Path(state['executable']).resolve()
        launched = [Path(part).resolve() for part in process.cmdline()[:2]]
        if Path(process.exe()).resolve() == expected or expected in launched:
            return process
    except (OSError, ValueError, KeyError, TypeError, psutil.Error):
        pass
    return None


async def responding(session: aiohttp.ClientSession | None = None) -> bool:
    owned = session is None
    session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2))
    try:
        async with session.get(URL + '/api/version', allow_redirects=False) as response:
            return response.status == 200
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return False
    finally:
        if owned:
            await session.close()


async def ensure_running(*, wait_seconds: float = 30.0) -> str:
    """Start the private runtime if it is not already serving. Returns its URL."""
    if await responding():
        return URL
    if not installed():
        raise RuntimeUnavailable('The local runtime is not installed yet. Open Replicants and choose Set up.')
    models_dir().mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'OLLAMA_HOST': f'127.0.0.1:{PORT}', 'OLLAMA_MODELS': str(models_dir()),
           'OLLAMA_NO_CLOUD': '1'}
    log = (root() / 'runtime.log').open('ab')
    flags = 0
    if os.name == 'nt':
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen([str(executable()), 'serve'], cwd=install_dir(), env=env, stdin=subprocess.DEVNULL,
                               stdout=log, stderr=log, creationflags=flags, start_new_session=os.name != 'nt')
    log.close()
    from replicants.desktop.protocol import private_write
    private_write(_state_path(), {'pid': process.pid, 'executable': str(executable()), 'port': PORT,
                                  'version': pin()['version'], 'started': time.time()})
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeUnavailable('The local runtime stopped while starting. See runtime.log in the Replicants folder.')
        if await responding():
            return URL
        await asyncio.sleep(0.25)
    raise RuntimeUnavailable('The local runtime did not start in time. Try again, or restart your computer.')


def stop() -> bool:
    process = _owned_process()
    if process is None:
        _state_path().unlink(missing_ok=True)
        return False
    try:
        for child in process.children(recursive=True):
            child.terminate()
        process.terminate()
        _, alive = psutil.wait_procs([process], timeout=5)
        for straggler in alive:
            straggler.kill()
    except psutil.Error:
        pass
    _state_path().unlink(missing_ok=True)
    return True


if __name__ == '__main__':  # pragma: no cover - manual diagnostics
    print(json.dumps(status(), indent=1))
    sys.exit(0)
