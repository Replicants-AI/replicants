import { ANIMS, compose, FW, FH, MASK, poseAt } from './motion.js';
import { BODY_DESIGNS, DesignDraft, pixels } from './body-design.ts';
import type { InbornDesign } from './types.ts';

const previewMotions = ANIMS.filter(motion => ['breathe', 'blink', 'look', 'walk', 'wave', 'sit', 'dance', 'yawn'].includes(motion.id));

function portrait(canvas: HTMLCanvasElement, design: InbornDesign, pose = {}) {
  canvas.width = FW; canvas.height = FH;
  const ctx = canvas.getContext('2d')!;
  for (const [x, y, color] of compose(design, pose)) { ctx.fillStyle = color; ctx.fillRect(x, y, 1, 1); }
}

export function designEditor(root: HTMLElement) {
  const initial = BODY_DESIGNS.find(item => item.id === 'art:01-classic')!;
  const draft = new DesignDraft(initial.design);
  let original = initial.design, brush = '#3D7BE0', tool = 'paint', locked = false;
  let stroke: number | null = null, last: { x: number; y: number } | null = null;
  root.innerHTML = `<section class="design-library" aria-labelledby="design-heading"><div class="design-heading"><h2 id="design-heading">Choose a starting design</h2><span>${BODY_DESIGNS.length} authored designs</span></div><div class="design-gallery" role="group" aria-label="Starting designs"></div></section>
    <section class="drawing-workspace" aria-label="Pixel editor"><div><div class="design-heading"><h2>Make it yours</h2><span>8 × 7 pixels</span></div><p class="quiet">Paint any body pixel. Drag to draw a stroke.</p><div class="pixel-grid" role="grid" aria-label="Body pixels"></div>
    <div class="paint-tools"><button type="button" data-tool="paint" aria-pressed="true">Brush</button><button type="button" data-tool="pick" aria-pressed="false">Eyedropper</button><label class="brush-color">Color<input type="color" aria-label="Brush color" value="${brush}"></label><label class="brush-hex">Hex<input type="text" aria-label="Hex color" maxlength="7" spellcheck="false" value="${brush}" pattern="#[0-9A-Fa-f]{6}"></label></div>
    <div class="drawing-actions"><button type="button" data-edit="undo" disabled>Undo</button><button type="button" data-edit="redo" disabled>Redo</button><button type="button" data-edit="reset">Reset drawing</button></div></div>
    <div class="design-preview"><h2>In motion</h2><div class="preview-stage"><canvas aria-label="Animated drawing preview" role="img"></canvas></div><label>Preview motion<select aria-label="Preview motion"></select></label><div class="drawing-actions"><button type="button" data-edit="export">Save drawing</button><button type="button" data-edit="import">Load drawing</button><input type="file" accept=".json,application/json" hidden></div><p class="quiet">Your drawing is set at birth. A name comes after first breath.</p></div></section><p class="drawing-status quiet" role="status" aria-live="polite"></p>`;
  const $ = <T extends HTMLElement = HTMLElement>(query: string) => root.querySelector<T>(query)!;
  const status = (message: string) => { $('.drawing-status').textContent = message; };
  const colorInput = $<HTMLInputElement>('input[type=color]'), hexInput = $<HTMLInputElement>('input[type=text]');
  const grid = $('.pixel-grid'), preview = $<HTMLCanvasElement>('.preview-stage canvas');
  const motions = $<HTMLSelectElement>('.design-preview select');
  for (const motion of previewMotions) {
    const option = document.createElement('option'); option.value = motion.id; option.textContent = motion.name; motions.append(option);
  }
  motions.value = 'breathe';
  const cells: HTMLButtonElement[][] = [];
  for (let y = 0; y < 7; y++) {
    const row = document.createElement('div'); row.setAttribute('role', 'row'); cells[y] = [];
    for (let x = 0; x < 8; x++) {
      const cell = document.createElement('button'); cell.type = 'button'; cell.dataset.x = String(x); cell.dataset.y = String(y);
      cell.setAttribute('role', 'gridcell'); cell.tabIndex = y === 0 && x === 1 ? 0 : -1;
      cell.disabled = MASK[y][x] === '.'; cell.className = cell.disabled ? 'empty-pixel' : 'body-pixel';
      if (cell.disabled) cell.setAttribute('aria-label', 'Outside body');
      cells[y][x] = cell; row.append(cell);
    }
    grid.append(row);
  }
  const selectTool = (value: string) => {
    tool = value; for (const button of root.querySelectorAll<HTMLButtonElement>('[data-tool]')) button.setAttribute('aria-pressed', String(button.dataset.tool === tool));
  };
  const setColor = (color: string) => { brush = color.toUpperCase(); colorInput.value = brush; hexInput.value = brush; hexInput.setCustomValidity(''); };
  colorInput.oninput = () => setColor(colorInput.value);
  hexInput.oninput = () => {
    if (/^#[\da-f]{6}$/i.test(hexInput.value)) setColor(hexInput.value);
    else hexInput.setCustomValidity('Use # followed by six hex digits.');
  };
  const refresh = () => {
    const colors = pixels(draft.value);
    for (let y = 0; y < 7; y++) for (let x = 0; x < 8; x++) if (colors[y][x]) {
      const cell = cells[y][x]; cell.style.backgroundColor = colors[y][x]!;
      cell.setAttribute('aria-label', `Pixel row ${y + 1}, column ${x + 1}, ${colors[y][x]}`);
      cell.disabled = locked;
    }
    $<HTMLButtonElement>('[data-edit=undo]').disabled = locked || !draft.canUndo;
    $<HTMLButtonElement>('[data-edit=redo]').disabled = locked || !draft.canRedo;
    for (const button of root.querySelectorAll<HTMLButtonElement>('[data-design]')) {
      button.setAttribute('aria-pressed', String(JSON.stringify(BODY_DESIGNS.find(item => item.id === button.dataset.design)!.design) === JSON.stringify(draft.value)));
    }
    portrait(preview, draft.value);
  };
  for (const item of BODY_DESIGNS) {
    const button = document.createElement('button'); button.type = 'button'; button.dataset.design = item.id;
    button.setAttribute('aria-label', `${item.name}, ${item.group}`); button.title = `${item.name} · ${item.group}`;
    const image = document.createElement('canvas'); image.setAttribute('aria-hidden', 'true'); portrait(image, item.design);
    const label = document.createElement('span'); label.textContent = item.name;
    button.append(image, label); button.onclick = () => { original = item.design; draft.replace(item.design); refresh(); status(`${item.name} selected. Every body pixel can be painted.`); };
    $('.design-gallery').append(button);
  }
  const finish = () => { draft.finishStroke(); stroke = null; last = null; refresh(); };
  const at = (event: PointerEvent) => {
    const rect = grid.getBoundingClientRect();
    return { x: Math.floor((event.clientX - rect.left) / rect.width * 8), y: Math.floor((event.clientY - rect.top) / rect.height * 7) };
  };
  const paint = (point: { x: number; y: number }) => {
    if (tool === 'pick') {
      const color = pixels(draft.value)[point.y]?.[point.x];
      if (color) { setColor(color); selectTool('paint'); status(`Picked ${color}.`); }
      return;
    }
    const start = last ?? point, steps = Math.max(Math.abs(point.x - start.x), Math.abs(point.y - start.y), 1);
    for (let i = 0; i <= steps; i++) draft.paint(Math.round(start.x + (point.x - start.x) * i / steps), Math.round(start.y + (point.y - start.y) * i / steps), brush);
    last = point; refresh();
  };
  grid.onpointerdown = event => {
    if (locked || event.button !== 0 || stroke !== null) return;
    const point = at(event); if (MASK[point.y]?.[point.x] !== '#') return;
    event.preventDefault(); cells[point.y][point.x].focus();
    if (tool === 'pick') { paint(point); return; }
    stroke = event.pointerId; draft.beginStroke(); grid.setPointerCapture(stroke); paint(point);
  };
  grid.onpointermove = event => {
    if (stroke !== event.pointerId) return;
    const point = at(event);
    if (point.x < 0 || point.x > 7 || point.y < 0 || point.y > 6) { last = null; return; }
    paint(point);
  };
  grid.onpointerup = grid.onpointercancel = event => {
    if (stroke === event.pointerId) { if (grid.hasPointerCapture(event.pointerId)) grid.releasePointerCapture(event.pointerId); finish(); }
  };
  grid.onlostpointercapture = () => { if (stroke !== null) finish(); };
  grid.onclick = event => {
    // Keyboard activation produces detail=0; pointer strokes are handled above.
    if (event.detail !== 0 || locked) return;
    const cell = (event.target as HTMLElement).closest<HTMLButtonElement>('.body-pixel'); if (!cell) return;
    paint({ x: Number(cell.dataset.x), y: Number(cell.dataset.y) }); finish();
  };
  grid.onkeydown = event => {
    const cell = (event.target as HTMLElement).closest<HTMLButtonElement>('.body-pixel'); if (!cell) return;
    const delta: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (!delta[event.key]) return;
    event.preventDefault(); let x = Number(cell.dataset.x), y = Number(cell.dataset.y); const [dx, dy] = delta[event.key];
    do { x += dx; y += dy; } while (x >= 0 && x < 8 && y >= 0 && y < 7 && MASK[y][x] === '.');
    if (MASK[y]?.[x] !== '#') return;
    for (const row of cells) for (const pixel of row) pixel.tabIndex = -1;
    cells[y][x].tabIndex = 0; cells[y][x].focus();
  };
  for (const button of root.querySelectorAll<HTMLButtonElement>('[data-tool]')) button.onclick = () => selectTool(button.dataset.tool!);
  $<HTMLButtonElement>('[data-edit=undo]').onclick = () => { draft.undo(); refresh(); status('Drawing restored.'); };
  $<HTMLButtonElement>('[data-edit=redo]').onclick = () => { draft.redo(); refresh(); status('Change restored.'); };
  $<HTMLButtonElement>('[data-edit=reset]').onclick = () => { draft.replace(original); refresh(); status('Starting design restored. Undo brings your drawing back.'); };
  $<HTMLButtonElement>('[data-edit=export]').onclick = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(draft.value, null, 2) + '\n'], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = 'replicant-drawing.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const file = $<HTMLInputElement>('input[type=file]');
  $<HTMLButtonElement>('[data-edit=import]').onclick = () => file.click();
  file.onchange = async () => {
    const selected = file.files?.[0]; if (!selected) return;
    try {
      if (selected.size > 65536) throw new Error('Choose a drawing file smaller than 64 KB.');
      const design = JSON.parse(await selected.text()) as InbornDesign; pixels(design);
      if (locked) return;
      draft.replace(design); original = structuredClone(draft.value); refresh(); status('Drawing loaded.');
    } catch (error) { status(error instanceof Error ? error.message : 'This drawing could not be loaded.'); }
    finally { file.value = ''; }
  };
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let frame = 0, destroyed = false;
  const animate = (time: number) => {
    if (destroyed || !root.isConnected) return;
    const motion = previewMotions.find(a => a.id === motions.value)!;
    portrait(preview, draft.value, reduced.matches ? {} : poseAt(motion, time));
    frame = requestAnimationFrame(animate);
  };
  refresh(); frame = requestAnimationFrame(animate);
  return {
    design: () => { draft.finishStroke(); return structuredClone(draft.value); },
    disabled(value: boolean) {
      finish(); locked = value;
      for (const element of root.querySelectorAll<HTMLInputElement | HTMLButtonElement | HTMLSelectElement>('button,input,select')) element.disabled = value;
      for (let y = 0; y < 7; y++) for (let x = 0; x < 8; x++) if (MASK[y][x] === '.') cells[y][x].disabled = true;
      refresh();
    },
    destroy() { destroyed = true; cancelAnimationFrame(frame); },
  };
}
