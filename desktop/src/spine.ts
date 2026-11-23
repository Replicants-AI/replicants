import { A, SEQ, OX, OY, createLifeMotion, poseAt, type LifeBody, type Pose } from './motion.js';
import { floors, type Physics } from './physics.ts';
import type { Behavior, BodyState, Desktop } from './types.ts';

/** Native placement around the motion page's unmodified poses and sequences. */
export class Spine {
  behavior: Behavior = 'idle'; awakeUntil = 0; target = 0;
  readonly life: LifeBody = { i: 0, x: 0, y: 0, flip: false, state: 'idle', t: 0, dur: 1800,
    sleepKind: 'nod', mood: .6, social: .45, next: 1200, blink: 0,
    walkTo: 0, step: 0, stepT: 0, vx: 0, vy: 0, peak: 0, tumbled: false, on: null };
  private engine: ReturnType<typeof createLifeMotion>;
  private random: () => number; private last = 0; private bedtime = false;
  private preview = ''; private previewAt = 0;
  constructor(random = Math.random) { this.random = random; this.engine = createLifeMotion(random); this.engine.register(this.life); }
  get animation() { return this.preview || (this.life.state === 'sleep' ? `sleep_${this.life.sleepKind}` : this.life.state); }
  get look() { return this.life.flip ? -1 : 1; }
  beginSleep() { this.engine.start(this.life, 'lieDown'); return this.life.sleepKind; }
  finishRest(name: string, now: number) {
    if (name === 'sleep') { this.bedtime = true; this.awakeUntil = 0; this.engine.start(this.life, 'sleep'); }
    else { this.bedtime = false; this.awakeUntil = now + 45_000; this.engine.start(this.life, 'stretch'); }
  }
  invalidate() { if (!['held', 'fall'].includes(this.life.state)) { this.engine.start(this.life, 'idle'); this.life.dur = 0; } }
  poke(now: number, state?: BodyState) {
    // The brain decides whether this stimulus is enough to wake the body.
    if (state?.vigilance === 'asleep') return;
    this.awakeUntil = now + 45_000; this.bedtime = false;
    const L = this.life;
    if (L.state === 'sleep' || L.state === 'lieDown') this.engine.start(L, 'getUp');
    else if (!['held', 'fall', 'boot', 'wallhit', 'wallslide'].includes(L.state)) {
      const reactions = ['wave', 'love', 'laugh', 'salute', 'bow', 'blush', 'giggle', 'thumbs', 'clap'];
      this.engine.start(L, reactions[Math.floor(this.random() * reactions.length)]);
    }
  }
  pose(): Pose { return this.preview ? { ...poseAt(A[this.preview], this.life.t - this.previewAt) } : this.engine.pose(this.life); }
  private choose(state: BodyState, near: boolean): string {
    const { curiosity, comfort, social, tension } = state.bars;
    // Deliberation is an observed in-flight chat, not an inferred energy level.
    if (state.substrate?.inference.in_flight.some(call => call.kind === 'chat')) return 'think';
    if (state.vigilance === 'drowsy') return this.random() < .3 ? 'yawn' : 'sit';
    const weights: [string, number][] = [
      ['idle', 2], ['look', .4 + curiosity], ['walk', .2 + curiosity * 2.2],
      ['sit', .3 + comfort], ['wave', social * (near ? 3 : .2)],
      ['tapfoot', tension * 1.5], ['shiver', tension * .5],
      ['hum', this.life.mood * .6], ['scratch', .3], ['sway', this.life.mood * .4],
    ];
    let value = this.random() * weights.reduce((sum, [, weight]) => sum + weight, 0);
    for (const [name, weight] of weights) { value -= weight; if (value <= 0) return name; }
    return 'idle';
  }
  tick(now: number, body: Physics, state: BodyState, world: Desktop, cursor: { x: number; y: number }, preview = '', controlled = false) {
    const L = this.life, s = body.scale, dt = this.last ? Math.min(250, now - this.last) : 0; this.last = now;
    L.t += dt; L.x = body.x / s - OX; L.y = body.y / s - OY;
    L.social = state.bars.social;
    L.mood = Math.max(.05, Math.min(1, .5 + state.bars.comfort * .5 - state.bars.tension * .7));
    const edge = floors(world).find(f => f.id === body.floor && body.center >= f.x && body.center <= f.x + f.width);
    L.on = edge && edge.id !== 'work-area' ? { x0: edge.x / s, x1: (edge.x + edge.width) / s } : null;
    this.engine.configure((world.work.x + world.work.width) / s, { x: cursor.x / s, y: cursor.y / s, inside: world.idle_seconds < 45 });
    if (preview !== this.preview) { this.preview = A[preview] ? preview : ''; this.previewAt = L.t; }
    // Airborne momentum belongs to physics, not the tonic behavior selector.
    if (body.floor) body.vx = 0;
    if (this.preview) { this.behavior = 'idle'; return; }
    // These blink timings and exclusions are those of the supplied desktop demo.
    L.blink = Math.max(0, L.blink - dt); L.next -= dt;
    if (L.next <= 0) { L.blink = 120; L.next = this.random() < .2 ? 260 : 2000 + this.random() * 4000; }
    if (body.dragging) { if (L.state !== 'held') this.engine.start(L, 'held'); return; }
    if (body.wallSliding) {
      const next = now - body.wallHitAt < 420 ? 'wallhit' : 'wallslide';
      if (L.state !== next) this.engine.start(L, next);
      L.flip = body.wallSide === 'left'; return;
    }
    if (!body.floor) {
      if (L.state !== 'fall') this.engine.start(L, 'fall');
      if (L.y < L.peak) L.peak = L.y;
      if (L.y - L.peak >= 22) L.tumbled = true;
      return;
    }
    if (controlled) return;
    if (L.state === 'fall' || L.state === 'held') this.engine.impact(L);
    else if (L.state === 'wallhit' || L.state === 'wallslide') this.engine.start(L, 'daze');
    const sleepy = state.vigilance !== undefined ? state.vigilance === 'asleep' : state.asleep && now >= this.awakeUntil;
    if (sleepy && !this.bedtime) {
      this.bedtime = true;
      this.target = body.center < world.work.x + world.work.width / 2 ? world.work.x + body.width : world.work.x + world.work.width - body.width;
      this.engine.start(L, 'yawn');
    } else if (!sleepy && this.bedtime) {
      this.bedtime = false;
      if (['sleep', 'lieDown'].includes(L.state)) this.engine.start(L, 'getUp');
    }
    const settle = () => {
      if (this.bedtime) {
        if (Math.abs(body.center - this.target) <= s * 2) this.engine.start(L, 'lieDown');
        else { this.engine.start(L, 'walk'); L.walkTo = (this.target - body.width / 2) / s - OX; L.flip = L.walkTo < L.x; }
      } else this.engine.start(L, 'idle');
    };
    switch (L.state) {
      case 'idle': {
        if (L.social > .35 && Math.abs(cursor.x - body.center) < 60 * s) L.flip = cursor.x < body.center;
        if (L.t > L.dur) {
          if (this.bedtime) settle();
          else {
            let pick = this.choose(state, world.idle_seconds < 45 && Math.hypot(cursor.x - body.center, cursor.y - body.bottom) < 60 * s);
            // Soma chooses bouts; poses/timing/transitions remain authored.
            if (state.vigilance !== 'drowsy' && state.bars.tension > .7 && this.random() < .55) pick = this.random() < .5 ? 'tapfoot' : 'shiver';
            else if (state.vigilance !== 'drowsy' && state.bars.comfort > .8 && this.random() < .55) pick = 'sit';
            else if (state.vigilance !== 'drowsy' && state.bars.curiosity > .75 && this.random() < .5) pick = this.random() < .65 ? 'walk' : 'look';
            this.engine.start(L, pick);
            if (pick === 'walk' && state.bars.social > .7 && world.idle_seconds < 45) { L.walkTo = Math.max(0, Math.min(world.work.width / s - 12, cursor.x / s - 6)); L.flip = L.walkTo < L.x; }
          }
        }
        break;
      }
      case 'walk': case 'run': {
        const run = L.state === 'run', ms = run ? 90 : 120, px = run ? 2 : 1;
        L.stepT += dt;
        while (L.stepT >= ms && ['walk', 'run'].includes(L.state)) {
          L.stepT -= ms;
          if (Math.abs(L.walkTo - L.x) < .001) { if (this.bedtime) settle(); else this.engine.start(L, run && this.random() < .4 ? 'cheer' : 'idle'); break; }
          const d = L.walkTo - L.x; L.x += Math.sign(d) * Math.min(px, Math.abs(d)); L.step++;
          body.x = (L.x + OX) * s;
        }
        break;
      }
      case 'sleep':
        // The host supplies actual sleep state; authored poses supply its expression.
        if (!sleepy && L.t >= 5000) this.engine.start(L, 'getUp');
        break;
      case 'land': if (L.t > 170) this.engine.start(L, 'surprise'); break;
      default: {
        const animation = SEQ[L.state] || A[L.state];
        if (animation && L.t >= animation.loop) {
          if (L.state === 'roll') body.x += (L.flip ? -3 : 3) * s;
          const next = this.engine.AFTER[L.state] || 'idle';
          if (next === 'idle' && this.bedtime) settle(); else this.engine.start(L, next);
        }
      }
    }
    this.behavior = L.state === 'sleep' ? 'sleep' : L.state === 'lieDown' ? 'doze' : L.state === 'yawn' ? 'yawn'
      : ['walk','run'].includes(L.state) ? this.bedtime ? 'doze' : state.bars.social > .7 ? 'approach_cursor' : 'wander'
      : L.state === 'sit' ? 'sit' : ['shiver','tapfoot','angry'].includes(L.state) ? 'fidget' : L.state === 'look' ? 'look_cursor' : L.state === 'think' ? 'inspect_window' : 'idle';
  }
}
