import type { Desktop, DesktopWindow } from './types.ts';

export class RoomView {
  private element = document.createElement('section');
  private title = document.createElement('strong');
  private source = document.createElement('div');
  private image = document.createElement('img');
  private opened = false;
  private rectangle: DesktopWindow | null = null;
  private front = true;
  private native: boolean;

  constructor(native = false) {
    this.native = native;
    this.element.className = 'room-window'; this.element.hidden = true;
    this.element.setAttribute('aria-label', 'The Replicant’s Room reader');
    this.image.alt = 'Live text browser in the Replicant’s own Room';
    this.element.append(this.title, this.source, this.image); document.body.append(this.element);
  }

  update(value: Record<string, any>) {
    const rect = value.window;
    this.opened = value.open === true;
    if (rect && ['x','y','width','height'].every(k => Number.isFinite(rect[k]))) this.rectangle = { ...rect, id: 'replicants-room' };
    this.front = value.front !== false;
    this.element.hidden = this.native || !this.opened;
    this.title.textContent = String(value.title || 'Room');
    this.source.textContent = String(value.url || 'A place to read.');
    if (typeof value.image === 'string' && /^[A-Za-z0-9+/=]+$/.test(value.image)) this.image.src = 'data:image/png;base64,' + value.image;
  }

  world(desktop: Desktop): Desktop {
    if (this.native) return desktop;
    const windows = desktop.windows.filter(w => w.id !== 'replicants-room');
    if (!this.opened || !this.rectangle) return { ...desktop, windows };
    const r = this.rectangle;
    Object.assign(this.element.style, { left: `${r.x - desktop.monitor.x}px`, top: `${r.y - desktop.monitor.y}px`,
      width: `${r.width}px`, height: `${r.height}px` });
    return { ...desktop, windows: this.front ? [r, ...windows] : [...windows, r] };
  }
}
