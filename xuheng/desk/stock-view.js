import {api,box,date,empty,esc,fmt,line,metric,note,pct,requireDay,select,table} from "./lab.js";
import {assessment,forwardStudy,relativeHistory,researchPrices,signalHistory,signalRating,simulateYear,valuationProfile,yearRisk} from "./stock-analysis.js";

const $=id=>document.getElementById(id);
const windows=[20,60,200], colors=["#176552","#b28c4a","#55769b","#a15341"];
const options={tab:"value",averages:new Set(windows),multiple:"pe"};
const tabs=[["value","历史估值位置"],["scenarios","一年收益情景"],["risk","回撤与市场联动"]];
const ratio=v=>Number.isFinite(v)?pct(v*100):"—";
const share=v=>Number.isFinite(v)?fmt(v*100,1)+"%":"—";
const simulationShare=v=>fmt(v*100,2)+"%";
const detail=(label,body)=>'<details class="research-detail"><summary>'+esc(label)+'</summary>'+body+'</details>';
const pairs=rows=>table(["项目","数据依据"],rows);
const metricRow=items=>'<div class="metrics research-metrics">'+items.join("")+'</div>';
const historyCache=new Map();

function valuations(code,day){
  const id=day+"/"+code;
  if(!historyCache.has(id)){
    const query=new URLSearchParams({symbol:code,asOf:day});
    const pending=api("/api/stock-valuation?"+query,100000).then(r=>{requireDay(r.day,day);return r;})
      .catch(err=>{if(historyCache.get(id)===pending)historyCache.delete(id);throw err;});
    historyCache.set(id,pending);
    if(historyCache.size>28)historyCache.delete(historyCache.keys().next().value);
  }
  return historyCache.get(id);
}

export function stockLayout(plot,yearControl,benchControl){
  const toggles=windows.map((n,i)=>'<label><input type="checkbox" data-ma="'+n+'" '+(options.averages.has(n)?"checked":"")+'><i style="background:'+colors[i+1]+'"></i>'+n+' 日均线</label>').join("");
  const price=box("价格与趋势",'<div class="research-ma"><span><i style="background:'+colors[0]+'"></i>收盘</span>'+toggles+'</div>'+plot);
  const verdict=box("研究结论",'<div id="research-verdict">'+empty("正在读取历史观测…")+'</div>'+
    '<section class="research-year"><h3>未来一年相对表现</h3><div class="controls">'+yearControl+'</div><div id="research-relative">'+empty("正在核对历史信号与基准…")+'</div></section><div id="research-levels"></div>'+
    detail("查看行情与基准依据",'<div id="stock-diagnosis"></div>'));
  const buttons=tabs.map(([id,label])=>'<button id="stock-tab-'+id+'" role="tab" aria-controls="stock-pane-'+id+'" data-stock-tab="'+id+'">'+label+'</button>').join("");
  const panels=tabs.map(([id,label])=>'<div id="stock-pane-'+id+'" class="stock-pane" role="tabpanel" aria-labelledby="stock-tab-'+id+'" hidden>'+
    (id==="risk"?'<div class="controls">'+benchControl+'</div><div id="research-risk"></div><h3>120 日滚动 Beta</h3><div id="stock-beta">'+empty("正在读取市场基准…")+'</div>':'<div id="research-'+id+'">'+empty("正在读取研究数据…")+'</div>')+'</div>').join("");
  return '<div class="stock-grid">'+price+verdict+'</div><section class="box stock-studies"><div class="stock-tabs" role="tablist" aria-label="个股研究明细">'+buttons+'</div>'+panels+'</section>';
}

function pp(v){
  if(!Number.isFinite(v))return "—";
  const rounded=Number((v*100).toFixed(2))||0;
  return (rounded>0?"+":"")+fmt(rounded)+" 个百分点";
}
const directionText=d=>d===1?"看多":d===-1?"看淡":"中性";
const badge=(value,d)=>'<strong class="research-badge" data-tone="'+(d===1?"positive":d===-1?"caution":"neutral")+'">'+esc(value)+'</strong>';
const summaryTable=(headers,rows)=>'<div class="signal-observations">'+table(headers,rows)+'</div>';

function signalEvidence(prices,result,history,sim,rating){
  const end=prices.end,[short,medium,long]=end.ma;
  const rows=[
    ["个股有效收盘",date(end.d)+" · "+fmt(end.close)+" 元"],
    ...[["收盘 / 20 日均线",end.adj,short],["20 / 60 日均线",short,medium],
      ["60 / 200 日均线",medium,long],["收盘 / 200 日均线",end.adj,long]]
      .map(([label,a,b])=>[label,fmt(a)+" / "+fmt(b)+" 元"]),
    ["趋势方向",fmt(result.trend,1)+" / 100。四项各 25 分，左侧高于右侧得满分，持平得半分。达到 62.5 分看多，37.5 分及以下看淡，其余中性。完整比较需要 200 个有效收盘。"],
    ["位置依据",result.basis?result.basis+" · 第 "+fmt(100*result.rank,1)+" 百分位 · "+date(result.from)+" 至 "+date(result.to)+"，"+result.n+(result.field?" 个月末":" 个有效收盘")+"。第 40 百分位及以下为低位，第 60 百分位及以上为高位。":"没有足够的历史位置样本。"],
    ["同类信号的一年实际收益",history.n?history.n+" 个月末，中位数 "+ratio(history.median)+"，"+history.wins+" 期为正，最多 "+history.nonoverlap+" 段互不重叠。":"尚无已走完一年的同类信号。"],
    ["一年模拟",sim?date(sim.start)+" 至 "+date(sim.end)+" 的 "+sim.observed+" 个有效日收益，连续五日成组重抽。"+fmt(Math.round(sim.win*sim.n),0)+" / "+fmt(sim.n,0)+" 条路径盈利，一年收益中位数 "+ratio(sim.quantiles[2])+"。":"需至少 252 个有效单日收益和 50 组连续五日样本。"],
    ["评级力度","看多且估值在低位，或看淡且估值在高位，再核对同类信号一年收益中位数与模拟中位数。两者都与趋势同向且历史至少有两段不重叠的一年，才升为强烈。价格位置可用于比较历史，强烈评级须有 PE 或 PB。"]
  ];
  let html=pairs(rows);
  if(rating.label&&result.direction!==0){
    const supports=ok=>ok?"支持":"未确认";
    html+=note("本期力度依据 · 估值"+supports(rating.valueSupports)+"，同类历史"+supports(rating.pastSupports)+"，模拟"+supports(rating.simulationSupports)+"。");
  }
  if(history.n)html+=detail("查看个股同类信号的全部观测",summaryTable(["信号月末","位置分位","趋势分","观察起点","一年后月末","个股收益"],
    history.rows.slice().reverse().map(r=>[date(r.signal),share(r.rank),fmt(r.trend,1),date(r.entry),date(r.exit),ratio(r.ret)])));
  return html;
}

function currentVerdict(prices,result,history,sim,rating,active,status){
  const end=prices.end;
  let html='<p class="research-stamp">诊断截至 '+date(end.d)+'</p>';
  if(!active)return html+badge(status==="D"?"已退市 · 历史回顾":"末次成交 · 历史回顾",0)+note("仅展示末次成交时的行情与历史指标。");
  html+='<h3 class="outlook-heading">当前判断 '+badge(rating.label||"趋势样本不足",result.direction)+'</h3>';
  if(!rating.label)return html+note("已有 "+prices.points.length+" 个连续可比的有效收盘，完整趋势判断需要 200 个。")+
    detail("查看当前判断依据",signalEvidence(prices,result,history,sim,rating));
  html+='<p>趋势 '+fmt(result.trend,1)+' 分。'+(result.basis?result.basis+"处于自身历史"+result.band+"（第 "+fmt(result.rank*100,1)+" 百分位）。":"估值历史不足。")+'</p>';
  html+=sim?'<p>一年模拟盈利占比 '+simulationShare(sim.win)+'，收益中位数 '+ratio(sim.quantiles[2])+'。</p>':note("有效收益历史尚不足以模拟一年。");
  const below=end.adj<end.ma[1];
  html+='<p class="research-review"><b>复评条件</b>　'+(below?"收盘重新站上":"收盘跌回")+' 60 日均线后复核趋势，当期均线 '+fmt(end.ma[1])+' 元。</p>';
  return html+detail("查看当前判断依据",signalEvidence(prices,result,history,sim,rating));
}

function levels(prices,result,rating){
  let html='<dl class="research-readings">';
  if(result.basis){
    const c=prices.end.close;
    html+='<dt>'+result.basis+'参考区间</dt><dd>'+fmt(result.low)+' – '+fmt(result.high)+' 元</dd><dt>收盘位置</dt><dd>'+
      (c<result.low?"低于下沿":c>result.high?"高于上沿":"位于区间内")+'</dd>';
  }
  html+='<dt>波动风险参考线</dt><dd>'+fmt(prices.stop)+(prices.stop===null?"":" 元")+'</dd><dt>模型参考仓位上限</dt><dd>'+share(rating.cap)+'</dd></dl>';
  return html+detail("查看区间与仓位依据",pairs([
    ["区间口径",result.field?"当日收盘 × 历史估值第 30 / 55 百分位 ÷ 同日估值，假设每股盈利或净资产不变。":"取历史可比收盘的第 30 / 55 百分位，数据不足时留空。"],
    ["位置与趋势评分",fmt(result.value,1)+" / "+fmt(result.trend,1)+"，两项等权均分 "+fmt(result.score,1)+"。当前方向取趋势分。"],
    ["风险参考线","收盘 "+fmt(prices.end.close)+" 元 − 2 × 最近 14 个成交日的平均真实波幅 "+fmt(prices.atr)+" 元。"],
    ["仓位规则","单股损失预算为净值的 0.5%，除以收盘至风险线的跌幅，再与评级上限取较低值。强烈看多 20%、看多 15%、中性 8%、看淡 5%、强烈看淡 0%。实际跳空可能超过预算。"]
  ]));
}

function yearVerdict(bench,relative,result,active,status){
  if(!active)return note(status==="D"?"该股已退市，一年期相对判断不适用。":"当期没有可核对的成交收盘，一年期相对判断暂停。");
  if(result.direction===null||!result.band)return note("当前缺少完整趋势或历史位置，无法匹配同类信号。");
  if(!bench||bench.state==="loading")return empty("正在读取所选基准的全收益序列…");
  if(bench.state==="error")return note(bench.reason)+'<button class="quiet" id="retry-year-bench">重读一年比较基准</button>';
  const dir=relative.direction;
  let label=dir===null?"可比历史不足":dir>0?"相对偏强":dir<0?"相对偏弱":"相对持平";
  let html=badge(label,dir)+' <span class="outlook-name">'+esc(bench.name)+'</span>';
  if(relative.n)html+='<p>同类信号 '+relative.n+' 期，'+relative.wins+' 期跑赢。个股减基准的一年收益差中位数为 <b>'+pp(relative.median)+'</b>。</p>';
  if(dir===null)html+=note("可用 "+relative.n+" 期，最多 "+relative.nonoverlap+" 段一年持有期互不重叠，方向判断需要至少两段。");
  const observations=relative.rows.slice().reverse().map(r=>[date(r.signal),date(r.entry),date(r.exit),ratio(r.ret),ratio(r.benchmark),pp(r.excess)]);
  return html+detail("查看一年相对判断依据",pairs([
    ["比较基准",esc(bench.name)+" · 全收益指数 "+esc(bench.code)+"，发布日期 "+date(bench.launch)+"。"],
    ["同类信号",result.basis+"位于同一档（"+result.band+"），趋势方向相同（"+directionText(result.direction)+"）。每个月末只使用当时及此前的数据。"],
    ["日期与收益","从信号月末的下一市场交易日收盘，到 12 个月后的月末收盘。两端均须有股票与基准报价，只统计已完整结束的月份。个股按除权参考前收盘衔接，基准使用全收益点位，均未扣交易费。"],
    ["判断规则","逐期计算个股收益减去同期基准收益，取中位数。正值偏强、负值偏弱，按 0.01 个百分点取整后为零列为持平。"],
    ["样本覆盖",relative.n?date(relative.rows[0].signal)+" 至 "+date(relative.rows.at(-1).signal)+"，最多 "+relative.nonoverlap+" 段互不重叠的一年。相邻月末的收益可能重叠。":"没有可配对且已走完一年的信号。"]
  ])+(relative.n?detail("查看全部 "+relative.n+" 期基准比较",summaryTable(["信号月末","观察起点","一年后月末","个股收益","基准收益","收益差"],observations)):""));
}

function histogram(sim){
  const {bins}=sim,largest=Math.max(...bins.map(b=>b.n)),lo=bins[0].lo,hi=bins.at(-1).hi;
  const zero=Math.min(100,Math.max(0,100*(-lo)/(hi-lo)));
  const columns=bins.map(b=>'<div class="hist-col" style="height:'+Math.max(0,b.n/largest*100)+'%;--bar:'+(b.hi<=1e-12?"#64897c":"#b97864")+'" title="'+esc(ratio(b.lo)+" 至 "+ratio(b.hi)+"，"+b.n+" 条路径")+'"></div>').join("");
  return '<figure class="histogram"><figcaption>一年末收益分布 · 2,000 条路径</figcaption><div class="hist-bars" role="img" aria-label="模拟收益直方图，亏损占 '+simulationShare(sim.loss)+'，盈利占 '+simulationShare(sim.win)+'">'+columns+
    '<span class="hist-zero" style="left:'+zero+'%"></span></div><div class="hist-axis"><span>'+ratio(lo)+'</span><span>虚线为零收益</span><span>'+ratio(hi)+'</span></div></figure>';
}
function scenarioPanel(sim,active,status){
  if(!active)return empty(status==="D"?"该股已退市，未来一年情景不适用。":"当期没有可核对的成交收盘，暂不生成未来一年情景。");
  if(!sim)return empty("一年情景至少需要 252 个有效单日收益和 50 组连续五日样本。");
  return metricRow([metric("模拟盈利占比",simulationShare(sim.win),"一年末高于期初"),metric("收益中位数",ratio(sim.quantiles[2]),"第 50 百分位"),metric("严重回撤情景",ratio(sim.dd),"路径最大回撤的第 5 百分位")])+
    histogram(sim)+table(["一年末情景","偏弱 P5","P25","中位 P50","P75","偏强 P95"],[["模拟收益",...sim.quantiles.map(ratio)]])+
    detail("查看模拟依据",note(date(sim.start)+" 至 "+date(sim.end)+"，最近最多 756 个市场交易日中有 "+sim.observed+" 个有效单日收益。抽取实际连续的五日收益块（"+sim.blocks+" 个可用起点），有放回拼成 252 日路径。每条路径从净值 1 开始计算回撤。相同股票和日期的模拟可复现。")+
      note("正收益占比为 "+fmt(sim.win*sim.n,0)+" / "+fmt(sim.n,0)+"。模拟沿用这段历史的收益特征，未计未来交易费用。"));
}

export function stockResearch({row,day,current,chart,range}){
  let prices,profile,result,risk,market,scenario,bench,history,rating;
  let active=false,complete=false,valueError="",editionDay=null;
  const quote={d:day,close:row[9],pe:row[12],pb:row[13]};
  function showRelative(){
    if(!current()||!complete||!result)return;
    const relative=active&&bench?.state==="ready"?relativeHistory(history,bench.bars,bench.launch):null;
    $("research-relative").innerHTML=yearVerdict(bench,relative,result,active,row[5]);
    const retry=$("retry-year-bench");
    if(retry)retry.onclick=bench.retry;
  }
  function drawPrice(){
    if(!prices?.end)return;
    const visible=prices.points.filter(p=>p.d>=range());
    if(!visible.length){$("security-plot").innerHTML=empty("所选区间没有可比的成交收盘。");return;}
    const traces=[{name:"可比收盘",color:colors[0],data:visible.map(p=>[p.d,p.adj])}];
    windows.forEach((n,i)=>{if(options.averages.has(n))traces.push({name:n+" 日均线",color:colors[i+1],
      data:visible.filter(p=>Number.isFinite(p.ma[i])).map(p=>[p.d,p.ma[i]])});});
    const band=result?.basis?[result.low,result.high]:null;
    chart("sec-chart",traces,{band,reference:prices.stop});
    $("sec-legend").innerHTML=note("曲线按除权参考前收盘衔接，以末次成交收盘为锚。"+
      (band?"浅绿色带为 "+date(prices.end.d)+" 的 "+result.basis+"参考区间。":"")+
      (prices.stop!==null?"红色虚线为当期风险参考线。":""));
  }
  function valuePanel(){
    const dst=$("research-value");
    if(valueError){dst.innerHTML=empty(valueError)+'<button class="quiet" id="retry-stock-values">重读估值</button>';$("retry-stock-values").onclick=loadValues;return;}
    if(!complete||!profile){dst.innerHTML=empty("正在读取该股月末估值…");return;}
    const f=options.multiple, label=f==="pe"?"滚动市盈率 PE":"市净率 PB", v=profile.metrics[f];
    dst.innerHTML='<div class="controls">'+select("stock-multiple","估值指标",[["pe","滚动市盈率 PE"],["pb","市净率 PB"]],f)+'</div>'+
      metricRow([metric("同日"+(f==="pe"?" PE":" PB"),fmt(v.value),date(profile.d)),metric("自身历史分位",share(v.position),v.n+" 个正值月末样本")])+
      (v.series.length?line("stock-multiple-chart"):empty("缺少有效的月末估值历史。"))+
      note("比较窗口为当月之前的 60 个自然月，至少 24 个正值月末才计算分位。行情与估值按同一交易日匹配，月末研究库截至 "+date(editionDay)+"。")+
      '<h3>相似估值后 12 个月的实际收益</h3><div id="stock-forward"></div>';
    $("stock-multiple").onchange=e=>{options.multiple=e.target.value;valuePanel();$("stock-multiple").focus({preventScroll:true});};
    if(v.series.length){const data=[...v.series];if(v.value>0)data.push([profile.d,v.value]);chart("stock-multiple-chart",[{name:label,data}]);}
    const study=forwardStudy(prices,profile,f);
    $("stock-forward").innerHTML=(study.n>=12?metricRow([metric("历史月份",fmt(study.n,0)),metric("后续收益中位数",ratio(study.median)),metric("取得正收益的月份",share(study.win))]):
      empty("有 "+study.n+" 个已走完随后 12 个月的相似观测，满 12 个月份后展示统计。"))+
      detail("查看历史比较依据",note("每个月末只使用此前 60 个月内的正估值记录计算当时的分位，选取与当期相差不超过 10 个百分点的月份。起点和一年后的月末都须有个股成交收盘，目标月份必须完整结束。相邻持有期可能重叠。")+
        (study.n?table(["观察月末","当时分位","一年后月末","实际收益"],study.rows.slice(-12).reverse().map(r=>[date(r.from),share(r.rank),date(r.to),ratio(r.ret)])):""));
  }
  function riskPanel(){
    const target=$("research-risk"), beta=market?.beta?.latest;
    if(!prices||!target)return;
    target.innerHTML=metricRow([metric("年化波动率",ratio(risk?.vol),risk?risk.n+" 对有效单日观测":"历史不足一年"),metric("近一年最大回撤",ratio(risk?.worst),risk?.worst<0?date(risk.peak)+" → "+date(risk.trough):"窗口内高点至低点"),
      metric("120 日相关系数",fmt(beta?.correlation,3),market?.name||"等待读取基准")])+
      (risk?line("stock-drawdown")+note("近 252 个市场交易日。回撤自窗口起点重新累计，范围 "+date(risk.start)+" 至 "+date(risk.end)+"。"):empty("完整的一年回撤需覆盖 252 个市场交易日及期初收盘。"))+
      detail("查看风险与相关性依据",note("波动率为同一市场交易日的个股日收益样本标准差 × √252，至少使用 120 个有效日。停牌和跨日复牌不参与单日估计。相关系数和 Beta 使用所选基准同一组 120 对收益。")+
        (beta?note("配对区间 "+date(beta.start)+" 至 "+date(beta.end)+"。Beta 衡量对基准的敏感度，相关系数衡量同步程度。"):note("基准样本不足或仍在读取。")));
    if(risk)chart("stock-drawdown",[{name:"回撤（%）",data:risk.curve}]);
  }
  function display(){
    if(!current())return;
    tabs.forEach(([id])=>{
      const selected=id===options.tab,b=$("stock-tab-"+id);b.setAttribute("aria-selected",String(selected));b.tabIndex=selected?0:-1;
      $("stock-pane-"+id).hidden=!selected;
    });
    if(!prices?.end)return;
    if(options.tab==="value")valuePanel();
    if(options.tab==="risk")riskPanel();
    if(options.tab==="scenarios")$("research-scenarios").innerHTML=scenarioPanel(scenario,active,row[5]);
  }
  function selectTab(id){options.tab=id;display();}
  tabs.forEach(([id],i)=>{
    const b=$("stock-tab-"+id);
    b.onclick=()=>selectTab(id);
    b.onkeydown=e=>{
      const which={ArrowLeft:(i+2)%3,ArrowRight:(i+1)%3,Home:0,End:2}[e.key];
      if(which!==undefined){e.preventDefault();const next=tabs[which][0];selectTab(next);$("stock-tab-"+next).focus();}
    };
  });
  document.querySelectorAll("[data-ma]").forEach(input=>input.onchange=()=>{
    const n=Number(input.dataset.ma);if(input.checked)options.averages.add(n);else options.averages.delete(n);drawPrice();
  });
  function unavailable(reason){
    if(!current())return;
    for(const id of ["research-verdict","research-relative","research-value","research-scenarios","research-risk"])$(id).innerHTML=empty(reason);
    $("research-levels").replaceChildren();
  }
  async function loadValues(){
    if(!current()||!prices?.end)return;
    valueError="";complete=false;$("research-relative").innerHTML=empty("正在核对同类信号…");
    if(options.tab==="value")valuePanel();
    try{
      const data=await valuations(row[0],day);
      if(!current())return;
      editionDay=data.edition;profile=valuationProfile(prices,data.rows,quote);
    }catch(err){
      if(!current())return;
      profile=valuationProfile(prices,[],quote);valueError=err.message||"暂时无法读取历史估值。";
    }
    complete=true;result=assessment(prices,profile);
    history=signalHistory(prices,profile,result);
    rating=signalRating(result,history,scenario,prices,active);
    $("research-verdict").innerHTML=currentVerdict(prices,result,history,scenario,rating,active,row[5])+
      (valueError?note("月末估值暂不可用。可在「历史估值位置」重读。"):"");
    $("research-levels").innerHTML=levels(prices,result,rating);
    showRelative();drawPrice();display();
  }
  display();
  return {
    prices(bars,calendar){
      const first=[row[6]||"20000101",row[0].endsWith(".BJ")?"20211115":"20000101"].sort().at(-1);
      const last=row[7]||day;
      prices=researchPrices(bars.filter(b=>{const d=b.day.replaceAll("-","");return d>=first&&d<=last;}),calendar);
      if(!prices.end){unavailable("没有可用于诊断的有效成交日。");return;}
      active=row[5]==="L"&&prices.end.d===day&&Number.isFinite(quote.close)&&Math.abs(quote.close-prices.end.close)<0.005;
      scenario=active?simulateYear(prices,row[0]):null;
      risk=yearRisk(prices);drawPrice();display();loadValues();
    },
    benchmark(next){
      bench=next;
      if(!complete&&current())$("research-relative").innerHTML=empty("正在核对同类信号与所选基准…");
      showRelative();
    },
    market(next){market=next;if(options.tab==="risk")riskPanel();},
    unavailable
  };
}
