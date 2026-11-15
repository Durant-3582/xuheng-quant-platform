// Reproduce a normal click, copying a link and browser back/forward in a hosted frame.
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
const course=new URL("https://course.example/?course=example");
const frame=new URL("https://course.example/component/desk/index.html");
const hostEvents={},docEvents={},childEvents=[];
const hostHistory=[course.href];let pointer=0;
function apply(u){course.href=u;}
const host={get location(){return course;},history:{
  state:{},pushState(_s,_t,u){hostHistory.splice(++pointer,Infinity,u.href);apply(u);},
  replaceState(_s,_t,u){hostHistory[pointer]=u.href;apply(u);}
},addEventListener(k,v){hostEvents[k]=v;},removeEventListener(){}};
const anchor={attrib:"#stocks/000001.SZ",dataset:{},getAttribute(){return this.attrib;}};
globalThis.window=globalThis;globalThis.top=host;globalThis.location=frame;
globalThis.history={state:{},replaceState(_s,_t,path){frame.href=new URL(path,frame).href;}};
globalThis.document={body:{},querySelectorAll(){return [anchor];},addEventListener(k,v){docEvents[k]=v;}};
globalThis.MutationObserver=class{observe(){}};
globalThis.HashChangeEvent=class{constructor(type){this.type=type;}};
globalThis.dispatchEvent=e=>childEvents.push(e.type);
globalThis.addEventListener=()=>{};
const source=await readFile(new URL("../xuheng/desk/navigation.js",import.meta.url),"utf8");
const {startNavigation,navigate}=await import("data:text/javascript;base64,"+Buffer.from(source).toString("base64"));
startNavigation("overview");
assert.equal(frame.hash,"#overview");
assert.equal(anchor.href,"https://course.example/?course=example&page=stocks&symbol=000001.SZ");
let prevented=false;
docEvents.click({target:{closest:()=>anchor},button:0,preventDefault(){prevented=true;}});
assert.ok(prevented);
assert.equal(frame.hash,"#stocks/000001.SZ");
navigate("portfolio/research");
assert.equal(course.searchParams.get("tab"),"research");
apply(hostHistory[--pointer]);hostEvents.popstate();
assert.equal(frame.hash,"#stocks/000001.SZ");
apply(hostHistory[--pointer]);hostEvents.popstate();
assert.equal(frame.hash,"#overview");
apply(hostHistory[++pointer]);hostEvents.popstate();
assert.equal(frame.hash,"#stocks/000001.SZ");
assert.equal(hostHistory.length,3);
docEvents.click({target:{closest:()=>anchor},button:0,metaKey:true,preventDefault(){throw Error("should open as a public link");}});
assert.equal(childEvents.length,5);
console.log("PASS: one history entry per click, back, forward, deep links, preserved settings and new-tab links.");
