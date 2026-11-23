"""Local runtime readiness, one-button setup, and explicit model downloads. Never runs inference."""
from __future__ import annotations

import asyncio
import json
import shutil
from typing import Callable

import aiohttp
import psutil

from replicants.desktop import hardware, local_runtime, settings


def _same_model(actual: str, requested: str) -> bool:
    return actual == requested or (':' not in requested.rsplit('/', 1)[-1]
                                   and actual == requested + ':latest')


async def check(preferences: dict | None = None) -> dict:
    prefs = settings.validate(preferences) if preferences is not None else settings.load()
    memory = psutil.virtual_memory()
    root = settings.data_home()
    root.mkdir(parents=True, exist_ok=True)
    if prefs['runtime'] == 'managed' and local_runtime.installed():
        try:
            await local_runtime.ensure_running()
        except local_runtime.RuntimeUnavailable as exc:
            prefs_issue = str(exc)
        else:
            prefs_issue = None
    else:
        prefs_issue = None
    base = settings.inference_url(prefs)
    report = {'settings': prefs, 'ollama': {'available': False, 'version': None},
              'runtime': {'mode': prefs['runtime'], 'url': base, **local_runtime.status()},
              'models': [], 'ready': False, 'missing': [], 'issues': [],
              'hardware': {'ram_total_bytes': memory.total, 'ram_available_bytes': memory.available,
                           'disk_free_bytes': shutil.disk_usage(root).free},
              'privacy': 'Inference stays on localhost. Model downloads need internet access.'}
    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.get(base + '/api/version', allow_redirects=False) as response:
                response.raise_for_status()
                version = await response.json()
            async with client.get(base + '/api/tags', allow_redirects=False) as response:
                response.raise_for_status()
                tags = await response.json()
            report['ollama'] = {'available': True, 'version': version.get('version')}
            report['models'] = [{'name': str(item.get('name', ''))[:200],
                                 'size': item.get('size'), 'digest': item.get('digest')}
                                for item in tags.get('models', []) if isinstance(item, dict)
                                and not item.get('remote_host') and not item.get('remote_model')
                                and not settings.cloud_model(str(item.get('name', '')))]
            for kind, key in (('chat', 'chat_model'), ('memory', 'embedding_model')):
                if not any(_same_model(item['name'], prefs[key]) for item in report['models']):
                    report['missing'].append({'kind': kind, 'name': prefs[key]})
            if not report['missing']:
                # Model metadata is a readiness check, not a prompt or inference call.
                async with client.post(base + '/api/show',
                                       json={'model': prefs['chat_model']}, allow_redirects=False) as response:
                    response.raise_for_status()
                    shown = await response.json()
                capabilities = shown.get('capabilities')
                if shown.get('remote_host') or shown.get('remote_model'):
                    report['issues'].append('The chat model points to a remote host. Choose a downloaded local model.')
                report['chat_capabilities'] = capabilities
                if isinstance(capabilities, list):
                    if 'completion' not in capabilities:
                        report['issues'].append('The chat model must support text completion.')
                    if prefs['decision_mode'] == 'tools' and 'tools' not in capabilities:
                        report['issues'].append('This model does not report tool support. Choose JSON mode.')
                async with client.post(base + '/api/show',
                                       json={'model': prefs['embedding_model']}, allow_redirects=False) as response:
                    response.raise_for_status()
                    embedding = await response.json()
                capabilities = embedding.get('capabilities')
                if embedding.get('remote_host') or embedding.get('remote_model'):
                    report['issues'].append('The memory model points to a remote host. Choose a downloaded local model.')
                if isinstance(capabilities, list) and 'embedding' not in capabilities:
                    report['issues'].append('The memory model must support embeddings.')
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError) as exc:
        report['issues'].append(prefs_issue or ('Thought is not ready yet. Choose Set up.' if prefs['runtime'] != 'external'
                                else 'Ollama is not ready. Start or install Ollama, then check again. '
                                f'({type(exc).__name__})'))
    report['ready'] = bool(report['ollama']['available'] and not report['missing'] and not report['issues'])
    return report


async def pull(model: str, emit: Callable[[dict], None], *, stage: str | None = None) -> None:
    prefs = settings.load()
    if model not in {prefs['chat_model'], prefs['embedding_model']}:
        raise ValueError('Save the selected chat or memory model before downloading it.')
    base = settings.inference_url(prefs)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=120)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        async with client.post(base + '/api/pull', json={'model': model, 'stream': True},
                               allow_redirects=False) as response:
            response.raise_for_status()
            async for line in response.content:
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get('error'):
                    raise ValueError(str(data['error'])[:500])
                event = {key: data[key] for key in ('status', 'digest', 'total', 'completed') if key in data}
                emit({**event, 'stage': stage} if stage else event)


async def require_ready() -> None:
    report = await check()
    if not report['ready']:
        missing = ', '.join(item['name'] for item in report['missing'])
        raise ValueError('Local models are not ready. Open Setup in Replicants. '
                         + ('Missing: ' + missing if missing else ' '.join(report['issues'])))


async def _external_running(url: str) -> bool:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as client:
            async with client.get(url + '/api/version', allow_redirects=False) as response:
                return response.status == 200
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return False


async def prepare(emit: Callable[[dict], None]) -> dict:
    """One button for people who have never opened a terminal.

    Checks the computer, gets thought running (an Ollama already on this computer,
    or the app's own private runtime), picks a mind that fits, and downloads what is
    missing, reporting progress in plain words. Nothing here runs inference.
    """
    prefs = settings.load()
    emit({'stage': 'survey', 'status': 'checking this computer'})
    survey = await hardware.survey()
    emit({'stage': 'survey', 'status': survey['message'], 'survey': survey})
    if survey['verdict'] == 'not_yet':
        raise ValueError(survey['message'])
    if prefs['runtime'] == 'auto':
        prefs['runtime'] = 'external' if await _external_running(prefs['ollama_url']) else 'managed'
    if prefs['runtime'] == 'managed':
        if not local_runtime.status()['supported_platform']:
            raise ValueError('The built-in runtime is available on Windows. Install Ollama, then choose Check again.')
        await local_runtime.install(emit)
        emit({'stage': 'runtime', 'status': 'starting'})
        await local_runtime.ensure_running()
    elif not await _external_running(prefs['ollama_url']):
        raise ValueError('Ollama is not running. Start it, or switch the runtime to automatic in Settings.')
    # Only replace the model choice if the person has not chosen one themselves.
    if prefs['chat_model'] == settings.DEFAULTS['chat_model'] and survey['chat_model']:
        prefs['chat_model'] = survey['chat_model']
    prefs = settings.save(prefs)
    report = await check(prefs)
    for item in report['missing']:
        await pull(item['name'], emit, stage='mind' if item['kind'] == 'chat' else 'memory')
    report = await check(prefs)
    emit({'stage': 'done', 'ready': report['ready'], 'status': 'ready' if report['ready'] else 'not ready'})
    return report
