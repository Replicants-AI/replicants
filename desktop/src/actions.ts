import { A, SEQ, poseAt, type Pose } from './motion.js';
import type { Physics } from './physics.ts';
import type { Act, Desktop } from './types.ts';

export interface ActResult { act_id: string; status: 'completed' | 'failed' | 'interrupted'; detail: string; evidence?: Record<string, number | string> }
interface Active { act: Act; started: number; duration: number; animation: string; step: number; steppedAt: number; target?: number; windowId?: string; flip: boolean; evidence?: Record<string, number | string> }

/** Acknowledgement describes a finished body action, never merely its receipt. */
export class Actions {
  current: Active | null = null;
  private result: (result: ActResult, act: Act) => void;
  private say: (text: string, duration: number) => void;
  constructor(result: (result: ActResult, act: Act) => void, say: (text: string, duration: number) => void) { this.result = result; this.say = say; }
  finish(status: ActResult['status'], detail: string) {
    if (!this.current) return;
    const act = this.current.act, evidence = this.current.evidence; this.current = null; this.result({ act_id: act.id, status, detail, evidence }, act);
  }
  start(act: Act, now: number, body: Physics, world: Desktop, cursor: { x: number; y: number }, sleepVariant = 'nod') {
    this.finish('interrupted', 'another_body_action');
    let animation = ({ sit: 'sit', sleep: 'lieDown', wake_up: 'getUp', look_at: 'look', wave: 'wave', inspect_window: 'think', say: 'breathe', emote: 'confused', walk_to: 'walk', approach_cursor: 'walk' } as Record<string,string>)[act.name];
    const next: Active = { act, started: now, duration: 1500, animation, step: 0, steppedAt: now, flip: cursor.x < body.center };
    this.current = next;
    if (!animation) { this.finish('failed', 'unknown_body_action'); return; }
    if (body.dragging || !body.floor) { this.finish('interrupted', body.dragging ? 'picked_up' : 'airborne'); return; }
    if (act.name === 'sleep' && sleepVariant === 'stand') animation = 'sleep_stand';
    if (act.name === 'look_at' && act.args.target === 'point' && Number.isFinite(Number(act.args.x))) next.flip = Number(act.args.x) < body.center;
    if (act.name === 'emote') {
      const glyph = String(act.args.glyph || '?');
      animation = ({ '?': 'confused', '!': 'surprise', z: 'yawn', sparkle: 'cheer', droplet: 'shiver' } as Record<string,string>)[glyph] || (A[glyph] ? glyph : 'confused');
    }
    if (act.name === 'walk_to' || act.name === 'approach_cursor') {
      const target = String(act.args.target || 'cursor');
      if (target === 'window') {
        const window = act.args.window_id ? world.windows.find(w=>w.id===act.args.window_id) : world.windows[0];
        if (!window) { this.finish('failed', 'window_missing'); return; }
        if (window.y < body.bottom - 8 && body.floor !== window.id) { this.finish('failed', 'window_edge_above_reach'); return; }
        next.target = window.x + window.width / 2; next.windowId = window.id;
      } else if (target === 'corner') next.target = act.args.side === 'right' ? world.work.x + world.work.width - body.width : world.work.x + body.width;
      else if (target === 'point') {
        const x = Number(act.args.x); if (!Number.isFinite(x)) { this.finish('failed', 'invalid_point'); return; } next.target = x;
        if (act.args.y !== undefined && (!Number.isFinite(Number(act.args.y)) || Math.abs(Number(act.args.y) - body.bottom) > body.scale * 2)) { this.finish('failed', 'point_not_on_current_edge'); return; }
      } else next.target = cursor.x;
      next.target = Math.max(world.work.x + body.width / 2, Math.min(world.work.x + world.work.width - body.width / 2, next.target));
      next.duration = Math.min(18_000, Math.max(2000, Math.abs(body.center - next.target) / body.scale * 120 + 1200));
    } else if (act.name === 'inspect_window') {
      const window = act.args.window_id ? world.windows.find(w=>w.id===act.args.window_id) : world.windows[0];
      if (!window) { this.finish('failed', 'window_missing'); return; }
      next.windowId = window.id; next.flip = window.x + window.width / 2 < body.center;
    } else if (act.name === 'say') {
      const text = String(act.args.text || '').trim().slice(0,240);
      if (!text) { this.finish('failed', 'empty_speech'); return; }
      next.duration = Math.min(10_000, Math.max(1800, text.length * 65)); this.say(text, next.duration);
    }
    next.animation = animation;
    if (next.target === undefined && act.name !== 'say') next.duration = (SEQ[animation] || A[animation]).loop;
  }
  tick(now: number, body: Physics, world: Desktop): Pose | null {
    const current = this.current; if (!current) return null;
    if (body.dragging) { this.finish('interrupted', 'picked_up'); return null; }
    // An action never absorbs release velocity or poses through a fall.
    if (!body.floor) { this.finish('interrupted', 'floor_lost'); return null; }
    body.vx = 0;
    if (current.windowId && !world.windows.some(w=>w.id===current.windowId)) { this.finish('failed', 'window_closed'); return null; }
    current.evidence = { body_x: body.center, body_y: body.bottom, floor: body.floor || '' };
    if (current.windowId) {
      const observed = world.windows.find(w => w.id === current.windowId)!;
      Object.assign(current.evidence, { window_id: observed.id, x: observed.x, y: observed.y, width: observed.width, height: observed.height });
    }
    if (current.target !== undefined) {
      if (body.floor) {
        while (now - current.steppedAt >= 120) {
          current.steppedAt += 120;
          const d = current.target - body.center;
          if (Math.abs(d) <= body.scale) { this.finish(current.windowId && body.floor !== current.windowId ? 'failed' : 'completed', current.windowId && body.floor !== current.windowId ? 'target_edge_not_reached' : 'reached_observed_position'); return null; }
          current.flip = d < 0; body.x += Math.sign(d) * body.scale; current.step++;
        }
      }
      if (now - current.started >= current.duration) { this.finish('failed', 'target_not_reached'); return null; }
    } else if (now - current.started >= current.duration) {
      this.finish('completed', current.windowId ? `observed_window_geometry:${current.windowId}` : 'sequence_finished'); return null;
    }
    const pose = current.target !== undefined ? A.walk.frames[current.step % A.walk.frames.length][1] : poseAt(SEQ[current.animation] || A[current.animation],now-current.started);
    return { ...pose, flip: !!pose.flip !== current.flip };
  }
}
