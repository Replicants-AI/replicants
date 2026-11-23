import json

import pytest
from aiohttp import web

from replicants.desktop.decision import REST, instruction, parse, schema
from replicants.desktop.entity import BODY_TOOLS, DesktopEntity
from replicants.desktop.inference import DesktopOllama
from replicants.inference.openai_transport import OpenAICompatibleTransport
from replicants.inference.types import ChatCompletionResult
from replicants.models import Input


def test_parses_plain_fenced_and_prose_wrapped_json():
    assert parse('{"action":"wave","args":{},"say":""}', BODY_TOOLS).action == 'wave'
    fenced = parse('```json\n{"action": "sit", "args": {}, "say": "hm"}\n```', BODY_TOOLS)
    assert fenced.action == 'sit' and fenced.say == 'hm'
    assert fenced.calls() == [('sit', {}), ('say', {'text': 'hm'})]
    wrapped = parse('I think {"action": "inspect_window", "args": {"window_id": "w1"}} feels right', BODY_TOOLS)
    assert wrapped.args == {'window_id': 'w1'}


def test_invalid_answers_become_rest_never_a_guess():
    for text, error in (('I would like to wave', 'no_json_object'),
                        ('{"action": "open_browser"}', 'unknown_action'),
                        ('{"action": "emote", "args": {}}', 'emote_without_glyph'),
                        ('{"action": "say", "args": {}, "say": ""}', 'say_without_text')):
        choice = parse(text, BODY_TOOLS)
        assert choice.action == REST and not choice.valid and choice.error.startswith(error)
        assert choice.calls() == []


@pytest.mark.parametrize('action', [None, [], {}, 3])
def test_non_string_action_becomes_rest(action):
    choice = parse(json.dumps({'action': action}), BODY_TOOLS)
    assert not choice.valid and choice.calls() == []


@pytest.mark.parametrize('x', [None, 'far', float('nan'), float('inf'), 10 ** 400])
def test_invalid_point_coordinates_become_rest(x):
    choice = parse(json.dumps({'action': 'walk_to', 'args': {'target': 'point', 'x': x}}), BODY_TOOLS)
    assert not choice.valid and choice.error == 'point_without_x' and choice.calls() == []


def test_arguments_are_filtered_to_the_schema_and_speech_is_capped():
    choice = parse(json.dumps({'action': 'walk_to', 'args': {'target': 'roof', 'side': 'left', 'x': 'far', 'rm': '-rf'},
                               'say': 'x' * 400}), BODY_TOOLS)
    assert choice.args == {'side': 'left'}
    assert len(choice.say) <= 240
    assert parse('{"action": "say", "args": {"text": "hello"}, "say": ""}', BODY_TOOLS).calls() == [('say', {'text': 'hello'})]


def test_schema_and_instruction_cover_every_body_action_and_rest():
    actions = schema(BODY_TOOLS)['properties']['action']['enum']
    assert set(actions) == set(BODY_TOOLS) | {REST}
    text = instruction(BODY_TOOLS)
    assert all(f'- {name}' in text for name in actions)


@pytest.mark.asyncio
async def test_structured_decisions_use_native_api_with_schema_and_thinking():
    requests = []
    async def chat(request):
        requests.append(await request.json())
        return web.json_response({'message': {'role': 'assistant', 'content': '{"action":"rest","args":{},"say":""}',
                                              'thinking': 'quiet'}, 'done_reason': 'stop',
                                  'eval_count': 12, 'eval_duration': 100000000})
    app = web.Application(); app.router.add_post('/api/chat', chat)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0); await site.start()
    port = site._server.sockets[0].getsockname()[1]
    client = DesktopOllama(OpenAICompatibleTransport(f'http://127.0.0.1:{port}'))
    try:
        result = await client.chat_completion('any-model', [{'role': 'user', 'content': 'x'}],
                                              think=True, format=schema(BODY_TOOLS))
        assert requests[0]['think'] is True and requests[0]['format']['required'] == ['action', 'args', 'say']
        assert result.timings == {'eval_duration': .1}    # deliberate turns now report pace
    finally:
        await client.close(); await runner.cleanup()


class Body:
    def __init__(self): self.published, self.actions, self.connected = [], [], True
    async def publish(self, kind, payload): self.published.append((kind, payload)); return True
    async def action(self, name, args):
        result = {'name': name, 'act_id': str(len(self.actions)), 'status': 'completed', 'detail': 'sequence_finished'}
        self.actions.append(result); return result


class JsonClient:
    """A model with no tool calling at all."""
    def __init__(self, answers): self.answers, self.prompts = list(answers), []
    async def ensure_models(self, *args): return True, []
    async def embed(self, *args, **kwargs): return [.1] * 768
    async def close(self): pass
    async def chat_completion(self, model, messages, **kwargs):
        assert not kwargs.get('tools')
        self.prompts.append(messages)
        if 'Choose what your body does' in messages[0]['content']:
            return ChatCompletionResult(self.answers.pop(0) if self.answers else '{"action":"rest","args":{},"say":""}')
        return ChatCompletionResult('{}')


@pytest.mark.asyncio
@pytest.mark.parametrize('ending', ['nonsense', '{"action":"rest","args":{},"say":""}'])
async def test_a_model_without_tool_calling_lives_through_json_decisions(tmp_path, monkeypatch, ending):
    from replicants.desktop.runtime import DesktopRuntime, PERSON, desktop_config
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('REPLICANTS_EXECUTION_WORKSPACE_DIR', str(tmp_path))
    config = desktop_config()
    config.raw.setdefault('desktop', {})['decision_mode'] = 'json'
    config.harness.memory.database_path = str(tmp_path / 'memory.db')
    config.projects_path = lambda: str(tmp_path / 'projects.json')
    config.self_model_path = lambda: str(tmp_path / 'self_model.json')
    config.harness.memory.relational.enabled = False
    config.harness.memory.distillation.enabled = False
    config.harness.soma['noise']['enabled'] = False
    client = JsonClient(['{"action":"wave","args":{},"say":"oh, hi"}', ending])
    monkeypatch.setattr('replicants.entity.build_inference_provider', lambda _: client)
    runtime = DesktopRuntime(DesktopEntity(config), Body())
    stimulus = Input('hello little one', PERSON, 'the person here', 'desktop', 'desktop')
    if ending == 'nonsense':
        from replicants.desktop.entity import DesktopTurnError
        with pytest.raises(DesktopTurnError, match='valid body decision'):
            await runtime.entity.perceive(stimulus)
    else:
        await runtime.entity.perceive(stimulus)
    assert [a['name'] for a in runtime.platform.actions] == ['wave', 'say']
    assert runtime.entity.decision_stats == ({'valid': 1, 'invalid': 1, 'errors': {'no_json_object': 1}}
        if ending == 'nonsense' else {'valid': 2, 'invalid': 0, 'errors': {}})
    await runtime.entity.shutdown()


class FailingWalkBody(Body):
    async def action(self, name, args):
        status = 'failed' if name == 'walk_to' else 'completed'
        result = {'name': name, 'act_id': str(len(self.actions)), 'status': status, 'detail': 'no_reachable_path'}
        self.actions.append(result); return result


@pytest.mark.asyncio
async def test_speech_paired_with_a_failed_action_is_not_spoken(tmp_path, monkeypatch):
    from replicants.desktop.runtime import DesktopRuntime, PERSON, desktop_config
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('REPLICANTS_EXECUTION_WORKSPACE_DIR', str(tmp_path))
    config = desktop_config()
    config.raw.setdefault('desktop', {})['decision_mode'] = 'json'
    config.harness.memory.database_path = str(tmp_path / 'memory.db')
    config.projects_path = lambda: str(tmp_path / 'projects.json')
    config.self_model_path = lambda: str(tmp_path / 'self_model.json')
    config.harness.memory.relational.enabled = False
    config.harness.memory.distillation.enabled = False
    config.harness.soma['noise']['enabled'] = False
    client = JsonClient(['{"action":"walk_to","args":{"target":"cursor"},"say":"walking toward you"}',
                         '{"action":"rest","args":{},"say":""}'])
    monkeypatch.setattr('replicants.entity.build_inference_provider', lambda _: client)
    runtime = DesktopRuntime(DesktopEntity(config), FailingWalkBody())
    await runtime.entity.perceive(Input('come here', PERSON, 'the person here', 'desktop', 'desktop'))
    assert [a['name'] for a in runtime.platform.actions] == ['walk_to']
    observed = next(m['content'] for m in client.prompts[1] if m['role'] == 'user' and 'Observed results' in m['content'])
    assert '"not_spoken"' in observed and 'paired_action_did_not_complete' in observed
    await runtime.entity.shutdown()
