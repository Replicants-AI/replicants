"""Authenticated loopback desktop platform; body tools await observed outcomes."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import math
import os
from pathlib import Path
import secrets
import time
from typing import Any, Callable

from aiohttp import WSMsgType, web

from replicants.desktop.protocol import InstanceLock, VERSION, RESULT_STATES, decode, packet, private_write
from replicants.presence.platforms.base import Platform

ALLOWED_ORIGINS = {'http://tauri.localhost', 'https://tauri.localhost', 'tauri://localhost',
                   'http://127.0.0.1:1420', 'http://localhost:1420'}


class DesktopPlatform(Platform):
    def __init__(self, session_path: Path | None = None):
        from replicants.desktop.settings import data_home
        self.session_path = session_path or Path(os.environ.get('REPLICANTS_SESSION_PATH', str(data_home() / 'desktop-session.json')))
        self.token = secrets.token_urlsafe(32)
        self.port = 0
        self.socket: web.WebSocketResponse | None = None
        self._runner: web.AppRunner | None = None
        self._instance_lock: InstanceLock | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=64)
        self._worker: asyncio.Task | None = None
        self._callback: Callable | None = None
        self._callback_ready = asyncio.Event()
        self.on_connect: Callable | None = None
        self._event_times: list[float] = []

    @property
    def connected(self) -> bool:
        return self.socket is not None and not self.socket.closed

    async def connect(self) -> None:
        self._instance_lock = InstanceLock(self.session_path.with_suffix('.lock'))
        try:
            app = web.Application(client_max_size=16384)
            app.router.add_get('/ws', self._websocket)
            self._runner = web.AppRunner(app, access_log=None)
            await self._runner.setup()
            site = web.TCPSite(self._runner, '127.0.0.1', 0)
            await site.start()
            self.port = site._server.sockets[0].getsockname()[1]
            private_write(self.session_path, {'protocol': VERSION, 'port': self.port,
                                             'token': self.token, 'pid': os.getpid()})
            self._worker = asyncio.create_task(self._consume())
        except BaseException:
            await self.disconnect()
            raise

    async def _websocket(self, request: web.Request) -> web.WebSocketResponse:
        origin = request.headers.get('Origin')
        if origin and origin not in ALLOWED_ORIGINS:
            raise web.HTTPForbidden(text='origin_not_allowed')
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=16384)
        await ws.prepare(request)
        try:
            first = await asyncio.wait_for(ws.receive_json(), 3)
            supplied = first.get('token', '') if isinstance(first, dict) else ''
            if not isinstance(supplied, str) or not secrets.compare_digest(supplied, self.token) or first.get('protocol') != VERSION or first.get('type') != 'hello':
                await ws.close(code=4401, message=b'unauthorized'); return ws
        except (TimeoutError, ValueError, TypeError):
            await ws.close(code=4401, message=b'unauthorized'); return ws
        if self.socket is not None:
            await self.socket.close(code=4000, message=b'reconnected')
            self._fail_pending('overlay_reconnected')
        self.socket = ws
        await ws.send_json(packet('ready', {'protocol': VERSION}))
        if self.on_connect is not None:
            await self.on_connect()
        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT: continue
                try:
                    data = decode(message.data)
                except (ValueError, TypeError):
                    await ws.send_json(packet('error', {'reason': 'invalid_message'})); continue
                if data['type'] == 'act_result':
                    payload = data['payload']
                    future = self._pending.get(str(payload.get('act_id', '')))
                    if future and not future.done() and payload.get('status') in RESULT_STATES:
                        evidence = {}
                        supplied = payload.get('evidence')
                        if isinstance(supplied, dict):
                            for key in ('x', 'y', 'width', 'height', 'body_x', 'body_y'):
                                value = supplied.get(key)
                                if isinstance(value, (int, float)) and math.isfinite(value): evidence[key] = value
                            for key in ('window_id', 'floor'):
                                if isinstance(supplied.get(key), str): evidence[key] = supplied[key][:32]
                        future.set_result({'status': payload['status'], 'detail': str(payload.get('detail', ''))[:1000], 'evidence': evidence})
                elif data['type'] in {'event', 'sense', 'control'}:
                    now = time.monotonic()
                    self._event_times = [t for t in self._event_times if now - t < 1]
                    if len(self._event_times) >= 20: continue
                    self._event_times.append(now)
                    with suppress(asyncio.QueueFull): self._queue.put_nowait(data)
        finally:
            if self.socket is ws:
                self.socket = None; self._fail_pending('overlay_disconnected')
        return ws

    def _fail_pending(self, reason: str):
        for future in self._pending.values():
            if not future.done(): future.set_result({'status': 'interrupted', 'detail': reason})

    async def _consume(self):
        await self._callback_ready.wait()
        while True:
            message = await self._queue.get()
            try:
                if self._callback is not None: await self._callback(message)
            except Exception:
                # Do not let one malformed stimulus permanently stop input.
                await self.publish('error', {'reason': 'stimulus_processing_failed'})
            finally:
                self._queue.task_done()

    async def publish(self, kind: str, payload: dict | None = None, *, message_id: str = '') -> bool:
        if not self.connected: return False
        try:
            await self.socket.send_json(packet(kind, payload, message_id=message_id))
            return True
        except (ConnectionError, RuntimeError):
            return False

    async def action(self, name: str, args: dict | None = None, *, timeout: float = 20) -> dict:
        act = packet('act', {'name': name, 'args': args or {}})
        if not self.connected: return {'status': 'failed', 'detail': 'overlay_disconnected'}
        future = asyncio.get_running_loop().create_future()
        self._pending[act['id']] = future
        try:
            if not await self.publish('act', act['payload'], message_id=act['id']):
                return {'status': 'failed', 'detail': 'overlay_disconnected'}
            try:
                result = await asyncio.wait_for(future, timeout)
            except TimeoutError:
                await self.publish('cancel_act', {'act_id': act['id']})
                result = {'status': 'failed', 'detail': 'action_timeout'}
            return {'act_id': act['id'], 'name': name, **result}
        finally:
            self._pending.pop(act['id'], None)

    async def send_message(self, channel: str, content: str) -> None:
        await self.action('say', {'text': content[:240]})

    async def send_tool_activity(self, description: str) -> None:
        pass  # No harness status chatter in a creature's speech bubble.

    async def on_message(self, callback: Callable[..., Any]) -> None:
        self._callback = callback
        self._callback_ready.set()

    async def set_presence(self, status: str) -> None:
        pass

    def get_person_id(self, message: Any) -> str:
        return 'desktop:local-person'

    def get_person_name(self, message: Any) -> str:
        return 'the person here'

    async def disconnect(self) -> None:
        self._fail_pending('brain_stopping')
        if self.socket is not None: await self.socket.close()
        if self._worker is not None:
            self._worker.cancel()
            with suppress(asyncio.CancelledError): await self._worker
        if self._runner is not None: await self._runner.cleanup()
        try:
            if json.loads(self.session_path.read_text()).get('token') == self.token:
                self.session_path.unlink(missing_ok=True)
        except (OSError, ValueError): pass
        if self._instance_lock is not None: self._instance_lock.close()
