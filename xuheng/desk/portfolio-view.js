import {api, box, date, esc, fmt, line, note, pct, select, signed, table, valuationNote,executionNote} from "./lab.js";

import {sectorTable} from "./holdings.js";

export const models=[["mom","60 日动量"],["vol","20 日低波动"],["rev","20 日短期反转"],["pb","低市净率（PB）"],["manual","使用自选名单"]];
export const controlsForPB=models.filter(([m])=>["mom","vol","rev"].includes(m));
const controlName=r=>label(controlsForPB,r.controlModel??"mom");
export const markets=[["","全 A 股"],["SH","沪市"],["SZ","深市"],["BJ","北交所"]];
export const weighting=[["equal","等权"],["tb","TB 配权（仅做多）"],["manual","手动权重"]];
export const frequency=[[1,"每月"],[3,"每季初"],[6,"每半年初"],["custom","自定义（交易日）"],["hold","买入并持有"]];
export const frequencyValue=r=>r.intervalUnit==="days"?"custom":r.intervalUnit==="hold"?"hold":String(r.interval);
export const benchmarks=[["000300.SH","沪深 300"],["000001.SH","上证指数"],["000905.SH","中证 500"],["000852.SH","中证 1000"],["899050.BJ","北证 50"]];
export const benchmarkNotes={"000300.SH":"沪深大盘股，自 2005-04-08 发布。","000001.SH":"沪市综合指数，覆盖 2000 年以来的样本。","000905.SH":"沪深中盘股，自 2007-01-15 发布。","000852.SH":"沪深小盘股，自 2014-10-17 发布。","899050.BJ":"北交所代表性股票，自 2022-11-21 发布。"};
export const namesForModel={mom:"按过去 60 个有效交易日的累计收益从高到低选股。",vol:"按过去 20 个有效交易日的波动率从低到高选股。",rev:"按过去 20 个有效交易日的累计收益从低到高选股。",pb:"信号日 PB 为正、具有 60 个有效交易日历史的股票进入共同股票池。低 PB 组优先选市净率最低的股票。两组使用相同的持股数、配权方式、调仓频率和费率。",manual:"按本页名单建仓。可直接增删股票，在「手动权重」下逐只填写比例。"};
export const label=(options,value)=>options.find(([key])=>String(key)===String(value))?.[1]||"";
export const request=(action,body)=>api("/api/portfolio",action==="compare"?180000*body.plan.candidates.length:180000,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,...body})});
export function dateField(id,label,value,last){
 return '<label>'+label+' <input id="'+id+'" type="date" min="2000-01-01" max="'+esc(date(last))+'" value="'+esc(value?date(value):"")+'" required></label>';
}
const dailyMode=r=>r.intervalUnit==="hold"||r.intervalUnit==="days";
export const cadence=r=>r.intervalUnit==="hold"?"买入并持有":r.intervalUnit==="days"?"每 "+r.interval+" 个交易日":label(frequency,r.interval);
export function saveResultText(r) {
  return label(models,r.model)+(r.model==="pb"?" 对照 "+controlName(r):"")+" · "+(r.model==="manual"?"自选 "+r.count+" 只":label(markets,r.exchange)+" · 前 "+r.count+" 只")
    +" · "+label(weighting,r.weighting)+" · "+cadence(r)+" · "+r.fee+" 基点 · "+label(benchmarks,r.bench);
}
function resultHTML(id,data,r,name,sector){
  const daily=dailyMode(r);
  const mainName=r.weighting==="equal"?"等权组合":r.weighting==="tb"?"TB 组合":"手动配权组合";
  const display=(name,metrics)=>[name,signed(metrics.total),data.market?(metrics.total-data.market.total).toFixed(2)+" 个百分点":"—",signed(metrics.dd),...(data.control?[metrics.cost==null?"—":pct(metrics.cost)]:[])];
  const rows=[display(data.control?"低 PB · "+mainName:mainName,data.main)];
  if(data.control)rows.push(display(controlName(r)+" · "+mainName,data.control));
  if(r.weighting!=="equal")rows.push(display(data.control?"低 PB 入选股等权":"同批候选股等权",data.equal));
  if(data.market)rows.push(display(label(benchmarks,r.bench),data.market));
  const end=data.months.at(-1);
  function holdTable(list,cash,isPB){
    const holdings=list.map(h=>[esc(name(h.code))+' <small>'+esc(h.code)+'</small>'+(h.ended?' · 已退市 '+date(h.ended):h.stale?' · 期末沿用旧价':''),h.value==null?"—":isPB?fmt(h.value,4)+" 倍":pct(h.value),
      h.alpha==null?"—":(h.alpha*100).toFixed(4)+"%",fmt(h.weight)+"%",fmt(h.endWeight)+"%"]);
    holdings.push(["现金","—","—",fmt(Math.max(0,100-list.reduce((s,h)=>s+h.weight,0)))+"%",fmt(cash)+"%"]);
    return table(["股票",isPB?"信号日 PB":"选股因子值","估计日 α",r.intervalUnit==="hold"?"期初目标权重":"最近目标权重","期末实际权重"],holdings)+sectorTable(list.map(h=>[h.code,h.endWeight]),sector,"查看期末行业权重");
  }
  const ledger='<details class="pf-details" id="'+id+'-ledger"><summary>'+(daily?"逐日交易记录":"逐月调仓记录")+'</summary><div id="'+id+'-lines"></div></details>';
  return note(date(data.months[0].entry)+" 至 "+date(end.end)+" · "+data.months.length+(daily?" 个交易日 · ":" 个持有期 · ")+(r.intervalUnit==="hold"?"仅期初尝试建仓，此后持有":data.months.filter(m=>m.rebalance).length+" 次计划调仓")+" · 组合收益已计交易成本")
    +table(["组合","累计收益","相对基准收益差",daily?"最大回撤（日收盘）":"最大回撤（月末）",...(data.control?["累计费用 / 初始资金"]:[])],rows)+line(id+"-curve")+'<div id="'+id+'-legend"></div>'
    +(r.intervalUnit==="hold"&&r.model==="manual"&&data.months[0].held<r.count?note("期初名单 "+r.count+" 只，实际建仓 "+data.months[0].held+" 只。目标为零、当时尚未上市或开盘未能买入的股票，之后不会补买。"):"")
    +executionNote(data.main.execution,data.control?"低 PB 组合":"组合",data.limitCoverage)+(data.control?executionNote(data.control.execution,controlName(r)):"")
    +valuationNote(data.valuation,data.control?"低 PB 组合":"组合",data.main.total)+(data.control?valuationNote(data.control.valuation,controlName(r),data.control.total):"")
    +(r.weighting!=="equal"?valuationNote(data.equal.valuation,"同批候选股等权对照",data.equal.total):"")
    +(data.missingFits?note("所选组合在此区间的调仓日均缺少合格的 120 日回归估计，TB 按规则持有现金。"):"")
    +(data.control?.missingFits?note("对照组合在此区间无合格的 120 日回归估计，TB 按规则持有现金。"):"")
    +(data.main.cashPeriods?note("其中 "+data.main.cashPeriods+(daily?" 个交易日收盘时为空仓。":" 个持有期期末全部为现金。")+"可展开交易记录核对当期选股和实际持仓数。"):"")
    +(data.market?"":data.overlap?note("全期基准收益缺失。最近连续可比区间为 "+date(data.overlap.from)+" 至 "+date(data.overlap.to)+"，"+label(benchmarks,r.bench)+" "+pct(data.overlap.market)+"，"+(data.control?"低 PB":"组合")+" "+pct(data.overlap.main)+(data.control?"，"+controlName(r)+" "+pct(data.overlap.control):"")+"。以上收益均按该区间计算。"):note("此区间没有所选指数发布后的完整报价。"))
    +(data.control&&data.firstSelection&&data.firstSelection!==data.months[0].entry?note("首次有共同候选股的调仓日为 "+date(data.firstSelection)+"。此前两个组合均持有现金。"):"")
    +'<details class="pf-details"><summary>'+(data.control?"查看低 PB 持仓和权重":"查看持仓和权重")+'</summary>'+note("最近信号日 "+date(data.lastSignal)+"，期末实际权重截至 "+date(end.end)+"。")+holdTable(data.holdings,end.cash,r.model==="pb")+'</details>'
    +(data.control?'<details class="pf-details"><summary>查看'+esc(controlName(r))+'持仓和权重</summary>'+holdTable(data.control.holdings,data.control.cash,false)+'</details>':"")
    +ledger;
}
function bindLedger(id,data,r){
  const details=document.getElementById(id+"-ledger"),area=document.getElementById(id+"-lines");
  const daily=dailyMode(r);let first=0,onlyRebalance=daily;
  function fill(){
    const records=onlyRebalance?data.months.filter(m=>m.rebalance):data.months;
    const end=records.length-first, slice=records.slice(Math.max(0,end-40),end).reverse();
    const pool=r.model==="pb";
    const headers=["信号日",daily?"交易日":"持有期","操作",...(pool?["共同股票池"]:[]),pool?"低 PB 入选 / 实持入选股":"候选 / 实持候选股","全部持仓","可估计 α 的候选数","期末缺报价持仓","期末现金"];
    area.innerHTML=(daily?'<label class="pf-ledger-filter"><input type="checkbox" data-only '+(onlyRebalance?"checked":"")+'> '+(r.intervalUnit==="hold"?"只看建仓日":"只看调仓日")+'</label>':"")+table(headers,slice.map(m=>[
      m.rebalance?date(m.signal):"—",daily?date(m.entry):date(m.entry)+" 至 "+date(m.end),m.rebalance?(r.intervalUnit==="hold"?"期初建仓":"调仓"):"持有",...(pool?[m.rebalance?fmt(m.pool,0):"—"]:[]),m.rebalance?m.candidates+" / "+m.filled:"—",String(m.held),m.rebalance?String(m.estimated):"—",String(m.stale),fmt(m.cash)+"%"]))
      +note("实持候选股是本次入选且期末仍持有的股票；全部持仓还包括未能卖出的旧仓。")+ '<div class="pager"><span>共 '+records.length+' 条 · 第 '+(Math.floor(first/40)+1)+' / '+Math.max(1,Math.ceil(records.length/40))+' 页</span><div><button type="button" class="quiet" data-prev '+(!first?"disabled":"")+'>上一页</button><button type="button" class="quiet" data-next '+(end<=40?"disabled":"")+'>下一页</button></div></div>';
    const toggle=area.querySelector("[data-only]");
    if(toggle)toggle.onchange=()=>{onlyRebalance=toggle.checked;first=0;fill();};
    area.querySelector("[data-prev]").onclick=()=>{first=Math.max(0,first-40);fill();};
    area.querySelector("[data-next]").onclick=()=>{if(end>40){first+=40;fill();}};
  }
  details.ontoggle=()=>{if(details.open&&!area.hasChildNodes())fill();};
}
function plotResult(id,data,r,chart,legend){
  const traces=[{name:data.control?"低 PB":r.weighting==="tb"?"TB 组合":r.weighting==="equal"?"等权组合":"手动配权组合",data:data.main.curve}];
  if(data.control)traces.push({name:controlName(r),data:data.control.curve});
  if(r.weighting!=="equal")traces.push({name:data.control?"低 PB 入选股等权":"同批候选股等权",data:data.equal.curve});
  if(data.market)traces.push({name:label(benchmarks,r.bench),data:data.marketCurve});
  chart(id+"-curve",traces);
  document.getElementById(id+"-legend").innerHTML=legend(traces.map(t=>t.name));
}

export function methods(){return '<details class="pf-details"><summary>计算口径</summary>'
    +note("PB 按总市值除以扣除其他权益工具后的净资产计算，单位为倍。历史值取自 Tushare 每日指标 daily_basic 的信号日截面。缺失、为零或负值均排除，每次使用当日记录。低 PB 对照中的各模型共用 60 个有效交易日的预热要求，按所选市场筛出同一批候选股，遇到同值按证券代码排序，实际成交和费用分别按各自交易记录计算。")
    +note("买入并持有只在各自区间首个交易日开盘尝试建仓，此后不调仓、不补买，期末按收盘价估值，不强制卖出。日频自定义按所选区间的所有交易日逐日估值，区间末不足一个完整调仓间隔也计算至最后一个交易日。按月、季、半年的预设只纳入从首个交易日开盘至当月末次收盘都落在区间内的月份。月末收盘选股，指定调仓月的首个交易日开盘执行。每季初为 1、4、7、10 月，每半年初为 1、7 月。每个区间从现金 100 起算，最后一期可截至最新收盘。按月估值的最大回撤可能低于日收盘回撤。")
    +note("自选名单按事前给定的股票模拟。用今天选的名单研究过去，会带入事后选择。TB 使用选定指数，以信号日及之前最近 120 个有效配对单日收益回归。无风险日利率取 0，截距估计日 α，正 α 除以残差方差后归一化。缺估计或非正分数的股票目标权重为零，所有分数均无效时目标为现金。只实现主动股票组合的仅做多配权。")
    +note("无有效开盘成交不下单。优先使用已入库的 Tushare 当日逐股涨跌停价。该接口始于 2007-01-04；更早、未归档或缺失的记录按前收盘的 5%、10%、20%、30% 保守估算，可能误拦正常交易。开在或越过上限不买、下限不卖；不使用当天稍后的最高、最低价决定开盘能否成交。卖不出的旧仓继续按可得价格估值；现金收益为零。成交额按单边费率扣费。持仓退市后的末价仅作账面估值，清偿款未知。回测采用连续权重，未模拟整手成交、滑点及排队。")+'</details>';}

export function showResult(container, heading, id, result, rules, {name,sector,chart,legend}){
  container.innerHTML=box(heading,resultHTML(id,result,rules,name,sector));
  bindLedger(id,result,rules);plotResult(id,result,rules,chart,legend);
}
export const readDate=input=>input.value.replaceAll("-","");
export function cadenceFields(value,days){
  return value==="hold"?{intervalUnit:"hold",interval:1}:value==="custom"?{intervalUnit:"days",interval:Number(days)}:{interval:Number(value)};
}
export function numberList(text){
  return text.trim()?text.trim().split(/[,，、;；\s]+/).filter(Boolean).map(Number):[];
}
