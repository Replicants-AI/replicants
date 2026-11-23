import asyncio
import hashlib
import io
import json
import os
import socket
import stat
import sys
import zipfile

import pytest
from aiohttp import web

from replicants.desktop import hardware, local_runtime, settings, setup


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]


FAKE = '''#!{python}
import http.server, os, json
assert os.environ.get('OLLAMA_NO_CLOUD') == '1'
host, port = os.environ['OLLAMA_HOST'].split(':')
os.makedirs(os.environ['OLLAMA_MODELS'], exist_ok=True)
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(json.dumps({{'version': 'fake'}}).encode())
    def log_message(self, *a): pass
http.server.HTTPServer((host, int(port)), H).serve_forever()
'''


def archive(executable='ollama.exe', extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        info = zipfile.ZipInfo(executable); info.external_attr = (stat.S_IFREG | 0o755) << 16
        z.writestr(info, FAKE.format(python=sys.executable))
        z.writestr('lib/readme.txt', 'runtime libraries')
        for name, data in (extra or {}).items(): z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('REPLICANTS_DATA_HOME', str(tmp_path / 'home'))
    port = free_port()
    monkeypatch.setattr(local_runtime, 'PORT', port)
    monkeypatch.setattr(local_runtime, 'URL', f'http://127.0.0.1:{port}')
    return tmp_path


def write_pin(tmp_path, monkeypatch, url, payload, sha=None):
    pin = {'name': 'ollama', 'version': '9.9.9', 'asset': 'ollama-windows-amd64.zip', 'url': url,
           'sha256': sha if sha is not None else hashlib.sha256(payload).hexdigest(), 'size': len(payload),
           'executable': 'ollama.exe'}
    path = tmp_path / 'pin.json'; path.write_text(json.dumps(pin))
    monkeypatch.setattr(local_runtime, 'PIN_FILE', path)
    return pin


async def serve(payload):
    app = web.Application()
    async def handler(request): return web.Response(body=payload)
    app.router.add_get('/runtime.zip', handler)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0); await site.start()
    return runner, f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/runtime.zip'


def test_an_unpinned_build_refuses_to_download(home, monkeypatch):
    path = home / 'unpinned.json'
    path.write_text(json.dumps({**json.loads(local_runtime.PIN_FILE.read_text()), 'sha256': None, 'size': None}))
    monkeypatch.setattr(local_runtime, 'PIN_FILE', path)
    assert not local_runtime.verified_build()
    with pytest.raises(local_runtime.RuntimeUnavailable, match='no verified local runtime'):
        asyncio.run(local_runtime.install(lambda e: None))


@pytest.mark.asyncio
async def test_install_verifies_checksum_and_unpacks_privately(home, monkeypatch):
    payload = archive()
    runner, url = await serve(payload)
    try:
        write_pin(home, monkeypatch, url, payload)
        events = []
        await local_runtime.install(events.append)
        assert local_runtime.installed()
        assert local_runtime.install_dir().is_relative_to(settings.data_home())
        assert events[-1] == {'stage': 'runtime', 'status': 'installed'}
        assert any(e.get('status') == 'downloading' and e['total'] == len(payload) for e in events)
        assert not list(local_runtime.root().glob('*.part'))
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_a_mismatched_download_installs_nothing(home, monkeypatch):
    payload = archive()
    runner, url = await serve(payload)
    try:
        write_pin(home, monkeypatch, url, payload, sha='0' * 64)
        with pytest.raises(local_runtime.RuntimeUnavailable, match='checksum'):
            await local_runtime.install(lambda e: None)
        assert not local_runtime.installed() and not local_runtime.install_dir().exists()
        assert not list(local_runtime.root().glob('*.part'))
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_unsafe_archive_paths_are_refused(home, monkeypatch):
    payload = archive(extra={'../escape.txt': 'x'})
    runner, url = await serve(payload)
    try:
        write_pin(home, monkeypatch, url, payload)
        with pytest.raises(local_runtime.RuntimeUnavailable, match='unsafe'):
            await local_runtime.install(lambda e: None)
        assert not (home / 'home' / 'escape.txt').exists() and not local_runtime.installed()
    finally:
        await runner.cleanup()


@pytest.mark.skipif(os.name == 'nt', reason='the fake runtime is a POSIX script')
@pytest.mark.asyncio
async def test_private_runtime_starts_on_its_own_port_and_stops_only_itself(home, monkeypatch):
    monkeypatch.setenv('OLLAMA_NO_CLOUD', '0')  # Private inference must override an inherited cloud preference.
    payload = archive()
    runner, url = await serve(payload)
    try:
        write_pin(home, monkeypatch, url, payload)
        await local_runtime.install(lambda e: None)
    finally:
        await runner.cleanup()
    os.chmod(local_runtime.executable(), 0o755)   # zip extraction carries no POSIX mode; Windows needs none
    assert not await local_runtime.responding()
    assert await local_runtime.ensure_running(wait_seconds=15) == local_runtime.URL
    assert await local_runtime.responding()
    assert local_runtime.models_dir().is_dir()
    assert await local_runtime.ensure_running() == local_runtime.URL   # already up: no second process
    assert local_runtime.stop() is True
    for _ in range(40):
        if not await local_runtime.responding(): break
        await asyncio.sleep(0.1)
    assert not await local_runtime.responding()
    assert local_runtime.stop() is False                                 # nothing of ours left to stop


def test_a_foreign_process_is_never_stopped(home):
    local_runtime.root().mkdir(parents=True)
    (local_runtime.root() / 'state.json').write_text(json.dumps({'pid': os.getpid(), 'executable': '/no/such/ollama.exe'}))
    assert local_runtime.stop() is False


def test_hardware_tiers():
    GB = hardware.GB
    assert hardware.choose(32 * GB, 24 * GB)['chat_model'] == 'gemma4:26b'
    assert hardware.choose(16 * GB, None)['chat_model'] == 'gemma4:e4b'
    assert hardware.choose(8 * GB, 8 * GB)['chat_model'] == 'gemma4:e4b'
    assert hardware.choose(8 * GB, None)['chat_model'] == 'gemma4:e2b'
    assert hardware.choose(4 * GB, None) == {}


def test_hardware_tiers_allow_small_os_reservation_and_keep_lower_hosts_out():
    from replicants.desktop import hardware
    GB, allowance = hardware.GB, hardware.RAM_RESERVED_ALLOWANCE
    assert hardware.choose(8584425472, None)['chat_model'] == 'gemma4:e2b'  # Observed 8 GiB Windows runner.
    assert hardware.choose(8 * GB - allowance, None)['chat_model'] == 'gemma4:e2b'
    assert hardware.choose(8 * GB - allowance - 1, None) == {}
    assert hardware.choose(16 * GB - allowance, None)['chat_model'] == 'gemma4:e4b'
    assert hardware.choose(4 * GB, 8 * GB - 1) == {}  # GPU threshold has no RAM allowance.


def test_settings_runtime_choice_and_where_thought_runs(home):
    prefs = settings.validate({})
    assert prefs['runtime'] == 'auto' and settings.inference_url(prefs) == prefs['ollama_url']
    assert settings.inference_url({**prefs, 'runtime': 'managed'}) == local_runtime.URL
    with pytest.raises(ValueError, match='runtime'): settings.validate({'runtime': 'cloud'})


def prepare_with(monkeypatch, *, external, survey_model='gemma4:e4b', chat_model=None):
    calls = {'installed': 0, 'started': 0, 'pulled': []}
    async def survey(): return {'verdict': 'lighter', 'message': 'Your computer can host a lighter replicant.',
                                'chat_model': survey_model}
    async def running(url): return external
    async def install(emit): calls['installed'] += 1; emit({'stage': 'runtime', 'status': 'installed'})
    async def ensure(**kw): calls['started'] += 1; return local_runtime.URL
    state = {'missing': True}
    async def check(prefs=None):
        p = settings.validate(prefs) if prefs is not None else settings.load()
        missing = [{'kind': 'chat', 'name': p['chat_model']}, {'kind': 'memory', 'name': p['embedding_model']}]
        return {'ready': not state['missing'], 'missing': missing if state['missing'] else [], 'settings': p}
    async def pull(model, emit, stage=None): calls['pulled'].append((model, stage)); state['missing'] = False
    monkeypatch.setattr(setup.hardware, 'survey', survey)
    monkeypatch.setattr(setup, '_external_running', running)
    monkeypatch.setattr(setup.local_runtime, 'install', install)
    monkeypatch.setattr(setup.local_runtime, 'ensure_running', ensure)
    monkeypatch.setattr(setup.local_runtime, 'status', lambda: {'supported_platform': True})
    monkeypatch.setattr(setup, 'check', check)
    monkeypatch.setattr(setup, 'pull', pull)
    if chat_model: settings.save({**settings.DEFAULTS, 'chat_model': chat_model})
    return calls


@pytest.mark.asyncio
async def test_one_button_setup_uses_the_private_runtime_and_a_fitting_mind(home, monkeypatch):
    calls = prepare_with(monkeypatch, external=False)
    events = []
    report = await setup.prepare(events.append)
    saved = settings.load()
    assert saved['runtime'] == 'managed' and saved['chat_model'] == 'gemma4:e4b'
    assert calls['installed'] == 1 and calls['started'] == 1
    assert [stage for _, stage in calls['pulled']] == ['mind', 'memory']
    assert report['ready'] and events[-1] == {'stage': 'done', 'ready': True, 'status': 'ready'}


@pytest.mark.asyncio
async def test_setup_prefers_an_ollama_already_running_and_keeps_a_chosen_model(home, monkeypatch):
    calls = prepare_with(monkeypatch, external=True, chat_model='my-own-model')
    await setup.prepare(lambda e: None)
    saved = settings.load()
    assert saved['runtime'] == 'external' and saved['chat_model'] == 'my-own-model'
    assert calls['installed'] == 0 and calls['started'] == 0


@pytest.mark.asyncio
async def test_setup_stops_honestly_on_a_computer_that_cannot_host_one(home, monkeypatch):
    prepare_with(monkeypatch, external=False)
    async def survey(): return {'verdict': 'not_yet', 'message': 'This computer does not have enough memory to host a replicant yet.', 'chat_model': None}
    monkeypatch.setattr(setup.hardware, 'survey', survey)
    with pytest.raises(ValueError, match='not have enough memory'):
        await setup.prepare(lambda e: None)
