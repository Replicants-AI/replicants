import atlas from './sprites.json' with { type: 'json' };
import { MASK, type Rep } from './motion.js';
import type { Appearance } from './types.ts';

type Layer = { palette: string[]; pixels: number[][]; slot?: string };
const designs: Record<string, Layer> = atlas.presets;
const layers: Record<string, Layer> = atlas.layers;
const cache = new Map<string, Rep>();

/** SVGs own colors; the motion page owns anatomy and movement. */
export function anatomy(appearance: Appearance, dormant = false): Rep {
  const key = JSON.stringify([appearance, dormant]);
  const known = cache.get(key); if (known) return known;
  const grid: (string | null)[][] = MASK.map(row => [...row].map(() => null));
  const paint = (layer: Layer, tint?: string) => layer.pixels.forEach((row, y) => row.forEach((index, x) => {
    if (index) grid[y][x] = tint ?? layer.palette[index];
  }));
  paint(atlas.base, dormant ? '#18181C' : appearance.palette);
  paint(atlas.eyes, dormant ? '#494955' : undefined);
  if (!dormant) {
    if (appearance.design) {
      const design = appearance.design;
      if (design.rows.length !== 7 || design.rows.some((r, y) => r.length !== 8 || [...r].some((c, x) =>
        (c === '.') !== (MASK[y][x] === '.') || (c !== '.' && !/^#[\da-f]{6}$/i.test(design.pal[c] ?? ''))))) throw new Error('Invalid inborn anatomy');
      design.rows.forEach((row, y) => [...row].forEach((key, x) => { if (key !== '.') grid[y][x] = design.pal[key]; }));
    }
    if (!appearance.design && appearance.preset && designs[appearance.preset]) paint(designs[appearance.preset]);
    for (const slot of atlas.layer_order) for (const name of appearance.layers) {
      if (layers[name]?.slot === slot) paint(layers[name]);
    }
  }
  const pal: Record<string, string> = {}, colors = new Map<string, string>();
  const rows = grid.map(row => row.map(color => {
    if (!color) return '.';
    if (!colors.has(color)) { const code = String.fromCharCode(65 + colors.size); colors.set(color, code); pal[code] = color; }
    return colors.get(color)!;
  }).join(''));
  if (rows.some((row, y) => [...row].some((c, x) => (c === '.') !== (MASK[y][x] === '.')))) throw new Error('Appearance violates shared 8x7 anatomy');
  const result = { name: appearance.design?.name || appearance.preset || 'newborn', rows, pal }; cache.set(key, result); return result;
}
