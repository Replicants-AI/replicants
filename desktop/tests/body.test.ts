import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { Physics, floors } from '../src/physics.ts';
import { Spine } from '../src/spine.ts';
import { newbornState, type Desktop } from '../src/types.ts';

const world = (): Desktop => ({ monitor: { x: 0, y: 0, width: 1000, height: 800 }, work: { x: 0, y: 0, width: 1000, height: 760 }, idle_seconds: 0, windows: [{ id: 'window', x: 100, y: 300, width: 500, height: 300 }] });
test('native window edges support, slow movements carry, fast movements detach', () => {
  const w = world(), b = new Physics(); b.geometry(w, 0); b.place(w); assert.equal(b.floor, 'window');
  const x = b.x; w.windows[0].x += 10; b.geometry(w, 250); assert.equal(b.x, x + 10); assert.equal(b.floor, 'window');
  w.windows[0].y += 100; b.geometry(w, 500); assert.equal(b.floor, null); assert.ok(b.vy > 0);
});
test('closing a supporting window causes gravity and landing above the taskbar', () => {
  const w = world(), b = new Physics(); b.geometry(w, 0); b.place(w); w.windows = []; b.geometry(w, 250);
  for (let i = 0; i < 300; i++) b.tick(1/30, 250 + i * 1000/30, w);
  assert.equal(b.floor, 'work-area'); assert.equal(b.bottom, 760); assert.equal(b.vy, 0);
});
test('walking beyond a window edge falls; dropping can land on a real edge', () => {
  const w = world(), b = new Physics(); b.geometry(w, 0); b.place(w); b.x = 590; b.vx = 100; b.tick(.05, 100, w); assert.equal(b.floor, null);
  b.pickUp(); b.x = 200; b.y = 100; b.release(200);
  for (let i = 0; i < 100; i++) b.tick(.033, 250+i*33, w);
  assert.equal(b.floor, 'window'); assert.equal(b.bottom, 300);
});
test('covered window-edge segments are excluded', () => {
  const w = world(); w.windows.unshift({ id: 'front', x: 200, y: 200, width: 200, height: 400 });
  assert.deepEqual(floors(w).filter(f => f.id === 'window').map(f => [f.x, f.width]), [[100, 100], [400, 200]]);
});
test('night plays authored yawn, corner walk, lie-down and sleep; poke plays get-up', () => {
  const w = world(), b = new Physics(), s = new Spine(() => .3), state = newbornState(); b.place(w); state.asleep = true;
  s.tick(100_000, b, state, w, {x:500,y:500}); assert.equal(s.behavior, 'yawn');
  const seen = new Set<string>();
  for(let t=100_050;t<130_000;t+=50){s.tick(t,b,state,w,{x:500,y:500});b.tick(.05,t,w);seen.add(s.animation);}
  assert.ok(seen.has('walk'));assert.ok(seen.has('lieDown'));assert.ok(s.animation.startsWith('sleep_'));
  s.poke(130_000);s.tick(130_050,b,state,w,{x:500,y:500});assert.equal(s.animation,'getUp');
});
test('a bout has hysteresis and temperaments produce different behavior distributions', () => {
  const w=world(), b=new Physics(), state=newbornState(); let seed=42;
  const rng=()=>((seed=(seed*1664525+1013904223)>>>0)/2**32);
  b.place(w);const s=new Spine(rng); s.tick(1e5,b,state,w,{x:500,y:500}); const first=s.animation;
  state.bars.tension=.99; s.tick(100_010,b,state,w,{x:500,y:500}); assert.equal(s.animation,first);
  const count=(tension:number,comfort:number)=>{ const totals:Record<string,number>={}; state.bars.tension=tension;state.bars.comfort=comfort;state.bars.curiosity=0; for(let i=0;i<100;i++){s.invalidate();s.tick(2e5+i*1000,b,state,w,{x:500,y:500});totals[s.behavior]=(totals[s.behavior]??0)+1;} return totals; };
  assert.ok((count(.99,.05).fidget??0) > (count(.01,.99).fidget??0));
});

test('brain vigilance overrides the old clock rule and local poke wake hold', () => {
  const w = world(), b = new Physics(), s = new Spine(() => .3), state = newbornState(); b.place(w);
  state.vigilance = 'awake'; state.sim_hour = 23; w.idle_seconds = 3600;
  s.tick(100_000, b, state, w, {x: 500, y: 500});
  assert.notEqual(s.behavior, 'yawn');
  state.vigilance = 'asleep'; state.asleep = true; s.awakeUntil = 200_000;
  s.tick(100_050, b, state, w, {x: 500, y: 500});
  assert.equal(s.behavior, 'yawn');
  s.finishRest('sleep', 100_100); s.poke(100_150, state);
  assert.ok(s.animation.startsWith('sleep_'));
});

test('drowsy body state selects an existing quiet pose without entering sleep', () => {
  const w = world(), b = new Physics(), s = new Spine(() => .1), state = newbornState(); b.place(w);
  state.vigilance = 'drowsy'; state.bars.curiosity = state.bars.tension = state.bars.comfort = .99;
  s.tick(1000, b, state, w, {x: 500, y: 500}); s.invalidate();
  s.tick(2000, b, state, w, {x: 500, y: 500});
  assert.equal(s.animation, 'yawn'); assert.equal(state.asleep, false);
});
test('live thinking follows actual inference', () => {
  const w = world(), b = new Physics(), s = new Spine(() => .8), state = newbornState(); b.place(w);
  state.bars.tension = .1; state.bars.comfort = .5; state.bars.curiosity = .5;
  state.substrate = { inference: { in_flight: [{kind: 'chat', model: 'local', elapsed_seconds: 2}] } };
  s.tick(1000, b, state, w, {x: 500, y: 500}); s.invalidate();
  s.tick(2000, b, state, w, {x: 500, y: 500});
  assert.equal(s.animation, 'think');
  assert.equal('energy' in state, false); assert.equal('energy' in s.life, false);
  state.substrate.inference.in_flight = []; s.invalidate();
  s.tick(3000, b, state, w, {x: 500, y: 500});
  assert.notEqual(s.animation, 'think');
});
test('all twenty SVG designs compile to exact 8x7 palette grids with separate layers', () => {
  const atlas=JSON.parse(readFileSync(new URL('../src/sprites.json',import.meta.url),'utf8'));
  assert.equal(Object.keys(atlas.presets).length,20);
  for(const [name, preset] of Object.entries(atlas.presets) as [string,{pixels:number[][];palette:string[]}][]) {
    assert.equal(preset.pixels.length,7);assert.ok(preset.pixels.every(row=>row.length===8));
    const svg=readFileSync(new URL(`../../assets/replicants/${name}.svg`,import.meta.url),'utf8');
    for(const m of svg.matchAll(/<rect x="(\d+)" y="(\d+)" width="10" height="10" fill="([^"]+)"/g)) assert.equal(preset.palette[preset.pixels[Number(m[2])/10][Number(m[1])/10]],m[3].toUpperCase());
  }
  assert.equal(atlas.layers.glasses.slot,'face'); assert.equal(atlas.layers.beanie.slot,'headwear');
  assert.equal(atlas.eyes.pixels[2][3],1);assert.equal(atlas.eyes.pixels[2][5],1);
});
