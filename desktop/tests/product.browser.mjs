// Isolated browser fixtures. These verify frontend behavior, not native Windows acceptance.
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { chromium } from 'playwright';

if (!process.env.CI && process.env.REPLICANTS_REMOTE_VALIDATION !== '1') throw new Error('Run browser validation on an isolated remote runner.');
const output = process.env.REPLICANTS_UI_ARTIFACTS || 'ui-artifacts';
await mkdir(output, { recursive: true });
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1', '--port', '1430', '--strictPort'], { stdio: 'pipe' });
let browser;
try {
  for (let attempt = 0; attempt < 60; attempt++) {
    try { if ((await fetch('http://127.0.0.1:1430')).ok) break; } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 600, height: 760 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const roomFixture = JSON.parse(await readFile(new URL('./fixtures/room-page.json', import.meta.url), 'utf8'));
  await page.addInitScript(roomImage => {
    let next = 0;
    const callbacks = new Map(), events = new Map();
    const settings = { version: 1, ollama_url: 'http://127.0.0.1:11434', chat_model: 'gemma4:26b', embedding_model: 'nomic-embed-text', decision_mode: 'json', context_tokens: 8192, reply_tokens: 1024, thinking: false, body_scale: 6, ambient: true, show_thoughts: false, reduced_motion: false, hide_fullscreen: true, max_wakes_per_hour: 6, runtime: 'auto' };
    const firstRun = location.search.includes('setup=1');
    let prepared = false;
    const snapshot = { connected: { value: !firstRun }, health: { status: 'running', paused: false, last_checkpoint_at: 1794042000 }, state: { name: 'Pip', vigilance: 'drowsy', gestating: false }, appearance: { palette: '#C8E5D1', layers: [] }, conversation: { messages: [{ id: 'first', role: 'replicant', text: 'a little quieter here', status: 'delivered', at: 1794042000 }] } };
    snapshot.room = { available: true, open: true, status: 'reading', title: 'Octopus', url: 'https://example.org/octopus', image: roomImage, history: [{ title: '<script>literal source title</script>', url: 'https://example.org/octopus' }] };
    window.__betaFixture = { calls: [], snapshot };
    const emit = (kind, value) => { snapshot[kind] = value; for (const [id, event] of events) if (event.name === 'product-update') callbacks.get(event.handler)?.({ event: event.name, id, payload: { kind, value } }); };
    window.__betaFixture.emit = emit;
    window.__TAURI_INTERNALS__ = {
      transformCallback(callback) { const id = ++next; callbacks.set(id, callback); return id; },
      unregisterCallback(id) { callbacks.delete(id); },
      async invoke(command, args = {}) {
        window.__betaFixture.calls.push({ command, args });
        if (command === 'plugin:event|listen') { const id = ++next; events.set(id, { name: args.event, handler: args.handler }); return id; }
        if (command === 'plugin:event|unlisten') { events.delete(args.eventId); return; }
        if (command === 'product_snapshot') return structuredClone(snapshot);
        if (command === 'life_library') return { lives: [] };
        if (command === 'preferences') return { settings };
        if (command === 'save_preferences') return { settings: args.value };
        if (command === 'prepare_local') {
          const send = (payload) => { for (const [id, event] of events) if (event.name === 'setup-progress') callbacks.get(event.handler)?.({ event: event.name, id, payload }); };
          send({ stage: 'survey', status: 'Your computer can host a lighter replicant.' });
          send({ stage: 'runtime', status: 'downloading', completed: 500000000, total: 1800000000 });
          window.__betaFixture.midSetup = document.querySelector('#setup-step')?.textContent;
          send({ stage: 'mind', status: 'pulling', completed: 1000000000, total: 3000000000 });
          send({ stage: 'done', ready: true, status: 'ready' });
          prepared = true; return;
        }
        if (command === 'setup_check' && firstRun && !prepared) return { ready: false, settings, runtime: { mode: 'auto' }, ollama: { available: false }, models: [], missing: [], issues: ['Thought is not ready yet. Choose Set up.'], hardware: {} };
        if (command === 'setup_check') return { ready: true, settings, ollama: { available: true, version: 'fixture' }, models: [{ name: 'gemma4:26b', size: 17000000000 }, { name: 'nomic-embed-text:latest', size: 280000000 }], missing: [], issues: [], hardware: { ram_available_bytes: 16000000000, ram_total_bytes: 32000000000, disk_free_bytes: 100000000000 } };
        if (command === 'send_message') { setTimeout(() => emit('conversation', { messages: [...snapshot.conversation.messages, { id: args.id, role: 'person', text: args.text, status: 'queued', at: Date.now() / 1000 }] }), 20); return; }
        if (command === 'export_diagnostics') return 'C:/fixture/replicants-support.json';
      },
    };
  }, roomFixture.image);
  await page.goto('http://127.0.0.1:1430/?view=home');
  await page.goto('http://127.0.0.1:1430/?view=home&setup=1');
  await page.waitForFunction(() => document.querySelector('#setup-title')?.textContent === 'One step before a first breath.');
  const firstRunText = await page.locator('#setup-card').innerText();
  assert.ok(!/ollama|model|terminal|github|python/i.test(firstRunText.replace('Choose models yourself', '')), firstRunText);
  await page.screenshot({ path: `${output}/home-first-run.png`, fullPage: true });
  await page.getByRole('button', { name: 'Set up', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#setup-title')?.textContent === 'Ready for a life.');
  assert.match(await page.evaluate(() => window.__betaFixture.midSetup), /^Preparing a place for thought… 0\.5 GB of 1\.7 GB$/);
  assert.equal(await page.locator('#setup-go').isHidden(), true);
  await page.goto('http://127.0.0.1:1430/?view=home');
  await page.waitForFunction(() => document.querySelector('#setup-title')?.textContent === 'Ready for a life.');
  assert.equal(await page.locator('#vigilance').textContent(), 'drowsy');
  await page.evaluate(() => window.__betaFixture.emit('state', { ...window.__betaFixture.snapshot.state,
    substrate: { inference: { in_flight: [{ elapsed_seconds: 12 }] } } }));
  await page.getByText('Thinking · 12 s elapsed. Loading a local mind can take time.', { exact: true }).waitFor();
  await page.screenshot({ path: `${output}/home.png`, fullPage: true });
  await page.goto('http://127.0.0.1:1430/?view=conversation');
  await page.getByText('a little quieter here').waitFor();
  await page.locator('#message').fill('hello from a remote fixture');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await page.getByText('hello from a remote fixture', { exact: true }).waitFor();
  assert.equal(await page.locator('#message').inputValue(), '');
  await page.screenshot({ path: `${output}/conversation.png`, fullPage: true });
  await page.goto('http://127.0.0.1:1430/?view=room');
  await page.getByText('https://example.org/octopus', { exact: true }).first().waitFor();
  await page.waitForFunction(() => { const image = document.querySelector('#room-page'); return image?.complete && image.naturalWidth === 640; });
  assert.equal(await page.locator('#room-history script').count(), 0);
  assert.equal(await page.locator('#room-history strong').textContent(), '<script>literal source title</script>');
  await page.getByRole('button', { name: 'Read below', exact: true }).click();
  assert.ok(await page.evaluate(() => window.__betaFixture.calls.some(call => call.command === 'request_control' && call.args.value.name === 'room_scroll' && call.args.value.direction === 'down')));
  await page.screenshot({ path: `${output}/room.png`, fullPage: true });
  await page.evaluate(() => window.__betaFixture.emit('room', { ...window.__betaFixture.snapshot.room, status: 'loading' }));
  await page.getByRole('button', { name: 'Close Room', exact: true }).click();
  assert.ok(await page.evaluate(() => window.__betaFixture.calls.some(call => call.command === 'request_control' && call.args.value.name === 'room_close')));
  await page.goto('http://127.0.0.1:1430/?view=settings');
  await page.getByText('Ready. Ollama fixture.').waitFor();
  await page.getByRole('button', { name: 'Download chat model' }).click();
  await page.getByText('Confirm the download above first.').waitFor();
  assert.equal(await page.evaluate(() => window.__betaFixture.calls.some(call => call.command === 'download_model')), false);
  await page.screenshot({ path: `${output}/settings.png`, fullPage: true });
  await page.setViewportSize({ width: 380, height: 700 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.setViewportSize({ width: 780, height: 900 });
  await page.goto('http://127.0.0.1:1430/?view=birth');
  await page.getByRole('heading', { name: 'A shape of their own.' }).waitFor();
  assert.equal(await page.locator('.design-gallery button').count(), 38);
  assert.equal(await page.locator('select[name=palette]').count(), 0);
  assert.equal(await page.locator('.design-preview option[value=charge]').count(), 0);
  await page.locator('[data-design="art:05-long-hair"]').click();
  const colors = () => page.locator('.body-pixel').evaluateAll(cells => cells.map(cell => cell.style.backgroundColor));
  const original = await colors();
  await page.getByRole('textbox', { name: 'Hex color', exact: true }).fill('#FF00AA');
  const pixel = page.locator('.body-pixel[data-x="1"][data-y="0"]');
  await pixel.click();
  const painted = await colors();
  assert.equal(painted.filter((color, index) => color !== original[index]).length, 1);
  assert.equal(painted[0], 'rgb(255, 0, 170)');
  await page.getByRole('button', { name: 'Undo', exact: true }).click(); assert.deepEqual(await colors(), original);
  await page.getByRole('button', { name: 'Redo', exact: true }).click(); assert.deepEqual(await colors(), painted);
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  const start = await pixel.boundingBox(), end = await page.locator('.body-pixel[data-x="6"][data-y="0"]').boundingBox();
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2); await page.mouse.down();
  await page.mouse.move(end.x + end.width / 2, end.y + end.height / 2, { steps: 2 }); await page.mouse.up();
  assert.equal((await colors()).filter((color, index) => color !== original[index]).length, 6);
  await page.getByRole('button', { name: 'Undo', exact: true }).click(); assert.deepEqual(await colors(), original);
  await page.getByRole('button', { name: 'Eyedropper', exact: true }).click(); await pixel.click();
  assert.deepEqual(await colors(), original);
  assert.equal(await page.getByRole('button', { name: 'Brush', exact: true }).getAttribute('aria-pressed'), 'true');
  await page.getByRole('textbox', { name: 'Hex color', exact: true }).fill('#123456');
  await pixel.focus(); await page.keyboard.press('ArrowRight'); await page.keyboard.press('Space');
  assert.equal((await colors())[1], 'rgb(18, 52, 86)');
  const downloaded = page.waitForEvent('download'); await page.getByRole('button', { name: 'Save drawing', exact: true }).click();
  await (await downloaded).saveAs(`${output}/drawing.json`);
  const drawing = JSON.parse(await readFile(`${output}/drawing.json`, 'utf8'));
  assert.ok(Object.values(drawing.pal).includes('#123456'));
  const file = page.locator('input[type=file]');
  await file.setInputFiles({ name: 'invalid.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ name: '<img onerror=alert(1)>', rows: [], pal: {} })) });
  await page.getByText('Use an 8 by 7 body drawing with six-digit hex colors.', { exact: true }).waitFor();
  assert.equal(await page.locator('.drawing-status img').count(), 0);
  const beforeBadLoad = await colors(); assert.equal(beforeBadLoad[1], 'rgb(18, 52, 86)');
  await file.setInputFiles({ name: 'drawing.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(drawing)) });
  await page.getByText('Drawing loaded.', { exact: true }).waitFor(); assert.deepEqual(await colors(), beforeBadLoad);
  await page.getByRole('combobox', { name: 'Preview motion', exact: true }).selectOption('look');
  await page.screenshot({ path: `${output}/birth-editor.png`, fullPage: true });
  await page.setViewportSize({ width: 380, height: 760 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: `${output}/birth-editor-narrow.png`, fullPage: true });
  await page.getByRole('button', { name: 'Conceive', exact: true }).click();
  const choice = await page.evaluate(() => window.__betaFixture.calls.find(call => call.command === 'conception_choice').args.value);
  assert.deepEqual(choice.design, drawing); assert.equal('palette' in choice, false);
  assert.equal(await page.getByRole('button', { name: 'Conceive', exact: true }).isDisabled(), true);
  await page.evaluate(() => window.__betaFixture.emit('error', { reason: 'Birth fixture rejected; try again.' }));
  await page.getByText('Birth fixture rejected; try again.', { exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Conceive', exact: true }).isEnabled(), true);
  assert.deepEqual(await colors(), beforeBadLoad);
  assert.deepEqual(errors, []);
  console.log('Product browser fixtures passed: setup, home, conversation, Room, settings, design selection, individual pixels, drag strokes, undo/redo, keyboard, eyedropper, drawing files, birth payload, error retry and narrow layout.');
} finally {
  await browser?.close();
  server.kill();
}
