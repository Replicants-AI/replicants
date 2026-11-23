import assert from 'node:assert/strict';
import { test } from 'node:test';
import atlas from '../src/sprites.json' with { type: 'json' };
import { A, ANIMS, REPS, compose, MASK, FW, FH } from '../src/motion.js';
import { anatomy } from '../src/appearance.ts';

test('all 85 animations fit known bounds; only roll-out travels outside the nominal frame', () => {
  assert.equal(ANIMS.length, 85); assert.equal(REPS.length, 18);
  for (const rep of REPS) for (const anim of ANIMS) for (const [, pose] of anim.frames) for (const flip of [false, true]) {
    for (const [x, y, color] of compose(rep, { ...pose, flip })) {
      const margin = anim.id === 'roll' ? 2 : 0;
      assert.ok(Number.isInteger(x) && Number.isInteger(y) && x >= -margin && x < FW + margin && y >= 0 && y < FH, `${rep.name}/${anim.id}: ${x},${y}`);
      assert.match(color, /^#[\da-f]{6}$/i);
    }
  }
});
test('all SVG presets and appearance layers share anatomy and animate through every pose', () => {
  for (const preset of ['', ...Object.keys(atlas.presets)]) for (const layers of [[], ['glasses'], ['beanie'], ['glasses', 'beanie']]) {
    const rep = anatomy({ preset, layers });
    assert.deepEqual(rep.rows.map(row => [...row].map(c => c === '.' ? '.' : '#').join('')), MASK);
    for (const anim of ANIMS) for (const [, pose] of anim.frames) for (const [x,y,color] of compose(rep,pose)) {
      const margin = anim.id === 'roll' ? 2 : 0;
      assert.ok(x >= -margin && x < FW + margin && y >= 0 && y < FH && color, `${preset}/${anim.id}`);
    }
  }
});
test('blink uses the lid and glances preserve bare-face rule without character exceptions', () => {
  const rep = anatomy({ layers: [] });
  const closed = compose(rep, { eyes: 'closed' });
  const at = (x:number,y:number) => closed.find(p=>p[0]===x+2 && p[1]===y+3)?.[2];
  assert.equal(at(3,2),at(4,2)); assert.equal(at(5,2),at(4,2));
  for(const r of REPS) {
    const idle=compose(r,{}), glance=compose(r,{gx:-1});
    assert.deepEqual(glance.filter(p=>p[1]<5),idle.filter(p=>p[1]<5));
  }
  const sleeps = ANIMS.filter(a=>a.cat==='Sleep'); assert.equal(sleeps.length,5);
  assert.ok(sleeps.every(a=>a.frames.every(([,p])=>p.lie!=='back')));
  assert.ok(A.replicate); // Visual effect, never identity replication.
});
