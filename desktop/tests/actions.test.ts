import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Actions, type ActResult } from '../src/actions.ts';
import { Physics } from '../src/physics.ts';
import { A, SEQ } from '../src/motion.js';
import { Spine } from '../src/spine.ts';
import { newbornState } from '../src/types.ts';
import type { Desktop } from '../src/types.ts';
const world=():Desktop=>({monitor:{x:0,y:0,width:1000,height:800},work:{x:0,y:0,width:1000,height:760},windows:[],idle_seconds:0});
test('body receipt is not completion; wave only acknowledges after its authored sequence',()=>{
  const results:ActResult[]=[];const w=world(),b=new Physics();b.place(w);const actions=new Actions(r=>results.push(r),()=>{});
  actions.start({id:'wave1',name:'wave',args:{}},0,b,w,{x:500,y:500});assert.equal(results.length,0);
  assert.ok(actions.tick(A.wave.loop-1,b,w));assert.equal(results.length,0);
  actions.tick(A.wave.loop,b,w);assert.equal(results[0].status,'completed');assert.equal(results[0].act_id,'wave1');
});
test('dragging interrupts an act and a closed target fails honestly',()=>{
  const results:ActResult[]=[];const w=world(),b=new Physics();b.place(w);const actions=new Actions(r=>results.push(r),()=>{});
  actions.start({id:'wave1',name:'wave',args:{}},0,b,w,{x:500,y:500});b.pickUp();actions.tick(10,b,w);assert.equal(results[0].status,'interrupted');
  b.place(w);b.dragging=false;w.windows=[{id:'win',x:100,y:100,width:200,height:300}];
  actions.start({id:'inspect',name:'inspect_window',args:{window_id:'win'}},20,b,w,{x:0,y:0});w.windows=[];actions.tick(30,b,w);assert.equal(results[1].detail,'window_closed');
});
test('walking acknowledgement requires reaching target, not just elapsed animation',()=>{
  const results:ActResult[]=[];const w=world(),b=new Physics();b.place(w);const actions=new Actions(r=>results.push(r),()=>{});
  actions.start({id:'walk',name:'walk_to',args:{target:'point',x:b.center+30}},0,b,w,{x:0,y:0});
  actions.tick(119,b,w);assert.equal(results.length,0);
  for(let t=120;t<=720;t+=120)actions.tick(t,b,w);
  assert.equal(results[0].status,'completed');
});
test('floor loss interrupts deliberate motion without absorbing a throw',()=>{
  const results:ActResult[]=[];const w=world(),b=new Physics();b.place(w);const actions=new Actions(r=>results.push(r),()=>{});
  actions.start({id:'wave',name:'wave',args:{}},0,b,w,{x:500,y:500});
  b.pickUp();b.release(20,{vx:1400,vy:-800});actions.tick(21,b,w);
  assert.equal(results[0].status,'interrupted');assert.equal(b.vx,1400);assert.equal(b.vy,-800);
});
test('deliberate sleep hands its authored transition to the spine without starting a second yawn',()=>{
  const w=world(),b=new Physics(),s=new Spine(()=>0),state=newbornState();b.place(w);
  const actions=new Actions((result,act)=>{assert.equal(result.status,'completed');state.asleep=true;s.finishRest(act.name,SEQ.lieDown.loop);},()=>{});
  const kind=s.beginSleep();actions.start({id:'sleep',name:'sleep',args:{}},0,b,w,{x:0,y:0},kind);
  assert.deepEqual(actions.tick(0,b,w),{...SEQ.lieDown.frames[0][1],flip:true});
  actions.tick(SEQ.lieDown.loop,b,w);s.tick(SEQ.lieDown.loop,b,state,w,{x:0,y:0});
  assert.equal(s.animation,'sleep_nod');
});
test('inspection returns actual geometry and never silently substitutes a missing window',()=>{
  const w=world(),b=new Physics(),results:ActResult[]=[];b.place(w);w.windows=[{id:'one',x:10,y:300,width:400,height:250}];
  const actions=new Actions(r=>results.push(r),()=>{});
  actions.start({id:'missing',name:'inspect_window',args:{window_id:'gone'}},0,b,w,{x:0,y:0});
  assert.equal(results[0].detail,'window_missing');
  actions.start({id:'exists',name:'inspect_window',args:{window_id:'one'}},0,b,w,{x:0,y:0});
  actions.tick(A.think.loop,b,w);
  assert.equal(results[1].status,'completed');assert.equal(results[1].evidence?.width,400);assert.equal(results[1].evidence?.window_id,'one');
});
