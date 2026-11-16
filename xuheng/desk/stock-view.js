import {api,box,date,empty,esc,fmt,line,metric,note,pct,requireDay,select,table} from "./lab.js";
import {assessment,forwardStudy,researchPrices,simulateYear,valuationProfile,yearRisk} from "./stock-analysis.js";

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

export function stockLayout(plot,benchControl){
  const toggles=windows.map((n,i)=>'<label><input type="checkbox" data-ma="'+n+'" '+(options.averages.has(n)?"checked":"")+'><i style="background:'+colors[i+1]+'"></i>'+n+' 日均线</label>').join("");
  const price=box("价格与趋势",'<div class="research-ma"><span><i style="background:'+colors[0]+'"></i>收盘</span>'+toggles+'</div>'+plot);
  const verdict=box("研究结论",'<div id="research-verdict">'+empty("正在读取历史观测…")+'</div>'+
    detail("查看行情与基准依据",'<div id="stock-diagnosis"></div>'));
  const buttons=tabs.map(([id,label])=>'<button id="stock-tab-'+id+'" role="tab" aria-controls="stock-pane-'+id+'" data-stock-tab="'+id+'">'+label+'</button>').join("");
  const panels=tabs.map(([id,label])=>'<div id="stock-pane-'+id+'" class="stock-pane" role="tabpanel" aria-labelledby="stock-tab-'+id+'" hidden>'+
    (id==="risk"?'<div class="controls">'+benchControl+'</div><div id="research-risk"></div><h3>120 日滚动 Beta</h3><div id="stock-beta">'+empty("正在读取市场基准…")+'</div>':'<div id="research-'+id+'">'+empty("正在读取研究数据…")+'</div>')+'</div>').join("");
  return '<div class="stock-grid">'+price+verdict+'</div><section class="box stock-studies"><div class="stock-tabs" role="tablist" aria-label="个股研究明细">'+buttons+'</div>'+panels+'</section>';
}

function researchVerdict(prices,result,active,status){
  const end=prices.end;
  if(!end)return empty("缺少有效成交日，无法评级。");
  const m=result.model;
  const label=active?(m?.[0]||"样本不足"):(status==="D"?"已退市 · 历史回顾":"末次成交 · 历史回顾");
  let html='<p class="research-stamp">诊断截至 '+esc(date(end.d))+'</p><strong class="research-badge" data-tone="'+
      (m?.[0]==="暂时回避"?"caution":m?.[0]==="积极配置"?"positive":"neutral")+'">'+esc(label)+'</strong>';
  if(m){
    const above=end.ma.filter(v=>end.adj>v).length;
    html+='<p>'+esc(m[2])+' '+esc(result.basis)+'处于自身第 '+fmt(result.rank*100,1)+' 百分位，收盘高于三条均线中的 '+above+' 条。</p>';
    const review=end.adj<end.ma[1]&&["积极配置","趋势持有"].includes(m[0])
      ?"收盘已低于 60 日均线，关注能否重新站上，以及短期均线是否继续走弱。":m[3];
    html+='<p><b>复评条件</b>　'+esc(review)+' 本期 60 日均线为 '+fmt(end.ma[1])+' 元。</p>';
  }
  else html+=note(active?"趋势至少需要 200 个有效成交收盘，位置需要可核验的历史样本。":"仅展示最后可核验的历史观测。");
  if(result.basis){
    html+='<dl class="research-readings"><dt>'+result.basis+'参考区间</dt><dd>'+fmt(result.low)+' – '+fmt(result.high)+' 元</dd>';
    const band=end.close<result.low?"低于下沿":end.close>result.high?"高于上沿":"位于区间内";
    html+='<dt>收盘位置</dt><dd>'+band+'</dd></dl>';
  }
  html+='<dl class="research-readings"><dt>波动风险参考线</dt><dd>'+fmt(prices.stop)+(prices.stop===null?"":" 元")+'</dd>'+
    '<dt>综合评分</dt><dd>'+fmt(result.score,1)+(result.score===null?"":" / 100")+'</dd>'+
    '<dt>模型参考仓位上限</dt><dd>'+share(result.cap)+'</dd></dl>';
  const mt=end.ma.map(v=>fmt(v)).join(" / ");
  const evidence=[
    ["数据日期",date(end.d)+" · 收盘 "+fmt(end.close)+" 元"],
    ["历史位置",result.basis?result.basis+" · 第 "+fmt(100*result.rank,1)+" 百分位 · "+date(result.from)+" 至 "+date(result.to)+"，"+result.n+(result.field?" 个月末":" 个收盘"):"可比观测不足"],
    ["区间口径",result.field?"当日收盘价 × 历史估值第 30 / 55 百分位 ÷ 同日估值倍数，假设每股盈利或净资产不变。":"历史可比收盘价的第 30 / 55 百分位，仅衡量价格位置。"],
    ["20 / 60 / 200 日均线",mt+" 元，均线使用截至诊断日的可比价格"],
    ["位置分 / 趋势分",fmt(result.value,1)+" / "+fmt(result.trend,1)+"。位置分 = 100 − 历史百分位，综合分取两项等权平均。"],
    ["趋势规则","收盘高于 MA20、MA20 高于 MA60、MA60 高于 MA200、收盘高于 MA200，各占 25 分，相等记半分。"],
    ["评级规则","位置分 ≥60 且趋势分 ≥62.5 为积极配置，位置分 ≥60 且趋势较弱为等待企稳。其余趋势分 ≥62.5 为趋势持有，位置分 ≤40 且趋势分 ≤25 为暂时回避，其余为审慎观察。"],
    ["风险与仓位","14 个成交日平均真实波幅 "+fmt(prices.atr)+" 元。参考线 = 当日收盘 − 2 倍波幅，仅适用于该观察日。"],
    ["模型假设","单股损失预算为模型净值的 0.5%。按预算除以收盘至风险线的跌幅，再取评级上限，依次为积极配置 20%、趋势持有 15%、等待企稳 5%、审慎观察 8%、暂时回避 0%。实际跳空可能超过预算。"],
  ];
  return html+detail("查看评分、区间与仓位依据",pairs(evidence));
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
  let prices,profile,result,risk,market,scenario,active=false,complete=false,valueError="",editionDay=null;
  const quote={d:day,close:row[9],pe:row[12],pb:row[13]};
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
    if(options.tab==="scenarios"){
      if(active&&scenario===undefined)scenario=simulateYear(prices,row[0]);
      $("research-scenarios").innerHTML=scenarioPanel(scenario,active,row[5]);
    }
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
    for(const id of ["research-verdict","research-value","research-scenarios","research-risk"])$(id).innerHTML=empty(reason);
  }
  async function loadValues(){
    if(!current()||!prices?.end)return;
    valueError="";complete=false;if(options.tab==="value")valuePanel();
    try{
      const data=await valuations(row[0],day);
      if(!current())return;
      editionDay=data.edition;profile=valuationProfile(prices,data.rows,quote);
    }catch(err){
      if(!current())return;
      profile=valuationProfile(prices,[],quote);valueError=err.message||"暂时无法读取历史估值。";
    }
    complete=true;result=assessment(prices,profile,active);
    $("research-verdict").innerHTML=researchVerdict(prices,result,active,row[5])+(valueError?note("估值读取失败，本次仅按有依据的价格位置评估。"):"");
    drawPrice();display();
  }
  display();
  return {
    prices(bars,calendar){
      const first=[row[6]||"20000101",row[0].endsWith(".BJ")?"20211115":"20000101"].sort().at(-1);
      const last=row[7]||day;
      prices=researchPrices(bars.filter(b=>{const d=b.day.replaceAll("-","");return d>=first&&d<=last;}),calendar);
      if(!prices.end){unavailable("没有可用于诊断的有效成交日。");return;}
      active=row[5]==="L"&&prices.end.d===day&&Number.isFinite(quote.close)&&Math.abs(quote.close-prices.end.close)<0.005;
      risk=yearRisk(prices);drawPrice();display();loadValues();
    },
    market(next){market=next;if(options.tab==="risk")riskPanel();},
    unavailable
  };
}
