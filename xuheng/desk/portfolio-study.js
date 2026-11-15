import {box,date,offerRefresh,requireDay,esc,fmt,note,pct,select,table} from "./lab.js";
import {editorMarkup,holdingsEditor} from "./holdings.js";
import {defaults as defaultMix,currentRule,readMix,totalText,validMix,weightInputs} from "./multifactor.js";
import {monthlyFrequency} from "./portfolio-view.js";
import {models,markets,controlsForPB,benchmarks,benchmarkNotes,weighting,frequency,frequencyValue,label,cadence,cadenceFields,dateField,readDate,numberList,weightError,request,saveResultText,showResult,methods} from "./portfolio-view.js";

const storage="xuheng.portfolio-comparison.v2";
const criteria=[["return","扣费后累计收益最高"],["drawdown","最大回撤最小（月度估值）"],["sharpe","月收益夏普比率最高"]];
const factorModels=models.filter(([m])=>m!=="manual");
const candidate=(count,weight="equal",freq="1")=>({model:"mom",count,weight,freq,days:"10",weights:""});
const defaults=day=>({common:{source:"factor",exchange:"",controlModel:"mom",bench:"000300.SH",fee:10,trainFrom:"20100101",trainTo:"20191231",testFrom:"20200101",testTo:day},
  criterion:"return",factor:[candidate(10),candidate(20)],manual:[candidate(0,"equal","hold"),candidate(0,"tb","hold")]});
let state,inside,outside;
function restore(day,legacy){
  if(state)return;
  try{state=JSON.parse(sessionStorage.getItem(storage));}catch{}
  if(!state?.draft?.common||!Array.isArray(state.draft.factor)||!Array.isArray(state.draft.manual)){
    state={draft:defaults(day)};
    const r=legacy.lock?.rules;
    if(legacy.lock?.token&&r){
      state.lock={...legacy.lock,legacy:true};
      const source=r.model==="manual"?"manual":"factor";
      Object.assign(state.draft.common,{source,exchange:r.exchange,bench:r.bench,fee:r.fee,controlModel:r.controlModel??"mom",
        trainFrom:r.trainFrom,trainTo:r.trainTo,testFrom:r.testFrom,testTo:r.testTo});
      const c={model:r.model,count:r.count,freq:frequencyValue(r),days:r.intervalUnit==="days"?String(r.interval):"10",weight:r.weighting,weights:r.weights.join(",")};
      state.draft[source]=[c,{...c,weight:c.weight==="equal"?"tb":"equal",weights:""}];
    }
  }
}
function persist(){try{sessionStorage.setItem(storage,JSON.stringify(state));return true;}catch{return false;}}
function candidateLabel(c,manual){
  const name=manual?"自选名单":label(factorModels,c.model)+(c.model==="multi"?"（"+currentRule(c.factorWeights)+"）":"")+" · "+c.count+" 只";
  return name+" · "+label(weighting,c.weighting)+" · "+cadence(c);
}
function rankingTable(assessment,plan){
  const manual=plan.common.source==="manual";
  const parameters=c=>{
    const description=esc(candidateLabel(c,manual));
    if(c.weighting!=="manual"||manual)return description;
    const values=c.weights.map(w=>esc(w)+"%").join("、");
    return '<details class="pf-ranked-weights"><summary>'+description+'</summary><span>按入选排名配权 · '+values+'</span></details>';
  };
  const rows=assessment.ranking.map(({index,rank,metrics})=>[
    rank===null?"不参与":String(rank),"候选 "+(index+1),parameters(plan.candidates[index]),pct(metrics.total),pct(metrics.dd),fmt(metrics.sharpe,3),
    metrics.invested?"有持仓":"全期现金"
  ]);
  const m=assessment.ranking[0].metrics;
  return box("样本内排名",note(date(m.from)+" 至 "+date(m.to)+" · "+label(criteria,plan.criterion)+(assessment.day?" · 行情版本 "+date(assessment.day):""))
    +table(["排名","候选","参数","扣费后累计收益","最大回撤（月度）","月收益夏普比率","实际持仓"],rows)
    +note("按未四舍五入的评价值排名。月度回撤使用每月最后一个区间内收盘净值，含期初资金和区间末尾。夏普比率使用完整月份的扣费后收益，月无风险利率取 0，以 √12 年化。本次有 "+m.completeMonths+" 个完整月份。"));
}
export function comparisonTab(ctx){
  const {panel,day,legacy,isCurrent,wireInput,name,stockExists}=ctx;
  restore(day,legacy);
  const draft=state.draft,common=draft.common,el=id=>panel.querySelector("#"+id);
  let busy="",revision=0;
  const comp=()=>state.assessment;
  const frozen=()=>!!state.lock;
  function actions(){
    return '<div class="actions pf-actions"><button type="button" class="act" id="pm-lock" disabled>锁定第一名</button><button type="button" class="act" id="pm-test" disabled>运行样本外</button><button type="button" class="quiet" id="pm-review" hidden>查看锁定的样本内明细</button><button type="button" class="quiet" id="pm-new" hidden>调整参数，重新比较</button></div>';
  }
  const settings='<div class="controls">'+select("ps-source","股票来源",[["factor","按模型选股"],["manual","使用自选名单"]],common.source)
    +select("ps-exchange","市场",markets,common.exchange)+select("ps-control","低 PB 对照模型",controlsForPB,common.controlModel)+select("ps-bench","市场基准",benchmarks,common.bench)
    +'<label>单边成本（基点） <input id="ps-cost" required type="number" min="0" max="100" step="0.1" value="'+esc(common.fee)+'"></label></div><p id="ps-bench-note" class="note"></p>'+editorMarkup()
    +'<div class="pf-windows"><div><h3>样本内 · 选择参数</h3><div class="controls">'+dateField("pm-is-from","起日",common.trainFrom,day)+dateField("pm-is-to","截止日",common.trainTo,day)+'</div></div>'
    +'<div><h3>样本外 · 检验已选参数</h3><div class="controls">'+dateField("pm-os-from","起日",common.testFrom,day)+dateField("pm-os-to","截止日",common.testTo,day)+'</div></div></div>'
    +'<p id="pm-seen" class="note"></p>';
  const candidates='<h3 class="pf-group-title">候选参数</h3><div id="ps-rows"></div><div class="actions"><button type="button" class="quiet" id="ps-add">添加一组候选</button></div><div class="controls pf-objective">'
    +select("ps-criterion","样本内评价标准",criteria,draft.criterion)+'</div>'+note("可以比较 2 至 8 组。共同设置适用于全部候选，评分使用各自主组合的扣费后表现。同分时取候选顺序靠前的一组。")
    +'<p class="note" id="ps-objective-note"></p>';
  panel.innerHTML=(!state.lock?.legacy?box("比较设置",'<form id="pm-form" novalidate><fieldset id="pm-fields">'+settings+candidates+'</fieldset><button type="submit" id="pm-compare-run" class="act">比较样本内表现</button></form>'):"")
    +'<div id="ps-ranking"></div><section class="box" id="ps-decision"><h2>锁定与样本外检验</h2><p id="pm-status" role="status" class="pf-status"></p>'+actions()+'<p id="pm-storage" class="note" hidden>此浏览器暂时无法保存比较设置，关闭页面后需要重新比较。</p></section><div id="pm-out"></div><div id="pm-in"></div>'+methods();
  const status=el("pm-status"),form=el("pm-form");
  const active=()=>draft[common.source],manual=()=>common.source==="manual";
  const listMode=()=>active().some(c=>c.weight==="manual")?"manual":active().every(c=>c.weight==="tb")?"tb":active().every(c=>c.weight==="equal")?"equal":"list";
  let removeListeners=()=>{};
  const editor=form?holdingsEditor({el,wireInput,name,stockExists,mode:listMode,isLocked:()=>frozen()||!!busy,onEdit:edited,legacy:legacy.draft}):null;
  function feedback(message,error=false){status.textContent=message;status.classList.toggle("error",error);}
  const keep=()=>{el("pm-storage").hidden=persist();};
  function rowHTML(c,i){
    const prefix="ps-"+i+"-",m=manual();
    const multi=!m&&c.model==="multi";
    if(multi){
      c.factorWeights??={...defaultMix};
      if(!["1","3","6"].includes(String(c.freq)))c.freq="1";
    }
    return '<div class="pf-candidate" data-row="'+i+'"><div class="pf-row-head"><strong>候选 '+(i+1)+'</strong><button type="button" class="quiet" data-remove-row="'+i+'" aria-label="移除候选 '+(i+1)+'" '+(active().length<=2?"disabled":"")+'>移除</button></div><div class="controls">'
      +(m?"":select(prefix+"model","选股模型",factorModels,c.model)+'<label>目标持股数 <input id="'+prefix+'count" required type="number" min="1" max="200" value="'+esc(c.count)+'"></label>')
      +select(prefix+"weight","配权方式",weighting,c.weight)+select(prefix+"freq","调仓频率",multi?monthlyFrequency:frequency,c.freq)
      +'<label '+(c.freq==="custom"?"":"hidden")+'>间隔（交易日） <input id="'+prefix+'days" type="number" step="1" min="1" required value="'+esc(c.days)+'" '+(c.freq==="custom"?"":"disabled")+'></label>'
      +(m?"":'<label '+(c.weight==="manual"?"":"hidden")+'>按排名填写权重（%） <input id="'+prefix+'weights" placeholder="例如 50,30,20" value="'+esc(c.weights)+'" '+(c.weight==="manual"?"required":"disabled")+'></label>')+'</div>'+
      (multi?'<fieldset><legend>选股因子权重</legend>'+weightInputs(prefix+"mix-",c.factorWeights)+'<p class="note" data-total>'+totalText(c.factorWeights)+'</p></fieldset>':"")+'</div>';
  }
  function drawRows(){el("ps-rows").innerHTML=active().map(rowHTML).join("");}
  function readShared(){
    Object.assign(common,{source:el("ps-source").value,exchange:el("ps-exchange").value,controlModel:el("ps-control").value,bench:el("ps-bench").value,fee:el("ps-cost").valueAsNumber,
      trainFrom:readDate(el("pm-is-from")),trainTo:readDate(el("pm-is-to")),testFrom:readDate(el("pm-os-from")),testTo:readDate(el("pm-os-to"))});
    draft.criterion=el("ps-criterion").value;
  }
  function plan(){
    const positions=manual()?editor.rows():[],hasManual=manual()&&active().some(c=>c.weight==="manual");
    return {criterion:draft.criterion,common:{...common,exchange:manual()?"":common.exchange,symbols:positions.map(p=>p[0]),weights:hasManual?positions.map(p=>p[1]):[]},
      candidates:active().map(c=>({model:manual()?"manual":c.model,...(!manual()&&c.model==="multi"?{factorWeights:{...c.factorWeights}}:{}),count:manual()?positions.length:Number(c.count),weighting:c.weight,...cadenceFields(c.freq,c.days),weights:!manual()&&c.weight==="manual"?numberList(c.weights):[]}))};
  }
  function invalidated(){
    revision++;state.assessment=null;state.plan=null;inside=outside=null;el("ps-ranking").replaceChildren();el("pm-in").replaceChildren();el("pm-out").replaceChildren();
  }
  function edited(){
    if(frozen()||busy)return;
    invalidated();feedback("");controls();keep();
  }
  function controls(){
    const locked=frozen(),a=comp();
    if(form){
      const m=manual(),pb=!m&&active().some(c=>c.model==="pb");
      el("ps-exchange").disabled=m;el("ps-exchange").closest("label").hidden=m;
      el("ps-control").disabled=!pb;el("ps-control").closest("label").hidden=!pb;
      el("ps-bench-note").textContent=benchmarkNotes[common.bench]+(pb?" 低 PB 候选只选正 PB 且满足信号历史长度的股票；其对照组合在该共同池内选股。":"");
      const lockList=locked&&m?{symbols:state.plan.common.symbols,weights:state.plan.common.weights,weighting:listMode()}:null;
      editor.render(m,lockList);
      if(m&&listMode()==="manual")el("pm-roster-note").textContent+=" 逐股比例只用于选择手动权重的候选。";
      el("pm-fields").disabled=locked||!!busy;el("ps-add").disabled=active().length>=8;
      el("pm-compare-run").disabled=locked||!!busy;el("pm-compare-run").hidden=locked;
      el("pm-seen").textContent=ctx.readHistory(common.testFrom,common.testTo)?"这个浏览器标签页已查看过与所选样本外重叠的历史表现。这段结果可作复验。":"";
      el("ps-objective-note").textContent=draft.criterion==="sharpe"?"夏普比率至少需要两个完整月份且月收益有波动。无法计算时，该候选不参与排名。":draft.criterion==="drawdown"?"所有候选按同一月度频率计算回撤。全程持有现金的组合可能以零回撤入选。":"";
    }
    el("ps-decision").hidden=!locked&&!a&&!busy&&!status.textContent;
    el("pm-lock").hidden=locked||!a?.receipt;el("pm-lock").disabled=locked||!a?.receipt||!!busy;
    el("pm-test").disabled=!locked||!!busy;el("pm-test").hidden=!locked&&!a?.receipt;
    el("pm-review").hidden=!locked||!!inside;el("pm-review").disabled=!!busy;
    el("pm-new").hidden=!locked;el("pm-new").disabled=!!busy;
  }
  function drawRanking(){if(state.plan&&comp())el("ps-ranking").innerHTML=rankingTable(comp(),state.plan);}
  function show(where,data,rules){
    const out=where==="pm-out";showResult(el(where),out?"样本外表现":"锁定方案的样本内明细",out?"pm-holdout":"pm-insample",data,rules,ctx);
  }
  const initialMsg=()=>state.lock?.legacy?"已恢复此前锁定的单一方案 · "+saveResultText(state.lock.rules):frozen()?"已锁定候选 "+(comp().winner+1)+" · "+saveResultText(state.lock.rules):comp()?.winner!=null?"样本内第一名为候选 "+(comp().winner+1)+"。锁定后可以运行样本外。":comp()?"所有候选的夏普比率均无法计算。请调整区间、候选参数或评价标准。":state.needsComparison?"已恢复比较设置，请核对名单和参数，重新比较并锁定第一名。":"";
  if(form){
    drawRows();
    form.oninput=form.onchange=e=>{
      if(frozen()||busy||e.target.closest("#pm-roster"))return;
      const row=e.target.closest("[data-row]");
      if(row){
        const i=Number(row.dataset.row),c=active()[i],field=e.target.id.slice(("ps-"+i+"-").length);
        if(e.target.hasAttribute("data-mix-factor")){
          c.factorWeights=readMix(row);row.querySelector("[data-total]").textContent=totalText(c.factorWeights);edited();return;
        }
        if(!Object.hasOwn(c,field))return;
        const before=c[field];
        c[field]=e.target.value;
        if(field==="model"&&before!==c.model){drawRows();el("ps-"+i+"-model").focus({preventScroll:true});edited();return;}
        for(const [id,show] of [["days",c.freq==="custom"],["weights",c.weight==="manual"]]){
          const n=el("ps-"+i+"-"+id);if(n){n.disabled=!show;n.required=show;n.closest("label").hidden=!show;}
        }
      }else{
        const old=common.source;readShared();if(old!==common.source)drawRows();
      }
      edited();
    };
    el("ps-add").onclick=()=>{
      if(frozen()||busy||active().length>=8)return;
      const last=active().at(-1);
      active().push({...last,...(!manual()?{count:Math.min(200,Number(last.count||0)+10)}:{freq:last.freq==="hold"?"1":"hold"})});
      drawRows();edited();el("ps-rows").lastElementChild.querySelector("select").focus();
    };
    el("ps-rows").onclick=e=>{
      const b=e.target.closest("[data-remove-row]");
      if(!b||frozen()||busy||active().length<=2)return;
      const i=Number(b.dataset.removeRow);active().splice(i,1);drawRows();edited();
      el("ps-rows").children[Math.min(i,active().length-1)].querySelector("select").focus();
    };
    const sync=e=>{if(isCurrent()&&!frozen()&&[null,"xuheng.positions.v1"].includes(e.key)){
      editor.reload();if(manual()){busy="";edited();feedback("自选名单已在其他页面修改，请按新名单比较。");controls();}
    }};
    removeListeners=()=>{window.removeEventListener("storage",sync);window.removeEventListener("hashchange",removeListeners);};
    window.addEventListener("storage",sync);window.addEventListener("hashchange",removeListeners,{once:true});
    form.onsubmit=async e=>{
      e.preventDefault();if(frozen()||busy)return;
      if(!form.reportValidity()){feedback("请检查候选参数和样本日期。",true);controls();return;}
      readShared();
      if(manual()&&!editor.rows().length){feedback("请先添加自选股票或载入示例。",true);controls();el("add-stock").focus();return;}
      const p=plan();
      for(const [i,c] of p.candidates.entries()){
        if(c.model==="multi"&&!validMix(c.factorWeights)){feedback("候选 "+(i+1)+" 的因子权重合计须为 100%。",true);controls();el("ps-"+i+"-mix-mom").focus();return;}
        if(c.weighting!=="manual")continue;
        const issue=weightError(manual()?p.common.weights:c.weights,c.count);
        if(issue){
          feedback("候选 "+(i+1)+" · "+issue,true);controls();
          (manual()?el("pm-roster-rows").querySelector("[data-weight]"):el("ps-"+i+"-weights"))?.focus();return;
        }
      }
      invalidated();keep();const ticket=revision;
      const current=()=>isCurrent()&&ticket===revision;
      busy="compare";feedback("正在比较样本内表现…");controls();
      try{
        const res=await request("compare",{plan:p,asOf:day});if(!current())return;
        requireDay(res.day,day);delete state.needsComparison;state.plan=p;state.assessment=res;drawRanking();
        const m=res.ranking[0].metrics;ctx.remember(m.from,m.to);
        feedback(initialMsg());keep();
      }catch(e){if(current()){feedback(e.message,true);offerRefresh(status,e,ctx.refresh);}}
      finally{if(current()){busy="";controls();}}
    };
    if(comp()&&!frozen()&&JSON.stringify(plan())!==JSON.stringify(state.plan)){invalidated();keep();}
  }
  async function step(action){
    if(busy||(action==="lock"?frozen()||!comp()?.receipt:!frozen()))return;
    if(action==="lock"&&JSON.stringify(plan())!==JSON.stringify(state.plan)){edited();feedback("设置已变更，请重新比较候选。",true);controls();return;}
    const ticket=revision,current=()=>isCurrent()&&ticket===revision;
    busy=action;feedback(action==="lock"?"正在锁定样本内第一名和样本日期…":action==="test"?"正在按锁定参数计算样本外表现…":"正在读取样本内明细…");controls();
    try{
      const res=await request(action,{token:action==="lock"?comp().receipt:state.lock.token});if(!current())return;
      if(action==="lock"){
        state.lock={token:res.token,rules:comp().rules};comp().receipt=null;feedback(initialMsg());
      }else if(action==="review"){
        inside=res.result;show("pm-in",inside,res.rules);feedback("已显示锁定方案的样本内明细。");
      }else{
        outside=res.result;const m=outside.months;ctx.remember(m[0].entry,m.at(-1).end);
        show("pm-out",outside,res.rules);feedback("样本外已完成 · "+saveResultText(res.rules));
      }
      keep();
    }catch(e){if(current())feedback(e.message,true);}
    finally{if(current()){busy="";controls();}}
  }
  el("pm-lock").onclick=()=>step("lock");el("pm-test").onclick=()=>step("test");el("pm-review").onclick=()=>step("review");
  el("pm-new").onclick=()=>{
    if(!frozen()||busy)return;
    removeListeners();state.lock=null;invalidated();keep();comparisonTab(ctx);
  };
  // Older screens stored only a lock flag and settings, without a verifiable winner.
  if(state.restoreLock && !state.lock){
    delete state.restoreLock;
    state.needsComparison=true;
    keep();
  }
  drawRanking();if(inside&&state.lock)show("pm-in",inside,state.lock.rules);if(outside&&state.lock)show("pm-out",outside,state.lock.rules);
  const msg=initialMsg();
  feedback(outside&&state.lock?"样本外已完成 · "+saveResultText(state.lock.rules):msg);controls();
}
