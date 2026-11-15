import {request as callPython} from "./bridge.js";
import {rank} from "./rank.js";
export {rank};
const $=s=>document.querySelector(s);
export const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
export const fmt=(v,n=2)=>Number.isFinite(v)?v.toLocaleString("zh-CN",{minimumFractionDigits:n,maximumFractionDigits:n}):"—";
export const pct=v=>Number.isFinite(v)?(v>0?"+":"")+v.toFixed(2)+"%":"—";
export const signed=v=>'<span class="'+(v>0?"up":v<0?"down":"")+'">'+pct(v)+'</span>';
export const date=d=>d?String(d).replace(/^(\d{4})(\d{2})(\d{2})$/,"$1-$2-$3"):"—";
export const title=(a,b)=>'<div class="intro"><h1>'+esc(a)+'</h1><p>'+esc(b)+'</p></div>';
export const box=(a,b,extra="")=>'<section class="box"><div class="ttl"><h2>'+esc(a)+'</h2>'+extra+'</div>'+b+'</section>';
export const metric=(a,v,h="")=>'<div class="metric"><span>'+esc(a)+'</span><b>'+v+'</b>'+(h?'<small>'+esc(h)+'</small>':'')+'</div>';
export const note=s=>'<p class="note">'+esc(s)+'</p>';
export function executionNote(e,label,coverage){
 if(!e)return "";
 return note(label+"开盘买卖意向：逐股限价可核对 "+fmt(e.verified,0)+" 笔，限价缺失、按近似规则判断 "+fmt(e.estimated,0)+" 笔，无有效开盘行情 "+fmt(e.unquoted,0)+" 笔。触及涨停不买、触及跌停不卖；这些次数包含被拦下的买卖意向。"+(coverage&&e.estimated?" 本期数据版本已入库 2007 年以来 "+fmt(coverage.verifiedDays,0)+" / "+fmt(coverage.vendorDays,0)+" 个交易日的逐股限价；估算可能多拦或漏拦成交。":""));
}
export function valuationNote(v,label,total){
 if(!v)return "";
 const stale=v.staleHeld?note(label+"期末有 "+v.staleHeld+" 只持仓缺当期收盘报价，沿用末次可得价格。"):"";
 if(!v.endedHeld)return stale;
 return stale+note(label+"期末持有 "+v.endedHeld+" 只已退市股票，按末次报价估值，占账面净值 "+fmt(v.endedWeight)+"%。退市清偿金额未知，这部分未计入可用现金。"+(Number.isFinite(total)?"若这部分最终没有回收，期末累计收益将为 "+fmt((100+total)*(1-v.endedWeight/100)-100)+"%。":""));
}
export const empty=s=>'<p class="empty">'+esc(s)+'</p>';
export const table=(headers,rows)=>rows.length?'<div class="tbl"><table><thead><tr>'+headers.map(s=>'<th scope="col">'+esc(s)+'</th>').join("")+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(s=>'<td>'+s+'</td>').join("")+'</tr>').join("")+'</tbody></table></div>':empty("此条件下没有可用记录。");
export function pager(id,page,total,size){
 return '<div class="pager"><span>'+fmt(total,0)+' 条 · '+(page+1)+' / '+Math.max(1,Math.ceil(total/size))+' 页</span><div><button class="quiet" data-pager="'+id+'" data-delta="-1" '+(!page?"disabled":"")+'>上一页</button><button class="quiet" data-pager="'+id+'" data-delta="1" '+((page+1)*size>=total?"disabled":"")+'>下一页</button></div></div>';
}
export const select=(id,label,opts,value)=>'<label>'+esc(label)+' <select id="'+id+'">'+opts.map(([v,t])=>'<option value="'+esc(v)+'" '+(String(v)===String(value)?"selected":"")+'>'+esc(t)+'</option>').join("")+'</select></label>';
export const line=(id)=>'<div class="chart"><canvas id="'+id+'" tabindex="0" role="img" aria-label="历史曲线，左右方向键可查看各日数值"></canvas><div class="tip" hidden></div></div>';
export function draw(id,traces){
 const c=document.getElementById(id);if(!c)return;const wrap=c.parentElement,tip=wrap.querySelector(".tip");
 const points=traces.flatMap(t=>t.data).filter(p=>Number.isFinite(p[1]));if(!points.length){wrap.innerHTML=empty("所选区间没有共同的有效数据。");return;}
 const days=Array.from(new Set(points.map(p=>p[0]))).sort(), positions=new Map(days.map((d,i)=>[d,i]));
 const vals=points.map(p=>p[1]),rawMin=vals.reduce((a,b)=>Math.min(a,b),Infinity),rawMax=vals.reduce((a,b)=>Math.max(a,b),-Infinity),margin=(rawMax-rawMin)*.07||Math.abs(rawMax)*.01||1,lo=rawMin-margin,hi=rawMax+margin;
 const colors=["#176552","#b28c4a","#6375a3","#a25949","#687d71"];let focus=null;
 const cached=traces.map((t,i)=>({...t,color:t.color||colors[i%colors.length],v:new Map(t.data)}));
 function paint(){
   if(!c.isConnected){o.disconnect();return;}
   const width=Math.max(c.clientWidth,120),height=Math.max(c.clientHeight,120),scale=Math.min(window.devicePixelRatio||1,2);
   c.width=Math.round(width*scale);c.height=Math.round(height*scale);
   const ctx=c.getContext("2d");ctx.scale(scale,scale);const left=55,right=width-12,top=12,bottom=height-27;
   const X=i=>days.length===1?(left+right)/2:left+i/(days.length-1)*(right-left),Y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);
   ctx.font="11px system-ui";ctx.fillStyle="#586d67";ctx.textAlign="right";
   for(let i=0;i<4;i++){const v=lo+(hi-lo)*i/3,y=Y(v);ctx.strokeStyle="#e4ebe5";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();ctx.fillText(fmt(v,Math.abs(v)>999?0:2),left-7,y+4);}
   ctx.textAlign="left";ctx.fillText(date(days[0]),left,height-5);ctx.textAlign="right";ctx.fillText(date(days.at(-1)),right,height-5);
   for(const t of cached){if(t.data.length===1){const [d,v]=t.data[0];ctx.fillStyle=t.color;ctx.beginPath();ctx.arc(X(positions.get(d)),Y(v),3,0,Math.PI*2);ctx.fill();continue;}ctx.beginPath();ctx.strokeStyle=t.color;ctx.lineWidth=2;let started=false;for(const [d,v] of t.data){if(v==null)continue;const x=X(positions.get(d)),y=Y(v);if(!started){ctx.moveTo(x,y);started=true;}else ctx.lineTo(x,y);}ctx.stroke();}
   if(focus!==null){const d=days[focus],x=X(focus);ctx.strokeStyle="#73908b";ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,bottom);ctx.stroke();ctx.setLineDash([]);tip.textContent=date(d)+"\n"+cached.filter(t=>t.v.has(d)).map(t=>t.name+" "+fmt(t.v.get(d))).join("\n");tip.hidden=false;tip.style.left=Math.max(2,Math.min(x+8,width-tip.offsetWidth-4))+"px";tip.style.top=(top+tip.offsetHeight+6)+"px";}else{tip.hidden=true;}
 }
 const o=new ResizeObserver(paint);o.observe(c);paint();
 c.onpointermove=e=>{const x=e.clientX-c.getBoundingClientRect().left;focus=Math.max(0,Math.min(days.length-1,Math.round((x-55)/Math.max(1,c.clientWidth-67)*(days.length-1))));paint();};c.onpointerleave=()=>{focus=null;paint();};
 c.onkeydown=e=>{if(!["ArrowLeft","ArrowRight","Escape"].includes(e.key))return;e.preventDefault();focus=e.key==="Escape"?null:Math.max(0,Math.min(days.length-1,(focus??days.length-1)+(e.key==="ArrowLeft"?-1:1)));paint();};c.onblur=()=>{focus=null;paint();};
 return ()=>o.disconnect();
}
export class DataDateError extends Error{
 constructor(){super("页面与行情库的交易日不一致，请刷新行情后重试。");}
}
export function requireDay(actual,expected){if(actual!==expected)throw new DataDateError();}
export function offerRefresh(container,error,refresh){
 if(!(error instanceof DataDateError))return false;
 const button=document.createElement("button");button.type="button";button.className="quiet";button.textContent="刷新行情";
 button.onclick=()=>{button.disabled=true;refresh();};container.append(" ",button);return true;
}
export async function api(path,timeout=45000,settings={}){
 try {
   return await callPython(path, settings.body ? JSON.parse(settings.body) : null, timeout);
 } catch (error) {
   if (error.code === "snapshot_changed") throw new DataDateError();
   throw error;
 }
}
const seriesCache=new Map();
export function series(code,day){
 const key=day+"|"+code;
 if(!seriesCache.has(key)){
  const task=api("/api/series?"+new URLSearchParams({symbol:code,asOf:day})).then(data=>{requireDay(data.until,day);
    const bars=data.rows.map(row=>({...Object.fromEntries(data.fields.map((field,i)=>[field,row[i]])),day:date(row[0])}));
    return {until:data.until,status:data.status,bars};}).catch(e=>{if(seriesCache.get(key)===task)seriesCache.delete(key);throw e;});
  seriesCache.set(key,task);if(seriesCache.size>32)seriesCache.delete(seriesCache.keys().next().value);
 }
 return seriesCache.get(key);
}
export function adjusted(data){
 let level=100;return data.map((b,i)=>{if(i){const ref=b.pre_close||data[i-1].close;if(ref>0)level*=b.close/ref;}return [b.day.replaceAll("-",""),level];});
}
export function compare(a,b,span=0){
 const m=new Map(b),ad=a.filter(([d])=>m.has(d));const rows=span?ad.slice(-span):ad;if(!rows.length)return [[],[]];
 const x=rows[0][1],y=m.get(rows[0][0]);return [rows.map(([d,v])=>[d,100*v/x]),rows.map(([d])=>[d,100*m.get(d)/y])];
}
