/** Mouse-release velocity using the motion page's 60ms history and throw caps. */
export class ThrowHistory {
  private points: { x: number; y: number; t: number }[] = [];
  sample(x: number, y: number, t: number) {
    this.points.push({ x, y, t }); if (this.points.length > 8) this.points.shift();
  }
  release(now: number, scale: number) {
    const last = this.points.at(-1);
    if (!last || now - last.t > 120 || this.points.length < 2) return { vx: 0, vy: 0 };
    let start = this.points[0];
    for (const p of this.points) if (now - p.t >= 60) start = p;
    const span = Math.max(16, last.t - start.t);
    return {
      vx: Math.max(-350 * scale, Math.min(350 * scale, (last.x - start.x) / span * 1000)),
      vy: Math.max(-350 * scale, Math.min(200 * scale, (last.y - start.y) / span * 1000)),
    };
  }
}
