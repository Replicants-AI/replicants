import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from replicants.desktop.substrate import ComputeLedger, MeteredClient, Substrate, parse_gpu
from replicants.inference.types import ChatCompletionResult


@pytest.mark.asyncio
async def test_measured_cost_unknown_usage_failure_and_restart():
    tick, wall = [10.0], [1000.0]
    ledger = ComputeLedger(wall=lambda: wall[0], monotonic=lambda: tick[0])
    async def chat(*args, **kwargs):
        assert ledger.snapshot()['in_flight'][0]['elapsed_seconds'] == 0
        tick[0] += 2.5
        return ChatCompletionResult('a thought', usage={'prompt_tokens': 30, 'completion_tokens': 5})
    client = MeteredClient(SimpleNamespace(chat_completion=chat, embed=AsyncMock(return_value=[.1])), ledger)
    await client.chat_completion('model', [])
    await client.embed('embedding', 'memory')
    snapshot = ledger.snapshot()
    assert snapshot['totals']['chat']['elapsed_seconds'] == 2.5
    assert snapshot['totals']['chat']['reported_completion_tokens'] == 5
    assert snapshot['totals']['embedding']['requests_with_prompt_tokens'] == 0
    assert snapshot['last_request']['reported_tokens'] is None
    client.inner.chat_completion = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(TimeoutError): await client.chat_completion('model', [])
    assert ledger.snapshot()['totals']['chat']['failed'] == 1
    assert not ledger.snapshot()['in_flight']
    tick[0] += 12
    assert ledger.snapshot()['seconds_since_last_completed_thought'] == 12
    wall[0] += 120
    restored = ComputeLedger(ledger.persisted(), wall=lambda: wall[0], monotonic=lambda: 0)
    assert restored.snapshot()['seconds_since_last_completed_thought'] == 120
    assert restored.totals['chat']['reported_completion_tokens'] == 5
    assert not restored.snapshot()['in_flight']


@pytest.mark.asyncio
async def test_cancellation_does_not_claim_a_completed_thought():
    client = MeteredClient(SimpleNamespace(chat_completion=AsyncMock(side_effect=asyncio.CancelledError())))
    with pytest.raises(asyncio.CancelledError): await client.chat_completion('model', [])
    state = client.ledger.snapshot()
    assert state['totals']['chat']['cancelled'] == 1
    assert state['seconds_since_last_completed_thought'] is None and not state['in_flight']


@pytest.mark.asyncio
async def test_stream_is_in_flight_until_consumed_and_has_unknown_tokens():
    async def chunks():
        yield 'a'
        yield 'b'
    client = MeteredClient(SimpleNamespace(chat_completion=AsyncMock(return_value=chunks())))
    stream = await client.chat_completion('model', [], stream=True)
    assert client.ledger.snapshot()['in_flight']
    assert [chunk async for chunk in stream] == ['a', 'b']
    assert not client.ledger.snapshot()['in_flight']
    assert client.ledger.last_request['reported_tokens'] is None


def test_gpu_scope_and_missing_values_are_not_fabricated():
    devices = parse_gpu('0, 75, 1024, 8192\n1, [N/A], [N/A], 16384\n')
    assert devices[0]['memory_used_bytes'] == 1024 ** 3
    assert devices[0]['utilization_percent'] == 75
    assert devices[1]['memory_used_bytes'] is None
    assert devices[1]['utilization_percent'] is None
    assert parse_gpu('not a GPU reading') == []


@pytest.mark.asyncio
async def test_sensor_failure_stays_unknown_and_does_not_generate_inference(monkeypatch):
    monkeypatch.setattr('replicants.desktop.substrate.host_memory', lambda: {'status': 'available', 'available_bytes': 100})
    monkeypatch.setattr('replicants.desktop.substrate.gpu_sample', AsyncMock(side_effect=TimeoutError()))
    substrate = Substrate(ComputeLedger())
    await substrate.sample()
    snapshot = substrate.snapshot()
    assert snapshot['memory']['available_bytes'] == 100
    assert snapshot['gpu']['status'] == 'unavailable' and 'devices' not in snapshot['gpu']
    assert snapshot['gpu']['age_seconds'] >= 0
    assert snapshot['inference']['totals']['chat']['started'] == 0


@pytest.mark.asyncio
async def test_elapsed_compute_is_independent_of_simulation_scale(monkeypatch):
    monkeypatch.setenv('REPLICANTS_TIME_SCALE', '360')
    tick = [0.0]
    ledger = ComputeLedger(monotonic=lambda: tick[0])
    request = ledger.begin('chat', 'model')
    tick[0] = 3
    ledger.finish(request, 'completed', ChatCompletionResult('yes', usage={'completion_tokens': 7}))
    assert ledger.totals['chat']['elapsed_seconds'] == 3
    assert ledger.totals['chat']['reported_completion_tokens'] == 7
