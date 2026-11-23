import assert from 'node:assert/strict';
import { test } from 'node:test';
import { BODY_DESIGNS, BODY_PIXELS, DesignDraft, drawing, pixels } from '../src/body-design.ts';
import { anatomy } from '../src/appearance.ts';
import { ANIMS, compose, FW, FH, MASK } from '../src/motion.js';

test('every authored starting design retains its own pixel colors', () => {
  assert.equal(BODY_DESIGNS.length, 38);
  for (const item of BODY_DESIGNS) {
    assert.deepEqual(pixels(drawing(pixels(item.design))), pixels(item.design));
    assert.deepEqual(pixels(anatomy({ design: item.design, layers: [] })), pixels(item.design));
  }
  const classic = BODY_DESIGNS.find(d => d.id === 'art:01-classic')!;
  assert.ok(new Set(pixels(classic.design).flat().filter(Boolean)).size > 3);
});

test('one stroke paints individual pixels and undo restores the whole stroke', () => {
  const original = BODY_DESIGNS[2].design, draft = new DesignDraft(original);
  const before = pixels(draft.value);
  draft.beginStroke(); draft.paint(1, 0, '#001122'); draft.paint(2, 0, '#334455'); draft.finishStroke();
  const after = pixels(draft.value);
  assert.equal(after[0][1], '#001122'); assert.equal(after[0][2], '#334455');
  for (let y = 0; y < 7; y++) for (let x = 0; x < 8; x++) if (y !== 0 || (x !== 1 && x !== 2)) assert.equal(after[y][x], before[y][x]);
  draft.undo(); assert.deepEqual(pixels(draft.value), before); assert.equal(draft.canUndo, false);
  draft.redo(); assert.deepEqual(pixels(draft.value), after);
  draft.undo(); draft.paint(3, 0, '#778899'); draft.finishStroke(); assert.equal(draft.canRedo, false);
  assert.equal(draft.paint(0, 0, '#FFFFFF'), false); assert.equal(draft.paint(-1, 0, '#FFFFFF'), false);
});

test('each body pixel supports an independent color through storage and every animation', () => {
  let index = 0;
  const grid = MASK.map(row => [...row].map(key => key === '.' ? null : '#' + (++index * 3217).toString(16).padStart(6, '0')));
  const design = drawing(grid);
  assert.equal(Object.keys(design.pal).length, BODY_PIXELS);
  const reopened = anatomy({ design: JSON.parse(JSON.stringify(design)), layers: [] });
  assert.deepEqual(pixels(reopened), pixels(design));
  for (const animation of ANIMS) for (const [, pose] of animation.frames) for (const flip of [false, true]) {
    for (const [x, y, color] of compose(reopened, { ...pose, flip })) {
      const margin = animation.id === 'roll' ? 2 : 0;
      assert.ok(x >= -margin && x < FW + margin && y >= 0 && y < FH); assert.match(color, /^#[\da-f]{6}$/i);
    }
  }
});

test('loading bad artwork preserves the current drawing', () => {
  const draft = new DesignDraft(BODY_DESIGNS[2].design), before = structuredClone(draft.value);
  assert.throws(() => draft.replace({ ...before, rows: ['........', ...before.rows.slice(1)] }));
  assert.throws(() => draft.replace({ ...before, pal: { A: 'url(https://example.com)' } }));
  assert.deepEqual(draft.value, before);
  draft.replace(BODY_DESIGNS[3].design); draft.undo(); assert.deepEqual(draft.value, before);
});
