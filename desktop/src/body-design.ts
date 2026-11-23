import atlas from './sprites.json' with { type: 'json' };
import { MASK, REPS } from './motion.js';
import { anatomy } from './appearance.ts';
import type { InbornDesign } from './types.ts';

export type PixelGrid = (string | null)[][];
const codes = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
export const BODY_PIXELS = MASK.join('').replaceAll('.', '').length;
const hex = /^#[\da-f]{6}$/i;

export function pixels(design: InbornDesign): PixelGrid {
  if (!design || typeof design.name !== 'string' || !design.name.trim() || design.name.length > 80 ||
      !Array.isArray(design.rows) || design.rows.length !== MASK.length ||
      !design.pal || typeof design.pal !== 'object' || Array.isArray(design.pal) ||
      Object.keys(design.pal).length < 1 || Object.keys(design.pal).length > BODY_PIXELS ||
      Object.entries(design.pal).some(([key, color]) => key.length !== 1 || key === '.' || typeof color !== 'string' || !hex.test(color))) {
    throw new Error('Use an 8 by 7 body drawing with six-digit hex colors.');
  }
  return design.rows.map((row, y) => {
    if (typeof row !== 'string' || row.length !== 8) throw new Error('Use eight pixels per row.');
    return [...row].map((key, x) => {
      if ((key === '.') !== (MASK[y][x] === '.') || (key !== '.' && !hex.test(design.pal[key] ?? ''))) {
        throw new Error('The drawing must fill the body shape.');
      }
      return key === '.' ? null : design.pal[key].toUpperCase();
    });
  });
}

export function drawing(grid: PixelGrid, name = 'Custom drawing'): InbornDesign {
  if (grid.length !== 7 || grid.some(row => row.length !== 8)) throw new Error('Use an 8 by 7 drawing.');
  const pal: Record<string, string> = {}, colors = new Map<string, string>();
  const rows = grid.map((row, y) => row.map((color, x) => {
    if ((color === null) !== (MASK[y][x] === '.')) throw new Error('Keep the body shape filled.');
    if (color === null) return '.';
    if (!hex.test(color)) throw new Error('Use six-digit hex colors.');
    color = color.toUpperCase();
    if (!colors.has(color)) { const key = codes[colors.size]; colors.set(color, key); pal[key] = color; }
    return colors.get(color)!;
  }).join(''));
  return { name, rows, pal };
}

export const BODY_DESIGNS = [
  ...Object.keys(atlas.presets).map(id => ({
    id: `art:${id}`, name: id.replace(/^\d+-/, '').replaceAll('-', ' ').replace(/\b\w/g, c => c.toUpperCase()),
    group: 'Illustrations', design: anatomy({ preset: id, layers: [] }),
  })),
  ...REPS.map((rep, i) => ({ id: `motion:${i}`, name: rep.name, group: 'Motion designs', design: rep })),
].map(item => ({ ...item, design: drawing(pixels(item.design), item.name) }));

/** A pointer stroke is one undo step, including a stroke across many cells. */
export class DesignDraft {
  value: InbornDesign;
  private past: InbornDesign[] = [];
  private future: InbornDesign[] = [];
  private beforeStroke: InbornDesign | null = null;
  constructor(design: InbornDesign) { this.value = drawing(pixels(design), design.name); }
  get canUndo() { return this.past.length > 0; }
  get canRedo() { return this.future.length > 0; }
  beginStroke() { this.beforeStroke ??= structuredClone(this.value); }
  paint(x: number, y: number, color: string) {
    if (!Number.isInteger(x) || !Number.isInteger(y) || MASK[y]?.[x] !== '#') return false;
    if (!hex.test(color)) throw new Error('Use six-digit hex colors.');
    const grid = pixels(this.value);
    if (grid[y][x] === color.toUpperCase()) return false;
    this.beginStroke(); grid[y][x] = color.toUpperCase(); this.value = drawing(grid); return true;
  }
  finishStroke() {
    if (this.beforeStroke && JSON.stringify(this.beforeStroke) !== JSON.stringify(this.value)) {
      this.remember(this.beforeStroke); this.future = [];
    }
    this.beforeStroke = null;
  }
  replace(design: InbornDesign) {
    const next = drawing(pixels(design), design.name);
    this.finishStroke();
    if (JSON.stringify(next) === JSON.stringify(this.value)) return;
    this.remember(this.value); this.future = []; this.value = next;
  }
  undo() {
    this.finishStroke(); const previous = this.past.pop();
    if (previous) { this.future.push(this.value); this.value = previous; }
  }
  redo() {
    this.finishStroke(); const next = this.future.pop();
    if (next) { this.remember(this.value); this.value = next; }
  }
  private remember(value: InbornDesign) { this.past.push(structuredClone(value)); if (this.past.length > 100) this.past.shift(); }
}
