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

function trendScore(point){
  const [short,medium,long]=point.ma;
  const tests=[[point.adj,short],[short,medium],[medium,long],[point.adj,long]];
  if(!tests.every(pair=>pair.every(positive)))return null;
  return 25*sum(tests.map(([a,b])=>Math.abs(a-b)<=1e-10*Math.max(a,b)?0.5:Number(a>b)));
}

function trendDirection(score){
  if(!Number.isFinite(score))return null;
  if(score>=62.5)return 1;
  if(score<=37.5)return -1;
  return 0;
}

function positionBand(rank){
  if(!Number.isFinite(rank))return null;
  if(rank<=.4+1e-12)return "低位";
  if(rank>=.6-1e-12)return "高位";
  return "中位";
}

export function assessment(prices,profile){
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
  const trend=trendScore(end);
  const value=rank===null?null:100*(1-rank);
  const score=trend!==null&&value!==null?(trend+value)/2:null;
  return {basis,field,n,from,to,rank,band:positionBand(rank),low,high,trend,direction:trendDirection(trend),value,score};
}

function outcomes(rows,field){
  const values=sorted(rows.map(r=>r[field]));
  let lastExit="",nonoverlap=0;
  for(const row of rows){
    if(row.entry>lastExit){nonoverlap++;lastExit=row.exit;}
  }
  return {rows,n:rows.length,nonoverlap,median:values.length?quantile(values,.5):null,
    wins:values.filter(v=>v>0).length};
}

// A signal only uses observations already available at the close of its month.
export function signalHistory(prices,profile,current){
  const rows=[];
  if(!current?.band||current.direction===null)return outcomes(rows,"ret");
  const {dates,points,byDate,end}=prices;
  const monthEnds=new Map(dates.map((d,i)=>[month(d),i]));
  const valuations=new Map((profile?.history||[]).map(v=>[v.d,v]));
  const field=current.field, prior=[];
  let priceStart=0,priceEnd=0;
  for(const [m,i] of monthEnds){
    const d=dates[i],point=byDate.get(d);
    if(m+12>=month(end.d))break; // the exit month must have finished
    if(!point)continue;
    let rank=null;
    if(field){
      while(prior.length&&prior[0].m<m-60)prior.shift();
      const v=valuations.get(d)?.[field];
      if(!positive(v))continue;
      if(prior.length>=24)rank=position(prior.map(r=>r.value),v);
      prior.push({m,value:v});
    }else{
      while(priceEnd<points.length&&points[priceEnd].d<d)priceEnd++;
      while(priceStart<priceEnd&&month(points[priceStart].d)<m-60)priceStart++;
      if(priceEnd-priceStart>=252)rank=position(points.slice(priceStart,priceEnd).map(p=>p.adj),point.adj);
    }
    const trend=trendScore(point);
    if(positionBand(rank)!==current.band||trendDirection(trend)!==current.direction)continue;
    const entry=dates[i+1],exit=dates[monthEnds.get(m+12)];
    const start=byDate.get(entry),finish=byDate.get(exit);
    if(start&&finish)rows.push({signal:d,entry,exit,rank,trend,ret:finish.adj/start.adj-1});
  }
  return outcomes(rows,"ret");
}

export function relativeHistory(history,bars,launch){
  const closes=new Map(bars.filter(b=>positive(b.close)).map(b=>[key(b.day),b.close]));
  const rows=[];
  for(const row of history.rows){
    const first=closes.get(row.entry),last=closes.get(row.exit);
    if(!launch||row.signal<key(launch)||!first||!last)continue;
    const benchmark=last/first-1;
    rows.push({...row,benchmark,excess:row.ret-benchmark});
  }
  const result=outcomes(rows,"excess");
  const pp=result.median===null?0:Number((result.median*100).toFixed(2));
  result.direction=result.nonoverlap>=2?Math.sign(pp):null;
  return result;
}

export function signalRating(current,history,scenario,prices,active){
  if(!active||current.direction===null)return {label:null,cap:null};
  const dir=current.direction;
  const valueSupports=Boolean(current.field)&&(dir===1&&current.band==="低位"||dir===-1&&current.band==="高位");
  const pastSupports=history.nonoverlap>=2&&dir*history.median>0;
  const simulationSupports=Number.isFinite(scenario?.quantiles[2])&&dir*scenario.quantiles[2]>0;
  const strong=valueSupports&&pastSupports&&simulationSupports;
  const levels=["强烈看淡","看淡","中性","看多","强烈看多"];
  const index=2+dir*(strong?2:1);
  const ceiling=[0,.05,.08,.15,.20][index];
  const distance=positive(prices.stop)?1-prices.stop/prices.end.close:null;
  const cap=ceiling===0?0:distance>0?Math.min(ceiling,.005/distance):null;
  return {label:levels[index],strong,valueSupports,pastSupports,simulationSupports,cap,ceiling};
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
