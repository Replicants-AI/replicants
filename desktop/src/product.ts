import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { compose, FW, FH } from './motion.js';
import { anatomy } from './appearance.ts';
import type { Appearance } from './types.ts';

type RecordValue = Record<string, any>;
const $ = <T extends HTMLElement = HTMLElement>(root: ParentNode, query: string) => root.querySelector<T>(query)!;
const text = (root: ParentNode, query: string, value: unknown) => { $(root, query).textContent = String(value ?? ''); };
const bytes = (value: number) => `${(value / 1024 ** 3).toFixed(1)} GB`;

function character(canvas: HTMLCanvasElement, appearance: Appearance = { palette: 'pearl', layers: [] }) {
  canvas.width = FW; canvas.height = FH;
  const context = canvas.getContext('2d')!;
  for (const [x, y, color] of compose(anatomy(appearance), {})) {
    context.fillStyle = color; context.fillRect(x, y, 1, 1);
  }
}

export async function product(panel: HTMLElement, view: string) {
  panel.hidden = false; document.body.classList.add('product');
  panel.innerHTML = `<header class="app-header"><button class="wordmark" data-panel="home">replicants<span class="version">beta</span></button><span id="connection" role="status">Connecting</span></header>
    <nav aria-label="Main"><button data-panel="home">Home</button><button data-panel="conversation">Conversation</button><button data-panel="room">Room</button><button data-panel="settings">Settings</button></nav>
    <div id="notice" class="notice" role="status" hidden></div><section id="content"></section><footer>Local life. Real compute.<button id="inspect" class="link-button">Inspector</button></footer>`;
  for (const button of panel.querySelectorAll<HTMLButtonElement>('[data-panel]')) {
    button.classList.toggle('selected', button.dataset.panel === view);
    button.onclick = () => void invoke('show_panel', { label: button.dataset.panel });
  }
  $(panel, '#inspect').onclick = () => void invoke('show_panel', { label: 'inspector' });
  const content = $(panel, '#content');
  let snapshot: RecordValue = {};
  let prefs: RecordValue = {};
  let ready = false;
  const notice = (value: unknown) => { text(panel, '#notice', value); $(panel, '#notice').hidden = !value; };
  const attempt = async (work: () => Promise<unknown>) => { try { await work(); } catch (error) { notice(error); } };
  const lifecycle = (kind: string) => attempt(async () => {
    if (['birth', 'open'].includes(kind) && !ready) { notice('Choose Set up on Home first.'); return; }
    notice(['quit', 'close'].includes(kind) ? 'Saving this life…' : 'Opening a life…');
    await invoke('request_lifecycle', { kind });
  });
  let updateView = () => {};
  let refreshSetup = async () => {};
  let refreshLibrary = async () => {};
  const update = () => {
    const connected = snapshot.connected?.value === true;
    const health = snapshot.health ?? {};
    const active = snapshot.state?.substrate?.inference?.in_flight?.length > 0;
    text(panel, '#connection', connected ? health.paused ? active ? 'Pausing after this thought' : 'Thinking paused' : health.status === 'degraded' ? 'Needs attention' : 'Local connection' : 'No life open');
    $(panel, '#connection').classList.toggle('online', connected);
    updateView();
  };
  await listen<{ kind: string; value: RecordValue }>('product-update', event => {
    snapshot[event.payload.kind] = event.payload.value;
    if (event.payload.kind === 'error') notice(event.payload.value.reason ?? 'Something needs attention.');
    if (event.payload.kind === 'connected') { notice(''); if (!event.payload.value.value) void refreshLibrary(); }
    update();
  });
  snapshot = await invoke<RecordValue>('product_snapshot') ?? {};
  await listen<RecordValue>('preferences-changed', event => { prefs = event.payload; void refreshSetup(); });
  const preferenceResult = await invoke<RecordValue>('preferences');
  prefs = preferenceResult.settings;
  if (preferenceResult.error) notice(preferenceResult.error);

  if (view === 'home') {
    content.innerHTML = `<div class="hero"><canvas id="portrait" aria-hidden="true"></canvas><div class="eyebrow">A life on your desktop</div><h1 id="life-name">Your Replicant starts here.</h1><p id="life-status">Choose local models, then welcome a new being or open an existing life.</p><p id="thought-wait" class="quiet" role="status" hidden></p></div>
      <div class="card" id="setup-card"><span class="eyebrow">This computer</span><h2 id="setup-title">Checking this computer…</h2><p id="setup-detail">Thought and memory run here, on your own computer.</p>
        <div id="setup-progress" hidden><progress id="setup-bar" max="1"></progress><p id="setup-step" role="status"></p></div>
        <div class="actions"><button id="setup-go" class="primary" hidden>Set up</button><button id="setup-cancel" hidden>Cancel</button><button data-panel="settings" class="link-button">Choose models yourself</button></div></div>
      <div class="actions"><button id="birth" class="primary" disabled>Welcome a new Replicant</button><button id="open" disabled>Open a .replicant life</button></div>
      <section class="card" id="library"><h2>Your lives</h2><div id="life-list"><p>Finding local lives…</p></div><button id="life-folder" class="link-button">Open life folder</button></section>
      <div class="card" id="living" hidden><div class="status-grid"><div><span class="eyebrow">Vigilance</span><strong id="vigilance"></strong></div><div><span class="eyebrow">Last saved</span><strong id="saved">Waiting for a checkpoint</strong></div></div>
      <div class="actions"><button id="finish-birth" hidden>Continue welcoming</button><button id="talk">Conversation</button><button id="sleep">Let sleep</button><button id="wake">Wake gently</button><button id="pause">Pause thinking</button></div><p class="quiet" id="pause-detail">Pausing lets the current turn finish and stops new inference. Sleep can include memory work.</p><button id="close" class="link-button">Save and close this life</button></div>
      <p class="quiet">A Replicant may speak, move, or stay quiet. Conversation history records what was actually said. Your life is saved in a portable .replicant file with a last-good backup.</p><button id="quit" class="link-button">Save and quit</button>`;
    $(content, '[data-panel]').onclick = () => void invoke('show_panel', { label: 'settings' });
    // One button for people who have never opened a terminal (replicants/desktop/setup.py: prepare).
    const step = (event: RecordValue) => {
      const total = Number(event.total) || 0, done = Number(event.completed) || 0;
      const size = total ? ` ${bytes(done)} of ${bytes(total)}` : '';
      const words: Record<string, string> = {
        survey: event.status ?? 'Checking this computer…',
        runtime: event.status === 'downloading' ? `Preparing a place for thought…${size}` : 'Preparing a place for thought…',
        mind: `Downloading a mind…${size}`, memory: `Downloading memory…${size}`,
        done: event.ready ? 'Ready for a life.' : 'Almost. Something still needs attention.',
      };
      if (event.stage === 'result') return;
      text(content, '#setup-step', words[event.stage] ?? event.status ?? '');
      const bar = $<HTMLProgressElement>(content, '#setup-bar');
      if (total) { bar.max = total; bar.value = done; } else bar.removeAttribute('value');
    };
    await listen<RecordValue>('setup-progress', event => step(event.payload));
    $(content, '#setup-go').onclick = () => void attempt(async () => {
      $(content, '#setup-progress').hidden = false; $(content, '#setup-go').hidden = true; $(content, '#setup-cancel').hidden = false;
      try { await invoke('prepare_local'); } finally { $(content, '#setup-cancel').hidden = true; $(content, '#setup-progress').hidden = true; await refreshSetup(); }
    });
    $(content, '#setup-cancel').onclick = () => void attempt(() => invoke('cancel_download'));
    character($(content, '#portrait'));
    for (const kind of ['birth', 'open', 'close', 'quit']) $(content, `#${kind}`).onclick = () => void lifecycle(kind);
    $(content, '#talk').onclick = () => void invoke('show_panel', { label: 'conversation' });
    $(content, '#finish-birth').onclick = () => void invoke('show_conception');
    $(content, '#life-folder').onclick = () => void attempt(() => invoke('show_life_folder'));
    refreshLibrary = async () => { await attempt(async () => {
      const result = await invoke<RecordValue>('life_library');
      const list = $(content, '#life-list'); list.replaceChildren();
      if (!result.lives?.length) { const empty = document.createElement('p'); empty.textContent = 'Your new Replicants will appear here. You can also open a life file from elsewhere.'; list.append(empty); }
      for (const life of result.lives ?? []) {
        const row = document.createElement('div'); row.className = 'life-row';
        const description = document.createElement('div'), name = document.createElement('strong'), detail = document.createElement('small');
        name.textContent = life.name; detail.textContent = `Saved ${new Date(life.modified_at * 1000).toLocaleDateString()}`;
        description.append(name, detail);
        const button = document.createElement('button'); button.textContent = 'Open'; button.setAttribute('aria-label', `Open ${life.name}`);
        button.disabled = snapshot.lifecycle?.busy === true;
        button.onclick = () => void attempt(async () => { if (!ready) { notice('Choose Set up on Home first.'); return; } await invoke('open_life', { file: life.file }); });
        row.append(description, button); list.append(row);
      }
    }); };
    void refreshLibrary();
    for (const name of ['sleep', 'wake']) $(content, `#${name}`).onclick = () => void attempt(() => invoke('request_control', { value: { name } }));
    $(content, '#pause').onclick = () => void attempt(() => invoke('request_control', { value: { name: snapshot.health?.paused ? 'resume' : 'pause' } }));
    updateView = () => {
      const state = snapshot.state ?? {}, health = snapshot.health ?? {}, connected = snapshot.connected?.value === true;
      const busy = snapshot.lifecycle?.busy === true;
      for (const id of ['birth', 'open', 'close', 'quit']) $<HTMLButtonElement>(content, `#${id}`).disabled = busy;
      for (const button of content.querySelectorAll<HTMLButtonElement>('#life-list button')) button.disabled = busy;
      for (const id of ['talk', 'sleep', 'wake', 'pause']) $<HTMLButtonElement>(content, `#${id}`).disabled = busy || !state.vigilance;
      text(content, '#life-name', connected ? state.name || 'A new life' : 'Your Replicant starts here.');
      text(content, '#life-status', connected ? state.gestating ? 'Growing curious. A first breath takes a little time.' : state.naming ? 'Ready for a name. Open Conversation to answer.' : 'A small presence, with a life of its own.' : 'Welcome a new being or open an existing life.');
      const calls = state.substrate?.inference?.in_flight ?? [];
      const elapsed = Math.floor(Math.max(0, ...calls.map((call: RecordValue) => Number(call.elapsed_seconds) || 0)));
      text(content, '#thought-wait', `Thinking · ${elapsed} s elapsed. Loading a local mind can take time.`);
      $(content, '#thought-wait').hidden = !connected || !calls.length;
      $(content, '#living').hidden = !connected;
      $(content, '#finish-birth').hidden = !connected || Boolean(state.vigilance);
      $(content, '#setup-card').hidden = connected;
      $(content, '#library').hidden = connected;
      $(content, '.actions').hidden = connected;
      text(content, '#vigilance', state.vigilance ?? (state.asleep ? 'asleep' : 'awake'));
      text(content, '#saved', health.last_checkpoint_at ? new Date(health.last_checkpoint_at * 1000).toLocaleTimeString() : 'Waiting for a checkpoint');
      text(content, '#pause', health.paused ? 'Resume thinking' : 'Pause thinking');
      text(content, '#pause-detail', health.paused ? 'New inference is paused. A turn already in progress can finish. The body clock continues.' : 'Pausing lets the current turn finish and stops new inference. Sleep can include memory work.');
      if (snapshot.appearance) character($(content, '#portrait'), snapshot.appearance);
      if (health.error) notice(health.error);
    };
    refreshSetup = async () => { await attempt(async () => {
      const report = await invoke<RecordValue>('setup_check'); ready = report.ready;
      const own = report.runtime?.mode === 'external';
      text(content, '#setup-title', ready ? 'Ready for a life.' : 'One step before a first breath.');
      text(content, '#setup-detail', ready ? 'Thought and memory are ready on this computer.'
        : own ? [...report.issues, ...report.missing.map((m: RecordValue) => `Missing ${m.kind} model: ${m.name}`)].join(' ')
        : 'Replicants will check this computer, prepare a place for thought, and download a mind that fits. Everything stays on this computer.');
      $(content, '#setup-go').hidden = ready;
      for (const id of ['birth', 'open']) $(content, `#${id}`).removeAttribute('disabled');
      update();
    }); };
    void refreshSetup();
  } else if (view === 'room') {
    content.innerHTML = `<div class="page-title"><div class="eyebrow">A place of its own</div><h1>Room</h1><p>The Replicant reads public pages here. Page text stays source material, and its speech stays in Conversation.</p></div>
      <div class="actions"><button id="room-open" class="primary">Open its Room</button><button id="room-close">Close Room</button></div>
      <p id="room-status" role="status"></p><p id="room-error" class="notice" hidden></p>
      <section id="room-reading" hidden><h2 id="room-title"></h2><p id="room-source" class="room-source"></p><img id="room-page" class="room-page" alt="The text currently visible in the Replicant's Room" />
      <div class="actions"><button id="room-up">Read above</button><button id="room-down">Read below</button></div></section>
      <section class="card"><h2>Pages read</h2><p class="quiet">The latest pages opened successfully in this life. A search counts as a page.</p><ol id="room-history"></ol></section>`;
    const control = (name: string, args = {}) => attempt(() => invoke('request_control', { value: { name, ...args } }));
    $(content, '#room-open').onclick = () => void control('room_open');
    $(content, '#room-close').onclick = () => void control('room_close');
    for (const direction of ['up', 'down']) $(content, `#room-${direction}`).onclick = () => void control('room_scroll', { direction });
    updateView = () => {
      const room = snapshot.room ?? {}, connected = snapshot.connected?.value === true;
      const available = connected && room.available !== false && Boolean(snapshot.room);
      const busy = ['starting', 'loading'].includes(room.status);
      $<HTMLButtonElement>(content, '#room-open').disabled = !available || busy;
      $<HTMLButtonElement>(content, '#room-close').disabled = !room.open;
      $(content, '#room-open').hidden = room.open === true;
      text(content, '#room-status', !connected ? 'Open a life from Home to use its Room.' : !available ? 'The isolated reader is unavailable. Reinstall the current beta to restore it.' : ({ starting: 'Opening the reader…', loading: 'Reading a page…', reading: 'Reading', idle: 'Open. A place to follow its curiosity.', closed: 'Closed. Open its Room when you want to share it.' } as Record<string, string>)[room.status] ?? 'The reader needs attention.');
      const errors: Record<string, string> = { room_reader_failed: 'The reader stopped. Close and reopen its Room to try again.', room_browser_restarted: 'The reader restarted. Close and reopen its Room to restore the page.', room_page_structure_limit: 'This page is too complex for the text reader.', host_wake_page_budget: 'The page limit for this wake has been reached.', host_hour_page_budget: 'The page limit for this hour has been reached.' };
      text(content, '#room-error', room.error ? `${errors[room.error] ?? 'The page could not be read.'}${room.attempted_url ? ` Attempted: ${room.attempted_url}` : ''} The previous page stays visible.` : '');
      $(content, '#room-error').hidden = !room.error;
      $(content, '#room-reading').hidden = !room.open;
      text(content, '#room-title', room.title || 'A place to read'); text(content, '#room-source', room.url || 'No page opened yet.');
      const image = $<HTMLImageElement>(content, '#room-page');
      if (typeof room.image === 'string' && /^[A-Za-z0-9+/=]+$/.test(room.image)) image.src = `data:image/png;base64,${room.image}`;
      else image.removeAttribute('src');
      for (const direction of ['up', 'down']) $<HTMLButtonElement>(content, `#room-${direction}`).disabled = busy || !room.open || !room.url;
      const history = $(content, '#room-history'); history.replaceChildren();
      for (const page of [...(room.history ?? [])].reverse()) {
        const row = document.createElement('li'), title = document.createElement('strong'), source = document.createElement('div');
        title.textContent = String(page.title ?? 'Untitled page'); source.textContent = String(page.url ?? ''); source.className = 'room-source';
        row.append(title, source); history.append(row);
      }
    };
  } else if (view === 'conversation') {
    content.innerHTML = `<div class="page-title"><div class="eyebrow">Being together</div><h1 id="conversation-name">Conversation</h1><p>Speech is optional. A completed turn can be quiet.</p><p id="presence" class="quiet" role="status"></p></div><div id="messages" class="messages" role="log" aria-label="Conversation history"></div>
      <form id="composer" class="composer"><label for="message">Say something</label><textarea id="message" maxlength="4000" rows="3" placeholder="Something to share…"></textarea><div class="compose-bottom"><span id="delivery" role="status">Messages and replies stay in this life file.</span><button class="primary" type="submit">Send</button></div></form>`;
    const input = $<HTMLTextAreaElement>(content, '#message');
    const messages = $(content, '#messages');
    let pending: { id: string; text: string } | null = null;
    let previous = '';
    const draftKey = 'replicants.conversation.draft';
    input.value = sessionStorage.getItem(draftKey) ?? '';
    input.oninput = () => { sessionStorage.setItem(draftKey, input.value); if (pending?.text !== input.value.trim()) pending = null; };
    updateView = () => {
      text(content, '#conversation-name', snapshot.state?.name ? `With ${snapshot.state.name}` : snapshot.state?.naming ? 'A name for a new life' : 'Conversation');
      const calls = snapshot.state?.substrate?.inference?.in_flight ?? [];
      const elapsed = Math.floor(Math.max(0, ...calls.map((call: RecordValue) => Number(call.elapsed_seconds) || 0)));
      text(content, '#presence', !snapshot.connected?.value ? 'Open a life from Home. Your draft stays here.'
        : snapshot.health?.paused ? calls.length ? 'Pausing after the current thought.' : 'Thinking paused. Resume from Home to be together.'
        : calls.length ? `Local inference in progress · ${elapsed} s elapsed. Longer thoughts can take time.`
        : snapshot.state?.vigilance === 'asleep' ? 'Sleeping. Your words are received; waking depends on sleep depth.'
        : snapshot.state?.vigilance === 'drowsy' ? 'Drowsy. It may settle into sleep.' : 'Together. It may speak, move, or stay quiet.');
      const list = snapshot.conversation?.messages ?? [];
      if (pending && list.some((message: RecordValue) => message.id === pending!.id)) {
        if (input.value.trim() === pending.text) { input.value = ''; sessionStorage.removeItem(draftKey); }
        pending = null; text(content, '#delivery', 'Received by your Replicant.');
      }
      const key = JSON.stringify(list); if (key === previous) return; previous = key;
      const atBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 80;
      messages.replaceChildren();
      if (!list.length) {
        const empty = document.createElement('p'); empty.className = 'empty-state';
        empty.textContent = snapshot.connected?.value ? 'A little space for whatever happens next.' : 'Open a life from Home to be together.'; messages.append(empty);
      }
      for (const message of list) {
        const article = document.createElement('article'); article.className = `message ${message.role === 'person' ? 'person' : 'replicant'}`;
        const label = document.createElement('span'); label.className = 'eyebrow'; label.textContent = message.role === 'person' ? 'You' : snapshot.state?.name || 'Replicant';
        const body = document.createElement('p'); body.textContent = message.text;
        const status = document.createElement('small'); status.textContent = `${new Date(message.at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · ${message.status}${message.detail ? ` · ${message.detail}` : ''}`;
        article.append(label, body, status);
        if (message.role === 'person' && ['failed', 'interrupted'].includes(message.status)) {
          const retry = document.createElement('button'); retry.className = 'link-button'; retry.textContent = 'Use these words again';
          retry.onclick = () => { input.value = message.text; input.dispatchEvent(new Event('input')); input.focus(); };
          article.append(retry);
        }
        messages.append(article);
      }
      if (atBottom) messages.scrollTop = messages.scrollHeight;
    };
    const send = () => attempt(async () => {
      if (!input.value.trim()) return;
      if (!snapshot.connected?.value) { text(content, '#delivery', 'Open a life from Home first. Your draft is saved in this window.'); return; }
      if (snapshot.health?.paused) { text(content, '#delivery', 'Resume thinking from Home before sending.'); return; }
      pending ??= { id: crypto.randomUUID(), text: input.value.trim() };
      await invoke('send_message', pending);
      text(content, '#delivery', 'Waiting for receipt. Your draft stays here until it arrives.');
    });
    $<HTMLFormElement>(content, '#composer').onsubmit = event => { event.preventDefault(); void send(); };
    input.onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); void send(); } };
  } else {
    content.innerHTML = `<div class="page-title"><div class="eyebrow">This computer</div><h1>Make room for a life.</h1><p>Thought runs through local Ollama. Choose models already installed, or download them explicitly below.</p></div>
      <form id="settings-form"><section class="card"><h2>Local models</h2><label>Where thought runs<select name="runtime"><option value="auto">Automatic (recommended)</option><option value="managed">Built into Replicants</option><option value="external">An Ollama I installed</option></select></label><label>Ollama address<input name="ollama_url" type="url" required></label><p class="quiet">Localhost only. No cloud inference or API keys.</p>
      <label>Chat model<input name="chat_model" list="installed-models" required></label><label>Memory model<input name="embedding_model" list="installed-models" required></label><datalist id="installed-models"></datalist>
      <label>Decision format<select name="decision_mode"><option value="json">JSON (works without tool calling)</option><option value="tools">Native tool calling</option></select></label>
      <div class="actions"><button type="button" id="check">Check connection</button><button type="button" id="ollama">Install Ollama</button></div><p id="setup-result" role="status">Checking local setup…</p><p id="hardware" class="quiet"></p></section>
      <section class="card"><h2>Downloads</h2><p>Models can use many gigabytes of disk and memory. Choose an appropriate model for your hardware. Downloads need internet access; inference stays local.</p>
      <label class="check"><input type="checkbox" id="download-consent">I want to download the selected model with Ollama.</label><div class="actions"><button type="button" id="pull-chat">Download chat model</button><button type="button" id="pull-memory">Download memory model</button><button type="button" id="cancel" hidden>Cancel download</button></div><progress id="download-progress" hidden></progress><p id="download-status" role="status"></p></section>
      <section class="card"><h2>Desktop presence</h2><label>Body size<input name="body_scale" type="range" min="3" max="12" step="1"></label><label class="check"><input name="ambient" type="checkbox">Sense window edges and idle time</label><label class="check"><input name="show_thoughts" type="checkbox">Show private thought fragments on hover</label><label class="check"><input name="reduced_motion" type="checkbox">Reduce idle animation</label><label class="check"><input name="hide_fullscreen" type="checkbox">Hide the body over fullscreen apps</label><p class="quiet">Replicants cannot read your screen or window contents. Active-app names stay off unless enabled for a session in the inspector.</p></section>
      <details class="card"><summary>Compute limits</summary><label>Context tokens<input name="context_tokens" type="number" min="2048" max="32768" step="1024"></label><label>Reply token limit<input name="reply_tokens" type="number" min="256" max="4096" step="256"></label><label>Autonomous wakes per hour<input name="max_wakes_per_hour" type="number" min="1" max="12"></label><label class="check"><input name="thinking" type="checkbox">Model reasoning mode</label><p class="quiet">These are limits, not a schedule. Pausing on Home stops new inference after the current turn. Sleep can still include memory work.</p></details>
      <button class="primary" id="save">Save settings</button><p class="quiet">Body preferences apply now. Model, sensing, and compute settings apply when you next open a life.</p></form>
      <section class="card"><h2>Support and updates</h2><p>Beta updates are installed manually. Your .replicant files remain separate from the application.</p><button id="releases">Beta downloads</button><button id="diagnostics">Export support details</button><p id="support-result" class="quiet" role="status">Support details exclude conversations, thoughts, paths, logs, and authentication.</p></section>`;
    const form = $<HTMLFormElement>(content, '#settings-form');
    for (const element of form.elements) {
      if (!(element instanceof HTMLInputElement || element instanceof HTMLSelectElement) || !(element.name in prefs)) continue;
      if (element instanceof HTMLInputElement && element.type === 'checkbox') element.checked = prefs[element.name];
      else element.value = String(prefs[element.name]);
    }
    const values = () => {
      const result = { ...prefs };
      for (const element of form.elements) {
        if (!(element instanceof HTMLInputElement || element instanceof HTMLSelectElement) || !(element.name in prefs)) continue;
        result[element.name] = element instanceof HTMLInputElement && element.type === 'checkbox' ? element.checked : typeof prefs[element.name] === 'number' ? Number(element.value) : element.value.trim();
      }
      return result;
    };
    const save = async () => { const result = await invoke<RecordValue>('save_preferences', { value: values() }); prefs = result.settings; };
    const check = () => attempt(async () => {
      text(content, '#setup-result', 'Checking…');
      const report = await invoke<RecordValue>('setup_check'); ready = report.ready;
      text(content, '#setup-result', ready ? `Ready. Ollama ${report.ollama.version}.` : [...report.issues, ...report.missing.map((m: RecordValue) => `Missing ${m.kind}: ${m.name}`)].join(' '));
      text(content, '#hardware', `${bytes(report.hardware.ram_available_bytes)} RAM available of ${bytes(report.hardware.ram_total_bytes)}. ${bytes(report.hardware.disk_free_bytes)} disk space available.`);
      const options = $(content, '#installed-models'); options.replaceChildren();
      for (const model of report.models) { const option = document.createElement('option'); option.value = model.name; option.label = model.size ? `${model.name} (${bytes(model.size)})` : model.name; options.append(option); }
    });
    form.onsubmit = event => { event.preventDefault(); void attempt(async () => { await save(); notice('Settings saved. Open your next life with these local models.'); await check(); }); };
    $(content, '#check').onclick = () => void attempt(async () => { await save(); await check(); });
    $(content, '#ollama').onclick = () => void attempt(() => invoke('open_help', { target: 'ollama' }));
    $(content, '#releases').onclick = () => void attempt(() => invoke('open_help', { target: 'releases' }));
    $(content, '#diagnostics').onclick = () => void attempt(async () => { const path = await invoke<string>('export_diagnostics'); text(content, '#support-result', `Saved: ${path}`); });
    await listen<RecordValue>('model-download', event => {
      const value = event.payload; text(content, '#download-status', value.error ?? value.status ?? 'Downloading…');
      const progress = $<HTMLProgressElement>(content, '#download-progress'); progress.hidden = false;
      if (value.total > 0) { progress.max = value.total; progress.value = value.completed ?? 0; } else progress.removeAttribute('value');
    });
    for (const [id, key] of [['pull-chat', 'chat_model'], ['pull-memory', 'embedding_model']]) $(content, `#${id}`).onclick = () => void attempt(async () => {
      if (!$<HTMLInputElement>(content, '#download-consent').checked) { notice('Confirm the download above first.'); return; }
      await save(); $(content, '#cancel').hidden = false;
      for (const button of content.querySelectorAll<HTMLButtonElement>('#pull-chat, #pull-memory, #save')) button.disabled = true;
      try { await invoke('download_model', { model: prefs[key] }); text(content, '#download-status', 'Download complete.'); await check(); }
      finally { $(content, '#cancel').hidden = true; for (const button of content.querySelectorAll<HTMLButtonElement>('#pull-chat, #pull-memory, #save')) button.disabled = false; }
    });
    $(content, '#cancel').onclick = () => void attempt(() => invoke('cancel_download'));
    void check();
  }
  update();
}
