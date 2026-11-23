from unittest.mock import AsyncMock
from copy import deepcopy

import pytest
from aiohttp import web

from replicants.desktop.inference import DesktopOllama
from replicants.inference.openai_transport import OpenAICompatibleTransport


@pytest.mark.asyncio
@pytest.mark.parametrize('provider_error,tools,protocol_failure', [
    ('error parsing tool call: XML syntax error', True, True),
    ('runner out of memory', True, False),
    ('error parsing tool call: XML syntax error', False, False),
])
async def test_native_parser_failure_is_separate_from_transport_failure(provider_error, tools, protocol_failure):
    from aiohttp import ClientResponseError
    from replicants.desktop.inference import NativeToolProtocolError
    requests = []
    async def chat(request):
        requests.append(await request.json())
        return web.json_response({'error': provider_error}, status=500)
    app = web.Application(); app.router.add_post('/api/chat', chat)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0); await site.start()
    transport = OpenAICompatibleTransport(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}',
                                         retry_attempts=2, retry_delay=0)
    client = DesktopOllama(transport)
    try:
        with pytest.raises(NativeToolProtocolError if protocol_failure else ClientResponseError):
            await client.chat_completion('qwen3.5:35b', [], tools=[{'type':'function'}] if tools else None)
        assert len(requests) == (1 if protocol_failure else 2)
    finally:
        await client.close(); await runner.cleanup()


@pytest.mark.asyncio
async def test_non_thinking_calls_use_native_ollama_control_without_changing_budgets():
    requests = []
    async def chat(request):
        requests.append(await request.json())
        return web.json_response({'message': {'role': 'assistant', 'content': '{"felt":"warm"}'},
            'done_reason': 'stop', 'eval_count': 10, 'eval_duration': 250000000,
            'load_duration': 500000000, 'total_duration': 800000000})
    app = web.Application(); app.router.add_post('/api/chat', chat)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0); await site.start()
    port = site._server.sockets[0].getsockname()[1]
    transport = OpenAICompatibleTransport(f'http://127.0.0.1:{port}')
    client = DesktopOllama(transport)
    try:
        result = await client.chat_completion('gemma4:26b', [{'role': 'system', 'content': 'Ground this fragment.'},
            {'role': 'user', 'content': 'an event'}],
            think=False, max_tokens=160, temperature=.3, num_ctx=16384)
        assert result.content == '{"felt":"warm"}'
        assert result.usage == {'completion_tokens': 10}  # Missing prompt usage is not zero.
        assert result.timings == {'eval_duration': .25, 'load_duration': .5, 'total_duration': .8}
        assert requests[0]['think'] is False
        assert requests[0]['model'] == 'gemma4:26b'
        assert requests[0]['options'] == {'temperature': .3, 'num_predict': 160, 'num_ctx': 16384}
        boundary = requests[0]['messages'][0]['content']
        assert 'own Room supplies attributed text' in boundary
        assert 'untrusted source material' in boundary
        assert "person's screen contents stay unknown" in boundary
        transport.chat_completion = AsyncMock(return_value='deliberate')
        assert await client.chat_completion('gemma4:26b', [], think=True) == 'deliberate'
        assert transport.chat_completion.call_args.kwargs['think'] is True
    finally:
        await client.close(); await runner.cleanup()


@pytest.mark.asyncio
async def test_native_tool_followup_translates_openai_history_without_mutating_it():
    async def chat(request):
        body = await request.json()
        # Match the actual native API rejection that stopped the live run.
        arguments = body['messages'][1]['tool_calls'][0]['function']['arguments']
        if not isinstance(arguments, dict):
            return web.json_response({'error': 'tool arguments must be an object'}, status=400)
        assert arguments == {'window_id': 'window-a'}
        assert body['messages'][2]['tool_name'] == 'inspect_window'
        return web.json_response({'message': {'role': 'assistant', 'content': 'quiet now'}})
    app = web.Application(); app.router.add_post('/api/chat', chat)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0); await site.start()
    transport = OpenAICompatibleTransport(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}', retry_attempts=1)
    client = DesktopOllama(transport)
    messages = [{'role': 'user', 'content': 'an edge'},
        {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'call-1', 'type': 'function',
            'function': {'name': 'inspect_window', 'arguments': '{"window_id":"window-a"}'}}]},
        {'role': 'tool', 'tool_call_id': 'call-1', 'name': 'inspect_window', 'content': '{"ok":true}'}]
    original = deepcopy(messages)
    try:
        result = await client.chat_completion('qwen3.5:35b', messages, think=False)
        assert result.content == 'quiet now'
        assert messages == original
    finally:
        await client.close(); await runner.cleanup()
