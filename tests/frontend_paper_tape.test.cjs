const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/static/paper-tape.js', 'utf8');

function harness(zoom=.69) {
  const listeners=new Map(), frames=new Map(), timers=new Map(), cancelled=[];
  let id=0, selected='0', selections=[], count=5;
  const strip={scrollLeft:0,scrollWidth:800,clientWidth:200,offsetWidth:200,
    classList:{add(){},remove(){}}, addEventListener:(name,fn)=>listeners.set(name,fn),
    getBoundingClientRect:()=>({left:90,width:200*zoom}),
    scrollTo({left}){this.scrollLeft=left;},contains:()=>true,
    querySelectorAll:()=>Array.from({length:count},(_,i)=>({dataset:{value:String(i)},getBoundingClientRect:()=>({left:90+(100+i*150-strip.scrollLeft-20)*zoom,width:40*zoom})})),
  };
  const window={MutsumiViewport:{elementScale:()=>zoom}};
  const sandbox={window,performance:{now:()=>1000},requestAnimationFrame:fn=>{frames.set(++id,fn);return id;},cancelAnimationFrame:n=>{cancelled.push(n);frames.delete(n);},setTimeout:fn=>{timers.set(++id,fn);return id;},clearTimeout:n=>timers.delete(n)};
  vm.runInNewContext(source,sandbox);
  const config={selector:'button',selected:()=>selected,onSelect:node=>{selected=node.dataset.value;selections.push(selected);}};
  window.PaperTape.bind(strip,config);
  return {tape:window.PaperTape,strip,selections,cancelled,
    render(n,value){count=n;selected=String(value);strip.scrollWidth=200+(n-1)*150;window.PaperTape.rendered(strip,selected);},
    emit:(name,event={})=>listeners.get(name)?.(event),
    drain(){for(let i=0;frames.size&&i<10;i++){const batch=[...frames.values()];frames.clear();batch.forEach(fn=>fn());}},
    unlock(){[...timers.values()].forEach(fn=>fn());timers.clear();},
    selected:()=>selected};
}

test('centering accounts for the tape offset and APK zoom',()=>{
  const h=harness();h.tape.center(h.strip,'3');assert.equal(Math.round(h.strip.scrollLeft),450);
  h.emit('scroll');h.drain();assert.deepEqual(h.selections,[],'programmatic scroll is not user selection');
});

test('parent rebuild invalidates an old child scroll and keeps both child endpoints reachable',()=>{
  const h=harness();h.strip.scrollLeft=600;h.emit('scroll');
  h.render(3,'0');h.render(7,'6');h.drain();assert.equal(Math.round(h.strip.scrollLeft),900);assert.deepEqual(h.selections,[]);
  h.unlock();h.emit('keydown',{key:'Home',preventDefault(){}});assert.equal(h.selected(),'0');assert.equal(Math.round(h.strip.scrollLeft),0);
  h.emit('keydown',{key:'End',preventDefault(){}});assert.equal(h.selected(),'6');assert.equal(Math.round(h.strip.scrollLeft),900);
});

test('manual mouse dragging uses logical distances and recovers after a child rebuild',()=>{
  const h=harness(.6);h.render(7,0);h.drain();h.unlock();
  h.emit('pointerdown',{pointerId:1,pointerType:'mouse',clientX:600});
  h.emit('pointermove',{pointerId:1,clientX:60});h.emit('pointerup',{pointerId:1,type:'pointerup'});
  assert.equal(Math.round(h.strip.scrollLeft),900);assert.equal(h.selected(),'6');
  h.render(3,0);h.drain();h.unlock();
  h.emit('pointerdown',{pointerId:2,pointerType:'mouse',clientX:400});h.emit('pointermove',{pointerId:2,clientX:220});h.emit('pointerup',{pointerId:2,type:'pointerup'});
  assert.equal(h.selected(),'2');assert.equal(Math.round(h.strip.scrollLeft),300);
});

test('touch pointer cancellation leaves native scrolling in control',()=>{
  const h=harness();h.emit('pointerdown',{pointerId:5,pointerType:'touch',clientX:400});
  h.emit('pointermove',{pointerId:5,clientX:100});assert.equal(Math.round(h.strip.scrollLeft),0);
  h.strip.scrollLeft=450;h.emit('pointercancel',{pointerId:5,type:'pointercancel'});h.emit('scroll');h.drain();
  assert.equal(h.selected(),'3');assert.equal(Math.round(h.strip.scrollLeft),450);
});
