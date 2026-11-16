// All calculations use the selected security's own dated observations.
const positive = n => Number.isFinite(n) && n > 0;
const key = d => d.replaceAll("-","");
const month = d => Number(d.slice(0,4))*12 + Number(key(d).slice(4,6))-1;
const sum = a => a.reduce((s,v)=>s+v,0);
const mean = a => sum(a)/a.length;
const sorted = a => [...a].sort((a,b)=>a-b);

function quantile(a,p) {
  const t=(a.length-1)*p, i=Math.floor(t);
  return a[i]+(a[Math.ceil(t)]-a[i])*(t-i);
}
function position(values,current) {
  const lower=values.filter(v=>v<current).length, tied=values.filter(v=>v===current).length;
  return (lower+tied/2)/values.length;
}

export function researchPrices(bars,calendar) {
  const dates=calendar.map(key), days=new Map(dates.map((d,i)=>[d,i]));
  let points=[], level=1;
  for(const b of bars) {
    if(b.volume===0) continue;
    if(!positive(b.volume)||!positive(b.close)){points=[];level=1;continue;}
    const ref=positive(b.pre_close)?b.pre_close:null;
    if(!ref){points=[];level=1;}
    const prior=points.at(-1), d=key(b.day), session=days.get(d);
    const growth=prior&&ref?b.close/ref:null;
    if(growth!==null)level*=growth;
    const daily=prior&&Number.isInteger(session)&&prior.session===session-1?growth-1:null;
    points.push({d,session,level,close:b.close,high:b.high,low:b.low,ref,daily});
  }
  if(!points.length)return {points,dates,byDate:new Map(),end:null};
  const last=points.at(-1), scale=last.close/last.level;
  const windows=[20,60,200], sums=[0,0,0];
  for(let i=0;i<points.length;i++){
    const p=points[i];p.adj=p.level*scale;
    p.ma=windows.map((w,j)=>{
      sums[j]+=p.adj;
      if(i>=w)sums[j]-=points[i-w].adj;
      return i+1>=w?sums[j]/w:null;
    });
    const validHL=positive(p.high)&&positive(p.low)&&p.high>=p.close&&p.low<=p.close&&p.high>=p.low;
    p.tr=validHL&&p.ref?Math.max(p.high-p.low,Math.abs(p.high-p.ref),Math.abs(p.low-p.ref))*p.adj/p.close:null;
  }
  const tail=points.slice(-14).map(p=>p.tr);
  const atr=tail.length===14&&tail.every(Number.isFinite)?mean(tail):null;
  const stop=positive(atr)&&last.close>2*atr?last.close-2*atr:null;
  return {points,dates,byDate:new Map(points.map(p=>[p.d,p])),end:last,atr,stop};
}

export function yearRisk(prices){
  const {points,dates,end}=prices;
  if(!end||!Number.isInteger(end.session)||end.session<252)return null;
  const startAt=end.session-252;
  if(!points.length||points[0].d>dates[startAt])return null;
  // Mark the opening boundary at the last available close if the stock was suspended.
  const anchor=points.findLast(p=>p.d<=dates[startAt]);
  if(!anchor)return null;
  let peak=anchor, trough=anchor, drawPeak=anchor, worst=0;
  const returns=[], curve=[[dates[startAt],0]];
  for(const p of points){
    if(p.d<=dates[startAt])continue;
    if(p.adj>=peak.adj)peak=p;
    const dd=p.adj/peak.adj-1;
    if(dd<worst){worst=dd;drawPeak=peak;trough=p;}
    curve.push([p.d,dd*100]);
    if(Number.isFinite(p.daily))returns.push(p.daily);
  }
  const avg=returns.length?mean(returns):0;
  const vol=returns.length>=120?Math.sqrt(sum(returns.map(r=>(r-avg)**2))/(returns.length-1)*252):null;
  return {start:dates[startAt],end:end.d,peak:drawPeak.d,trough:trough.d,worst,vol,n:returns.length,curve};
}

export function valuationProfile(prices,rows,quote){
  const {end,byDate}=prices;
  if(!end)return null;
  const period=month(end.d);
  const history=rows.filter(r=>r[0]<=end.d&&byDate.has(r[0])).map(([d,pe,pb])=>({d,m:month(d),pe,pb}));
  const exact=history.findLast(p=>p.d===end.d);
  const current=quote?.d===end.d&&positive(quote.close)&&Math.abs(quote.close-end.close)<0.005?quote:exact;
  const metrics={};
  for(const field of ["pe","pb"]){
    const past=history.filter(p=>p.m>=period-60&&p.m<period&&positive(p[field]));
    const values=sorted(past.map(p=>p[field]));
    const value=current?.[field]??null;
    const usable=positive(value)&&values.length>=24;
    metrics[field]={value,n:values.length,from:past[0]?.d,to:past.at(-1)?.d,
      position:usable?position(values,value):null,series:past.map(p=>[p.d,p[field]]),
      q30:usable?quantile(values,0.30):null,q55:usable?quantile(values,0.55):null};
  }
  return {metrics,history,period,d:end.d};
}

export function forwardStudy(prices,profile,field){
  const current=profile?.metrics[field].position;
  if(!Number.isFinite(current))return {rows:[],n:0};
  const endDates=new Map(prices.dates.map(d=>[month(d),d]));
  const selected=[];
  const past=[];
  for(const p of profile.history){
    while(past.length&&past[0].m<p.m-60)past.shift();
    if(positive(p[field])&&past.length>=24&&p.m+12<profile.period){
      const rank=position(past.map(r=>r[field]),p[field]);
      const future=endDates.get(p.m+12), end=prices.byDate.get(future), start=prices.byDate.get(p.d);
      if(Math.abs(rank-current)<=0.10+1e-12&&start&&end&&endDates.get(p.m)===p.d)
        selected.push({from:p.d,to:future,rank,ret:end.adj/start.adj-1});
    }
    if(positive(p[field]))past.push(p);
  }
  const n=selected.length;
  const rs=sorted(selected.map(r=>r.ret));
  return {n,rows:selected,median:n>=12?quantile(rs,.5):null,win:n>=12?rs.filter(r=>r>0).length/n:null};
}

const models={
  strong:["积极配置",.20,"估值或价格处于相对低位，均线趋势也偏强。","若价格失守中期均线，重新核对趋势的支持。"],
  wait:["等待企稳",.05,"位置相对偏低，趋势尚未给出同等支持。","关注价格与 60 日均线的关系，以及短期均线能否持续改善。"],
  hold:["趋势持有",.15,"均线趋势偏强，当前位置的历史折价有限。","若价格回到中期均线下方，重新评估趋势。"],
  avoid:["暂时回避",0,"历史位置偏高，均线趋势同时偏弱。","回到参考区间或均线转强时，分别复核价格位置和趋势。"],
  neutral:["审慎观察",.08,"历史位置与趋势尚未同时满足积极或回避条件。","当均线排列或历史分位跨过评级阈值时复评。"],
};
export function assessment(prices,profile,active){
  const {end,points}=prices;
  if(!end)return null;
  let basis=null, field=null, rank=null, low=null, high=null, n=0,from=null,to=null;
  for(const f of ["pe","pb"]){
    const m=profile?.metrics[f];
    if(m&&Number.isFinite(m.position)){
      field=f;basis=f==="pe"?"PE 估值":"PB 估值";rank=m.position;n=m.n;from=m.from;to=m.to;
      low=end.close*m.q30/m.value;high=end.close*m.q55/m.value;break;
    }
  }
  if(!basis){
    const past=points.filter(p=>p.d<end.d&&month(p.d)>=month(end.d)-60);
    if(past.length>=252){
      const values=sorted(past.map(p=>p.adj));
      basis="历史价格";rank=position(values,end.adj);n=values.length;from=past[0].d;to=past.at(-1).d;
      low=quantile(values,.30);high=quantile(values,.55);
    }
  }
  const [m20,m60,m200]=end.ma;
  const tests=[[end.adj,m20],[m20,m60],[m60,m200],[end.adj,m200]];
  const trend=tests.every(pair=>pair.every(positive))?25*sum(tests.map(([a,b])=>a>b?1:a<b?0:.5)):null;
  const value=rank===null?null:100*(1-rank);
  const score=trend!==null&&value!==null?(trend+value)/2:null;
  const result={basis,field,n,from,to,rank,low,high,trend,value,score,tests,model:null,cap:null};
  if(!active||score===null)return result;
  const state=value>=60?(trend>=62.5?"strong":"wait"):trend>=62.5?"hold":value<=40&&trend<=25?"avoid":"neutral";
  const model=models[state];result.model=model;
  const distance=prices.stop===null?null:1-prices.stop/end.close;
  result.cap=model[1]===0?0:distance>0?Math.min(model[1],.005/distance):null;
  return result;
}

function generator(seed){
  let s=2166136261;
  for(const c of seed)s=Math.imul(s^c.charCodeAt(0),16777619);
  return ()=>{s=(s+0x6d2b79f5)>>>0;let t=Math.imul(s^(s>>>15),1|s);
    t^=t+Math.imul(t^(t>>>7),61|t);return ((t^(t>>>14))>>>0)/4294967296;};
}
export function simulateYear(prices,code){
  const {end,points}=prices;
  if(!end||!Number.isInteger(end.session))return null;
  const sample=points.filter(p=>p.session>end.session-756&&Number.isFinite(p.daily));
  const starts=[];
  for(let i=0;i+4<sample.length;i++)if(sample[i+4].session-sample[i].session===4)starts.push(i);
  if(sample.length<252||starts.length<50)return null;
  const random=generator(code+end.d),n=2000,finals=[],drawdowns=[];
  for(let path=0;path<n;path++){
    let nav=1,peak=1,worst=0;
    for(let day=0;day<252;){
      const start=starts[Math.floor(random()*starts.length)];
      for(let i=0;i<5&&day<252;i++,day++){
        nav*=1+sample[start+i].daily;peak=Math.max(peak,nav);worst=Math.min(worst,nav/peak-1);
      }
    }
    finals.push(nav-1);drawdowns.push(worst);
  }
  finals.sort((a,b)=>a-b);drawdowns.sort((a,b)=>a-b);
  const first=finals[0],last=finals.at(-1);
  const width=Math.max(Math.max(0,last)-Math.min(0,first),.024)/24;
  const origin=Math.floor(Math.min(0,first)/width)*width;
  const bins=Array.from({length:Math.max(1,Math.ceil((Math.max(0,last)-origin)/width))},(_,i)=>({lo:origin+i*width,hi:origin+(i+1)*width,n:0}));
  for(const r of finals)bins[Math.min(bins.length-1,Math.max(0,Math.floor((r-origin)/width)))].n++;
  return {n,observed:sample.length,blocks:starts.length,start:sample[0].d,end:end.d,
    win:finals.filter(r=>r>0).length/n,loss:finals.filter(r=>r<0).length/n,
    quantiles:[.05,.25,.5,.75,.95].map(p=>quantile(finals,p)),dd:quantile(drawdowns,.05),bins};
}
