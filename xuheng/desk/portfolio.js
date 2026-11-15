import {box,esc,note,select,requireDay,offerRefresh} from "./lab.js";
import {editorMarkup,holdingsEditor} from "./holdings.js";
import {models,controlsForPB,markets,weighting,frequency,frequencyValue,benchmarks,benchmarkNotes,namesForModel,request,dateField,readDate,numberList,cadenceFields,showResult,methods} from "./portfolio-view.js";
import {comparisonTab} from "./portfolio-study.js";

function get(key,fallback){
  try{return JSON.parse(sessionStorage.getItem(key))??fallback;}catch{return fallback;}
}
const record=value=>value&&typeof value==="object"&&!Array.isArray(value)?value:{};
const previous=record(get("xuheng.portfolio-study.v1",{}));
const rangeKey="xuheng.portfolio-range.v2", seenKey="xuheng.portfolio-seen.v2";
const saved=record(get(rangeKey,{}));
let latestRange=null;
const rawHistory=get(seenKey,previous.seen);
const history=Array.isArray(rawHistory)?rawHistory.filter(p=>Array.isArray(p)&&p.length===2&&p.every(d=>typeof d==="string"&&/^20\d{6}$/.test(d))&&p[0]<=p[1]):[];
function readHistory(from,to){return history.some(([a,b])=>from&&to&&from<=b&&to>=a);}
export function remember(from,to){
  if(!readHistory(from,to)||!history.some(([a,b])=>a<=from&&b>=to))history.push([from,to]);
  try{sessionStorage.setItem(seenKey,JSON.stringify(history));}catch{}
}
export function portfolioStudy(ctx){
  const research=ctx.research;
  ctx.panel.innerHTML='<div class="pf-tabs" aria-label="组合表现视图"><a href="#portfolio" '+(!research?'aria-current="page"':'')+'>区间回测</a><a href="#portfolio/research" '+(research?'aria-current="page"':'')+'>参数比较与样本外检验</a></div><div id="pf-view"></div>';
  const view={...ctx,panel:ctx.panel.querySelector("#pf-view"),legacy:previous,readHistory,remember};
  if(research)comparisonTab(view);else rangeTab(view);
}
function rangeTab(ctx){
  const {panel,day,openManual,isCurrent,wireInput,name,stockExists}=ctx;
  const el=id=>panel.querySelector("#"+id);
  const start=String(Number(day.slice(0,4))-1)+day.slice(4,6)+"01";
  const old=saved.draft||previous.draft||{};
  const r={model:"mom",exchange:"",count:10,weighting:"equal",interval:1,bench:"000300.SH",fee:10,weights:[],symbols:[],...old};
  const initialFrom=saved.from??start,initialTo=saved.to??day;
  const cadences=saved.cadences??={...(previous.cadences||{})};
  const factor=saved.factor??={count:r.model==="manual"?10:r.count,weight:r.model==="manual"?"equal":r.weighting,
    exchange:r.exchange||"",control:r.controlModel||"mom"};
  let manualWeight=r.model==="manual"?r.weighting:saved.manualWeight||"manual";
  const group=m=>m==="manual"?"manual":"factor";
  const preference=m=>cadences[group(m)]||{freq:m==="manual"?"hold":"1",days:"10"};
  let f=frequencyValue(r),days=r.intervalUnit==="days"?String(r.interval):preference(r.model).days;
  if(openManual&&r.model!=="manual"){
    cadences.factor={freq:f,days};Object.assign(r,{model:"manual",weighting:manualWeight});
    ({freq:f,days}=preference("manual"));latestRange=null;
  }
  const fields=select("pm-model","选股模型",models,r.model)+select("pm-control","对照模型",controlsForPB,factor.control)+select("pm-exchange","市场",markets,factor.exchange)
    +'<label>目标持股数 <input id="pm-count" required type="number" min="1" max="200" value="'+esc(factor.count)+'"></label>'
    +select("pm-weight","配权方式",weighting,r.weighting)+select("pm-frequency","调仓频率",frequency,f)
    +'<label id="pm-days-label">间隔（交易日） <input id="pm-days" type="number" min="1" step="1" required value="'+esc(days)+'"></label>'
    +select("pm-bench","市场基准",benchmarks,r.bench)
    +'<label>单边成本（基点） <input id="pm-cost" required type="number" min="0" max="100" step="0.1" value="'+esc(r.fee)+'"></label>';
  panel.innerHTML=box("组合规则",'<form id="pm-form" novalidate><fieldset id="pm-fields"><div class="controls">'+fields+'</div><p class="note" id="pm-model-note"></p><p class="note" id="pm-bench-note"></p><div id="pm-manual"><label for="pm-weights">按排名填写权重（%）</label> <input id="pm-weights" class="entry" placeholder="例如 50,30,20" value="'+esc(r.rankWeightText??(r.model==="manual"?"":r.weights?.join(",")||""))+'"></div>'+editorMarkup()+'<div class="pf-windows"><div><h3>回测区间</h3><div class="controls">'+dateField("pm-from","起日",initialFrom,day)+dateField("pm-to","截止日",initialTo,day)+'</div></div></div></fieldset><div class="actions"><button type="submit" id="pm-run" class="act">运行区间回测</button></div></form><p id="pm-status" class="pf-status" role="status"></p>'+methods())+'<div id="pm-in"></div>';
  const form=el("pm-form"),status=el("pm-status");
  let busy=false,lastModel=r.model,revision=0;
  const editor=holdingsEditor({el,wireInput,name,stockExists,mode:()=>el("pm-weight").value,isLocked:()=>busy,onEdit:edited,legacy:previous.draft});
  function values(){
    const model=el("pm-model").value,m=model==="manual",w=el("pm-weight").value,rows=editor.rows();
    return {model,...(model==="pb"?{controlModel:el("pm-control").value}:{}),exchange:m?"":el("pm-exchange").value,
      count:m?rows.length:el("pm-count").valueAsNumber,weighting:w,...cadenceFields(el("pm-frequency").value,el("pm-days").value),
      bench:el("pm-bench").value,fee:el("pm-cost").valueAsNumber,symbols:m?rows.map(p=>p[0]):[],
      weights:w!=="manual"?[]:m?rows.map(p=>p[1]):numberList(el("pm-weights").value),
      trainFrom:readDate(el("pm-from")),trainTo:readDate(el("pm-to"))};
  }
  function update(){
    const model=el("pm-model").value,m=model==="manual",weight=el("pm-weight").value,freq=el("pm-frequency").value;
    for(const [id,visible] of [["pm-count",!m],["pm-exchange",!m],["pm-control",model==="pb"],["pm-days",freq==="custom"]]){
      el(id).disabled=!visible;el(id).closest("label").hidden=!visible;
    }
    el("pm-manual").hidden=m||weight!=="manual";el("pm-weights").disabled=el("pm-manual").hidden;
    editor.render(m,null);
    el("pm-model-note").textContent=namesForModel[model]+(freq==="hold"?" 仅在区间首个交易日开盘尝试建仓。":freq==="custom"?" 从区间首个交易日开始，按交易日计数调仓。":m?" 每次调仓保留名单，重新计算目标权重。":"")
      +(weight==="tb"?" TB 使用最近 120 个有效配对交易日，按正 α 配权。":"");
    el("pm-bench-note").textContent=benchmarkNotes[el("pm-bench").value];
    el("pm-fields").disabled=busy;el("pm-run").disabled=busy;
  }
  function feedback(msg,error=false){status.textContent=msg;status.classList.toggle("error",error);}
  function save(v){
    if(v.model==="manual")manualWeight=v.weighting;
    else Object.assign(factor,{count:el("pm-count").value,weight:v.weighting,exchange:v.exchange,control:el("pm-control").value});
    Object.assign(saved,{draft:{...v,rankWeightText:el("pm-weights").value},from:v.trainFrom,to:v.trainTo,cadences,manualWeight,factor});
    try{sessionStorage.setItem(rangeKey,JSON.stringify(saved));}catch{}
  }
  function edited(){
    const model=el("pm-model").value;
    if(group(lastModel)!==group(model)){
      cadences[group(lastModel)]={freq:el("pm-frequency").value,days:el("pm-days").value};
      const next=preference(model);el("pm-frequency").value=next.freq;el("pm-days").value=next.days;
      if(model==="manual")el("pm-weight").value=manualWeight;
      else{manualWeight=el("pm-weight").value;el("pm-count").value=factor.count;el("pm-weight").value=factor.weight;}
    }
    lastModel=model;cadences[group(model)]={freq:el("pm-frequency").value,days:el("pm-days").value};
    revision++;busy=false;latestRange=null;el("pm-in").replaceChildren();update();save(values());feedback("");
  }
  const changed=e=>{if(!e.target.closest("#pm-roster"))edited();};
  form.addEventListener("input",changed);form.addEventListener("change",changed);
  const sync=e=>{if(isCurrent()&&[null,"xuheng.positions.v1"].includes(e.key)){editor.reload();if(el("pm-model").value==="manual")edited();}};
  window.addEventListener("storage",sync);window.addEventListener("hashchange",()=>window.removeEventListener("storage",sync),{once:true});
  function display(result,rules){showResult(el("pm-in"),"区间回测结果","pm-range",result,rules,ctx);}
  form.onsubmit=async e=>{
    e.preventDefault();if(busy)return;
    if(!form.reportValidity()){feedback("请检查所选参数和回测日期。",true);return;}
    const v=values();
    if(v.model==="manual"&&!v.count){feedback("自选名单为空，请添加股票或载入示例。",true);el("add-stock").focus();return;}
    const ticket=++revision;save(v);busy=true;update();feedback("正在计算区间收益、回撤和持仓…");
    try{
      const res=await request("range",{rules:v,asOf:day});if(!isCurrent()||ticket!==revision)return;
      requireDay(res.day,day);
      latestRange={day,key:JSON.stringify(v),result:res.result,rules:res.rules};
      ctx.remember(res.result.months[0].entry,res.result.months.at(-1).end);
      display(res.result,res.rules);feedback("回测已完成。");
    }catch(e){if(isCurrent()&&ticket===revision){feedback(e.message,true);offerRefresh(status,e,ctx.refresh);}}
    finally{if(isCurrent()&&ticket===revision){busy=false;update();}}
  };
  update();if(openManual)save(values());
  if(latestRange?.day===day&&latestRange.key===JSON.stringify(values())){display(latestRange.result,latestRange.rules);feedback("回测已完成。");}
}
