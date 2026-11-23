import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { ANIMS, REPS, A, SEQ, compose, poseAt } from '../src/motion.js';
import { Renderer } from '../src/render.ts';
import { Physics } from '../src/physics.ts';
import { Spine } from '../src/spine.ts';
import { newbornState, type Desktop } from '../src/types.ts';

const html=readFileSync(new URL('../../assets/motion/Replicant Motion.html',import.meta.url),'utf8');
const sandbox:{window:Record<string,any>}={window:{}};
// Execute the ORIGINAL supplied engine, without the document or demo UI.
const script=html.slice(html.indexOf('<script>')+8,html.indexOf('</script>'));
vm.runInNewContext(script,sandbox);
const original=sandbox.window.REPLICANT_ENGINE;

test('extracted engine preserves original pixels at every keyframe boundary and midpoint',()=>{
  for(let ri=0;ri<REPS.length;ri++)for(const animation of ANIMS){
    const authored=original.ANIMS.find((a:any)=>a.id===animation.id);let t=0;
    for(const [duration] of animation.frames){
      for(const at of [t,t+duration/2,t+duration-1]){
        const expected=original.compose(original.REPS[ri],original.poseAt(authored,at));
        const actual=compose(REPS[ri],poseAt(animation,at));
        assert.equal(JSON.stringify(actual),JSON.stringify(expected),`${animation.id}@${at}`);
      }
      t+=duration;
    }
  }
});
test('renderer draws selected poses verbatim without extra blink, glance, squash, or flip',()=>{
  const b=new Physics();b.x=120;b.y=180;b.floor='ground';b.landedAt=1;b.vx=50;
  const renderer=new Renderer();const pixels:unknown[]=[];
  const recorder={fillStyle:'',save(){},restore(){},fillRect(x:number,y:number,w:number,h:number){pixels.push([x,y,w,h,recorder.fillStyle]);}};
  const ctx=recorder as unknown as CanvasRenderingContext2D;
  for(const id of ['walk','blink','sleep_curl','roll','spin','dance']){
    const pose=poseAt(A[id],A[id].loop*.55);pixels.length=0;
    renderer.draw(ctx,b,pose,{preset:'01-classic',layers:[]},50_000);
    const authored=original.ANIMS.find((a:any)=>a.id===id);
    const expected=original.compose(original.REPS[0],original.poseAt(authored,authored.loop*.55))
      .map(([x,y,color]:[number,number,string])=>[108+x*6,162+y*6,6,6,color]);
    assert.equal(JSON.stringify(pixels),JSON.stringify(expected),id);
    assert.deepEqual(pose,poseAt(A[id],A[id].loop*.55));
  }
});
const world:Desktop={monitor:{x:0,y:0,width:1200,height:900},work:{x:0,y:0,width:1200,height:860},windows:[],idle_seconds:0};
test('native walking advances exactly one six-pixel cell per authored 120ms step',()=>{
  const b=new Physics();b.place(world);const s=new Spine(()=>.5),state=newbornState();s.tick(1000,b,state,world,{x:500,y:500});
  Object.assign(s.life,{state:'walk',t:0,stepT:0,step:0,walkTo:s.life.x+10});const x=b.x;
  s.tick(1119,b,state,world,{x:500,y:500});assert.equal(b.x,x);
  s.tick(1120,b,state,world,{x:500,y:500});assert.equal(b.x,x+6);assert.equal(s.life.step,1);
  assert.deepEqual(s.pose(),{...A.walk.frames[1][1],flip:false});
});
test('sleep and recovery use authored transition durations; preview clock starts at frame zero',()=>{
  const b=new Physics();b.place(world);const s=new Spine(()=>.5),state=newbornState();s.tick(1000,b,state,world,{x:0,y:0});
  Object.assign(s.life,{state:'getUp',t:SEQ.getUp.loop-100});
  s.tick(1050,b,state,world,{x:0,y:0});assert.equal(s.animation,'getUp');
  s.tick(1100,b,state,world,{x:0,y:0});assert.equal(s.animation,'stretch');
  s.tick(1200,b,state,world,{x:0,y:0},'roll');assert.deepEqual(s.pose(),poseAt(A.roll,0));
  s.tick(1320,b,state,world,{x:0,y:0},'roll');assert.deepEqual(s.pose(),poseAt(A.roll,120));
});
