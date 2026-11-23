"""Model-agnostic decisions: one JSON object per round, validated before the body acts.

Native tool calling depends on a model having been trained for it. A schema-constrained
JSON choice works with any model that can write JSON. Ollama's structured outputs
constrain the shape; truncated or invalid answers still become rest, never a guess.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import re
from replicants.desktop.room import ROOM_REQUIRED

REST = 'rest'
SPEECH_LIMIT = 240


def clip_speech(text: str, limit: int = SPEECH_LIMIT) -> str:
    """Fit speech to the bubble without cutting a word: end at a sentence if one ends late enough."""
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    if len(text) <= limit:
        return text
    head = text[:limit + 1]
    sentence = max(head.rfind(mark, 0, limit) for mark in ('. ', '! ', '? ', '… '))
    if sentence >= limit * 0.5:
        return head[:sentence + 1].strip()
    space = head.rfind(' ', 0, limit - 1)
    return (head[:space] if space > 0 else head[:limit - 1]).rstrip(' ,;:-—') + '…'


@dataclass
class Decision:
    action: str
    args: dict = field(default_factory=dict)
    say: str = ''
    valid: bool = True
    error: str = ''

    def calls(self) -> list[tuple[str, dict]]:
        """The body actions this decision asks for, in order. Speech follows the action."""
        calls = [] if self.action == REST else [(self.action, self.args)]
        if self.say and self.action != 'say':
            calls.append(('say', {'text': self.say}))
        return calls


def schema(body_tools: dict) -> dict:
    return {'type': 'object', 'additionalProperties': False, 'required': ['action', 'args', 'say'],
            'properties': {'action': {'type': 'string', 'enum': [*body_tools, REST]},
                           'args': {'type': 'object'},
                           'say': {'type': 'string', 'maxLength': SPEECH_LIMIT}}}


def instruction(body_tools: dict) -> str:
    lines = []
    for name, (description, properties) in body_tools.items():
        args = ', '.join(f'{key}: ' + ('|'.join(spec['enum']) if 'enum' in spec else spec['type'])
                         for key, spec in properties.items())
        lines.append(f'- {name}' + (f' {{{args}}}' if args else '') + f': {description}')
    return ('Choose what your body does by answering with exactly one JSON object and nothing else:\n'
            '{"action": "<one action>", "args": {<arguments>}, "say": "<optional words, or empty>"}\n'
            'Actions:\n' + '\n'.join(lines) + '\n'
            f'- {REST}: do nothing now. Choosing rest with empty "say" is complete silence.\n'
            f'"say" is optional speech of at most {SPEECH_LIMIT} characters. Leave it empty unless you want to speak.')


def _first_object(text: str):
    text = re.sub(r'```(?:json)?', '', text or '')
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{', text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _valid_arg(spec: dict, value) -> bool:
    if 'enum' in spec:
        return value in spec['enum']
    if spec.get('type') == 'string':
        return isinstance(value, str)
    if spec.get('type') == 'number' and isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return math.isfinite(value)
        except OverflowError:
            return False
    return False


def parse(text: str, body_tools: dict) -> Decision:
    value = _first_object(text)
    if value is None:
        return Decision(REST, valid=False, error='no_json_object')
    action = value.get('action')
    if not isinstance(action, str) or (action != REST and action not in body_tools):
        return Decision(REST, valid=False, error=f'unknown_action:{str(action)[:40]}')
    raw = value.get('args') if isinstance(value.get('args'), dict) else {}
    properties = body_tools[action][1] if action in body_tools else {}
    args = {k: v for k, v in raw.items() if k in properties and _valid_arg(properties[k], v)}
    say = value.get('say') if isinstance(value.get('say'), str) else ''
    say = clip_speech(say)
    for required in ROOM_REQUIRED.get(action, []):
        if not args.get(required): return Decision(REST, valid=False, error=f'{action}_without_{required}')
    if action in {'walk_to', 'look_at'} and args.get('target') == 'point' and 'x' not in args:
        return Decision(REST, valid=False, error='point_without_x')
    if action == 'say':
        text_arg = clip_speech(args.get('text') or say)
        if not text_arg:
            return Decision(REST, valid=False, error='say_without_text')
        return Decision('say', {'text': text_arg})
    if action == 'emote' and not args.get('glyph'):
        return Decision(REST, valid=False, error='emote_without_glyph')
    return Decision(action, args, say)
