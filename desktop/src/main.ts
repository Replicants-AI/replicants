import './style.css';
import './product.css';
import { product } from './product.ts';
import { renderConception } from './conception.ts';
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import atlas from './sprites.json' with { type: 'json' };
import { Physics } from './physics.ts';
import { Spine } from './spine.ts';
import { Renderer } from './render.ts';
import { ANIMS } from './motion.js';
import { ThrowHistory } from './throw.ts';
import { Actions } from './actions.ts';
import { Bridge } from './bridge.ts';
import { Lifecycle } from './lifecycle.ts';
import { inspector } from './inspector.ts';
import { RoomView } from './room.ts';
import { contains, newbornState, type Appearance, type BodyState, type Desktop, type Rect } from './types.ts';

const view = new URLSearchParams(location.search).get('view') ?? 'overlay';
const panel = document.querySelector<HTMLElement>('#panel')!;
const canvas = document.querySelector<HTMLCanvasElement>('#world')!;
const chat = document.querySelector<HTMLFormElement>('#chat')!;
const chatInput = chat.querySelector('input')!;

async function conception() {
  canvas.hidden = true; panel.hidden = false;
  document.body.classList.add('product');
  const birth = renderConception(panel, value => invoke('conception_choice', { value }),
    () => void invoke('request_lifecycle', { kind: 'close' }));
  const unlisten = await listen<{ kind: string; value: { reason?: string } }>('product-update', event => {
    if (event.payload.kind === 'error') birth.showError(event.payload.value.reason ?? 'The birth could not start. Try again.');
  });
  window.addEventListener('pagehide', () => { birth.destroy(); unlisten(); }, { once: true });
}

async function studio() {
  canvas.hidden = true; panel.hidden = false;
  let state = newbornState();
  let appearance: Appearance = { preset: '01-classic', layers: [] };
  let scale = 6;
  let animation = '';
  const send = () => invoke('set_mock_state', { value: { state, appearance, scale, animation } });
  panel.innerHTML = '<h1>Body studio</h1><p>Mock body. No inference calls.</p><div id="presets"></div><div id="sliders"></div><h2>Appearance studies</h2><select id="design"><option value="">Newborn</option></select><button id="glasses">Glasses layer</button><button id="beanie">Headwear layer</button><h2>Motion</h2><p class="quiet">Poke, drag, or double-click the creature. Ctrl+Alt+R opens its chat. Move a window slowly to carry it; move it quickly to let it fall.</p><pre id="telemetry"></pre>';
  const presets: Record<string, Partial<BodyState>> = {
    Curious: { temperament: 'curious', bars: { social: .3, curiosity: .98, creative: .5, tension: .12, comfort: .25 }, asleep: false, sim_hour: 13 },
    Tense: { temperament: 'shy', bars: { social: .2, curiosity: .3, creative: .2, tension: .98, comfort: .1 }, asleep: false, sim_hour: 15 },
    Social: { temperament: 'social', bars: { social: .98, curiosity: .4, creative: .3, tension: .1, comfort: .3 }, asleep: false, sim_hour: 14 },
    Calm: { temperament: 'calm', bars: { social: .1, curiosity: .05, creative: .2, tension: .01, comfort: .99 }, asleep: false, sim_hour: 16 },
    Night: { asleep: true, sim_hour: 1 },
  };
  const sliderArea = panel.querySelector('#sliders')!;
  const renderSliders = () => {
    sliderArea.replaceChildren();
    for (const key of [...Object.keys(state.bars), 'sim_hour', 'scale']) {
      const max = key === 'sim_hour' ? 24 : key === 'scale' ? 12 : 1;
      const label = document.createElement('label'); label.textContent = key;
      const slider = document.createElement('input'); slider.type = 'range'; slider.min = key === 'scale' ? '3' : '0'; slider.max = String(max); slider.step = key === 'scale' ? '1' : '.01';
      const value = key === 'scale' ? scale : key in state.bars ? state.bars[key as keyof typeof state.bars] : state.sim_hour;
      slider.value = String(value); const output = document.createElement('output'); output.textContent = value.toFixed(1);
      slider.oninput = () => { const v = Number(slider.value); output.textContent = v.toFixed(1); if (key === 'scale') scale = v; else if (key in state.bars) state.bars[key as keyof typeof state.bars] = v; else state.sim_hour = v; void send(); };
      label.append(slider, output); sliderArea.append(label);
    }
  };
  for (const [label, value] of Object.entries(presets)) {
    const button = document.createElement('button'); button.textContent = label;
    button.onclick = () => { state = { ...newbornState(), ...value }; renderSliders(); void send(); };
    panel.querySelector('#presets')!.append(button);
  }
  const select = panel.querySelector<HTMLSelectElement>('#design')!;
  const motions = document.createElement('select');
  const automatic = document.createElement('option'); automatic.value = ''; automatic.textContent = 'Motion from body state'; motions.append(automatic);
  for (const anim of ANIMS) { const option = document.createElement('option'); option.value = anim.id; option.textContent = `${anim.cat}: ${anim.name}`; motions.append(option); }
  motions.onchange = () => { animation = motions.value; void send(); }; select.after(motions);
  for (const name of Object.keys(atlas.presets)) { const option = document.createElement('option'); option.value = name; option.textContent = name; select.append(option); }
  select.value = appearance.preset || '';
  select.onchange = () => { appearance.preset = select.value; void send(); };
  for (const name of ['glasses', 'beanie']) panel.querySelector<HTMLButtonElement>(`#${name}`)!.onclick = () => {
    appearance.preset = ''; appearance.layers = appearance.layers.includes(name) ? appearance.layers.filter(n => n !== name) : [...appearance.layers, name]; void send();
  };
  renderSliders();
  setInterval(async () => { panel.querySelector('#telemetry')!.textContent = JSON.stringify(await invoke('view_state'), null, 2); }, 1000);
}

async function overlay() {
  const runtimeOptions = await invoke<{ verify_hidden: boolean; development: boolean; native_room?: boolean }>('runtime_options');
  let preferences = (await invoke<{ settings: Record<string, any> }>('preferences')).settings;
  const ctx = canvas.getContext('2d', { alpha: true })!;
  const body = new Physics(), spine = new Spine(), renderer = new Renderer();
  let state = newbornState(), appearance: Appearance = { preset: '01-classic', layers: [] };
  let animation = '';
  const room = new RoomView(runtimeOptions.native_room === true);
  let hostWorld = await invoke<Desktop>('desktop_snapshot');
  let lastRoomGeometry = '';
  let world = room.world(hostWorld);
  let cursor = { x: 0, y: 0, hit: false };
  let thought = '';
  let speech = '', speechUntil = 0, glyph = '', glyphUntil = 0;
  let regions: Rect[] = [], painted: Rect[] = [], last = performance.now(), reported = 0;
  let drawingKey = '', bodyRegions: Rect[] = [];
  let down: { x: number; y: number; dx: number; dy: number; history: ThrowHistory } | null = null;
  let lastThrow = { vx: 0, vy: 0 };
  let pokes = 0, drags = 0;
  const bridge = new Bridge();
  let everConnected = false, lastSense = '', sensedAt = 0;
  let ambientEnabled = true, activeAppEnabled = false, activeApp: string | null = null;
  let namingShown = false;
  let inspection: Record<string, any> = {};
  let awaitingLaunch = false;
  let lifecycleStarting = false;
  let bodyHidden = false;
  const issue = (reason: unknown) => {
    speech = String(reason); speechUntil = performance.now() + 15000;
    inspection = { ...inspection, error: String(reason) }; void invoke('cache_inspector', { value: inspection });
    void invoke('cache_product', { kind: 'error', value: { reason: String(reason) } });
  };
  const lifecycle = new Lifecycle({ connected: () => bridge.connected,
    sendQuit: () => bridge.send('control', { name: 'quit' }), running: () => invoke<boolean>('brain_running'),
    finish: async (kind, file) => {
      await invoke('finish_lifecycle', { kind, file: file ?? null });
      if (!['quit', 'close'].includes(kind)) { awaitingLaunch = true; namingShown = false; speech = 'Opening a life…'; speechUntil = performance.now() + 5000; }
    } });
  const actions = new Actions((result, act) => {
    bridge.send('act_result', { ...result });
    if (result.status === 'completed' && ['sleep', 'wake_up'].includes(act.name)) {
      if (state.vigilance === undefined) state = { ...state, asleep: act.name === 'sleep' };
      spine.finishRest(act.name, performance.now());
    } else spine.invalidate();
  }, (text, duration) => { speech = text; speechUntil = performance.now() + duration; });
  bridge.onPacket = packet => {
    if (['state', 'health', 'conversation', 'appearance', 'error', 'room'].includes(packet.type)) void invoke('cache_product', { kind: packet.type, value: packet.payload });
    if (packet.type === 'ready') {
      void invoke('cache_product', { kind: 'conversation', value: { messages: [] } });
      void invoke('cache_product', { kind: 'state', value: {} });
      void invoke('cache_product', { kind: 'health', value: { status: 'starting' } });
      void invoke('cache_product', { kind: 'connected', value: { value: true } });
    }
    switch (packet.type) {
      case 'room': room.update(packet.payload); world = room.world(hostWorld); body.geometry(world, performance.now()); break;
      case 'ready': everConnected = true; awaitingLaunch = false; animation = ''; lastSense = ''; thought = ''; namingShown = false; inspection = {}; void invoke('cache_inspector', { value: inspection }); break;
      case 'stopped': lifecycle.stopped(packet.payload.checkpointed === true); break;
      case 'inspector': inspection = packet.payload; void invoke('cache_inspector', { value: inspection }); break;
      case 'error': lifecycle.failed(String(packet.payload.reason)); issue(packet.payload.reason); break;
      case 'state': {
        state = packet.payload as BodyState;
        if (state.vigilance === 'asleep' && actions.current?.act.name !== 'sleep') actions.finish('interrupted', 'body_fell_asleep');
        if (state.gestating !== undefined) void invoke('show_body');
        if (state.naming && !namingShown) { namingShown = true; void invoke('open_chat'); }
        if (!state.naming) chatInput.placeholder = 'Say something...';
        break;
      }
      case 'conception': void invoke('show_conception'); break;
      case 'appearance': appearance = packet.payload as Appearance; break;
      case 'thought': thought = String(packet.payload.text || '').slice(0, 240); break;
      case 'act': {
        if (bodyHidden) { bridge.send('act_result', { act_id: packet.id, status: 'interrupted', detail: 'fullscreen_app' }); break; }
        const name = String(packet.payload.name);
        const variant = name === 'sleep' && body.floor && !body.dragging ? spine.beginSleep() : 'nod';
        actions.start({ id: packet.id, name, args: packet.payload.args || {} }, performance.now(), body, world, cursor, variant); break;
      }
      case 'cancel_act': if (actions.current?.act.id === packet.payload.act_id) actions.finish('interrupted', 'brain_cancelled'); break;
      case 'say': speech = String(packet.payload.text || '').slice(0, 240); speechUntil = performance.now() + 7000; break;
      case 'senses': ambientEnabled = packet.payload.ambient !== false; activeAppEnabled = packet.payload.active_app === true; if (!activeAppEnabled) activeApp = null; lastSense = ''; break;
    }
  };
  bridge.onDisconnect = () => {
    void invoke('set_body_visible', { visible: false });
    void invoke('cache_product', { kind: 'connected', value: { value: false } });
    actions.finish('interrupted', 'brain_disconnected');
    lifecycle.failed('The brain disconnected before confirming its checkpoint. The last complete save is intact.');
    inspection = { ...inspection, connected: false }; void invoke('cache_inspector', { value: inspection });
  };
  const size = () => { canvas.width = Math.round(innerWidth * devicePixelRatio); canvas.height = Math.round(innerHeight * devicePixelRatio); ctx.imageSmoothingEnabled = false; };
  size(); addEventListener('resize', size);
  body.scale = preferences.body_scale ?? 6;
  await listen<Record<string, any>>('preferences-changed', e => {
    preferences = e.payload;
    const bottom = body.bottom; body.scale = preferences.body_scale; body.y = bottom - body.height; drawingKey = '';
  });
  body.geometry(world, performance.now()); body.place(world);
  const setMock = (value: { state?: BodyState; appearance?: Appearance; scale?: number; animation?: string }) => {
    if (value.state) state = value.state;
    if (value.appearance) appearance = value.appearance;
    if (value.animation !== undefined) animation = value.animation;
    if (value.scale) { const bottom = body.bottom; body.scale = Math.max(3, Math.min(12, Math.round(value.scale))); body.y = bottom - body.height; }
    spine.invalidate(); thought = state.asleep ? 'the edge feels quiet now' : state.bars.tension > .7 ? 'something keeps shifting' : 'a little space along this edge';
  };
  const saved = await invoke<null | { state?: BodyState }>('mock_state'); if (saved) setMock(saved);
  await listen<{ x: number; y: number; hit: boolean }>('cursor', e => { cursor = e.payload; });
  await listen<Desktop>('desktop', e => {
    hostWorld = e.payload; world = room.world(hostWorld); body.geometry(world, performance.now());
    if (runtimeOptions.native_room) {
      const rect = hostWorld.windows.find(window => window.id === 'replicants-room');
      const key = JSON.stringify(rect ?? null);
      if (rect && key !== lastRoomGeometry) bridge.send('control', { name: 'room_move', rect });
      lastRoomGeometry = key;
    }
    const hidden = preferences.hide_fullscreen && world.fullscreen === true;
    if (hidden !== bodyHidden) {
      bodyHidden = hidden; drawingKey = '';
      if (hidden) actions.finish('interrupted', 'fullscreen_app');
      void invoke('set_body_visible', { visible: !hidden && (bridge.connected || runtimeOptions.development) });
    }
  });
  await listen<Parameters<typeof setMock>[0]>('mock-state', e => { if (!everConnected) setMock(e.payload); });
  await listen<{ name: string }>('brain-control', e => { bridge.send('control', e.payload); });
  await listen<{ id: string; text: string }>('send-message', e => {
    if (!bridge.send('event', { kind: 'chat', text: e.payload.text }, e.payload.id)) issue('The local connection is unavailable. Your draft is still in Conversation.');
  });
  await listen<{ kind: string; file?: string }>('lifecycle', async e => {
    if (lifecycleStarting) { issue('A life is already being saved or opened.'); return; }
    lifecycleStarting = true;
    try {
      const file = e.payload.kind === 'open' ? e.payload.file ?? await invoke<string | null>('choose_replicant') : undefined;
      if (file === null) return;
      await invoke('cache_product', { kind: 'lifecycle', value: { busy: true, kind: e.payload.kind } });
      try { await lifecycle.run(e.payload.kind, file); }
      finally { await invoke('cache_product', { kind: 'lifecycle', value: { busy: false } }); }
    } catch (error) { issue(error); }
    finally { lifecycleStarting = false; }
  });
  await listen<Record<string, unknown>>('conception-choice', e => { bridge.send('control', { name: 'conceive', ...e.payload }); });
  void bridge.start();
  setInterval(async () => {
    if (!awaitingLaunch) return;
    const status = await invoke<number | null>('launch_status');
    if (status !== null) {
      awaitingLaunch = false;
      issue('The life could not open. Details are in ~/.replicants/desktop-brain.log. Your last complete save is intact.');
    }
  }, 2000);
  const openChat = () => {
    if (!runtimeOptions.verify_hidden) void invoke('open_chat');
  };
  await listen('open-chat', openChat);
  canvas.ondblclick = openChat;
  chat.onsubmit = e => {
    e.preventDefault(); chat.hidden = true;
    const text = chatInput.value.trim(); chatInput.value = '';
    if (!text) return;
    if (!bridge.send('event', { kind: 'chat', text: text.slice(0, 4000) })) {
      speech = everConnected ? 'the brain connection is resting' : 'mock body - no brain attached'; speechUntil = performance.now() + 5000;
    }
  };
  chatInput.onkeydown = e => { if (e.key === 'Escape') chat.hidden = true; };
  canvas.onpointerdown = e => {
    if (state.gestating) return;
    const x = e.clientX * devicePixelRatio, y = e.clientY * devicePixelRatio;
    if (!painted[0] || !contains(painted[0], x, y)) return;
    const history = new ThrowHistory(); history.sample(x, y, e.timeStamp);
    down = { x, y, dx: x - body.x, dy: y - body.y, history }; canvas.setPointerCapture(e.pointerId);
  };
  canvas.onpointermove = e => {
    if (!down) return;
    const x = e.clientX * devicePixelRatio, y = e.clientY * devicePixelRatio;
    if (!body.dragging && Math.hypot(x - down.x, y - down.y) > 5) { actions.finish('interrupted', 'picked_up'); body.pickUp(); drags++; bridge.send('event', { kind: 'drag_start' }); }
    if (body.dragging) {
      const samples = e.getCoalescedEvents?.() || [e];
      for (const p of samples.length ? samples : [e]) down.history.sample(p.clientX * devicePixelRatio, p.clientY * devicePixelRatio, p.timeStamp);
      body.x = Math.max(world.work.x, Math.min(world.work.x + world.work.width - body.width, x - down.dx));
      body.y = Math.max(0, Math.min(world.work.y + world.work.height - body.height, y - down.dy));
    }
  };
  canvas.onpointerup = e => {
    if (!down) return;
    const now = performance.now();
    if (body.dragging) { lastThrow = down.history.release(now, body.scale); body.release(now, lastThrow); bridge.send('event', { kind: 'drag_end', velocity: lastThrow }); }
    else { actions.finish('interrupted', 'poked'); spine.poke(now, state); pokes++; bridge.send('event', { kind: 'poke' }); }
    glyphUntil = now + 1600; down = null; canvas.releasePointerCapture(e.pointerId);
  };
  canvas.onpointercancel = e => {
    if (body.dragging) { body.release(performance.now()); bridge.send('event', { kind: 'drag_end' }); }
    down = null; if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
  };
  const frame = (now: number) => {
    const dt = Math.min(.1, (now - last) / 1000); last = now;
    if (bodyHidden || (!bridge.connected && !runtimeOptions.development)) {
      ctx.clearRect(0, 0, canvas.width, canvas.height); painted = []; drawingKey = '';
      void invoke('report_view', { report: { regions: [], capture: false, body: { brain_connected: false } } });
      setTimeout(() => requestAnimationFrame(frame), 250); return;
    }
    const actionPose = actions.tick(now, body, world);
    if (!preferences.reduced_motion || actionPose) spine.tick(now, body, state, world, cursor, animation, !!actionPose || state.gestating === true);
    else if (body.floor && !body.dragging) body.vx = 0;
    body.tick(dt, now, world);
    const pose = state.gestating ? {} : actionPose || (preferences.reduced_motion ? {} : spine.pose()), symbol = now < glyphUntil ? glyph : '';
    if (bridge.connected && ambientEnabled && now - sensedAt >= 3000) {
      if (activeAppEnabled) void invoke<string | null>('active_app_name').then(name => { activeApp = name; });
      const sense = { window_count: world.windows.length, window_ids: world.windows.map(w => w.id).sort(), idle: world.idle_seconds >= 30, idle_seconds: Math.floor(world.idle_seconds / 30) * 30, hour: new Date().getHours(), ...(activeAppEnabled && activeApp ? { active_app: activeApp } : {}) };
      const key = JSON.stringify(sense);
      if (key !== lastSense) { bridge.send('sense', sense); lastSense = key; }
      sensedAt = now;
    }
    const bubble = now < speechUntil ? speech : preferences.show_thoughts && cursor.hit && !body.dragging ? thought : '';
    const thinking = now >= speechUntil;
    const nextKey = JSON.stringify([Math.round(body.x), Math.round(body.y), body.scale, pose, appearance, symbol, bubble, thinking, canvas.width, canvas.height, state.gestating ? Math.floor(now / 50) : 0]);
    // Match the page's refresh timing, but repaint only when pixels change.
    if (nextKey !== drawingKey) {
      for (const r of painted) ctx.clearRect(r.x - 2, r.y - 2, r.width + 4, r.height + 4);
      painted = [renderer.draw(ctx, body, pose, appearance, now, symbol, state.gestating)];
      if (bubble) painted.push(renderer.bubble(ctx, bubble, body, canvas.width, thinking));
      bodyRegions = painted.map(r => ({ ...r })); drawingKey = nextKey;
    }
    regions = [...bodyRegions];
    if (!chat.hidden) { const r = chat.getBoundingClientRect(); regions.push({ x: r.x * devicePixelRatio, y: r.y * devicePixelRatio, width: r.width * devicePixelRatio, height: r.height * devicePixelRatio }); }
    if (now - reported > 100) {
      void invoke('report_view', { report: { regions, capture: !!down, body: { x: body.x, y: body.y, vx: body.vx, vy: body.vy, floor: body.floor, behavior: spine.behavior, animation: actions.current?.animation || spine.animation, dragging: body.dragging, pokes, drags, last_throw: lastThrow, appearance, scale: body.scale, state, brain_connected: bridge.connected, window_count: world.windows.length } } });
      reported = now;
    }
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

void (view === 'overlay' ? overlay() : ['home', 'conversation', 'settings', 'room'].includes(view) ? (canvas.hidden = true, product(panel, view)) : view === 'birth' ? conception() : view === 'inspector' ? (canvas.hidden = true, inspector(panel)) : studio()).catch(error => {
  panel.hidden = false; panel.textContent = `Replicants could not open this surface: ${String(error)}`;
  void invoke('report_view', { report: { regions: [], capture: false, body: { error: String(error) } } });
});
