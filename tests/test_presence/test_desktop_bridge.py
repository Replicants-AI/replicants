import asyncio
import json

from aiohttp import ClientSession, WSMsgType, WSServerHandshakeError
import pytest

from replicants.desktop.protocol import VERSION, packet, InstanceLock
from replicants.presence.platforms.desktop import DesktopPlatform


async def authenticated(client, platform):
    ws = await client.ws_connect(f'http://127.0.0.1:{platform.port}/ws')
    await ws.send_json({'type': 'hello', 'protocol': VERSION, 'token': platform.token})
    assert (await ws.receive_json())['type'] == 'ready'
    return ws


@pytest.mark.asyncio
async def test_loopback_auth_private_descriptor_and_origin(tmp_path):
    platform = DesktopPlatform(tmp_path / 'session.json')
    await platform.connect()
    try:
        descriptor = json.loads(platform.session_path.read_text())
        assert descriptor['port'] > 0 and len(descriptor['token']) >= 32
        assert set(descriptor) == {'protocol', 'port', 'token', 'pid'}
        async with ClientSession() as client:
            ws = await client.ws_connect(f'http://127.0.0.1:{platform.port}/ws')
            await ws.send_json({'type': 'hello', 'protocol': 1, 'token': 'wrong'})
            assert (await ws.receive()).type == WSMsgType.CLOSE
            assert ws.close_code == 4401
            with pytest.raises(WSServerHandshakeError):
                await client.ws_connect(f'http://127.0.0.1:{platform.port}/ws', origin='https://unrelated.example')
            ws = await authenticated(client, platform)
            await ws.send_json({'type': 'event'})
            assert (await ws.receive_json())['type'] == 'error'
            await ws.close()
    finally:
        await platform.disconnect()
    assert not platform.session_path.exists()


@pytest.mark.asyncio
async def test_actions_wait_for_matching_ack_and_disconnect_is_not_success(tmp_path):
    platform = DesktopPlatform(tmp_path / 'session.json')
    await platform.connect()
    try:
        async with ClientSession() as client:
            ws = await authenticated(client, platform)
            action = asyncio.create_task(platform.action('wave'))
            sent = await ws.receive_json()
            assert sent['type'] == 'act' and not action.done()
            await ws.send_json(packet('act_result', {'act_id': 'unrelated', 'status': 'completed'}))
            await asyncio.sleep(.01); assert not action.done()
            await ws.send_json(packet('act_result', {'act_id': sent['id'], 'status': 'completed', 'detail': 'sequence finished',
                'evidence': {'x': 100, 'window_id': '123', 'title': 'never accepted'}}))
            result = await action
            assert result['status'] == 'completed'
            assert result['evidence'] == {'x': 100, 'window_id': '123'}
            action = asyncio.create_task(platform.action('sit'))
            await ws.receive_json(); await ws.close()
            assert (await action)['status'] == 'interrupted'
            ws = await authenticated(client, platform)
            action = asyncio.create_task(platform.action('wave', timeout=.03))
            await ws.receive_json()
            assert (await action)['detail'] == 'action_timeout'
            assert (await ws.receive_json())['type'] == 'cancel_act'
            await ws.close()
    finally:
        await platform.disconnect()


@pytest.mark.asyncio
async def test_event_handler_can_wait_on_body_action_without_blocking_ack_reader(tmp_path):
    platform = DesktopPlatform(tmp_path / 'session.json')
    finished = asyncio.Event()
    async def receive(message):
        assert message['payload']['name'] == 'poke'
        result = await platform.action('emote', {'glyph': '?'})
        assert result['status'] == 'completed'
        finished.set()
    await platform.on_message(receive)
    await platform.connect()
    try:
        async with ClientSession() as client:
            ws = await authenticated(client, platform)
            await ws.send_json(packet('event', {'name': 'poke'}))
            act = await ws.receive_json()
            await ws.send_json(packet('act_result', {'act_id': act['id'], 'status': 'completed'}))
            await asyncio.wait_for(finished.wait(), 1)
            await ws.close()
    finally:
        await platform.disconnect()


def test_identity_lock_excludes_second_process_and_releases(tmp_path):
    lock = InstanceLock(tmp_path / 'identity.lock')
    try:
        with pytest.raises(RuntimeError, match='already awake'):
            InstanceLock(tmp_path / 'identity.lock')
    finally:
        lock.close()
    InstanceLock(tmp_path / 'identity.lock').close()
