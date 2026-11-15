import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {webcrypto} from "node:crypto";
import vm from "node:vm";

const html = await readFile(new URL("../xuheng/browser_settings/index.html",import.meta.url),"utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const origin = "https://course.invalid";
const storage = new Map();
const clients = new Set();
const locks = new Map();
const tick = () => new Promise(resolve => setTimeout(resolve, 8));

function client(deny=false,sessionStorage=new Map()) {
  const handlers = {};
  const messages = [];
  const emit = (type, event) => handlers[type]?.(event);
  const parent = {postMessage(msg, dest) {
    assert.equal(dest,origin);
    if (msg.type==="streamlit:setComponentValue") messages.push(JSON.parse(JSON.stringify(msg.value)));
  }};
  const makeStorage = (map, local) => ({
    getItem(key) { if (deny) throw Error(); return map.get(key) ?? null; },
    setItem(key,value) {
      if (deny) throw Error();
      const changed = map.get(key)!==value;
      map.set(key,value);
      if (local && changed) for (const listener of clients) {
        if (listener!==emit) setTimeout(() => listener("storage",{key}),0);
      }
    }
  });
  const window = {localStorage:makeStorage(storage,true),sessionStorage:makeStorage(sessionStorage,false)};
  vm.runInNewContext(script,{window,parent,URL,location:{origin},document:{referrer:origin+"/"},
    crypto:webcrypto,addEventListener:(type,fn) => handlers[type]=fn,clearTimeout,setTimeout,
    navigator:{locks:{request(key,fn) {
      const next=(locks.get(key)||Promise.resolve()).then(fn);
      locks.set(key,next);return next;
    }}}});
  clients.add(emit);
  return {messages,render(args) {
    emit("message",{source:parent,origin,data:{type:"streamlit:render",args}});
  },close() {clients.delete(emit);}};
}

const first=client(), second=client();
const save=(id,name,factor)=>({id,name,action:"save",rule:{factor,market:"SZ",sector:"全部行业"}});
const render=(c,sid,edits=[])=>c.render({mode:"filters",sid,edits});
render(first,"one"); render(second,"two");
await tick();
render(first,"one",[save("1","甲","mom")]);
render(second,"two",[save("2","乙","vol")]);
await tick(); await tick();
assert.deepEqual(first.messages.at(-1).rules.map(r=>r.name).sort(),["乙","甲"]);
const refreshed=client();
render(refreshed,"three");await tick();
assert.equal(refreshed.messages.at(-1).rules.length,2);
render(refreshed,"three",[save("3","乙","pe"),{id:"4",action:"delete",name:"甲"}]);await tick();await tick();
assert.deepEqual(second.messages.at(-1).rules.map(r=>[r.name,r.factor]),[["乙","pe"]]);
first.close();second.close();refreshed.close();

const a=client(), b=client();
const write=(c,sid,roster,ack)=>c.render({sid,ack,write:true,equal:false,roster,draft:{version:"example"}});
a.render({sid:"a"});b.render({sid:"b"});
const roster=[["600000.SH",32.123456]];
write(a,"a",roster,a.messages.at(-1).id);
await tick();await tick();
assert.equal(b.messages.at(-1).event,"sync");
assert.deepEqual(b.messages.at(-1).roster,roster);
write(b,"b",[],"stale");
assert.deepEqual(JSON.parse(storage.get("xuheng.independent.holdings.v1")),roster);
const serverTabStore=new Map([["xuheng.independent.study.v1",JSON.stringify({tab:"区间回测"})]]);
const remount=client(false,serverTabStore);
remount.render({sid:"same-live-session",write:true,draft:{tab:"参数比较与样本外检验"}});
assert.equal(remount.messages.at(-1).event,"sync");
assert.equal(remount.messages.at(-1).draft,undefined);
remount.render({sid:"same-live-session",write:true,ack:remount.messages.at(-1).id,roster,equal:false,draft:{tab:"参数比较与样本外检验"}});
assert.equal(JSON.parse(serverTabStore.get("xuheng.independent.study.v1")).tab,"参数比较与样本外检验");
const refreshedTab=client(false,serverTabStore);
refreshedTab.render({sid:"new-session",write:false});
assert.equal(refreshedTab.messages.at(-1).draft.tab,"参数比较与样本外检验");
const noStorage=client(true);
render(noStorage,"private",[save("5","本次","turn")]);await tick();
assert.equal(noStorage.messages.at(-1).storageError,true);
assert.deepEqual(noStorage.messages.at(-1).rules.map(r=>r.name),["本次"]);
console.log("PASS: concurrent named rules, refresh, overwrite/delete, local six-decimal roster sync, blocked storage.");
