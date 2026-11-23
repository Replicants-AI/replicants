import type { Desktop, DesktopWindow } from './types.ts';
export interface Floor { id: string; x: number; y: number; width: number }

/** Subtract covered portions of lower windows, using native front-to-back z order. */
export function floors(world: Desktop): Floor[] {
  const output: Floor[] = [];
  for (let i = 0; i < world.windows.length; i++) {
    const w = world.windows[i];
    let spans = [[Math.max(world.work.x, w.x), Math.min(world.work.x + world.work.width, w.x + w.width)]];
    for (const above of world.windows.slice(0, i)) {
      if (above.y > w.y || above.y + above.height <= w.y) continue;
      spans = spans.flatMap(([a, b]) => {
        if (above.x >= b || above.x + above.width <= a) return [[a, b]];
        return [[a, Math.min(b, above.x)], [Math.max(a, above.x + above.width), b]].filter(([a,b]) => b > a);
      });
    }
    for (const [a, b] of spans) if (b - a >= 10) output.push({ id: w.id, x: a, y: w.y, width: b - a });
  }
  output.push({ id: 'work-area', x: world.work.x, y: world.work.y + world.work.height, width: world.work.width });
  return output;
}

export class Physics {
  x = 100; y = 100; vx = 0; vy = 0; scale = 6; floor: string | null = null;
  dragging = false; landedAt = -1; fellAt = -1;
  wallHitAt = -1; wallSliding = false; wallSide: 'left' | 'right' = 'left';
  private random: () => number;
  private previousWindows = new Map<string, DesktopWindow>();
  private previousGeometryAt = 0;
  constructor(random = Math.random) { this.random = random; }
  get width() { return 8 * this.scale; }
  get height() { return 7 * this.scale; }
  get center() { return this.x + this.width / 2; }
  get bottom() { return this.y + this.height; }

  geometry(world: Desktop, now: number) {
    if (this.floor && this.floor !== 'work-area' && !this.dragging) {
      const old = this.previousWindows.get(this.floor);
      const next = world.windows.find(w => w.id === this.floor);
      if (!next || !old) this.detach(now);
      else {
        const dx = next.x - old.x, dy = next.y - old.y;
        const distance = Math.hypot(dx, dy), seconds = Math.max(.05, (now - this.previousGeometryAt) / 1000);
        if (distance > 48 || distance / seconds > 180) this.detach(now);
        else { this.x += dx; this.y += dy; }
      }
    }
    this.previousWindows = new Map(world.windows.map(w => [w.id, { ...w }]));
    this.previousGeometryAt = now;
  }
  detach(now: number) { this.floor = null; this.fellAt = now; this.vy = Math.max(20, this.vy); }
  pickUp() { this.dragging = true; this.floor = null; this.vx = this.vy = 0; this.wallSliding = false; }
  release(now: number, velocity = { vx: 0, vy: 0 }) {
    this.dragging = false; this.floor = null; this.fellAt = now;
    this.vx = velocity.vx; this.vy = velocity.vy;
  }
  place(world: Desktop) {
    const first = floors(world).find(f => f.id !== 'work-area' && f.y >= this.height + 8 && f.width > this.width * 3) ?? floors(world).at(-1)!;
    this.x = first.x + Math.min(first.width / 3, 200); this.y = first.y - this.height; this.floor = first.id;
  }
  tick(dt: number, now: number, world: Desktop) {
    if (this.dragging) return;
    dt = Math.min(.05, Math.max(0, dt));
    const edges = floors(world);
    const before = this.bottom;
    this.x += this.vx * dt;
    const minX = world.work.x, maxX = world.work.x + world.work.width - this.width;
    if (this.x < minX || this.x > maxX) {
      this.wallSide = this.x < minX ? 'left' : 'right';
      this.x = Math.max(minX, Math.min(maxX, this.x));
      if (!this.floor && Math.abs(this.vx) > 150 * this.scale && this.random() < .25) {
        this.wallSliding = true; this.wallHitAt = now; this.vx = this.vy = 0;
      } else this.vx = -this.vx * .35;
    }
    const support = edges.find(f => f.id === this.floor && this.center >= f.x && this.center <= f.x + f.width && Math.abs(f.y - this.bottom) < 2);
    if (this.floor && !support) this.detach(now);
    if (this.floor) { this.vy = 0; return; }
    if (this.wallSliding && now - this.wallHitAt < 420) return;
    // The supplied page uses G=.0004 sprite cells/ms² and wall slide=.02 cells/ms.
    this.vy = this.wallSliding ? 20 * this.scale : this.vy + 400 * this.scale * dt;
    this.y += this.vy * dt;
    if (this.y < 0) { this.y = 0; this.vy = Math.max(0, this.vy); }
    const landing = edges.filter(f => this.center >= f.x && this.center <= f.x + f.width && before <= f.y + 1 && this.bottom >= f.y && this.vy > 0).sort((a,b) => a.y - b.y)[0];
    if (landing) { this.y = landing.y - this.height; this.floor = landing.id; this.vx = this.vy = 0; this.landedAt = now; this.wallSliding = false; }
    if (this.bottom > world.work.y + world.work.height) { this.y = world.work.y + world.work.height - this.height; this.floor = 'work-area'; this.vx = this.vy = 0; this.landedAt = now; this.wallSliding = false; }
  }
}
