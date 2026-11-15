import {assistantPage} from "./assistant.js";
import {breadthLink,breadthPage} from "./breadth.js";
import {navigate} from "./navigation.js";
import {livePanel} from "./live.js";
import {esc,fmt,pct,signed,date,title,box,metric,note,empty,table,pager,focusTable,select,line,draw,api,DataDateError,requireDay,offerRefresh,series,adjusted,compare} from "./lab.js";
import {portfolioStudy,remember} from "./portfolio.js";
import {backtest} from "./backtest.js";
import {rangeControl,bindRange} from "./ranges.js";
import {searchField as nameInput,bindSearch} from "./search.js";
import {rollingBeta} from "./beta.js";
import {stockWindows} from "./diagnosis.js";
import {renderDiagnosis} from "./diagnosis-view.js";
import {newsPage} from "./news.js";
import {factorTabs, setSingleTest, financialReports, financeLink, financialScreen, showReportsOnArrival, multiPage, testPage, rotationPage} from "./studies.js";
const $=id=>document.getElementById(id),P=$("panel");
const sections=[["overview","市场总览","M3 12h4l3-6 4 12 3-7h4"],["news","新闻情绪","M4 4h16v16H4z M7 8h10 M7 12h4 M13 12h4 M7 16h10"],["indices","指数中心","M3 18h18M4 14l5-5 4 2 7-7"],["stocks","个股研究","M4 17h16M8 4v9m8-6v8M6 7h4m4 3h4"],["factors","因子选股","M3 5h18M6 11h12M9 17h6"],["backtest","策略回测","M4 18V5m0 13h17M7 14l4-5 4 2 5-7"],["portfolio","组合表现","M11 3a9 9 0 1 0 10 10H11Zm3 0v7h7a8 8 0 0 0-7-7z"]];
sections.push(["assistant","研究问答","M3 4h18v12H9l-6 5V4z M7 8h10 M7 12h7"]);
const benchmarks=["000001.SH","399001.SZ","000300.SH","000905.SH","000852.SH","399006.SZ","899050.BJ"];
const venues={SSE:"沪市",SZSE:"深市",BSE:"北交所",CSI:"中证",CNI:"国证",SW:"申万",CI:"中信",CICC:"中信",OTH:"其他"};
const sourceScopes={stock:"A 股",equity:"编制说明覆盖境内股票",benchmark:"市场基准 / 已核股票指数",industry:"行业系列",review:"样本范围待核"};
let app,items=[],byCode=new Map(),aliases={},aliasRows=[],version=0,pageName="",routeCode="",killGraphs=new Map();
const opt=(id,label,values,v)=>select(id,label,values,v);
const chart=(id,traces)=>{
 killGraphs.get(id)?.();
 const cleanup=draw(id,traces);
 if(cleanup)killGraphs.set(id,cleanup);else killGraphs.delete(id);
};
const plotColors=["#176552","#b28c4a","#6375a3","#a25949","#687d71"];
const legend=(names)=>'<div class="legend">'+names.map((n,i)=>'<span><i style="background:'+plotColors[i%plotColors.length]+'"></i>'+esc(n)+'</span>').join("")+'</div>';
const sym=r=>'<a class="sym" href="#'+(r[2]==="index"?"indices":"stocks")+'/'+encodeURIComponent(r[0])+'"><strong>'+esc(r[1])+'</strong><small>'+esc(r[0])+'</small></a>';
const symbolLink=code=>byCode.has(code)?sym(byCode.get(code)):esc(code);
function active(r){return r[5]==="L"&&r[9]!==null;}
const name=c=>byCode.get(c)?.[1]||c;
const benchOpts=()=>benchmarks.filter(c=>byCode.has(c)).map(c=>[c,name(c)]);
const bench="000300.SH";
const notice=e=>'<p class="empty error">'+esc(e?.message||e)+'</p>';
function retryIn(container,error,callback,id,caption="重新读取"){
 if(error instanceof DataDateError){caption="刷新行情";callback=()=>boot();}
 container.innerHTML=notice(error);
 const button=document.createElement("button");button.type="button";button.className="quiet";button.id=id;button.textContent=caption;
 button.onclick=()=>{button.disabled=true;callback();};container.append(button);
}
const dayKey=d=>d.replaceAll("-","");
const detailRanges={stocks:{days:252,custom:false},indices:{days:252,custom:false}};
const overviewRange={days:126,custom:false};
let betaBenchmark=bench;
let industry="",detailPage=0,indexFilter="",indexScope="",indPage=0,factorKey="mom",factorVenue="",factorPage=0,factorSector="",overviewBench=bench,secondBench="000905.SH";
const ruleKey="xuheng.filters.v1";
const validateRules=rs=>Array.isArray(rs)?rs.filter(r=>r&&typeof r.label==="string"&&["mom","vol","pe","pb","turn"].includes(r.factorKey)&&["","SH","SZ","BJ"].includes(r.factorVenue)&&typeof r.factorSector==="string"):[];
let savedFilters=[],ruleStorageFailed=false;
function readRules(){try{return validateRules(JSON.parse(localStorage.getItem(ruleKey)));}catch{return savedFilters;}}
function displayRules(){
 const area=$("saved-list");if(!area)return;
 area.innerHTML=savedFilters.length?table(["规则名称","动作"],savedFilters.map(r=>[esc(r.label),'<button class="quiet" data-load-rule="'+esc(r.label)+'">应用</button> <button class="quiet" data-del-rule="'+esc(r.label)+'">删除</button>'])):note("规则保存在此浏览器。");
}
window.addEventListener("storage",e=>{if(e.key===ruleKey||e.key===null){ruleStorageFailed=false;savedFilters=readRules();displayRules();}});
async function changeRules(mutate,message){
 const status=$("rule-status");
 const write=()=>{
  savedFilters=mutate(ruleStorageFailed?savedFilters:readRules());
  try{localStorage.setItem(ruleKey,JSON.stringify(savedFilters));ruleStorageFailed=false;}catch{ruleStorageFailed=true;}
  displayRules();if(status?.isConnected)status.textContent=ruleStorageFailed?"浏览器未允许保存，更改仅在当前页面有效。":message+"（仅此浏览器）。";
 };
 if(navigator.locks){let entered=false;try{await navigator.locks.request(ruleKey,()=>{entered=true;write();});}catch(e){if(entered)throw e;write();}}
 else write();
}
let bt={factor:"mom",count:30,fee:10,exchange:"",from:"",to:"",benchmark:bench},detailSymbol="";
function allStocks(){return items.filter(r=>r[2]==="stock");}
function blank(reason,ready){P.innerHTML=notice(reason)+'<button class="quiet" id="retry-screen">重试</button>';$("retry-screen").onclick=()=>boot(ready);}
function wireInput(id,kind,done){
 bindSearch(id,q=>{
   const found=new Map();
   for(const r of aliasRows){
     const [old,code]=r,item=byCode.get(code);
     if(item?.[2]===kind && old.toLowerCase().includes(q))found.set(code,[code,item[1],"原代码 "+old]);
   }
   for(const r of items){
     if(r[2]!==kind||!(r[0]+" "+r[1]).toLowerCase().includes(q))continue;
     if(!found.has(r[0]))found.set(r[0],[r[0],r[1],""]);
   }
   const priority=r=>{const c=r[0].toLowerCase(),name=r[1].toLowerCase(),a=r[2].slice(4).toLowerCase();return c===q||c.split(".")[0]===q||name===q||a===q||a.split(".")[0]===q?0:c.startsWith(q)||name.startsWith(q)?1:2;};
   return [...found.values()].sort((a,b)=>priority(a)-priority(b)||a[0].localeCompare(b[0]));
 },done);
}

function redrawAt(render,id){
 render();
 $(id)?.focus({preventScroll:true});
}
function bindPager(id,drawfn,jump){
 const buttons='[data-pager="'+id+'"]';
 document.querySelectorAll(buttons).forEach(b=>b.onclick=async()=>{
  const pageVersion=version;
  jump(Number(b.dataset.delta));
  await drawfn();
  // A visitor may already be typing the next search while this page is loading.
  const active=document.activeElement;
  if(version!==pageVersion || (active!==document.body && active!==b && active!==$("methods")))return;
  const pager=document.querySelector(buttons)?.closest(".pager");
  if(pager)focusTable(pager.previousElementSibling);
 });
}
async function loadFactors(ticket){
 if(app.factors)return;
 const result=await api("/api/workspace?view=factors&asOf="+app.day);
 if(ticket!==version)return;
 requireDay(result.day,app.day);if(result.factors)requireDay(result.factors.day,app.day);
 if(result.factors)app.factors=result.factors;
}
function studyEnv(ticket){return {panel:P,day:app.day,current:()=>ticket===version,symbol:symbolLink,chart,legend};}
function route(){
 if(!app)return;killGraphs.forEach(f=>f());killGraphs.clear();const [tab,c=""]=location.hash.slice(1).split("/");pageName=sections.some(s=>s[0]===tab)?tab:"overview";
 try{routeCode=decodeURIComponent(c);}catch{routeCode="无效代码";}
 if((pageName==="stocks"&&routeCode!=="screen")||pageName==="indices"){
   routeCode=routeCode.trim().toUpperCase();routeCode=aliases[routeCode]||routeCode;
 }
 const ticket=++version;document.querySelectorAll("#navigation a").forEach(a=>{a.classList.toggle("active",a.dataset.id===pageName);if(a.dataset.id===pageName)a.setAttribute("aria-current","page");else a.removeAttribute("aria-current");});
 const study=({"overview/breadth":breadthPage,"overview/rotation":rotationPage,"stocks/screen":financialScreen,"factors/multi":multiPage,"factors/test":testPage})[pageName+"/"+routeCode];
 if(study){study(studyEnv(ticket));return;}
 if(pageName==="assistant"){assistantPage(studyEnv(ticket));return;}
 if(pageName==="news")killGraphs.set("news",newsPage({panel:P,wireInput,name,isCurrent:()=>ticket===version}));
 if(pageName==="overview")overview(ticket);if(pageName==="stocks"||pageName==="indices")security(ticket);if(pageName==="factors"){
  const render=()=>{if(ticket===version)factors();};
  if(app.factors)render();else{P.innerHTML=title("因子选股","正在读取历史研究样本…");loadFactors(ticket).then(render).catch(e=>{if(ticket===version)blank(e);});}
 }
 if(pageName==="backtest")backtest({panel:P,day:app.day,remember,settings:bt,benchmarks:benchOpts(),refresh:()=>boot(),isCurrent:()=>ticket===version,chart,legend});
 if(pageName==="portfolio"){
  const openManual=routeCode==="manual";
  if(openManual)navigate("portfolio",true,false);
  P.innerHTML=title("组合表现","查看组合在指定区间的收益、回撤与持仓，或比较参数并检验样本外表现。")+'<div id="portfolio-content"></div>';
  portfolioStudy({panel:$("portfolio-content"),day:app.day,name,chart,legend,openManual,research:routeCode==="research",isCurrent:()=>ticket===version,
    stockExists:c=>byCode.get(c)?.[2]==="stock",refresh:()=>boot(),sector:c=>byCode.get(c)?.[4]||"未分类",wireInput});
 }
}
async function boot(ready){
 $("method").disabled=true;
 try{app=await api("/api/workspace");items=app.rows;aliases=app.aliases||{};aliasRows=Object.entries(aliases);byCode=new Map(items.map(r=>[r[0],r]));$("stamp").textContent=date(app.day)+" · 盘后";$("documentation").innerHTML="<p>股票、财报及市场指数来自 Tushare Pro。行业轮动使用申万宏源研究所发布的 31 个一级行业价格指数。日线查询从 2000 年起，按证券的存续期与实际返回日期展示。股票单位为元，指数单位为点。成交额采用接口的千元口径。</p><p>股票价格表显示不复权价格，动量及波动率使用收盘价与当日除权参考前收盘的比值。无收盘、无当日报价和无接口权限分别标示。对跨市场、债券等已识别系列做排除，未核实成分范围的指数单列。</p><p>市场涨跌按有报价的股票计算。当日行业涨跌采用股票目录当前分类。行业轮动使用申万 2021 版一级行业分类。历史选股按信号日实际有行情的证券构建。策略回测和组合表现按开盘成交限制、成交额和所选费率记账；指数用于策略比较或 Beta 估计时，从发布日期起使用。</p>";
 if(app.sample)$("stamp").textContent+=" · 验收样本";
 route();$("method").disabled=false;ready?.();}catch(e){blank(e,ready);}
}
async function overview(ticket){
 const stocks=allStocks(),quoted=stocks.filter(active),up=quoted.filter(r=>r[10]>0).length,down=quoted.filter(r=>r[10]<0).length,flat=quoted.filter(r=>r[10]===0).length;
 const turn=quoted.reduce((s,r)=>s+(r[11]||0),0)/1e9;const groups=new Map();
 for(const r of quoted){if(!r[4]||r[10]==null)continue;const g=groups.get(r[4])||[0,0];g[0]+=r[10];g[1]++;groups.set(r[4],g);}
 const sorted=Array.from(groups,([n,[s,c]])=>[n,s/c,c]).sort((a,b)=>b[1]-a[1]);
 const bars=quoted.filter(r=>!industry||r[4]===industry).sort((a,b)=>(b[10]??-Infinity)-(a[10]??-Infinity)).slice(0,10);
 const tiles=[...sorted.slice(0,3),...sorted.slice(-3).reverse()];
 P.innerHTML=title("市场总览",date(app.day)+" 收盘 · 沪、深、北三地 A 股")+ '<div class="metrics">'+metric("当日有报价",fmt(quoted.length,0),"只股票")+metric("上涨家数",fmt(up,0),"较参考前收盘")+metric("下跌家数",fmt(down,0),"平盘 "+flat+" 只")+metric("成交额",fmt(turn,2),"万亿元")+'</div><div class="two">'+box("主要指数走势",'<div class="controls">'+opt("main-index","指数",benchOpts(),overviewBench)+rangeControl("overview-range","行情区间",[[60,"近 60 日"],[126,"近半年"],[252,"近 1 年"],[0,"全部历史"]],overviewRange)+'</div>'+line("ov-chart"),'<a class="link-btn" href="#indices/'+overviewBench+'">查看指数 →</a>')+box("指数收盘",table(["指数","收盘","日涨跌"],benchmarks.filter(c=>byCode.has(c)).map(c=>{const r=byCode.get(c);return [sym(r),fmt(r[9]),signed(r[10])];})))+'</div><div class="two even">'+box("行业表现",'<div class="thematic">'+tiles.map(([n,v,k])=>'<button data-sector="'+esc(n)+'" data-sign="'+(v>0?"up":"down")+'"><b>'+esc(n)+'</b>'+signed(v)+' <small>'+k+' 只</small></button>').join("")+'</div>'+note("按行业内有报价股票的涨跌幅等权平均，显示领涨与领跌行业。"),'<a class="link-btn" href="#overview/rotation">查看行业轮动 →</a>')+box("市场宽度",'<div class="meter">'+[[up,"gainers"],[flat,"flats"],[down,"fallers"]].map(([n,c])=>'<i style="width:'+100*n/Math.max(quoted.length,1)+'%" class="'+c+'"></i>').join("")+'</div>'+table(["市场","上涨","平盘","下跌"],["SSE","SZSE","BSE"].map(v=>{const g=quoted.filter(r=>r[3]===v);return [venues[v],fmt(g.filter(r=>r[10]>0).length,0),fmt(g.filter(r=>r[10]===0).length,0),fmt(g.filter(r=>r[10]<0).length,0)];}))+breadthLink(app.breadth))+'</div>'+box(industry?industry+" · 当日涨幅":"当日涨幅",table(["股票","行业","收盘","日涨跌"],bars.map(r=>[sym(r),esc(r[4]),fmt(r[9]),signed(r[10])])),industry?'<button id="clear-sector" class="quiet">全部行业</button>':"")+coverage();
 bindRange("overview-range",overviewRange,route);
 $("main-index").onchange=e=>{overviewBench=e.target.value;redrawAt(route,"main-index");};document.querySelectorAll("[data-sector]").forEach(b=>b.onclick=()=>{industry=b.dataset.sector;route();document.querySelector("#clear-sector")?.scrollIntoView({block:"nearest"});});if($("clear-sector"))$("clear-sector").onclick=()=>{industry="";route();};
 try{const data=await series(overviewBench,app.day);if(ticket===version)chart("ov-chart",[{name:name(overviewBench),data:(overviewRange.days?data.bars.slice(-overviewRange.days):data.bars).map(b=>[dayKey(b.day),b.close])}]);}catch(e){if(ticket===version)retryIn($("ov-chart").parentElement,e,route,"retry-overview");}
}
function coverage(){
 const stocks=allStocks(),indices=items.filter(r=>r[2]==="index"),pr=app.progress;return '<div class="source-line">Tushare Pro · 股票目录 '+fmt(stocks.length,0)+' 只（含退市） · 指数及待核目录 '+fmt(indices.length,0)+' 条。'+(pr?' 历史库已校验 '+fmt(pr.ready,0)+' 个有数据标的，'+fmt(pr.bars,0)+' 条日线。':' 查询证券时会读取并保存其可用历史日线。')+'</div>';
}
function indexDirectory(){
 const universe=items.filter(r=>r[2]==="index"&&(!indexScope||r[8]===indexScope)&&(r[0]+" "+r[1]+" "+r[4]).toLowerCase().includes(indexFilter.toLowerCase())).sort((a,b)=>(b[8]==="benchmark")-(a[8]==="benchmark")||a[0].localeCompare(b[0]));
 const size=12;indPage=Math.min(indPage,Math.max(0,Math.ceil(universe.length/size)-1));return table(["指数","发布市场","类别","范围"],universe.slice(indPage*size,(indPage+1)*size).map(r=>[sym(r),esc(venues[r[3]]||r[3]),esc(r[4]||"—"),esc(sourceScopes[r[8]])]))+pager("catalog",indPage,universe.length,size);
}
async function security(ticket){
 const isIndex=pageName==="indices",kind=isIndex?"index":"stock";const code=routeCode||(isIndex?bench:"600519.SH"),row=byCode.get(code);
 if(!row||row[2]!==kind){P.innerHTML=title(isIndex?"指数中心":"个股研究","未找到链接中的证券，请按名称或代码重新搜索。")+nameInput("quick","查询证券，输入股票或指数代码");wireInput("quick",kind,c=>navigate(pageName+"/"+c));return;}
 const range=detailRanges[pageName];
 if(detailSymbol!==code){detailPage=0;detailSymbol=code;}
 let html=title(isIndex?"指数中心":"个股研究",isIndex?"查找指数，并在共同交易日比较走势。":"查询个股行情、诊断依据和财务披露。")+nameInput("quick",isIndex?"搜索指数名称或代码":"搜索股票名称或代码");
 const summary='<div class="summary"><span>'+esc(code)+'</span><span>'+esc(venues[row[3]]||row[3])+' · '+esc(row[4]||"未分类")+'</span><span>'+esc(row[5]==="D"?"已终止 / 退市":sourceScopes[row[8]])+'</span></div><div class="metrics">'+metric("最新收盘",fmt(row[9]),row[9]==null?"当日无报价":date(app.day))+metric("日涨跌",pct(row[10]))+(isIndex?metric("发布日期",date(row[6]))+metric("成交额",fmt(row[11]!=null?row[11]/100000:null),"亿元"):metric("滚动市盈率",fmt(row[12]),"倍")+metric("市净率",fmt(row[13]),"倍"))+'</div>';
 const plot='<div class="controls">'+rangeControl("range","行情区间",[[20,"近 20 日"],[60,"近 60 日"],[252,"近 1 年"],[0,"全部历史"]],range)+(isIndex?opt("second","比较指数",[["","仅看本指数"],...benchOpts().filter(v=>v[0]!==code)],secondBench!==code?secondBench:""):"")+'</div><div id="security-plot">'+line("sec-chart")+'</div><div id="sec-legend"></div><div id="metadata" class="note"></div>';
 if(isIndex)html+=box(row[1],summary+plot);
 else {
   html+=box(row[1],summary)+box("个股诊断",'<div id="stock-diagnosis">'+empty("正在读取个股日线…")+'</div>',
     '<div class="controls diagnosis-control">'+opt("beta-bench","市场基准",benchOpts(),betaBenchmark)+'</div>')+box("行情走势",plot);
   html+=box("120 日滚动 Beta",'<div id="stock-beta">'+empty("正在计算 Beta…")+'</div>'+note("图表使用「个股诊断」选定的市场基准，沿用上方行情区间。每个点使用 120 对同日收益，跳过停牌及跨日复牌收益。"));
 }
 html+=box("历史记录",'<div id="bar-table">'+empty("读取日线…")+'</div>','<button class="quiet" id="download" disabled>导出 CSV</button>');
 html+=box(isIndex?"历史成分与权重":"财务披露",'<div class="controls">'+(isIndex?'<label>截至日期 <input id="member-date" type="date" min="2000-01-01" value="'+date(app.day)+'" max="'+date(app.day)+'"></label>':'')+'<button id="extra-data" class="quiet">'+(isIndex?'查询最近一期成分':'查看财报指标')+'</button></div><div id="extra-result"></div>',isIndex?"":financeLink(code));
 if(isIndex)html+=box("指数目录",'<div class="controls"><label>搜索 <input id="index-find" value="'+esc(indexFilter)+'" placeholder="代码、名称或类别"></label>'+opt("scope","范围",[["","全部目录"],["benchmark","基准 / 已核"],["equity","境内股票指数"],["industry","行业系列"],["review","范围待核"]],indexScope)+'</div><div id="listing"></div>');
 P.innerHTML=html;livePanel(P,code);wireInput("quick",kind,c=>navigate(pageName+"/"+c));bindRange("range",range,()=>{detailPage=0;route();});
 let history,comparisonVersion=0;
 function updateStockComparison(){
   if(!history||ticket!==version)return;
   const revision=++comparisonVersion;
   renderStockComparison(history,betaBenchmark,()=>ticket===version&&revision===comparisonVersion,updateStockComparison);
 }
 if(!isIndex)$("beta-bench").onchange=e=>{betaBenchmark=e.target.value;updateStockComparison();};
 let extraRevision=0;
 if(isIndex)$("member-date").oninput=()=>{extraRevision++;$("extra-result").replaceChildren();$("extra-data").disabled=false;};
 $("extra-data").onclick=async()=>{
 const button=$("extra-data"),dst=$("extra-result"),revision=++extraRevision;
 const current=()=>ticket===version&&revision===extraRevision;
 if(!isIndex&&!app.sample){await financialReports(studyEnv(ticket),code,dst,button);return;}
 if(isIndex&&(!$("member-date").value||!$("member-date").validity.valid)){
  dst.innerHTML=empty("请选择 2000 年起至数据截止日之间的有效日期。");return;
 }
 button.disabled=true;dst.innerHTML=empty("正在读取…");
 try{
  const d=isIndex?dayKey($("member-date").value):"",res=await api("/api/research?type="+(isIndex?"members":"financial")+"&symbol="+encodeURIComponent(code)+"&day="+d+"&asOf="+app.day);
  if(!current())return;
  if(isIndex){
   let page=0;
   const fill=()=>{dst.innerHTML=res.items.length?note("权重日期 "+date(res.day)+" · 共 "+res.items.length+" 只。")
    +table(["成分股","权重"],res.items.slice(page*30,(page+1)*30).map(r=>[symbolLink(r[0]),pct(r[2])]))+pager("members",page,res.items.length,30)
    :empty("所选日期之前 95 天内，数据源未返回这个指数的成分。");
    bindPager("members",fill,d=>page+=d);};fill();
  }
  else dst.innerHTML=res.items.length?table(["报告期","公告日","每股收益","净资产收益率","毛利率","资产负债率"],res.items.map(r=>[date(r[0]),date(r[1]),fmt(r[2]),pct(r[3]),pct(r[4]),pct(r[5])])):empty("近三年未返回财报指标。");
 }catch(e){if(current()){dst.innerHTML=notice(e);offerRefresh(dst,e,()=>boot());}}finally{if(current())button.disabled=false;}
 };
 if(!isIndex&&showReportsOnArrival(code)){
   const disclosure=$("extra-data");
   const section=disclosure.closest("section");
   P.querySelector(".metrics").closest("section").after(section);
   disclosure.onclick().then(()=>{
     if(disclosure.isConnected)section.scrollIntoView({block:"start"});
   });
 }
 if(isIndex){
 $("second").onchange=e=>{secondBench=e.target.value;redrawAt(route,"second");};const drawList=()=>{$("listing").innerHTML=indexDirectory();bindPager("catalog",drawList,d=>indPage+=d);};drawList();
 $("index-find").oninput=e=>{indexFilter=e.target.value;indPage=0;drawList();};$("scope").onchange=e=>{indexScope=e.target.value;indPage=0;drawList();};
 }
 try{
 const result=await series(code,app.day);if(ticket!==version)return;
 if(row[9]==null&&result.bars.length){
  const latest=result.bars.at(-1),cards=P.querySelectorAll(".metrics .metric");
  cards[0].querySelector("b").textContent=fmt(latest.close);cards[0].querySelector("small").textContent=latest.day+" · 末次报价";
  cards[1].querySelector("b").textContent=pct(latest.pct);
 }
 const data=range.days?result.bars.slice(-range.days):result.bars;
 if(!data.length){
 const reason=result.status==="denied"?"当前账号缺少此系列日线权限。":"数据源在查询区间内未返回有效收盘价。";$("security-plot").innerHTML=empty(reason);$("bar-table").innerHTML=empty(reason);if(!isIndex){$("stock-beta").innerHTML=empty(reason);$("stock-diagnosis").innerHTML=empty(reason);}return;}
 if(!isIndex){
   history={bars:result.bars,firstVisible:data[0].day,windows:stockWindows(result.bars),release:date(app.day),status:row[5]};
   updateStockComparison();
 }
 const renderTable=()=>{const size=12,rows=data.slice().reverse();detailPage=Math.min(detailPage,Math.max(0,Math.ceil(rows.length/size)-1));$("bar-table").innerHTML=table(["交易日","开盘","最高","最低","收盘","日涨跌","成交额（万元）"],rows.slice(detailPage*size,(detailPage+1)*size).map(b=>[date(b.day),fmt(b.open),fmt(b.high),fmt(b.low),fmt(b.close),signed(b.pct),fmt(b.amount==null?null:b.amount/10)]))+pager("bars",detailPage,rows.length,size);bindPager("bars",renderTable,d=>detailPage+=d);};renderTable();
 $("metadata").textContent="可查 "+result.bars[0].day+" 至 "+result.bars.at(-1).day+"，共 "+fmt(result.bars.length,0)+" 个有效收盘日。当前显示 "+data.length+" 个交易日。开、高、低缺值保留为空。"+(isIndex&&row[6]&&dayKey(result.bars[0].day)<row[6]?" 发布日 "+date(row[6])+" 之前为指数回溯序列。":"");
 $("download").disabled=false;$("download").onclick=()=>{
 const csv=[["代码","名称","日期","开","高","低","收","百分比涨跌","成交量（手）","成交额（千元）"],...data.map(b=>[code,row[1],b.day,b.open,b.high,b.low,b.close,b.pct,b.volume,b.amount])].map(a=>a.map(v=>'"'+String(v??"").replaceAll('"','""')+'"').join(",")).join("\r\n");
 const url=URL.createObjectURL(new Blob(["\uFEFF"+csv],{type:"text/csv;charset=utf-8"}));const a=document.createElement("a");a.href=url;a.download=code+"_"+data[0].day+"_"+data.at(-1).day+".csv";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
 const direct=data.map(b=>[dayKey(b.day),b.close]);let traces=[{name:row[1],data:direct}];
 if(isIndex&&secondBench&&secondBench!==code){
 try{const other=await series(secondBench,app.day);if(ticket!==version)return;const [a,b]=compare(direct,other.bars.map(b=>[dayKey(b.day),b.close]));if(a.length){traces=[{name:row[1],data:a},{name:name(secondBench),data:b}];$("sec-legend").innerHTML=legend(traces.map(t=>t.name))+note("两条曲线从首个共同交易日的 100 起算。");}else{$("sec-legend").innerHTML=note("比较指数在所选区间无共同报价，显示当前指数点位。");}}catch(e){if(ticket!==version)return;retryIn($("sec-legend"),e instanceof DataDateError?e:"比较指数暂不可用，显示当前指数点位。",route,"retry-comparison","重试指数比较");}
 }chart("sec-chart",traces);
 }catch(e){if(ticket===version){retryIn($("security-plot"),e,route,"retry-series","重新读取行情");$("bar-table").innerHTML=empty("日线读取未完成。");if(!isIndex){$("stock-beta").innerHTML=empty("等待个股行情后计算 Beta。");retryIn($("stock-diagnosis"),e,route,"retry-diagnosis","重新读取行情");}}}
}
async function renderStockComparison(stock,benchmark,current,retry){
 const target=$("stock-diagnosis"),out=$("stock-beta");
 const listed=byCode.get(benchmark)?.[6];
 const market={code:benchmark,name:name(benchmark),launch:listed?date(listed):"",state:"loading"};
 renderDiagnosis(target,stock,market);
 killGraphs.get("beta-chart")?.();killGraphs.delete("beta-chart");
 out.innerHTML=empty("正在读取"+market.name+"…");
 try{
  const index=await series(benchmark,app.day);
  if(!current())return;
  if(index.status==="denied")throw new Error("当前账号缺少该基准的日线权限。");
  market.bars=market.launch?index.bars.filter(b=>b.day>=market.launch):[];
  market.beta=rollingBeta(stock.bars,market.bars);
  market.state="ready";
  renderDiagnosis(target,stock,market);
  const {pairs,points}=market.beta;
  const visible=points.filter(([d])=>d>=dayKey(stock.firstVisible));
  if(!visible.length){
   out.innerHTML=empty(pairs<120?"只有 "+pairs+" 个有效配对日，满 120 个后显示 Beta。":"所选区间无可估计的 Beta。");
   return;
  }
  const [day,value]=visible.at(-1);
  out.innerHTML='<div class="beta-value"><b id="beta-value">'+fmt(value,3)+'</b><span>'+esc(name(benchmark))+' · '+date(day)+'</span></div>'+line("beta-chart");
  chart("beta-chart",[{name:"120 日 Beta",data:visible}]);
 }catch(error){if(current()){market.state="error";renderDiagnosis(target,stock,market);retryIn(out,error,retry,"retry-beta");}}
}
function factors(){
 const f=app.factors,latest=new Map((f?.latest||[]).map(r=>[r[0],r]));
 const rows=allStocks().filter(active).filter(r=>(!factorVenue||r[0].endsWith("."+factorVenue))&&(!factorSector||r[4]===factorSector)).map(r=>{const vals=latest.get(r[0]);return {r,v:factorKey==="mom"?vals?.[1]:factorKey==="vol"?vals?.[2]:factorKey==="pe"?r[12]:factorKey==="pb"?r[13]:r[15]};}).filter(i=>Number.isFinite(i.v)&&(!["pe","pb"].includes(factorKey)||i.v>0)).sort((a,b)=>(["vol","pe","pb"].includes(factorKey)?a.v-b.v:b.v-a.v)||a.r[0].localeCompare(b.r[0]));
 const facs=[["mom","60 日动量"],["vol","20 日低波动"],["pe","低市盈率"],["pb","低市净率"],["turn","换手率"]];
 const factorHeading={mom:"60 日动量",vol:"年化波动率",pe:"市盈率（倍）",pb:"市净率（倍）",turn:"换手率"}[factorKey];
 const size=20;factorPage=Math.min(factorPage,Math.max(0,Math.ceil(rows.length/size)-1));
 P.innerHTML=title("因子选股","在当期有报价的 A 股中，按明确的规则筛选和排序。")+factorTabs("factors")+box("筛选条件",'<div class="controls">'+opt("factor","排序因子",facs,factorKey)+opt("venue","市场",[["","全 A 股"],["SH","沪市"],["SZ","深市"],["BJ","北交所"]],factorVenue)+opt("sector","行业",[["","全部行业"],...Array.from(new Set(allStocks().map(r=>r[4]).filter(Boolean))).sort().map(s=>[s,s])],factorSector)+'</div>'+note(factorKey==="mom"?"按最近 60 个有效交易日的复权参考收益连乘，由高到低排序。":factorKey==="vol"?"按最近 20 个有效交易日收益率的样本标准差 × √252，由低到高排序。" :["pe","pb"].includes(factorKey)?"从低到高排列，仅纳入信号日为正的估值倍数。":"按当日换手率从高到低排序，缺失值不参与。"),'<a class="link-btn" href="#stocks/screen">按财务条件筛选 →</a>')+box("入选结果",(!f&&["mom","vol"].includes(factorKey)?empty("该交易日的动量与波动率正在入库。估值与换手率可先查询。"):table(["排名 / 股票","行业",factorHeading,"市值（亿元）","日涨跌"],rows.slice(factorPage*size,(factorPage+1)*size).map((o,i)=>[(factorPage*size+i+1)+"　"+sym(o.r),esc(o.r[4]),factorKey==="mom"?pct(o.v):fmt(o.v)+(["vol","turn"].includes(factorKey)?"%":""),fmt(o.r[14]==null?null:o.r[14]/10000),signed(o.r[10])]))+pager("factor",factorPage,rows.length,size)),(["mom","vol"].includes(factorKey)&&!factorSector&&f?'<button class="act" id="to-back">用此规则回测 →</button>':'<small>可用样本 '+fmt(rows.length,0)+' 只</small>'));
 P.insertAdjacentHTML("beforeend",'<section class="box"><details><summary>保存与调用选股规则</summary><div class="controls" style="margin-top:12px"><label>规则名称 <input id="rule-name" maxlength="40" value="'+esc(facs.find(a=>a[0]===factorKey)[1]+(factorVenue?" · "+({SH:"沪市",SZ:"深市",BJ:"北交所"})[factorVenue]:"")+(factorSector?" · "+factorSector:""))+'"></label><button id="rule-save" class="quiet">保存规则</button></div><p id="rule-status" role="status" class="note"></p><div id="saved-list"></div></details></section>');
 $("rule-save").onclick=()=>{const label=$("rule-name").value.trim();if(!label){$("rule-status").textContent="请先填写一个规则名称。";$("rule-name").focus();return;}
  const item={label,factorKey,factorVenue,factorSector};changeRules(rs=>[...rs.filter(r=>r.label!==label),item],"已保存规则："+label);};
 $("saved-list").onclick=e=>{const b=e.target.closest("button");if(!b)return;
  if(b.hasAttribute("data-load-rule")){const r=savedFilters.find(x=>x.label===b.dataset.loadRule);if(!r)return;factorKey=r.factorKey;factorVenue=r.factorVenue;factorSector=r.factorSector;factorPage=0;redrawAt(factors,"factor");}
  else if(b.hasAttribute("data-del-rule")){const label=b.dataset.delRule;changeRules(rs=>rs.filter(r=>r.label!==label),"已删除此规则");}};
 if(!ruleStorageFailed)savedFilters=readRules();displayRules();
 if(!factorSector){
  const actions=P.querySelectorAll(".box .ttl")[1];
  actions?.insertAdjacentHTML("beforeend",'<button class="quiet" id="single-test">检验当前规则 →</button>');
  $("single-test").onclick=()=>setSingleTest(factorKey,factorVenue);
 }else P.insertAdjacentHTML("beforeend",note("行业筛选采用本期股票分类。历史检验可选择全 A 股或单个交易市场。"));
 $("factor").onchange=e=>{factorKey=e.target.value;factorPage=0;redrawAt(factors,"factor");};$("venue").onchange=e=>{factorVenue=e.target.value;factorPage=0;redrawAt(factors,"venue");};$("sector").onchange=e=>{factorSector=e.target.value;factorPage=0;redrawAt(factors,"sector");};bindPager("factor",factors,d=>factorPage+=d);
 if($("to-back"))$("to-back").onclick=()=>{bt.factor=factorKey;bt.exchange=factorVenue;navigate("backtest");};
}
$("navigation").innerHTML=sections.map(([key,t,path])=>'<a href="#'+key+'" data-id="'+key+'"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="'+path+'"/></svg>'+esc(t)+'</a>').join("");
const statusText={ready:"已有日线",empty:"未返回收盘",denied:"权限受限"};
let coverageGeneration=0,coverageTimer;
function openDetails(saved={}){
 const generation=++coverageGeneration;$("methods").showModal();
 if(!$("coverage-data")){
 livePanel($("documentation"));
 $("documentation").insertAdjacentHTML("beforeend",'<h3>历史日线覆盖</h3><div class="controls"><label>证券 <input type="search" id="cov-find" placeholder="代码或名称"></label>'+opt("cov-kind","类型",[["","全部"],["stock","股票"],["index","指数"]],"")+opt("cov-status","状态",[["","全部"],["ready","已有日线"],["empty","未返回收盘"],["denied","权限受限"]],"")+'</div><div id="coverage-data"></div>');
 }
 if(saved.query!==undefined){
   $("cov-find").value=saved.query;$("cov-kind").value=saved.kind;$("cov-status").value=saved.status;
 }
 let page=saved.page??0,revision=0;
 const area=$("coverage-data");
 const pending=()=>{
   area.setAttribute("aria-busy","true");
   area.replaceChildren(document.createTextNode("正在读取覆盖记录…"));
 };
 const fill=async()=>{
 const ticket=++revision,requestedPage=page;pending();
 try{const args=new URLSearchParams({page:String(requestedPage),q:$("cov-find").value,kind:$("cov-kind").value,status:$("cov-status").value});const res=await api("/api/coverage?"+args);
 if(generation!==coverageGeneration||ticket!==revision||!$("methods").open)return;
 if(res.day!==app.day){
   retryIn(area,"覆盖明细与当前行情目录的交易日不一致。",()=>{
     const filters={page:requestedPage,query:$("cov-find").value,kind:$("cov-kind").value,status:$("cov-status").value};
     $("methods").close();boot(()=>openDetails(filters));
   },"retry-coverage","刷新行情");
   return;
 }
 const last=Math.max(0,Math.ceil(res.total/12)-1);
 if(requestedPage>last){page=last;fill();return;}
 area.innerHTML=table(["标的","状态","起日","末日","收盘日数"],res.rows.map(r=>[symbolLink(r.code),statusText[r.status],date(r.first_day),date(r.last_day),fmt(r.bars,0)]))+pager("coverage",requestedPage,res.total,12)+note("按已完成校验的证券统计，只有有效收盘才计入行数。");
 area.querySelectorAll("a").forEach(a=>a.onclick=()=>$("methods").close());bindPager("coverage",fill,x=>{page=requestedPage+x;});
 }catch(e){if(generation===coverageGeneration&&ticket===revision&&$("methods").open)retryIn(area,e,fill,"retry-coverage");}
 finally{if(generation===coverageGeneration&&ticket===revision)area.setAttribute("aria-busy","false");}
 };
 $("cov-kind").onchange=$("cov-status").onchange=()=>{clearTimeout(coverageTimer);page=0;fill();};
 $("cov-find").oninput=()=>{page=0;revision++;pending();clearTimeout(coverageTimer);coverageTimer=setTimeout(fill,160);};
 clearTimeout(coverageTimer);fill();
}
$("methods").addEventListener("close",()=>{if(!$("methods").open){coverageGeneration++;clearTimeout(coverageTimer);}});
document.querySelector(".skip").onclick=e=>{e.preventDefault();$("content").focus({preventScroll:true});$("content").scrollIntoView({block:"start"});};
window.addEventListener("hashchange",()=>{window.scrollTo(0,0);route();const nav=$("navigation"),active=nav.querySelector("a.active");if(active&&nav.scrollWidth>nav.clientWidth)nav.scrollLeft+=active.getBoundingClientRect().left-nav.getBoundingClientRect().left-(nav.clientWidth-active.offsetWidth)/2;});
$("method").onclick=openDetails;$("close-method").onclick=()=>$("methods").close();boot();
