import {esc,fmt,table} from "./lab.js";
import {searchField} from "./search.js";

const key="xuheng.positions.v1", autoKey="xuheng.position-weights-auto.v1", migration="xuheng.holdings-unified.v1";
const fetchLocal=(k,fallback)=>{try{return JSON.parse(localStorage.getItem(k))??fallback;}catch{return fallback;}};
const number=w=>typeof w==="number"&&Number.isFinite(w)&&w>=0&&w<=100;
const round=w=>Math.round(w*1e6)/1e6;
function split(n){const units=1e6,each=Math.floor(100*units/n),extra=100*units-each*n;return Array.from({length:n},(_,i)=>(each+(i<extra?1:0))/units);}
export function sectorTable(list,sector,title){
  const groups=new Map();
  for(const [c,w] of list)if(w>0){const s=sector(c);groups.set(s,(groups.get(s)||0)+w);}
  return groups.size?'<details class="pf-details"><summary>'+esc(title)+'</summary>'+table(["行业","股票权重"],[...groups].sort((a,b)=>b[1]-a[1]).map(([s,w])=>[esc(s),fmt(w)+"%"]))+'<p class="note">按当前行业分类汇总，现金单列。</p></details>':"";
}
export const editorMarkup=()=>'<section id="pm-roster" aria-labelledby="pm-roster-title" hidden><h3 id="pm-roster-title">自选股票与目标权重</h3><div id="pm-add">'+searchField("add-stock","输入股票名称或代码添加")+'</div><div id="pm-roster-rows"></div><div id="pm-roster-summary" class="note" aria-live="polite"></div><div class="actions" id="pm-roster-buttons"><button type="button" id="pm-equalize" class="quiet">等权分配</button><button type="button" id="pm-example" class="quiet">载入三只股票示例</button></div><p id="pm-roster-note" class="note" role="status"></p></section>';
export function holdingsEditor({el,wireInput,name,stockExists,mode,isLocked,onEdit,legacy}){
  const validRows=src=>{
    const seen=new Set();return (Array.isArray(src)?src:[]).filter(p=>Array.isArray(p)&&stockExists(p[0])&&number(p[1])&&!seen.has(p[0])&&seen.add(p[0])).slice(0,200).map(p=>[p[0],p[1]]);
  };
  let list=validRows(fetchLocal(key,[])),auto=fetchLocal(autoKey,null),storageError=false,view="",rowsShown="",lastLock=null;
  if(typeof auto!=="boolean")auto=list.length===0||(list.length===1&&list[0][1]===100);
  const save=()=>{try{localStorage.setItem(key,JSON.stringify(list));localStorage.setItem(autoKey,JSON.stringify(auto));localStorage.setItem(migration,"true");storageError=false;}catch{storageError=true;}};
  if(!fetchLocal(migration,false)){
    // Nominal weights in an existing manual experiment belong to their original ordered symbols.
    const w=typeof legacy?.weightText==="string"?legacy.weightText.trim().split(/[,，、;；\s]+/).filter(Boolean).map(Number):legacy?.weights;
    if(legacy?.model==="manual"&&legacy.weighting==="manual"&&Array.isArray(legacy.symbols)&&legacy.symbols.length&&JSON.stringify(legacy.symbols)===JSON.stringify(list.map(p=>p[0]))&&Array.isArray(w)&&w.length===list.length&&w.every(number)&&w.reduce((a,b)=>a+b,0)<=100.0000001){
      list=list.map(([c],i)=>[c,w[i]]);auto=false;
    }
    save();
  }
  function effective(lock){
    return lock?lock.symbols.map((c,i)=>[c,lock.weighting==="manual"?lock.weights[i]:0]):list;
  }
  const total=xs=>xs.reduce((v,p)=>v+p[1],0);
  const storable=()=>list.every(p=>number(p[1]))&&total(list)<=100.0000001;
  const spread=()=>{const weights=split(list.length);list.forEach((p,i)=>{p[1]=weights[i];});};
  function totals(){
    const xs=effective(lastLock),m=mode(),risk=el("pm-roster-summary");
    const raw=xs.map(p=>p[1]),bad=raw.some(w=>!number(w)),sum=total(xs);
    risk.classList.toggle("error",m==="manual"&&(bad||sum>100.0000001));
    risk.textContent=!xs.length?"名单为空。可搜索股票，也可载入示例。":m==="tb"?xs.length+" 只股票 · TB 在建仓或调仓时估计权重；可在结果中查看。":m==="equal"?xs.length+" 只股票 · 各占 "+fmt(100/xs.length)+"%（成交前目标）":bad?"请补齐每只股票的权重（0 至 100%）。":xs.length+" 只股票 · 目标合计 "+fmt(sum)+"% · "+(sum>100.0000001?"超过 100%，请调低权重。":"预留现金 "+fmt(Math.max(0,100-sum))+"%");
    if(m==="list"&&xs.length)risk.textContent=xs.length+" 只股票 · 各候选共用名单，分别按所选规则配权。";
    el("pm-roster-note").textContent=lastLock?"本次检验使用锁定时的名单。":(m==="manual"?(auto?"增删股票时自动等分；修改任一权重后保留手动比例。":"新增股票使用剩余现金；移除股票腾出的资金保留为现金。 "):"")+(!storable()?"当前权重草稿尚未保存，请补齐比例并将合计控制在 100% 以内。":storageError?"此浏览器暂时无法保存名单。":"名单和手动权重仅保存在此浏览器。");
  }
  function render(manual,lock,force=false){
    const root=el("pm-roster");root.hidden=!manual;
    if(!manual){el("pm-roster-rows").querySelectorAll("[data-weight]").forEach(n=>{n.disabled=true;});view="";return;}
    lastLock=lock;const xs=effective(lock), m=mode(), next=m+":"+Boolean(lock), codes=xs.map(p=>p[0]).join();
    const rows=el("pm-roster-rows");
    if(force||view!==next||codes!==rowsShown){
      view=next;rowsShown=codes;
      rows.innerHTML=xs.map(([c,w])=>'<div class="pf-position"><span><strong>'+esc(name(c))+'</strong> <small>'+esc(c)+'</small></span>'+
        (m==="manual"?'<label><input data-weight="'+esc(c)+'" aria-label="'+esc(name(c))+'目标权重" type="number" min="0" max="100" step="any" inputmode="decimal" required value="'+(number(w)?w:"")+'"> %</label>':'<span class="pf-rule-weight">'+(m==="equal"?fmt(100/xs.length)+"%":m==="tb"?"按 TB 估计":"按候选规则")+'</span>')+
        (!lock?'<button type="button" class="quiet" data-remove="'+esc(c)+'" aria-label="移除'+esc(name(c))+'">移除</button>':'')+'</div>').join("");
    }
    rows.querySelectorAll("[data-weight]").forEach(n=>{n.disabled=!!lock;});
    el("pm-add").hidden=!!lock;el("pm-roster-buttons").hidden=!!lock;
    el("pm-equalize").hidden=!xs.length||m!=="manual";el("pm-example").hidden=!!xs.length;
    totals();
  }
  const write=()=>{if(storable())save();};
  function changed(redraw=true){write();if(redraw)render(true,null,true);else totals();onEdit();}
  const rows=el("pm-roster-rows");
  rows.oninput=e=>{
    const n=e.target.closest("[data-weight]");if(!n||isLocked()||mode()!=="manual")return;
    const p=list.find(([c])=>c===n.dataset.weight);if(!p)return;
    p[1]=n.value===""||!n.validity.valid?null:n.valueAsNumber;auto=false;changed(false);
  };
  rows.onclick=e=>{
    const b=e.target.closest("[data-remove]");if(!b||isLocked())return;
    const i=list.findIndex(p=>p[0]===b.dataset.remove);if(i<0)return;
    list.splice(i,1);if(!list.length)auto=true;else if(auto)spread();changed();
    (Array.from(rows.querySelectorAll("[data-remove]"))[Math.min(i,list.length-1)]||el("add-stock")).focus();
  };
  wireInput("add-stock","stock",c=>{
    if(isLocked()||!stockExists(c))return;
    if(list.some(p=>p[0]===c)){el("pm-roster-note").textContent=name(c)+"已在名单中。";const n=Array.from(rows.querySelectorAll("[data-weight]")).find(n=>n.dataset.weight===c);n?.focus();n?.select();return;}
    if(list.length>=200){el("pm-roster-note").textContent="自选名单最多 200 只，请先移除一只。";return;}
    list.push([c,auto?0:round(Math.max(0,100-total(list)))]);if(auto)spread();changed();el("add-stock").focus();
  });
  el("add-stock").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.isComposing)e.preventDefault();});
  el("pm-equalize").onclick=()=>{if(isLocked())return;auto=true;spread();changed();};
  el("pm-example").onclick=()=>{if(isLocked()||list.length)return;list=validRows([["600519.SH",40],["000001.SZ",30],["300750.SZ",30]]);auto=false;changed();};
  return {render,rows:()=>list.map(p=>[...p]),reload(){
    const updated=fetchLocal(key,[]);list=validRows(updated);auto=fetchLocal(autoKey,list.length===0)===true;view="";
  }};
}
