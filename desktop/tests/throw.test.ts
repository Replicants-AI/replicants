import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ThrowHistory } from '../src/throw.ts';
import { Physics } from '../src/physics.ts';
import { Spine } from '../src/spine.ts';
import { newbornState, type Desktop } from '../src/types.ts';
const world:Desktop={monitor:{x:0,y:0,width:1200,height:900},work:{x:0,y:0,width:1200,height:860},windows:[],idle_seconds:0};
test('quick upward release carries mouse velocity; holding still before release drops',()=>{
  const h=new ThrowHistory();h.sample(200,400,1000);h.sample(240,380,1020);h.sample(280,340,1040);h.sample(320,300,1060);
  const throwVelocity=h.release(1065,6);assert.ok(throwVelocity.vx>1000);assert.ok(throwVelocity.vy< -1000);
  assert.deepEqual(h.release(1200,6),{vx:0,vy:0});
});
test('thrown momentum survives spine ticks, arcs upward, and settles on the work floor',()=>{
  const b=new Physics(()=>1),s=new Spine(()=>.5),state=newbornState();b.x=300;b.y=300;b.pickUp();b.release(1000,{vx:650,vy:-600});
  s.tick(1000,b,state,world,{x:0,y:0});assert.equal(b.vx,650);
  const x=b.x,y=b.y;b.tick(.04,1040,world);assert.ok(b.x>x);assert.ok(b.y<y);
  for(let t=1080;t<4000;t+=40){s.tick(t,b,state,world,{x:0,y:0});b.tick(.04,t,world);if(b.floor)break;}
  assert.equal(b.floor,'work-area');assert.equal(b.vx,0);assert.equal(b.vy,0);
});
test('throws bounce at the desktop edge; hard wall hits can hold then slide',()=>{
  const b=new Physics(()=>1);b.x=1;b.y=300;b.release(0,{vx:-1000,vy:0});b.tick(.02,20,world);assert.equal(b.x,0);assert.equal(b.vx,350);
  const c=new Physics(()=>0);c.x=1;c.y=300;c.release(0,{vx:-1200,vy:0});c.tick(.02,20,world);assert.ok(c.wallSliding);
  const y=c.y;c.tick(.02,200,world);assert.equal(c.y,y);c.tick(.02,500,world);assert.ok(c.y>y);
  const s=new Spine();s.tick(500,c,newbornState(),world,{x:0,y:0});assert.equal(s.animation,'wallslide');
});
