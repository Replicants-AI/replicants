import type { Appearance, Rect } from './types.ts';
import type { Physics } from './physics.ts';
import { pixelText, wrap } from './font.ts';
import { compose, FW, FH, OX, OY, type Pose } from './motion.js';
import { anatomy } from './appearance.ts';

export class Renderer {
  draw(ctx: CanvasRenderingContext2D, body: Physics, pose: Pose, appearance: Appearance, now: number, glyph = '', gestating = false): Rect {
    const s = body.scale;
    const originX = Math.round(body.x) - OX * s, originY = Math.round(body.y) - OY * s;
    ctx.save();
    if (gestating) ctx.globalAlpha = .35 + .45 * Math.abs(Math.sin(now / 210));
    const pixels = compose(anatomy(appearance, gestating), pose);
    for (const [x, y, color] of pixels) {
      ctx.fillStyle = color; ctx.fillRect(originX + x * s, originY + y * s, s, s);
    }
    if (glyph) {
      ctx.fillStyle = '#f3dbaa';
      if (glyph === 'sparkle') { ctx.fillRect(originX + 22, originY - 12, 2, 12); ctx.fillRect(originX + 17, originY - 7, 12, 2); }
      else if (glyph === 'droplet') { ctx.fillStyle = '#9dcded'; ctx.fillRect(originX + 24, originY - 10, 2, 3); ctx.fillRect(originX + 22, originY - 7, 6, 5); }
      else pixelText(ctx, glyph.slice(0, 1), originX + 22, originY - 12, 2);
    }
    ctx.restore();
    // Roll-out deliberately travels past its nominal frame. Damage/hit bounds
    // follow actual pixels so moving extremities never leave trails or clip.
    const left = Math.min(0, ...pixels.map(p => p[0])), right = Math.max(FW, ...pixels.map(p => p[0] + 1));
    return { x: originX + left * s, y: originY - (glyph ? 14 : 0), width: (right - left) * s, height: FH * s + (glyph ? 14 : 0) };
  }
  bubble(ctx: CanvasRenderingContext2D, text: string, body: Physics, width: number, thought = false): Rect {
    const lines = wrap(text), size = 2;
    const w = Math.max(50, Math.max(...lines.map(x => x.length)) * 4 * size + 16), h = lines.length * 14 + 12;
    const x = Math.round(Math.max(4, Math.min(width - w - 4, body.center - w / 2)));
    const above = body.y - h - 24;
    // On high window edges, placing speech at the top margin covers the face.
    // Use the space below the body when there is no room above it.
    const y = Math.round(above >= 4 ? above : body.bottom + 16);
    ctx.save(); ctx.globalAlpha = thought ? .63 : .96;
    ctx.fillStyle = '#171b26'; ctx.fillRect(x, y, w, h); ctx.strokeStyle = thought ? '#687184' : '#c1cada'; ctx.lineWidth = 2; ctx.strokeRect(x + 1, y + 1, w - 2, h - 2);
    ctx.fillStyle = '#e5e9f0'; lines.forEach((line, i) => pixelText(ctx, line, x + 8, y + 8 + i * 14, size));
    ctx.restore(); return { x, y, width: w, height: h };
  }
}
