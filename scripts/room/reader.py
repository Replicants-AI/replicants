"""JSON-lines reader running inside the separate, network-disabled Room container."""
import asyncio
import base64
import html
import json
import sys

from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context('/tmp/room-profile', headless=True,
            java_script_enabled=False, accept_downloads=False, viewport={'width': 640, 'height': 420},
            args=['--no-sandbox', '--disable-background-networking', '--disable-sync'])
        page = context.pages[0]
        async def block(route): await route.abort()
        await context.route('**/*', block)
        while line := await asyncio.to_thread(sys.stdin.readline):
            try:
                request = json.loads(line)
                if request['op'] in {'blank', 'show'}:
                    content = request.get('page') or {'title': 'Room', 'text': 'A place to read.', 'links': []}
                    title = html.escape(str(content['title'])[:200])
                    text = str(content['text'])[:12000]
                    paragraphs = ''.join('<p data-reading>' + html.escape(t) + '</p>' for t in text.splitlines() if t.strip())
                    links = ''.join('<p data-reading>' + html.escape('[' + link['link_id'] + '] ' + link['title']) + '</p>'
                                    for link in content.get('links', [])[:30])
                    await page.set_content('<!doctype html><meta http-equiv="Content-Security-Policy" '
                        'content="default-src \'none\'; style-src \'unsafe-inline\'; form-action \'none\'">'
                        '<style>body{font:17px/1.5 system-ui;margin:24px;color:#193c47;background:#fcfaf3}h1{font-size:23px}p{white-space:pre-wrap}</style>'
                        '<h1>' + title + '</h1>' + paragraphs + links)
                elif request['op'] == 'scroll':
                    await page.evaluate('(d) => window.scrollBy(0, d === "down" ? 330 : -330)', request['direction'])
                else: raise ValueError('unknown operation')
                visible = await page.locator('[data-reading]').evaluate_all(
                    '(nodes) => nodes.filter(n => {const r=n.getBoundingClientRect(); return r.bottom>0 && r.top<innerHeight})'
                    '.map(n=>n.textContent).join("\\n")')
                image = base64.b64encode(await page.screenshot(type='png')).decode()
                response = {'ok': True, 'page_text': visible[:4000], 'image': image}
            except Exception:
                response = {'ok': False, 'error': 'reader_operation_failed'}
            print(json.dumps(response), flush=True)
        await context.close()


asyncio.run(main())
