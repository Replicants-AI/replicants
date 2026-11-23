"""Bounded local transcript of received messages and actually delivered speech."""
from __future__ import annotations

import json
from pathlib import Path
import time
import uuid

from replicants.desktop.protocol import private_write


class Conversation:
    LIMIT = 400

    def __init__(self, path: Path):
        self.path = path
        self.messages = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
        if not isinstance(self.messages, list):
            raise ValueError('Conversation record is invalid.')
        self.messages = self.messages[-self.LIMIT:]
        delivered = {m.get('reply_to') for m in self.messages
                     if m.get('role') == 'replicant' and m.get('status') == 'delivered'}
        interrupted = False
        for message in self.messages:
            if message.get('status') in {'queued', 'processing'}:
                if message['id'] in delivered:
                    message.update(status='completed', detail='Your reply was saved. Background processing was interrupted when the previous session ended.')
                else:
                    message.update(status='interrupted', detail='The previous session ended before a reply was saved. Send again to retry.')
                interrupted = True
        if interrupted:
            self.save()

    def save(self):
        self.messages = self.messages[-self.LIMIT:]
        private_write(self.path, self.messages)

    def find(self, message_id):
        return next((m for m in self.messages if m['id'] == message_id), None)

    def receive(self, message_id: str, text: str):
        previous = self.find(message_id)
        if previous:
            return previous, False
        message = dict(id=message_id, role='person', text=text, at=time.time(), status='queued')
        self.messages.append(message)
        self.save()
        return message, True

    def status(self, message_id, status, detail=''):
        message = self.find(message_id)
        if message:
            message.update(status=status, detail=detail)
            self.save()

    def spoken(self, text: str, reply_to=None):
        self.messages.append(dict(id=str(uuid.uuid4()), role='replicant', text=text,
                                  at=time.time(), status='delivered', reply_to=reply_to))
        self.save()

    def snapshot(self):
        return {'messages': list(self.messages), 'limit': self.LIMIT}
