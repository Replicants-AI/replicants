"""Measured compute interoception: the body reads its real conditions."""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress
from copy import deepcopy
import csv
import logging
import math
import os
import shutil
import subprocess
import time

import psutil

log = logging.getLogger(__name__)


def measurement(value):
    """Unavailable counters stay unknown; they are never substituted with zero."""
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


class ComputeLedger:
    def __init__(self, saved=None, *, wall=time.time, monotonic=time.monotonic):
        self.wall, self.monotonic = wall, monotonic
        saved = saved or {}
        self.since = saved.get('since', wall())
        self.totals = deepcopy(saved.get('totals', {}))
        for kind in ('chat', 'embedding'):
            counters = self.totals.setdefault(kind, {})
            for key in ('started', 'completed', 'failed', 'cancelled', 'elapsed_seconds',
                        'reported_prompt_tokens', 'reported_completion_tokens',
                        'requests_with_prompt_tokens', 'requests_with_completion_tokens'):
                counters.setdefault(key, 0)
        self.last_request = saved.get('last_request')
        self.last_chat_at = saved.get('last_chat_completed_at')
        self._last_chat_end = None
        self._active = {}
        self._sequence = 0
        # Each finished request is delivered once to every listener, so
        # consumers never reconstruct work by diffing totals between samples.
        self.listeners = []

    def begin(self, kind, model):
        self._sequence += 1
        self._active[self._sequence] = {'kind': kind, 'model': model, 'started': self.monotonic()}
        self.totals[kind]['started'] += 1
        return self._sequence

    def finish(self, key, status, result=None):
        request = self._active.pop(key)
        elapsed = max(0, self.monotonic() - request['started'])
        totals = self.totals[request['kind']]
        totals[status] += 1
        totals['elapsed_seconds'] += elapsed
        usage = {}
        for name in ('prompt_tokens', 'completion_tokens'):
            value = measurement(getattr(result, 'usage', {}).get(name))
            if value is not None:
                usage[name] = int(value)
                totals['reported_' + name] += int(value)
                totals['requests_with_' + name] += 1
        self.last_request = {'kind': request['kind'], 'model': request['model'],
            'status': status, 'finished_at': self.wall(), 'elapsed_seconds': elapsed,
            'reported_tokens': usage or None, 'provider_seconds': getattr(result, 'timings', {}) or None}
        if status == 'completed' and request['kind'] == 'chat':
            self.last_chat_at = self.wall()
            self._last_chat_end = self.monotonic()
        observation = {'kind': request['kind'], 'model': request['model'], 'status': status,
            'started': request['started'], 'finished': request['started'] + elapsed,
            'elapsed_seconds': elapsed, 'reported_tokens': usage,
            'provider_seconds': dict(getattr(result, 'timings', {}) or {})}
        for listener in list(self.listeners):
            try:
                listener(observation)
            except Exception:
                # Telemetry must never turn a completed inference into a failure.
                log.exception('compute_listener_failed')

    def active_starts(self):
        """Monotonic start times of requests still in flight."""
        return [request['started'] for request in self._active.values()]

    def persisted(self):
        # In-flight work is not restored as if an old process were still thinking.
        return deepcopy({'since': self.since, 'totals': self.totals, 'last_request': self.last_request,
                         'last_chat_completed_at': self.last_chat_at})

    def snapshot(self):
        since = (max(0, self.monotonic() - self._last_chat_end) if self._last_chat_end is not None
                 else max(0, self.wall() - self.last_chat_at) if self.last_chat_at is not None else None)
        return {**self.persisted(), 'seconds_since_last_completed_thought': since,
            'in_flight': [{'kind': r['kind'], 'model': r['model'],
                'elapsed_seconds': max(0, self.monotonic() - r['started'])} for r in self._active.values()],
            'accounting': 'Reported tokens only; missing usage and work in failed/retried requests may be unreported. '
                'Elapsed seconds include transport, queueing, retries and inference; they are not GPU seconds. '
                'A thought here means a completed chat inference, including auxiliary calls.'}


class MeteredClient:
    """Meter the actual provider calls, including embeddings and failed requests."""
    def __init__(self, client, ledger=None):
        self.inner = client
        self.ledger = ledger or ComputeLedger()
        self.calls = deque(maxlen=10000)  # Existing diagnostic chat-call counter.

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def chat_completion(self, model, *args, **kwargs):
        self.calls.append(self.ledger.wall())
        key = self.ledger.begin('chat', model)
        try:
            result = await self.inner.chat_completion(model, *args, **kwargs)
        except BaseException as exc:
            self.ledger.finish(key, 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed')
            raise
        if hasattr(result, '__aiter__'):
            async def stream():
                status = 'cancelled'
                try:
                    async for chunk in result:
                        yield chunk
                    status = 'completed'
                except Exception:
                    status = 'failed'
                    raise
                finally:
                    self.ledger.finish(key, status)
            return stream()
        self.ledger.finish(key, 'completed', result)
        return result

    async def embed(self, model, *args, **kwargs):
        key = self.ledger.begin('embedding', model)
        try:
            result = await self.inner.embed(model, *args, **kwargs)
        except BaseException as exc:
            self.ledger.finish(key, 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed')
            raise
        # The inherited embedding API returns a vector, not token usage.
        self.ledger.finish(key, 'completed')
        return result


def host_memory():
    memory = psutil.virtual_memory()
    return {'status': 'available', 'source': 'psutil', 'scope': 'host RAM and this Python brain process',
        'total_bytes': memory.total, 'available_bytes': memory.available,
        'used_percent': memory.percent, 'brain_rss_bytes': psutil.Process().memory_info().rss}


def parse_gpu(output):
    devices = []
    for row in csv.reader(output.splitlines()):
        if len(row) != 4:
            continue
        index, utilization, used, total = (measurement(value.strip()) for value in row)
        if index is None:
            continue
        devices.append({'index': int(index), 'utilization_percent': utilization,
            'memory_used_bytes': int(used * 1024 ** 2) if used is not None else None,
            'memory_total_bytes': int(total * 1024 ** 2) if total is not None else None})
    return devices[:8]


async def gpu_sample():
    executable = shutil.which('nvidia-smi')
    if not executable:
        return {'status': 'unavailable', 'reason': 'nvidia-smi not installed; no supported GPU sensor'}
    process = await asyncio.create_subprocess_exec(executable,
        '--query-gpu=index,utilization.gpu,memory.used,memory.total', '--format=csv,noheader,nounits',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 3)
        devices = parse_gpu(output.decode('utf-8', errors='replace'))
        if process.returncode or not devices:
            return {'status': 'unavailable', 'reason': 'GPU driver returned no supported measurements'}
        return {'status': 'available', 'source': 'nvidia-smi',
            'scope': 'whole devices, shared with other applications; not attributed to this Replicant',
            'devices': devices}
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.communicate()


class Substrate:
    """Real-time sensors run separately from cognition and simulation time."""
    def __init__(self, ledger):
        self.ledger = ledger
        self.hardware = {'memory': {'status': 'not_sampled'}, 'gpu': {'status': 'not_sampled'}}
        self._sampled = {}

    async def sample(self):
        for name, sensor in (('memory', lambda: asyncio.to_thread(host_memory)), ('gpu', gpu_sample)):
            try:
                self.hardware[name] = await sensor()
            except (OSError, TimeoutError, psutil.Error):
                self.hardware[name] = {'status': 'unavailable', 'reason': 'sensor failed'}
            self._sampled[name] = time.monotonic()

    def snapshot(self):
        return {'inference': self.ledger.snapshot(), **{name: {**deepcopy(value),
            'age_seconds': max(0, time.monotonic() - self._sampled[name]) if name in self._sampled else None}
            for name, value in self.hardware.items()}}
