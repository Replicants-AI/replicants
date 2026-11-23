"""Bounded localhost protocol fixture for isolated CI. This is not model validation."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

if os.environ.get('CI') != 'true' and os.environ.get('REPLICANTS_REMOTE_VALIDATION') != '1':
    raise SystemExit('This fixture belongs on an isolated remote runner.')

background_allowed = threading.Event()
background_allowed.set()
blocked_requests = 0
blocked_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def reply(self, value, status=200):
        content = json.dumps(value).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(content))); self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.path == '/fixture/state':
            with blocked_lock:
                self.reply({'held': not background_allowed.is_set(), 'blocked_requests': blocked_requests})
        elif self.path == '/fixture/release':
            background_allowed.set()
            self.reply({'released': True})
        elif self.path == '/api/version': self.reply({'version': 'beta-protocol-fixture'})
        elif self.path == '/api/tags': self.reply({'models': [{'name': 'beta-fixture:latest', 'size': 0}, {'name': 'beta-memory:latest', 'size': 0}]})
        elif self.path in {'/v1/models', '/models'}: self.reply({'data': [{'id': 'beta-fixture:latest'}, {'id': 'beta-memory:latest'}]})
        else: self.reply({'error': 'fixture route missing'}, 404)

    def do_POST(self):
        global blocked_requests
        size = int(self.headers.get('Content-Length', 0))
        if size > 2_000_000: self.reply({'error': 'too large'}, 413); return
        request = json.loads(self.rfile.read(size))
        if self.path == '/api/show':
            self.reply({'capabilities': ['embedding'] if 'memory' in request.get('model', '') else ['completion', 'tools']}); return
        if self.path in {'/v1/embeddings', '/embeddings', '/api/embeddings', '/api/embed'}:
            vector = [0.1] * 768
            self.reply({'data': [{'embedding': vector}], 'embedding': vector, 'embeddings': [vector]}); return
        if self.path not in {'/api/chat', '/v1/chat/completions', '/chat/completions'}:
            self.reply({'error': 'fixture route missing'}, 404); return
        if not background_allowed.is_set():
            with blocked_lock: blocked_requests += 1
            try:
                if not background_allowed.wait(180):
                    self.reply({'error': 'fixture background hold timed out'}, 503); return
            finally:
                with blocked_lock: blocked_requests -= 1
        time.sleep(.1)
        system = '\n'.join(str(m.get('content', '')) for m in request.get('messages', []) if m.get('role') == 'system')
        schema = request.get('format')
        decision_schema = isinstance(schema, dict) and 'action' in schema.get('properties', {})
        messages = request.get('messages', [])
        last = str(messages[-1].get('content', '')) if messages else ''
        if decision_schema and 'fixture-crash-after-reply' in last and 'Observed results:' not in last:
            content = json.dumps({'action': 'rest', 'args': {}, 'say': 'fixture reply saved before background work'})
            background_allowed.clear()
        elif decision_schema and 'fixture-room-read' in last and 'Observed results:' not in last:
            content = json.dumps({'action': 'open_page', 'args': {'url': 'https://www.iana.org/help/example-domains'}, 'say': ''})
        elif request.get('format') or 'Choose what your body does' in system:
            content = json.dumps({'action': 'rest', 'args': {}, 'say': 'hello from the protocol fixture'})
        elif 'appraisal layer' in system:
            content = json.dumps({'bar_effects': {'comfort': 2, 'social': 2}, 'tags': ['contact'], 'felt': 'an observed reply'})
        elif 'inner voice' in system:
            content = 'i feel a little curious\na small pressure to move\ni can stay here a moment'
        else: content = '{}'
        message = {'role': 'assistant', 'content': content}
        self.reply({'message': message, 'done': True, 'done_reason': 'stop', 'eval_count': 20,
                    'prompt_eval_count': 30, 'eval_duration': 100000000, 'total_duration': 100000000,
                    'choices': [{'message': message, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 30, 'completion_tokens': 20}})


ThreadingHTTPServer(('127.0.0.1', 11435), Handler).serve_forever()
