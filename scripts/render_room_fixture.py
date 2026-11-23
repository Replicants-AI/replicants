"""Generate the browser fixture using the shipping text reader, only on a remote validation machine."""
import json
import os
from pathlib import Path

if os.environ.get('REPLICANTS_REMOTE_VALIDATION') != '1':
    raise SystemExit('Generate this fixture on the isolated remote runner.')
from replicants.desktop.room_reader import TextBrowser

page = TextBrowser().request({'op': 'show', 'page': {'title': 'Octopus', 'text':
    'An octopus has eight arms.\n\nThis is a fixed page fixture for the Room interface. '
    'The reader displays extracted source text.\n\nSource: https://example.org/octopus',
    'links': [{'link_id': '1', 'title': 'Another page'}]}})
destination = Path('desktop/tests/fixtures/room-page.json')
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(page, indent=2), encoding='utf-8')
