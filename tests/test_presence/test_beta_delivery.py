import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from replicants.desktop import settings
from replicants.desktop.archive import ReplicantArchive, verify
from replicants.desktop.conversation import Conversation
from replicants.desktop.genome import conceive
from replicants.desktop.runtime import DesktopRuntime


def test_delivery_is_deduplicated_and_crashed_turns_are_visible(tmp_path):
    path = tmp_path / 'conversation.json'
    record = Conversation(path)
    assert record.receive('one', 'hello')[1]
    assert not record.receive('one', 'hello')[1]
    record.status('one', 'processing')
    record.spoken('hello back', 'one')
    restored = Conversation(path)
    assert restored.find('one')['status'] == 'completed'
    assert 'reply was saved' in restored.find('one')['detail']
    assert 'retry' not in restored.find('one')['detail']
    assert restored.messages[-1]['text'] == 'hello back'
    assert restored.messages[-1]['status'] == 'delivered'
    assert len(restored.messages) == 2


def test_crashed_turn_without_a_delivered_reply_remains_retryable(tmp_path):
    path = tmp_path / 'conversation.json'
    record = Conversation(path)
    record.receive('one', 'hello')
    record.status('one', 'processing')
    restored = Conversation(path)
    assert restored.find('one')['status'] == 'interrupted'
    assert 'before a reply was saved' in restored.find('one')['detail']


@pytest.mark.parametrize('endpoint', ['https://127.0.0.1:11434', 'http://example.com',
    'http://localhost:11434/remote', 'http://user:secret@localhost:11434', 'file:///models'])
def test_beta_settings_reject_remote_or_ambiguous_endpoints(endpoint):
    with pytest.raises(ValueError): settings.validate({'ollama_url': endpoint})


@pytest.mark.parametrize('model', ['gemma4:cloud', 'gemma4:31b-cloud'])
def test_beta_settings_reject_cloud_proxy_models(model):
    with pytest.raises(ValueError, match='local model'):
        settings.validate({'chat_model': model})


def test_desktop_preferences_control_the_actual_deliberate_inference_parameters(tmp_path, monkeypatch):
    from replicants.desktop.runtime import desktop_config
    from replicants.cognition.deliberate import DeliberateCognition
    monkeypatch.setenv('REPLICANTS_DATA_HOME', str(tmp_path))
    settings.save({'thinking': False, 'reply_tokens': 512})
    config = desktop_config()
    cognition = object.__new__(DeliberateCognition)
    cognition.entity = config
    _, tokens, think, _ = cognition._inference_params('deliberate')
    assert tokens == 512 and think is False


def test_beta_reopens_an_accelerated_development_life_at_real_speed(monkeypatch):
    from replicants.desktop.clock import SimClock
    monkeypatch.setenv('REPLICANTS_BETA', '1')
    monkeypatch.setenv('REPLICANTS_TIME_SCALE', '360')
    tick = [0.0]
    clock = SimClock({'scale': 60, 'sim': 1000, 'wall': 2000},
                     wall=lambda: 2010, monotonic=lambda: tick[0])
    assert clock.now() == 1600  # The saved development rate governed the offline gap.
    tick[0] = 10
    assert clock.now() == 1610 and clock.scale == 1


@pytest.mark.asyncio
async def test_setup_rejects_a_cloud_alias_even_when_the_name_looks_local(tmp_path, monkeypatch):
    from aiohttp import web
    from replicants.desktop.setup import check
    monkeypatch.setenv('REPLICANTS_DATA_HOME', str(tmp_path))
    async def version(_): return web.json_response({'version': 'fixture'})
    async def tags(_): return web.json_response({'models': [{'name': 'alias:latest'}, {'name': 'memory:latest'}]})
    async def show(request):
        model = (await request.json())['model']
        return web.json_response({'capabilities': ['embedding']} if model == 'memory' else
            {'capabilities': ['completion'], 'remote_host': 'https://ollama.com', 'remote_model': 'gemma4:31b'})
    app = web.Application(); app.router.add_get('/api/version', version)
    app.router.add_get('/api/tags', tags); app.router.add_post('/api/show', show)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0); await site.start()
    try:
        port = site._server.sockets[0].getsockname()[1]
        report = await check({'ollama_url': f'http://127.0.0.1:{port}', 'chat_model': 'alias', 'embedding_model': 'memory'})
        assert not report['ready'] and any('remote host' in issue for issue in report['issues'])
    finally: await runner.cleanup()


def test_host_preferences_do_not_change_genome_and_archive_snapshot_is_coherent(tmp_path):
    being = ReplicantArchive.create(conceive(), tmp_path / 'one.replicant', tmp_path / 'data')
    try:
        being.append('observed', {'value': 'before'})
        snapshot = being.snapshot()
        being.append('observed', {'value': 'after'})
        being.manifest['name'] = 'Later name'
        being.checkpoint(snapshot=snapshot)
        manifest, members = verify(being.path)
        assert manifest['name'] is None
        assert being.manifest['name'] == 'Later name'
        assert json.loads(members['lineage.jsonl'].splitlines()[-1])['data']['value'] == 'before'
        being.checkpoint()
        manifest, members = verify(being.path)
        assert manifest['name'] == 'Later name'
        assert json.loads(members['lineage.jsonl'].splitlines()[-1])['data']['value'] == 'after'
        assert members['genome.yaml'] == being.genome_bytes
    finally: being.close()


def test_library_finds_named_lives_and_external_files_without_opening_them(tmp_path, monkeypatch):
    from replicants.desktop.library import lives, remember
    monkeypatch.setenv('REPLICANTS_DATA_HOME', str(tmp_path / 'data'))
    being = ReplicantArchive.create(conceive(), tmp_path / 'elsewhere' / 'pip.replicant')
    being.manifest['name'] = 'Pip'; being.checkpoint(); being.close()
    assert lives()['lives'] == []
    remember(being.path)
    record = lives()['lives'][0]
    assert record['name'] == 'Pip' and record['file'] == str(being.path)
    # A preview does not acquire the identity lock; full verification still occurs on wake.
    reopened = ReplicantArchive.open(being.path)
    try: assert lives()['lives'][0]['id'] == reopened.id
    finally: reopened.close()


def test_bootstrap_library_json_uses_utf8_with_an_inherited_ascii_code_page(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    from replicants.desktop.library import remember
    monkeypatch.setenv('REPLICANTS_DATA_HOME', str(tmp_path / 'data'))
    being = ReplicantArchive.create(conceive(), tmp_path / 'life.replicant')
    being.manifest['name'] = 'Pip \u9752'; being.checkpoint(); being.close()
    remember(being.path)
    result = subprocess.run([sys.executable, '-m', 'replicants.desktop.bootstrap', 'library'],
        env={**os.environ, 'PYTHONIOENCODING': 'ascii'}, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.decode('utf-8'))['lives'][0]['name'] == 'Pip \u9752'


@pytest.mark.asyncio
async def test_missing_desktop_exits_after_reconnect_grace_without_new_inference(monkeypatch):
    import time
    monkeypatch.setenv('REPLICANTS_BETA', '1')
    runtime = object.__new__(DesktopRuntime)
    runtime.clock = SimpleNamespace(now=lambda: 0)
    runtime.platform = SimpleNamespace(connected=False)
    runtime._stop = asyncio.Event(); runtime.health = {}
    runtime._disconnected_at = time.monotonic() - 91
    await asyncio.wait_for(runtime._body_loop(), 1)
    assert runtime._stop.is_set() and runtime.health['status'] == 'stopping'


@pytest.mark.asyncio
async def test_background_failure_still_checkpoints_and_disconnects():
    @asynccontextmanager
    async def session(): yield object()
    tonic = SimpleNamespace(restore_state_db=AsyncMock())
    entity = SimpleNamespace(store=SimpleNamespace(session=session), tonic=tonic,
                             _ensure_state_hydrated=AsyncMock(), shutdown=AsyncMock())
    platform = SimpleNamespace(_runner=object(), connected=False, on_message=AsyncMock(),
                               publish=AsyncMock(), disconnect=AsyncMock())
    runtime = object.__new__(DesktopRuntime)
    runtime.entity, runtime.platform = entity, platform
    runtime.health = {}; runtime._tasks = []; runtime._stop = asyncio.Event()
    runtime.started = AsyncMock(); runtime.before_shutdown = AsyncMock(); runtime.after_shutdown = AsyncMock()
    runtime.save_runtime = lambda: None
    async def wait(): await asyncio.Event().wait()
    async def fail(): raise RuntimeError('deliberate remote-only fixture failure')
    runtime._body_loop = fail; runtime._mind_loop = wait
    runtime._turn_worker = wait; runtime._substrate_loop = wait; runtime.extra_loops = lambda: []
    await asyncio.wait_for(runtime.run(launch=False), 2)
    runtime.before_shutdown.assert_awaited_once()
    entity.shutdown.assert_awaited_once()
    runtime.after_shutdown.assert_awaited_once()
    platform.disconnect.assert_awaited_once()
    assert any(call.args == ('stopped', {'checkpointed': True}) for call in platform.publish.call_args_list)


@pytest.mark.asyncio
async def test_unavailable_model_turn_is_failed_rather_than_completed(tmp_path, monkeypatch):
    from replicants.desktop.entity import DesktopEntity
    from replicants.entity import Entity
    from replicants.models import Input
    entity = object.__new__(DesktopEntity)
    entity.decision_stats = {'valid': 0, 'invalid': 0, 'errors': {}}
    entity.dormant = True
    monkeypatch.setattr(Entity, 'perceive', AsyncMock(return_value=('model unavailable', False)))
    runtime = object.__new__(DesktopRuntime)
    runtime.entity = entity; runtime.paused = False
    runtime._jobs = asyncio.Queue(); runtime._cognition = asyncio.Lock()
    runtime.platform = SimpleNamespace(publish=AsyncMock())
    runtime.conversation = Conversation(tmp_path / 'conversation.json')
    runtime.conversation.receive('unavailable', 'hello')
    runtime.settle_outreach = AsyncMock(); runtime.conversation_checkpoint = AsyncMock()
    await runtime._jobs.put(Input('hello', 'person', 'person', 'desktop', 'desktop',
                                 metadata={'desktop_message_id': 'unavailable'}))
    worker = asyncio.create_task(runtime._turn_worker())
    await asyncio.wait_for(runtime._jobs.join(), 2)
    worker.cancel(); await asyncio.gather(worker, return_exceptions=True)
    assert runtime.conversation.find('unavailable')['status'] == 'failed'
    assert 'Ollama is unavailable' in runtime.conversation.find('unavailable')['detail']
    runtime.conversation_checkpoint.assert_not_awaited()
