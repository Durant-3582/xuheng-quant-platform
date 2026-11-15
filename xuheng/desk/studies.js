import {api, box, date, empty, esc, fmt, line, metric, note, pager, pct, select, signed, table, title} from "./lab.js";
import {navigate} from "./navigation.js";
import {loadPlotly} from "./news-charts.js";

const el=id=>document.getElementById(id);
const factors={mom:"60 日动量",vol:"20 日低波动",pb:"低市净率",roe:"最近年报 ROE",pe:"低滚动市盈率",turn:"当日高换手"};
const markets=[["","全 A 股"],["SH","沪市"],["SZ","深市"],["BJ","北交所"]];
const defaults={mom:25,vol:0,pb:40,roe:35,pe:0,turn:0};
const multi={weights:{...defaults},venue:"",page:0};
const screen={minROE:10,maxDebt:70,sort:"revenue",period:"",venue:"",page:0};
const test={rule:"mom",venue:"",from:"",to:""};
const rot={from:"",to:"",top:5,fee:10,timing:true};
let selectedStock="",autoReport="",screenResults=null,multiResults=null,testResults=null,rotationResults=null;
let stamp="",metaTask;
const action=(id,label)=>'<button type="submit" class="act" id="'+id+'">'+esc(label)+'</button>';
const field=(id,label,value,attrs="")=>'<label>'+esc(label)+' <input required id="'+id+'" value="'+esc(value)+'" '+attrs+'></label>';
const error=e=>'<p class="error" role="alert">'+esc(e?.message||String(e))+'</p>';
const clean=s=>s.replaceAll("-","");
const key=o=>JSON.stringify(o);
const sum=w=>Object.values(w).reduce((s,x)=>s+x,0);
const currentRule=w=>Object.entries(w).filter(([,v])=>v>0).map(([k,v])=>factors[k]+" "+v+"%").join(" · ");
const makeRequest=(env,body)=>api("/api/studies",120000,{body:JSON.stringify({...body,asOf:env.day})});
function metadata(env) {
  if(stamp!==env.day){
    stamp=env.day;metaTask=null;screenResults=multiResults=testResults=rotationResults=null;
  }
  if(!metaTask)metaTask=makeRequest(env,{action:"meta"}).catch(e=>{metaTask=null;throw e;});
  return metaTask;
}
const tabs=[["factors","单因子选股"],["factors/multi","多因子选股"],["factors/test","因子检验"]];
export function factorTabs(active) {
  return '<div class="pf-tabs" role="navigation" aria-label="选股研究">'+tabs.map(([r,t])=>'<a href="#'+r+'" '+(r===active?'aria-current="page"':'')+'>'+t+'</a>').join("")+'</div>';
}
export function setSingleTest(k,venue) {
  test.rule=k;test.venue=venue;testResults=null;navigate("factors/test");
}
export function showReportsOnArrival(code) {
  const show=code===autoReport;autoReport="";return show;
}
function cutoffNote(res,env) {
  return note("研究数据截至 "+date(res.cutoff)+(env.day!==res.cutoff?"；行情库已更新至 "+date(env.day):"")+"。");
}
function bindPages(root,fn) {
  root.querySelectorAll("button[data-pager]").forEach(b=>b.onclick=()=>fn(Number(b.dataset.delta)));
}
function bindRetry(root,e,retry){
  root.innerHTML=error(e)+'<button class="quiet" type="button">重新读取</button>';
  root.querySelector("button").onclick=retry;
}
function selectStock(root) {
  root.querySelectorAll("a.sym").forEach(a=>a.addEventListener("click",e=>{
    if(e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
    autoReport=(a.dataset.deskRoute||a.getAttribute("href").replace(/^#/,"")).split("/").pop();
  }));
}

export async function financialReports(env,code,root,button) {
  button.disabled=true;
  root.innerHTML=empty("正在读取已披露财报…");
  try {
    const res=await makeRequest(env,{action:"reports",code});
    if(!env.current()||!root.isConnected)return;
    if(!res.rows.length){root.innerHTML=empty("数据源在该证券的已核查区间内没有返回财报。");return;}
    const rows=res.rows;
    const names=["ROE（累计）","营业总收入同比","归母净利润同比"];
    root.innerHTML=cutoffNote(res,env)+'<h3>最近 '+rows.length+' 个已披露报告期</h3><div id="fin-plot" class="study-plot"></div>'+
      note("ROE 使用年初至报告期末的累计值，一季报与年报的累计时长不同。同比均与上年同一报告期比较。")+
      table(["报告期","公告日","每股收益（元）","ROE","毛利率","资产负债率","营业总收入同比","归母净利润同比"],
        rows.map(r=>[date(r[0]),date(r[1]),fmt(r[2]),pct(r[3]),pct(r[4]),pct(r[5]),pct(r[6]),pct(r[7])]));
    const node=el("fin-plot"),plotly=await loadPlotly();
    if(!env.current()||!node?.isConnected)return;
    const ordered=[...rows].reverse();
    await plotly.newPlot(node,[3,6,7].map((col,i)=>({type:"scatter",mode:"lines+markers",name:names[i],
      x:ordered.map(r=>date(r[0])),y:ordered.map(r=>r[col]),connectgaps:false,
      line:{color:["#176552","#a47d3e","#6678a2"][i]},hovertemplate:"%{x|%Y-%m-%d} · %{y:.2f}%<extra>%{fullData.name}</extra>"})),
      {autosize:true,height:265,margin:{l:52,r:15,t:12,b:38},legend:{orientation:"h",y:1.17},xaxis:{type:"date",tickformat:"%Y-%m"},yaxis:{ticksuffix:"%",gridcolor:"#e2e8e2"}},
      {responsive:true,displayModeBar:false});
  } catch(e){if(env.current()&&root.isConnected)bindRetry(root,e,()=>financialReports(env,code,root,button));}
  finally{if(root.isConnected)button.disabled=false;}
}

export function financeLink(code){
  selectedStock=code;
  return '<a class="link-btn" href="#stocks/screen">按财务条件筛选 →</a>';
}

async function setup(env,heading,fn) {
  const {panel}=env;
  panel.innerHTML=heading+'<div id="study-main">'+empty("正在读取研究数据…")+'</div>';
  const root=el("study-main");
  try {
    const meta=await metadata(env);
    if(env.current()&&root.isConnected)await fn(root,meta);
  } catch(e){if(env.current()&&root.isConnected)bindRetry(root,e,()=>setup(env,heading,fn));}
}

export function financialScreen(env) {
  const head=title("财务条件选股","在有当日报价的沪深北 A 股中，按已披露财报筛选公司。")+
    '<a class="link-btn" href="#stocks'+(selectedStock?"/"+esc(selectedStock):"")+'">← 个股研究</a>';
  return setup(env,head,async(root,meta)=>{
    if(!screen.period||(screen.period!=="latest"&&!meta.periods.includes(screen.period)))screen.period=meta.defaultPeriod;
    root.innerHTML=box("筛选条件",'<form id="fin-form" class="controls study-form">'+
      select("fin-period","报告期",[["latest","各公司最近已披露"],...meta.periods.map(d=>[d,date(d)])],screen.period)+
      select("fin-venue","市场",markets,screen.venue)+field("fin-roe","ROE 下限（%）",screen.minROE,'type="number" step="any"')+
      field("fin-debt","负债率上限（%）",screen.maxDebt,'type="number" min="0" max="1000" step="any"')+
      select("fin-sort","排序",[["revenue","营业总收入同比 · 高到低"],["profit","归母净利润同比 · 高到低"],["roe","ROE · 高到低"],["gross","毛利率 · 高到低"],["pe","正 PE · 低到高"],["debt","负债率 · 低到高"]],screen.sort)+
      action("fin-run","筛选股票")+'</form>'+note("默认使用最多在市公司最近披露的报告期，便于横向比较累计 ROE。缺少所用字段的公司不参加本次筛选；PE 取研究截止日。"))+'<div id="fin-output"></div>';
    const form=el("fin-form"),out=el("fin-output");
    let seq=0;
    function inputs(){
      Object.assign(screen,{period:el("fin-period").value,venue:el("fin-venue").value,minROE:el("fin-roe").valueAsNumber,
        maxDebt:el("fin-debt").valueAsNumber,sort:el("fin-sort").value});
    }
    async function run(){
      const ticket=++seq;
      if(!form.reportValidity())return;
      inputs();const payload={action:"screen",...screen},id=key(payload);
      out.innerHTML=empty("正在筛选…");
      try{
        const res=screenResults?.id===id?screenResults.res:await makeRequest(env,payload);
        if(ticket!==seq||!env.current())return;
        screenResults={id,res};screen.page=res.page;
        out.innerHTML=box("入选公司",cutoffNote(res,env)+note("股票池 "+fmt(res.pool,0)+" 只，筛选和排序字段齐备 "+fmt(res.available,0)+" 只，符合条件 "+fmt(res.total,0)+" 只。")+
          table(["股票","报告期","公告日","ROE","负债率","毛利率","营收同比","归母净利润同比","滚动 PE"],res.rows.map(([c,r])=>[env.symbol(c),date(r[0]),date(r[1]),pct(r[3]),pct(r[5]),pct(r[4]),pct(r[6]),pct(r[7]),fmt(r[8])]))+pager("financial",res.page,res.total,25));
        selectStock(out);bindPages(out,delta=>{screen.page+=delta;run();});
      }catch(e){if(env.current()&&ticket===seq)bindRetry(out,e,run);}
    }
    form.oninput=()=>{seq++;screen.page=0;out.innerHTML=note("条件已更改，点击「筛选股票」更新结果。");};
    form.onsubmit=e=>{e.preventDefault();screen.page=0;run();};
    await run();
  });
}

export function multiPage(env) {
  const head=title("因子选股","按信号日可用数据计算因子排名。")+factorTabs("factors/multi");
  return setup(env,head,async(root,meta)=>{
    root.innerHTML=box("多因子配分",'<form id="mix-form"><div class="controls">'+select("mix-venue","股票池",markets,multi.venue)+'</div>'+
      '<div class="study-weights">'+Object.keys(factors).map(k=>field("w-"+k,factors[k]+"（%）",multi.weights[k],'type="number" min="0" max="100" step="0.01"')).join("")+'</div>'+
      '<div class="controls">'+action("mix-run","计算排名")+'<button type="button" class="quiet" id="mix-reset">恢复默认权重</button><span id="mix-sum"></span></div></form>'+
      note("先取所选因子均有数据的股票，再在同一股票池内计算百分位。低估值和低波动按低值优先，其余按高值优先。总分为各项百分位的加权平均；权重为零的因子不影响入选。质量使用最近已披露且距信号日不超过 18 个月的年报 ROE。"))+'<div id="mix-output"></div>';
    const form=el("mix-form"),out=el("mix-output");
    let seq=0;
    function inputs(){
      multi.venue=el("mix-venue").value;
      multi.weights=Object.fromEntries(Object.keys(factors).map(k=>[k,el("w-"+k).valueAsNumber]));
      const total=sum(multi.weights);
      const valid=form.checkValidity()&&Number.isFinite(total)&&Math.abs(total-100)<0.005;
      el("mix-sum").textContent=(Number.isFinite(total)?"合计 "+fmt(total,2)+"%":"请填写所有权重")+(valid?"":" · 合计须为 100%");
      el("mix-run").disabled=!valid;
      return valid;
    }
    async function run(){
      if(!inputs())return;
      const ticket=++seq,payload={action:"rank",...multi},id=key(payload);
      out.innerHTML=empty("正在计算全股票池排名…");
      try{
        const res=multiResults?.id===id?multiResults.res:await makeRequest(env,payload);
        if(ticket!==seq||!env.current())return;
        multiResults={id,res};multi.page=res.page;
        out.innerHTML=box("综合排名",cutoffNote(res,env)+note("股票池 "+fmt(res.pool,0)+" 只，所选因子齐备 "+fmt(res.total,0)+" 只。综合分满分 100，同分按证券代码排列。")+
          table(["排名","股票","综合分","配分依据"],res.rows.map(([c,score,vals,parts,annual],i)=>[res.page*25+i+1,env.symbol(c),fmt(score,3),
            '<details><summary>查看分项</summary>'+table(["因子","原值","百分位分","贡献分"],res.keys.map((k,j)=>[factors[k],fmt(vals[j])+(["pb","pe"].includes(k)?" 倍":"%"),fmt(parts[j]),fmt(parts[j]*multi.weights[k]/100)]))+
            (annual?note("ROE 取自 "+date(annual[0])+" 年报，公告日 "+date(annual[1])+"。"):"")+'</details>']))+
          pager("multi",res.page,res.total,25),'<button type="button" class="quiet" id="mix-test">检验当前规则 →</button>');
        el("mix-test").onclick=()=>{test.rule="multi";test.venue=multi.venue;testResults=null;navigate("factors/test");};
        bindPages(out,delta=>{multi.page+=delta;run();});
      }catch(e){if(ticket===seq&&env.current())bindRetry(out,e,run);}
    }
    function dirty(){seq++;multi.page=0;inputs();out.innerHTML=note("配分已更改，点击「计算排名」更新结果。");}
    form.oninput=dirty;
    form.onsubmit=e=>{e.preventDefault();multi.page=0;run();};
    el("mix-reset").onclick=()=>{for(const [k,v] of Object.entries(defaults))el("w-"+k).value=v;dirty();};
    await run();
  });
}

const dateInput=(id,label,value,min,max)=>field(id,label,date(value),'type="date" min="'+date(min)+'" max="'+date(max)+'"');
function testWeights(){
  return test.rule==="multi"?multi.weights:Object.fromEntries(Object.keys(factors).map(k=>[k,k===test.rule?100:0]));
}
export function testPage(env) {
  const head=title("因子选股","比较月末因子排名与随后一个完整持有月的表现。")+factorTabs("factors/test");
  return setup(env,head,async(root,meta)=>{
    test.from||=String(Number(meta.cutoff.slice(0,4))-3)+"0101";test.to||=meta.cutoff;
    root.innerHTML=box("检验条件",'<form id="ic-form" class="controls">'+select("ic-rule","规则",[["multi","当前多因子配分"],...Object.entries(factors)],test.rule)+
      select("ic-venue","股票池",markets,test.venue)+dateInput("ic-from","自",test.from,"20000101",meta.cutoff)+dateInput("ic-to","至",test.to,"20000101",meta.cutoff)+
      action("ic-run","运行因子检验")+'</form><p class="note" id="ic-weights"></p>')+'<div id="ic-output"></div>';
    const form=el("ic-form"),out=el("ic-output");let seq=0;
    function inputs(){
      Object.assign(test,{rule:el("ic-rule").value,venue:el("ic-venue").value,from:clean(el("ic-from").value),to:clean(el("ic-to").value)});
      const w=testWeights();
      el("ic-weights").textContent=currentRule(w);
      const valid=Number.isFinite(sum(w)) && Math.abs(sum(w)-100)<0.005 && Object.values(w).every(v=>v>=0&&v<=100);
      el("ic-run").disabled=!valid;
      if(!valid)el("ic-weights").textContent+=" · 请先在多因子页将权重合计设为 100%。";
    }
    async function run(){
      if(!form.reportValidity())return;
      inputs();
      if(test.from>test.to){out.innerHTML=error("起始日期须早于或等于结束日期。");return;}
      const ticket=++seq,payload={action:"test",from:test.from,to:test.to,venue:test.venue,weights:testWeights()},id=key(payload);
      out.innerHTML=empty("正在逐月检验排名与后续收益…");
      try{
        const res=testResults?.id===id?testResults.res:await makeRequest(env,payload);
        if(ticket!==seq||!env.current())return;
        testResults={id,res};const s=res.summary;
        if(!s.months){out.innerHTML=empty("此区间没有完整且可分为五组的持有月。可扩大日期区间或更换股票池。");return;}
        out.innerHTML='<div class="metrics">'+metric("平均 Rank IC",fmt(s.meanIC,3))+metric("IC 为正的月份",pct(s.positive))+
          metric("有效 IC 月数",fmt(s.nIC,0))+metric("配对股票月数",fmt(s.pairs,0))+'</div>'+
          box("五组持有期收益",table(["组别","等权组合收益","组内股票收益中位数"],s.groups.map((v,i)=>[i===0?"第 1 组 · 得分最高":i===4?"第 5 组 · 得分最低":"第 "+(i+1)+" 组",signed(v),signed(s.medians[i])]))+
          note("月末按得分分为人数相近的五组，次月首个交易日开盘建仓。无法买入的份额留现金，期末缺报价沿用最后估值。两列收益分别逐月计算，再取各月算术平均，均未扣费。早期缺少官方涨跌停价时，用开盘价和前收盘价估算成交限制。"))+
          box("逐年检验",table(["年份","分组月数","有效 IC 月数","平均 Rank IC","IC 为正占比"],res.annual.map(([y,a])=>[y,a.months,a.nIC,fmt(a.meanIC,3),pct(a.positive)]))+
          note("Rank IC 为因子得分与下月开盘至月末收盘收益的秩相关系数。只用有首日开盘和月末收盘的配对股票；两组排名任一没有差异时，该月不计 IC。每个月权重相同。"))+
          box("信号能持续多久",'<details><summary>比较第 1、2、3、6 个月的 Rank IC</summary>'+
            note("固定最初的因子得分，分别与随后第 1、2、3、6 个月的单月收益做秩相关。每月收益从该月首日开盘计至月末收盘，只使用所选区间内已经结束的月份。")+
            table(["信号后第几个月","有效月数","平均 Rank IC","配对股票月数"],res.persistence.map(([h,n,v,p])=>[h,n,fmt(v,3),fmt(p,0)]))+'</details>')+
          box("因子之间的相关性",'<details><summary>查看六个因子的两两秩相关</summary>'+
            note("用六项均有有效值的同一批股票，先统一选股方向，再计算每月横截面秩相关，最后逐月等权平均。接近 +1 表示两项倾向选到相同的股票。共同样本共 "+fmt(res.commonPairs,0)+" 个股票月。")+
            table(["因子一","因子二","平均秩相关","有效月数"],res.overlap.map(([a,b,v,n])=>[factors[a],factors[b],fmt(v,3),n]))+'</details>')+
          box("逐月明细",'<details><summary>查看 '+s.months+' 个持有月</summary>'+table(["信号日","建仓日","期末","可评分","收益可配对","Rank IC"],[...res.months].reverse().map(m=>[date(m.signal),date(m.entry),date(m.end),m.n,m.paired,fmt(m.ic,3)]))+'</details>');
      } catch(e){if(ticket===seq&&env.current())bindRetry(out,e,run);}
    }
    form.oninput=()=>{seq++;inputs();out.innerHTML=note("条件已更改，点击「运行因子检验」更新结果。");};
    form.onsubmit=e=>{e.preventDefault();run();};inputs();
    if(testResults)await run();
  });
}

export function rotationPage(env) {
  const head=title("行业轮动","申万 2021 版一级行业 · 官方日线")+'<a class="link-btn" href="#overview">← 市场总览</a>';
  return setup(env,head,async(root,meta)=>{
    const res=await makeRequest(env,{action:"sectors"});
    if(!env.current())return;
    rot.from||="20220101";rot.to||=res.cutoff;
    root.innerHTML=box("价格位置与行业动量",cutoffNote(res,env)+'<div class="study-plot" id="sector-plot"></div>'+
      note("横轴为收盘指数在自身近 1,260 个交易日的价格分位（至少 252 个观测）；纵轴为 12−1 月动量在本期行业中的百分位。动量从 12 个月前月末计至上月末。"))+
      box("行业动量排名",'<details id="sector-list"><summary>查看 '+res.rows.length+' 个行业</summary>'+table(["排名","行业","12−1 月动量","历史价格分位","动量分位","价格样本天数"],
        res.rows.map(([c,n,m,position,p,days],i)=>[m==null?"—":i+1,esc(n),signed(m),position==null?"—":fmt(position)+"%",p==null?"—":fmt(p)+"%",days]))+'</details>')+
      box("行业轮动回测",'<form id="rot-form" class="controls study-form">'+dateInput("rot-from","自",rot.from,res.first,res.cutoff)+
        dateInput("rot-to","至",rot.to,res.first,res.cutoff)+field("rot-top","每期行业数",rot.top,'type="number" min="1" max="31" step="1"')+
        field("rot-fee","单边费用（基点）",rot.fee,'type="number" min="0" max="100" step="any"')+
        '<label><input type="checkbox" id="rot-timing" '+(rot.timing?"checked":"")+'> 沪深 300 高于 200 日均线才持仓</label>'+action("rot-run","运行行业轮动回测")+'</form>'+
        note("月末按已公布的行业收盘数据选前 N 名，次月首个行业开盘报价齐备日调整。基准等权持有当期全部有报价行业，两组按同一费率对实际买卖双边扣费。使用价格指数模拟配置，未计股息、跟踪误差。"))+
      '<div id="rot-output"></div>';
    const node=el("sector-plot"),form=el("rot-form"),out=el("rot-output");let seq=0;
    loadPlotly().then(plotly=>{
      if(!env.current()||!node.isConnected)return;
      const dots=res.rows.filter(r=>r[3]!=null&&r[4]!=null);
      return plotly.newPlot(node,[{type:"scatter",mode:"markers",x:dots.map(r=>r[3]),y:dots.map(r=>r[4]),text:dots.map(r=>r[1]),
        marker:{size:11,color:"#257462"},hovertemplate:"%{text}<br>历史价格分位 %{x:.1f}%<br>行业动量分位 %{y:.1f}%<extra></extra>"}],
        {height:295,margin:{l:55,r:15,t:10,b:46},xaxis:{range:[-3,103],title:"历史价格分位（%）"},yaxis:{range:[-3,103],title:"行业动量分位（%）"},
         shapes:[{type:"line",x0:50,x1:50,y0:0,y1:100,line:{dash:"dot",color:"#9caea7"}},{type:"line",x0:0,x1:100,y0:50,y1:50,line:{dash:"dot",color:"#9caea7"}}]}, {responsive:true,displayModeBar:false});
    }).catch(()=>{if(node.isConnected)node.innerHTML=empty("暂时无法绘图，可在下方行业排名查看各项数值。");});
    async function run(){
      if(!form.reportValidity())return;
      Object.assign(rot,{from:clean(el("rot-from").value),to:clean(el("rot-to").value),top:el("rot-top").valueAsNumber,fee:el("rot-fee").valueAsNumber,timing:el("rot-timing").checked});
      if(rot.from>rot.to){out.innerHTML=error("起始日期须早于或等于结束日期。");return;}
      const ticket=++seq,payload={action:"rotation",...rot},id=key(payload);
      out.innerHTML=empty("正在按交易日模拟组合…");
      try{
        const r=rotationResults?.id===id?rotationResults.res:await makeRequest(env,payload);
        if(ticket!==seq||!env.current())return;
        rotationResults={id,res:r};
        if(!r.curve.length){out.innerHTML=empty("此区间没有满足历史长度和行业数要求的调仓日。");return;}
        const [a,b]=r.summary;
        out.innerHTML=box("轮动回测结果",note("实际区间 "+date(r.curve[0][0])+" 至 "+date(r.curve.at(-1)[0])+"，共 "+r.log.length+" 个调仓日。")+
          (r.missing.length?'<details><summary>有 '+r.missing.length+' 个交易日缺少官方收盘报价</summary>'+note("保留实际持仓，这些日期不计算净值或回撤："+r.missing.map(date).join("、")+"。")+'</details>':"")+
          table(["组合","累计收益","可估值日最大回撤","累计费用 / 初始本金"],[["动量轮动",signed(a[0]),pct(a[1]),pct(a[2])],["全部行业等权",signed(b[0]),pct(b[1]),pct(b[2])]])+
          line("rot-curve")+env.legend(["动量轮动","全部行业等权"]))+
          box("调仓记录",'<details><summary>查看行业与择时依据</summary>'+table(["信号日","行业报价日","调仓日","轮动目标","基准行业数","沪深 300 收盘","200 日均线"],[...r.log].reverse().map(x=>[date(x.signal),date(x.observed),date(x.entry),esc(x.names.join("、")||"现金"),x.base,fmt(x.market),fmt(x.ma)]))+'</details>');
        env.chart("rot-curve",["动量轮动","全部行业等权"].map((name,i)=>({name,data:r.curve.map(r=>[r[0],r[i+1]])})));
      }catch(e){if(ticket===seq&&env.current())bindRetry(out,e,run);}
    }
    form.oninput=()=>{seq++;out.innerHTML=note("条件已更改，点击「运行行业轮动回测」更新结果。");};
    form.onsubmit=e=>{e.preventDefault();run();};
    if(rotationResults)await run();
  });
}
