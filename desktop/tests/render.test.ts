import assert from 'node:assert/strict';
import test from 'node:test';
import { Physics } from '../src/physics.ts';
import { Renderer } from '../src/render.ts';

const context = () => ({ save() {}, restore() {}, fillRect() {}, strokeRect() {} }) as unknown as CanvasRenderingContext2D;

test('speech stays below a character perched near the top of the desktop', () => {
  const body = new Physics(); body.x = 200; body.y = 8;
  const bubble = new Renderer().bubble(context(), 'hello from this edge', body, 1024);
  assert.ok(bubble.y >= body.bottom + 8);
  assert.ok(bubble.x >= 0 && bubble.x + bubble.width <= 1024);
});

test('speech stays above a character when there is room', () => {
  const body = new Physics(); body.x = 200; body.y = 600;
  const bubble = new Renderer().bubble(context(), 'a little quieter here', body, 1024);
  assert.ok(bubble.y >= 0 && bubble.y + bubble.height < body.y);
});
