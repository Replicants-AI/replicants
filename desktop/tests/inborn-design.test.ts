import assert from 'node:assert/strict';
import { test } from 'node:test';
import design from '../../assets/inborn/sea-glass.json' with { type: 'json' };
import atlas from '../src/sprites.json' with { type: 'json' };
import { anatomy } from '../src/appearance.ts';
import { ANIMS, compose, REPS, MASK, FW, FH } from '../src/motion.js';

test('the original inborn design fills the mask and differs from all 38 source designs', () => {
  const rep = anatomy({ layers: [], design });
  assert.deepEqual(rep.rows.map(r => [...r].map(c => c === '.' ? '.' : '#').join('')), MASK);
  const colors = (r: {rows: string[]; pal: Record<string,string>}) => r.rows.map(row => [...row].map(c => c === '.' ? null : r.pal[c]));
  const originals = [...REPS.map(colors), ...Object.values(atlas.presets).map(p => p.pixels.map(row => row.map(i => i ? p.palette[i] : null)))];
  assert.equal(originals.length, 38);
  for (const other of originals) assert.notDeepEqual(colors(rep), other);
  for (const anim of ANIMS) for (const [,pose] of anim.frames) for (const flip of [false, true]) {
    for (const [x,y,color] of compose(rep, {...pose,flip})) {
      const margin = anim.id === 'roll' ? 2 : 0;
      assert.ok(x >= -margin && x < FW + margin && y >= 0 && y < FH);
      assert.match(color, /^#[\da-f]{6}$/i);
    }
  }
  assert.throws(() => anatomy({layers:[], design:{...design,rows:['........',...design.rows.slice(1)]}}));
});
