"""Validated host preferences; never part of an immutable genome."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from replicants.desktop.protocol import private_write

DEFAULTS = {
    'version': 1, 'ollama_url': 'http://127.0.0.1:11434',
    'chat_model': 'gemma4:26b', 'embedding_model': 'nomic-embed-text',
    'decision_mode': 'json', 'context_tokens': 8192, 'reply_tokens': 1024,
    'thinking': False, 'body_scale': 6, 'ambient': True,
    'show_thoughts': False, 'reduced_motion': False, 'hide_fullscreen': True,
    'max_wakes_per_hour': 6,
    # 'auto' resolves during setup: an Ollama you installed if one is running, otherwise
    # the private runtime the app manages itself (replicants/desktop/local_runtime.py).
    'runtime': 'auto',
}
MODEL_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}$')


def cloud_model(name: str) -> bool:
    tag = name.rsplit(':', 1)[-1].lower()
    return tag == 'cloud' or tag.endswith('-cloud')


def data_home() -> Path:
    override = os.environ.get('REPLICANTS_DATA_HOME')
    return Path(override).expanduser().resolve() if override else Path.home() / '.replicants'


def settings_path() -> Path:
    return data_home() / 'desktop-settings.json'


def validate(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError('Settings must be an object.')
    if value.get('version', 1) != 1:
        raise ValueError('These settings were written by a newer application.')
    result = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in value:
            result[key] = value[key]
    endpoint = result['ollama_url']
    if not isinstance(endpoint, str):
        raise ValueError('Ollama address must be a local HTTP address.')
    parsed = urlsplit(endpoint)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError('Invalid Ollama port.') from exc
    if (parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {'', '/'} or (port is not None and not 1 <= port <= 65535)):
        raise ValueError('Ollama must use localhost HTTP without a path or credentials.')
    result['ollama_url'] = endpoint.rstrip('/')
    for key in ('chat_model', 'embedding_model'):
        if not isinstance(result[key], str) or not MODEL_NAME.fullmatch(result[key]):
            raise ValueError(f'Invalid {key.replace("_", " ")}.')
        if cloud_model(result[key]):
            raise ValueError('Choose a downloaded local model. Ollama cloud models are outside the desktop beta.')
    if result['runtime'] not in {'auto', 'managed', 'external'}:
        raise ValueError('Choose auto, managed or external local runtime.')
    if result['decision_mode'] not in {'tools', 'json'}:
        raise ValueError('Choose tools or JSON decision mode.')
    for key, low, high in (('context_tokens', 2048, 32768), ('reply_tokens', 256, 4096),
                           ('body_scale', 3, 12), ('max_wakes_per_hour', 1, 12)):
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError(f'{key.replace("_", " ")} must be between {low} and {high}.')
    for key in ('thinking', 'ambient', 'show_thoughts', 'reduced_motion', 'hide_fullscreen'):
        if type(result[key]) is not bool:
            raise ValueError(f'{key.replace("_", " ")} must be true or false.')
    return result


def inference_url(prefs: dict) -> str:
    """Where thought runs: the app's private runtime, or the person's own Ollama."""
    if prefs.get('runtime') == 'managed':
        from replicants.desktop.local_runtime import URL
        return URL
    return prefs['ollama_url']


def load() -> dict:
    path = settings_path()
    if not path.exists():
        return dict(DEFAULTS)
    try:
        return validate(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError('Desktop settings could not be read. Your life files are unchanged. '
                         f'Open settings to repair them. ({exc})') from exc


def save(value: dict) -> dict:
    result = validate(value)
    private_write(settings_path(), result)
    return result


def apply(config):
    """The packaged application opts in; inherited harness entry points stay separate."""
    if not settings_path().is_file() and os.environ.get('REPLICANTS_BETA') != '1':
        return config
    prefs = load()
    config.harness.inference.base_url = inference_url(prefs)
    config.harness.inference.provider = 'local'
    config.harness.ollama.base_url = inference_url(prefs)
    config.harness.deployment.mode = 'local'
    config.harness.models.reflex = config.harness.models.deliberate = prefs['chat_model']
    config.harness.models.embedding = prefs['embedding_model']
    config.cognition.reflex_model = config.cognition.deliberate_model = prefs['chat_model']
    config.cognition.max_context_tokens = prefs['context_tokens']
    config.cognition.deliberate_max_tokens = prefs['reply_tokens']
    config.harness.cognition.reflex_max_tokens = prefs['reply_tokens']
    config.cognition.thinking_mode = prefs['thinking']
    config.harness.cognition.thinking_mode = prefs['thinking']
    config.harness.cognition.deliberate_max_tokens = prefs['reply_tokens']
    config.raw.setdefault('desktop', {})['decision_mode'] = prefs['decision_mode']
    config.harness.autonomy.max_cycles_per_hour = prefs['max_wakes_per_hour']
    return config
