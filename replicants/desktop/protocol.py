"""Versioned local body/brain messages and private session discovery."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from typing import Any

VERSION = 1
BODY_TYPES = {'sense', 'event', 'act_result', 'control'}
RESULT_STATES = {'completed', 'failed', 'interrupted'}


def packet(kind: str, payload: dict | None = None, *, message_id: str = '') -> dict:
    return {'protocol': VERSION, 'type': kind, 'id': message_id or uuid.uuid4().hex,
            'timestamp': time.time(), 'payload': payload or {}}


def decode(raw: str) -> dict:
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('protocol') != VERSION:
        raise ValueError('unsupported_protocol')
    if data.get('type') not in BODY_TYPES or not isinstance(data.get('id'), str) or not data['id']:
        raise ValueError('invalid_envelope')
    if not isinstance(data.get('timestamp'), (float, int)) or not isinstance(data.get('payload'), dict):
        raise ValueError('invalid_envelope')
    if len(data['id']) > 128:
        raise ValueError('invalid_id')
    return data


def private_write(path: Path, value: dict[str, Any]) -> None:
    """Atomic descriptor replacement; protect the token BEFORE writing it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if os.name == 'nt':
            flags = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(['whoami.exe', '/user', '/fo', 'csv', '/nh'],
                                    capture_output=True, text=True, check=True, creationflags=flags)
            sid = next(csv.reader([result.stdout.strip()]))[-1]
            subprocess.run(['icacls.exe', str(temporary), '/inheritance:r', '/grant:r',
                            f'*{sid}:(F)', '/grant:r', '*S-1-5-18:(F)'],
                           capture_output=True, check=True, creationflags=flags)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            fd = -1
            json.dump(value, stream)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0: os.close(fd)
        temporary.unlink(missing_ok=True)


class InstanceLock:
    """OS-held lock released even if the owning process is killed."""
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open('a+b')
        try:
            self.stream.seek(0, 2)
            if not self.stream.tell(): self.stream.write(b'0'); self.stream.flush()
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                # A terminated writer can be signalled before Windows has
                # finished releasing its file locks. Allow that short cleanup
                # interval, without removing or bypassing a live owner's lock.
                deadline = time.monotonic() + .25
                while True:
                    try:
                        msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline: raise
                        time.sleep(.01)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise RuntimeError('This Replicant is already awake in another process.') from exc

    def close(self):
        if self.stream.closed: return
        if os.name == 'nt':
            import msvcrt
            self.stream.seek(0); msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()
