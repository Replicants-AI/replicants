"""Desktop Ollama adapter that actually honors non-thinking auxiliary calls."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import aiohttp

from replicants.inference.providers import LocalRuntimeProvider
from replicants.desktop.substrate import measurement
from replicants.desktop.room import ROOM_SENSE


SUBCONSCIOUS = 'You are the subconscious of'
BOUNDARY = ('Desktop sensory boundary: supplied body state, completed action receipts, recorded events, '
            'geometry, activity and memories are observations. The person\'s screen contents stay unknown. '
            'The being\'s own Room supplies attributed text through confirmed reading receipts. ' + ROOM_SENSE + ' '
            'Inner fragments are its own subconscious thoughts and images. They can be about anything and they '
            'shape how it feels, and they are remembered as thoughts it had, never as events or as anyone else\'s words.\n\n')


class NativeToolProtocolError(ValueError):
    """The provider could generate text but could not decode its native tool syntax."""


class DesktopOllama(LocalRuntimeProvider):
    async def chat_completion(self, model, messages, *, tools=None, tool_choice=None,
                              temperature=.7, max_tokens=1024, think=False,
                              stream=False, num_ctx=None, format=None):
        # Structured decisions use the native API, which honors a JSON schema with or
        # without thinking. Other thinking/streaming calls keep the inherited transport.
        if stream or (think and format is None):
            return await super().chat_completion(model, messages, tools=tools, tool_choice=tool_choice,
                temperature=temperature, max_tokens=max_tokens, think=think, stream=stream, num_ctx=num_ctx)
        # Appraisal, affect and memory prompts share deliberate cognition's sensory
        # boundary, including before a name exists. GEN, the subconscious, does not.
        messages = deepcopy(messages)
        for message in messages:
            # The entity keeps OpenAI history (JSON-string arguments and `name`
            # on tool results). /api/chat uses argument objects and `tool_name`.
            # Translate at this transport boundary without changing the history.
            for call in message.get('tool_calls') or []:
                function = call['function']
                arguments = function.get('arguments', {})
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    raise ValueError('Native tool arguments must be a JSON object.')
                function['arguments'] = arguments
            if message.get('role') == 'tool' and message.get('name'):
                message['tool_name'] = message['name']
        for message in messages:
            content = message.get('content')
            # The subconscious is free; every other auxiliary call keeps the senses honest.
            if message.get('role') == 'system' and isinstance(content, str) and not content.startswith(SUBCONSCIOUS):
                message['content'] = BOUNDARY + content
        # The inherited /v1 adapter only *prompts* for no thinking. With this
        # Gemma build, short appraisal/GEN budgets were entirely consumed by
        # reasoning (finish_reason=length, empty content). Native think:false
        # controls the runtime itself without changing model or token defaults.
        payload = {'model': model, 'messages': messages, 'think': bool(think), 'stream': False,
                   'options': {'temperature': temperature, 'num_predict': max_tokens}}
        if num_ctx is not None: payload['options']['num_ctx'] = num_ctx
        if tools: payload['tools'] = tools
        if format is not None: payload['format'] = format
        session = await self._t._session_get()
        for attempt in range(self._t.retry_attempts):
            try:
                async with session.post(self._t.base_url + '/api/chat', json=payload, allow_redirects=False) as response:
                    if tools and response.status == 500:
                        try: detail = await response.json(content_type=None)
                        except (ValueError, aiohttp.ClientError): detail = {}
                        error = str(detail.get('error', '')).lower() if isinstance(detail, dict) else ''
                        if 'tool' in error and ('pars' in error or 'invalid' in error):
                            # Repeating the same native prompt can repeat a cached
                            # parser failure. Let the embodied turn recover as JSON.
                            raise NativeToolProtocolError('native_tool_parse_error')
                    response.raise_for_status()
                    data = await response.json()
                if data.get('error'): raise RuntimeError(str(data['error']))
                message = data.get('message', {})
                if message.get('thinking'): message['reasoning_content'] = message['thinking']
                usage = {target: int(value) for source, target in (
                    ('prompt_eval_count', 'prompt_tokens'), ('eval_count', 'completion_tokens'))
                    if (value := measurement(data.get(source))) is not None}
                result = self._t._parse_chat_response({'choices': [{'message': message, 'finish_reason': data.get('done_reason')}],
                    'usage': usage})
                result.timings = {name: value / 1_000_000_000 for name in (
                    'total_duration', 'load_duration', 'prompt_eval_duration', 'eval_duration')
                    if (value := measurement(data.get(name))) is not None}
                return result
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt + 1 >= self._t.retry_attempts: raise
                await asyncio.sleep(self._t.retry_delay * 2 ** attempt)
