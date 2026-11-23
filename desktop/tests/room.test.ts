import assert from 'node:assert/strict';
import { test } from 'node:test';
import { RoomView } from '../src/room.ts';
import { Physics, floors } from '../src/physics.ts';
import type { Desktop } from '../src/types.ts';

test('Room geometry supports the shipping body, respects stacking and disappears on close', () => {
  const original = globalThis.document;
  const node = () => ({style:{},append(){},setAttribute(){},hidden:false});
  globalThis.document = {createElement:node,body:node()} as unknown as Document;
  try {
    const room = new RoomView();
    const host: Desktop = {monitor:{x:0,y:0,width:1280,height:800},work:{x:0,y:0,width:1280,height:760},idle_seconds:0,windows:[]};
    const packet = {open:true,window:{x:620,y:160,width:640,height:460},front:true};
    room.update(packet);
    const world = room.world(host), body = new Physics();
    body.geometry(world,0); body.pickUp();body.x=800;body.y=0;body.release(0);
    for(let i=0;i<200;i++)body.tick(.03,i*30,world);
    assert.equal(body.floor,'replicants-room');assert.equal(body.bottom,160);
    const covering = {...host,windows:[{id:'cover',x:700,y:100,width:200,height:400}]};
    room.update({...packet,front:false});
    assert.deepEqual(floors(room.world(covering)).filter(f=>f.id==='replicants-room').map(f=>[f.x,f.width]),[[620,80],[900,360]]);
    room.update({open:false});const closed=room.world(host);body.geometry(closed,6000);
    for(let i=0;i<200;i++)body.tick(.03,6000+i*30,closed);
    assert.equal(body.floor,'work-area');assert.equal(body.bottom,760);
    assert.equal(closed.windows.length,0);
    const native = new RoomView(true);
    native.update(packet);
    assert.equal(native.world(covering), covering, 'Native geometry and stacking come from DWM unchanged');
  } finally {globalThis.document=original;}
});
