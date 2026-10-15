const {test} = require("node:test"), assert = require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../../app/static/server-note-pagination.js"),"utf8");
const flush=()=>new Promise(resolve=>setImmediate(resolve));

function harness({accepts=[true],fail=false,badFragment=false,pending=false}={}) {
  const events={}, handlers={}, calls=[], histories=[], decisions=[];
  let release;
  const feedback={hidden:true,textContent:"",append(node){this.link=node;}}, heading={setAttribute(){},focus(){this.focused=true;}};
  const controls=[{dataset:{}},{dataset:{}}], count={textContent:"250"};
  const replacement={dataset:{projectId:"1",notesPage:"2",notesSize:"20",noteTotal:"250"},childNodes:["next notes"],classList:{contains:()=>false},querySelector:()=>null};
  const section={dataset:{projectId:"1",notesPage:"1",notesSize:"20",noteTotal:"250"},childNodes:["original draft"],replacements:0,
    querySelectorAll:()=>controls, querySelector:s=>s==="h2"?heading:feedback,
    setAttribute(){},removeAttribute(){},classList:{toggle(){}},scrollIntoView(){},
    replaceChildren(...nodes){this.childNodes=nodes;this.replacements++;},addEventListener(name,callback){handlers[name]=callback;}};
  const response={ok:!fail,headers:{get:()=>badFragment?null:"notes"},text:async()=>"safe fragment"};
  const window={location:{href:"http://127.0.0.1/projects/1",origin:"http://127.0.0.1"},
    ProjMemoDrafts:{async requestDiscard(root){assert.equal(root,section); const answer=accepts.shift()??true;decisions.push(answer);return answer;}},
    history:{replaceState(_a,_b,url){histories.push(url);}},setTimeout(){return 1;},clearTimeout(){}};
  const document={getElementById:id=>id==="project-notes"?section:id==="project-content"?{dataset:{view:"list"}}:{textContent:JSON.stringify({failed:"Preserved",fallback:"Open directly"})},
    querySelector:()=>count,createElement:()=>({}),dispatchEvent:event=>calls.push(event.type),addEventListener(name,cb){events[name]=cb;}};
  vm.runInNewContext(source,{document,window,URL,AbortController,Event,DOMParser:class {parseFromString(){return {getElementById:()=>replacement};}},
    fetch:async(url,options)=>{calls.push({url,options});if(pending)await new Promise(resolve=>{release=resolve;});return response;}});
  const click=()=>{const event={button:0,target:{closest:()=>({href:"http://127.0.0.1/projects/1?notes_page=2&notes_size=20#project-notes"})},preventDefault(){this.prevented=true;}};handlers.click(event);return event;};
  return {section,feedback,heading,controls,calls,histories,click,handlers,events,replacement,decisions,release:()=>release()};
}

test("paging only replaces note children, preserves section identity, view and exact total",async()=>{
  const p=harness();const identity=p.section;p.click();await flush();
  assert.equal(p.section,identity);assert.equal(p.section.replacements,1);
  assert.equal(p.section.dataset.noteTotal,"250");assert.equal(p.heading.focused,true);
  assert.match(p.histories[0],/detail_view=list/);assert.match(p.histories[0],/notes_page=2/);
  assert.equal(p.calls[0].options.headers["X-ProjMemo-Fragment"],"notes");
  assert.ok(p.calls.includes("projmemo:notes-loaded"));
  assert.equal(p.controls[0].dataset.pagingEnhanced,"true");
});

test("declined draft discard does not fetch or replace DOM",async()=>{
  const p=harness({accepts:[false]});p.click();await flush();
  assert.equal(p.calls.length,0);assert.equal(p.section.childNodes[0],"original draft");
});

for(const problem of [{fail:true},{badFragment:true}])test("failed/unexpected response retains drafts and offers explicit native fallback "+JSON.stringify(problem),async()=>{
  const p=harness(problem);p.click();await flush();
  assert.equal(p.section.replacements,0);assert.equal(p.section.childNodes[0],"original draft");
  assert.equal(p.feedback.hidden,false);assert.match(p.feedback.link.href,/notes_page=2/);
  assert.equal(p.histories.length,0);
});

test("late edits require fresh confirmation, and concurrent requests are suppressed",async()=>{
  const p=harness({pending:true,accepts:[true,false]});p.click();await flush();
  p.click();p.handlers.input();p.release();await flush();
  assert.equal(p.calls.filter(call=>typeof call==="object").length,1);
  assert.deepEqual(p.decisions,[true,false]);assert.equal(p.section.replacements,0);
});
