"""Monthly SW2021 industry rotation, traded at the following exchange open."""
from bisect import bisect_right
from functools import lru_cache
from itertools import groupby
import math

import numpy as np

from .factor_studies import percentile, read, window

LAUNCH = '20211213'  # SW2021 classification effective date


@lru_cache(maxsize=2)
def market_data(store, digest, cutoff, reader):
    items=read({'files':{'industries':digest}},'industries',reader)
    dates=[d for d in store.daily['dates'] if d<=cutoff]
    positions={d:i for i,d in enumerate(dates)}
    opens=np.full((len(dates),len(items)),np.nan)
    closes=np.full_like(opens,np.nan)
    for j,item in enumerate(items):
        for d,op,cl in item['bars']:
            if d in positions:
                i=positions[d]
                opens[i,j],closes[i,j]=op,cl
    months={m:list(g) for m,g in groupby(range(len(dates)),key=lambda i:dates[i][:6])}
    ends={m:ids[-1] for m,ids in months.items()}
    observations={m:max(i for i in ids if np.isfinite(closes[i]).any()) for m,ids in months.items()
                  if np.isfinite(closes[ids]).any()}
    benchmark={r[0]:r[4] for r in store.series('000300.SH')['bars'] if r[0]>=store.catalog['000300.SH'][6]}
    hs=np.array([benchmark.get(d,np.nan) for d in dates])
    return dates,opens,closes,ends,hs,[(p['code'],p['name']) for p in items],observations


def month_key(day, offset):
    y,m=divmod(int(day[:4])*12+int(day[4:6])-1+offset,12)
    return f'{y:04d}{m+1:02d}'


def momentum(i,dates,closes,ends):
    before,last=(ends.get(month_key(dates[i],k)) for k in (-12,-1))
    values=np.full(closes.shape[1],np.nan)
    if before is not None and last is not None:
        valid=np.isfinite(closes[i]) & (closes[before]>0) & (closes[last]>0)
        values[valid]=100*(closes[last,valid]/closes[before,valid]-1)
    return values


def ranking(data):
    dates,_,closes,_,_,names,observations=data
    i=len(dates)-1
    mom=momentum(i,dates,closes,observations)
    valid=np.flatnonzero(np.isfinite(mom))
    pct=dict(zip(valid,percentile(mom[valid]))) if len(valid) else {}
    rows=[]
    for j in sorted(range(len(names)),key=lambda j:(-mom[j] if j in pct else math.inf,names[j][0])):
        history=closes[max(0,i-1259):i+1,j]
        history=history[np.isfinite(history)]
        position=None
        if len(history)>=252 and np.isfinite(closes[i,j]):
            position=100*(np.count_nonzero(history<closes[i,j])+0.5*np.count_nonzero(history==closes[i,j]))/len(history)
        rows.append([*names[j],float(mom[j]) if j in pct else None,position,pct.get(j),len(history)])
    return rows


def exchange(positions,cash,opening,weights,rate):
    held=positions!=0
    if np.any(held & ~np.isfinite(opening)):
        raise ValueError('回测区间缺少已持有行业的开盘指数，无法核实调仓。')
    old=positions*np.nan_to_num(opening)
    capital=float(old.sum()+cash)
    weights=np.where(np.isfinite(opening) & (opening>0),weights,0.)
    after=capital
    for _ in range(16):
        turnover=np.abs(weights*after-old).sum()
        revised=capital-rate*turnover
        if abs(after-revised)<1e-13*capital:
            after=revised
            break
        after=revised
    target=weights*after
    units=np.divide(target,opening,out=np.zeros_like(positions),where=np.isfinite(opening)&(opening>0))
    return units, max(0.,float(after-target.sum())), capital, float(np.abs(target-old).sum()*rate)


def backtest(data,start,end,n,rate,timing):
    dates,opens,closes,ends,hs,names,observations=data
    entries={}
    for month,sig in ends.items():
        if dates[sig]<LAUNCH or sig+1>=len(dates) or month not in observations:
            continue
        observed=observations[month]
        mom=momentum(observed,dates,closes,observations)
        available=np.flatnonzero(np.isfinite(closes[observed]))
        ranked=np.flatnonzero(np.isfinite(mom))
        if len(ranked)<n or not len(available):
            continue
        if timing and (sig<199 or not np.all(np.isfinite(hs[sig-199:sig+1]))):
            continue
        invested=not timing or hs[sig]>hs[sig-199:sig+1].mean()
        picks=sorted(ranked,key=lambda j:(-mom[j],names[j][0]))[:n] if invested else []
        fill=sig+1
        intended_month=dates[fill][:6]
        while fill<len(dates) and dates[fill][:6]==intended_month and not np.all(opens[fill,available]>0):
            fill+=1
        if fill<len(dates) and dates[fill][:6]==intended_month and start<=dates[fill]<=end:
            entries[fill]=(available,picks,sig,observed)
    if not entries:
        return dict(curve=[],log=[],summary=[],missing=[])
    units=np.zeros((2,len(names)))
    cash=np.ones(2)
    peaks=np.ones(2)
    dd=np.zeros(2)
    fees=np.zeros(2)
    nav=np.ones(2)
    curve,log,missing=[],[],[]
    for i in range(min(entries),bisect_right(dates,end)):
        if i in entries:
            available,picks,sig,observed=entries[i]
            for book,targets in enumerate((picks,available)):
                w=np.zeros(len(names))
                if len(targets):
                    w[targets]=1./len(targets)
                units[book],cash[book],_,cost=exchange(units[book],cash[book],opens[i],w,rate)
                fees[book]+=cost
            log.append(dict(signal=dates[sig],observed=dates[observed],entry=dates[i],names=[names[j][1] for j in picks],
                            base=len(available),market=float(hs[sig]),ma=float(hs[sig-199:sig+1].mean())))
        if not np.any(np.isfinite(closes[i])) or np.any((units!=0) & ~np.isfinite(closes[i])):
            missing.append(dates[i])
            continue
        nav=cash+units @ np.nan_to_num(closes[i])
        peaks=np.maximum(peaks,nav)
        dd=np.minimum(dd,nav/peaks-1)
        curve.append([dates[i],*nav.tolist()])
    return dict(curve=curve,log=log,missing=missing,
                summary=[[100*(nav[b]-1),100*dd[b],100*fees[b]] for b in range(2)])


def industry_request(store,index,reader,settings):
    data=market_data(store,index['files']['industries'],index['day'],reader)
    if settings['action']=='sectors':
        return dict(rows=ranking(data),first=LAUNCH)
    start,end=window(settings,index['day'])
    n,fee,timing=settings.get('top',5),settings.get('fee',10),settings.get('timing',True)
    if type(n)!=int or not 1<=n<=31 or type(fee) not in (int,float) or not 0<=fee<=100 or type(timing)!=bool:
        raise ValueError('请检查行业数（1–31）、单边费用（0–100 基点）和择时规则。')
    return backtest(data,start,end,n,fee/10000,timing)
