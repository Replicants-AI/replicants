"""The Room's offline text-browser renderer, launched inside an OS sandbox.

Its input is bounded readable text and link labels, never a live web document.
The broker owns navigation. This process owns its reading position and pixels.
"""
from __future__ import annotations

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT, MARGIN, LINE = 640, 420, 24, 25


class TextBrowser:
    def __init__(self):
        candidates = [Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts/arial.ttf',
                      Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
        self.font = next((ImageFont.truetype(str(p), 17) for p in candidates if p.is_file()),
                         ImageFont.load_default(size=17))
        self.lines, self.offset = [], 0
        self.measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))

    def wrap(self, text):
        for paragraph in text.splitlines():
            current = ''
            for character in paragraph:
                if ord(character) < 32: continue
                if current and self.measure.textlength(current + character, font=self.font) > WIDTH - MARGIN * 2:
                    yield current
                    current = ''
                current += character
            yield current
            yield ''

    def request(self, request):
        op = request.get('op')
        if op in {'blank', 'show'}:
            page = request.get('page') or {'title': 'Room', 'text': 'A place to read.', 'links': []}
            text = str(page.get('title', 'Room'))[:200] + '\n\n' + str(page.get('text', ''))[:12000]
            for link in page.get('links', [])[:30]:
                text += '\n[' + str(link['link_id'])[:8] + '] ' + str(link['title'])[:120]
            self.lines, self.offset = list(self.wrap(text)), 0
        elif op == 'scroll' and request.get('direction') in {'up', 'down'}:
            self.offset += 13 if request['direction'] == 'down' else -13
        else:
            raise ValueError('invalid_reader_operation')
        count = (HEIGHT - MARGIN * 2) // LINE
        self.offset = max(0, min(self.offset, max(0, len(self.lines) - count)))
        visible = self.lines[self.offset:self.offset + count]
        image = Image.new('RGB', (WIDTH, HEIGHT), '#fcfaf3')
        draw = ImageDraw.Draw(image)
        for i, line in enumerate(visible):
            draw.text((MARGIN, MARGIN + i * LINE), line, font=self.font, fill='#193c47')
        output = BytesIO()
        image.save(output, format='PNG')
        return {'ok': True, 'image': base64.b64encode(output.getvalue()).decode('ascii'),
                'page_text': '\n'.join(visible)[:4000]}


def main():
    browser = TextBrowser()
    while line := sys.stdin.buffer.readline(262145):
        try:
            if len(line) > 262144 or not line.endswith(b'\n'):
                break
            request = json.loads(line)
            if not isinstance(request, dict): raise ValueError('invalid_reader_message')
            response = browser.request(request)
        except (ValueError, TypeError, KeyError, OSError):
            response = {'ok': False, 'error': 'reader_operation_failed'}
        print(json.dumps(response), flush=True)


if __name__ == '__main__':
    main()
