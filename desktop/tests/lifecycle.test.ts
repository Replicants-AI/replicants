import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Lifecycle } from '../src/lifecycle.ts';

test('replacement waits for a successful checkpoint receipt', async () => {
  const log: string[] = [];
  const life = new Lifecycle({ connected: () => true, running: async () => true,
    sendQuit: () => { log.push('save'); return true; }, finish: async kind => { log.push(kind); } });
  const task = life.run('birth');
  assert.deepEqual(log, ['save']);
  await assert.rejects(life.run('quit'), /already/);
  life.stopped(true); await task;
  assert.deepEqual(log, ['save', 'birth']); assert.equal(life.busy, false);
});

test('checkpoint failure or disconnection never exits the body', async () => {
  let exited = false;
  const life = new Lifecycle({ connected: () => true, running: async () => true,
    sendQuit: () => true, finish: async () => { exited = true; } });
  const task = life.run('quit');
  life.failed('checkpoint_failed');
  await assert.rejects(task, /checkpoint_failed/); assert.equal(exited, false);
  const disconnected = new Lifecycle({ connected: () => false, running: async () => true,
    sendQuit: () => false, finish: async () => { exited = true; } });
  await assert.rejects(disconnected.run('open', 'life.replicant'), /disconnected/);
  assert.equal(exited, false);
});
