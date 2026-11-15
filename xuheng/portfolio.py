"""A self-financing A-share ledger. All signal inputs predate the opening auction."""
from __future__ import annotations

import base64
import math
import struct
from copy import deepcopy
from functools import lru_cache
from datetime import datetime

from .frames import BENCHMARKS, COL, MARKETS, MODELS, WEIGHTS, Rules, frames
from .study_store import factor_snapshot


def check_window(start,end,cutoff):
    for s in (start,end):
        try:
            if len(s)!=8 or datetime.strptime(s,"%Y%m%d").strftime("%Y%m%d")!=s:
                raise ValueError
        except (ValueError,TypeError):
            raise ValueError("请填写有效的起日和截止日。") from None
    if start < "20000101" or end > cutoff or start>end:
        raise ValueError("日期须在 2000 年至数据截止日之间，且截止日不早于起日。")


def validate(store,r,start,end):
    check_window(start,end,store.day)
    if r.model not in MODELS or r.exchange not in MARKETS or r.bench not in BENCHMARKS or r.weighting not in WEIGHTS:
        raise ValueError("请选择有效的模型、市场、基准和配权方式。")
    if not isinstance(r.count,int) or not 1<=r.count<=200 or not math.isfinite(r.fee) or not 0<=r.fee<=100:
        raise ValueError("目标持股数须为 1 至 200，单边费率须为 0 至 100 个基点。")
    if r.cadence not in ("hold","days","months") or not isinstance(r.interval,int) or r.interval<1:
        raise ValueError("自定义调仓间隔须为正整数交易日。")
    if r.cadence=="hold" and r.interval!=1 or r.cadence=="months" and r.interval not in (1,3,6):
        raise ValueError("请选择有效的调仓频率。")
    if r.model=="multi":
        if r.cadence!="months":
            raise ValueError("历史多因子截面按月末归档，请选择每月、每季初或每半年初调仓。")
        from .factor_studies import FACTORS, weights
        if len(r.factor_weights)!=len(FACTORS):
            raise ValueError("请设置六项因子的权重。")
        weights({'weights':dict(zip(FACTORS,r.factor_weights))})
    if not r.daily and start==end:
        raise ValueError("按月估值须覆盖完整持有期。")
    if r.model=="pb" and r.control not in COL:
        raise ValueError("低 PB 需要一个可比较的选股模型。")
    if r.model=="manual" and (len(set(r.symbols))!=len(r.symbols) or len(r.symbols)!=r.count or any(c not in store.stock_life for c in r.symbols)):
        raise ValueError("请添加 1 至 200 只不同的 A 股。")
    if r.weighting=="manual" and (len(r.weights)!=r.count or any(not math.isfinite(w) or not 0<=w<=100 for w in r.weights) or sum(r.weights)>100.0000001):
        raise ValueError("每只股票或每个名次须有一个非负权重，合计不能超过 100%。")


def select(store,r,rows,by_code,day,rank,ordered):
    if rank is not None:
        chosen=rank
    elif r.model=="manual":
        chosen=[(c,None) for c in r.symbols]
    else:
        field=COL[r.model]
        chosen=[(row[0],row[field]) for row in rows if row[field] is not None and (not r.exchange or row[0].endswith("."+r.exchange))]
        if not ordered:
            chosen.sort(key=lambda x:(-x[1] if r.model=="mom" else x[1],x[0]))
        chosen=chosen[:r.count]
    ac=7 if r.bench=="000300.SH" else 9 if r.bench=="000001.SH" else 11
    picks=[]
    for code,score in chosen:
        q=by_code.get(code)
        listed,ended=store.stock_life.get(code,("",""))
        eligible=(not listed or listed<=day) and (not ended or day<=ended) and (r.model=="manual" or bool(q and q[6]&8))
        alpha,var=q[ac:ac+2] if q is not None and len(q)>ac+1 else (None,None)
        picks.append((code,score,eligible,alpha,var))
    return picks


def targets(picks,r,style):
    if not picks:
        return {}
    scores=[a/v if ok and a is not None and v is not None and a>0 and v>0 else 0.0 for _,_,ok,a,v in picks]
    total=sum(scores)
    if style=="tb":
        weights=[s/total if total else 0 for s in scores]
    elif style=="manual":
        weights=[w/100 for w in r.weights]
    else:
        weights=[1/len(picks)]*len(picks)
    return {c:w if ok else 0 for (c,_,ok,_,_),w in zip(picks,weights)}


def opening_rules(store,day):
    encoded=store.bands["days"].get(day)
    if encoded is None:
        return lambda code,raw: raw&3
    patch={v>>3:v&7 for (v,) in struct.iter_unpack("<H",base64.b64decode(encoded,validate=True))}
    ids=store.band_ids
    def flags(code,raw):
        if not raw or code not in ids:
            return raw&3
        value=patch.get(ids[code])
        if value is None:
            return 4 | (raw&3)
        return raw&3 if value&4 else 4 | (value&3)
    return flags


class Book:
    def __init__(self):
        self.cash=1.0
        self.positions={}
        self.peak=self.nav=1.0
        self.dd=self.cost=self.turn=0.0
        self.periods=self.cash_periods=0
        self.curve=[]
        self.orders={"verified":0,"estimated":0,"unquoted":0}

    def advance(self,quotes,weights,fee,rebalance,at_open,day):
        previous=self.nav
        opening={}
        wealth=self.cash
        for c,amount in self.positions.items():
            o=amount*(quotes[c][4] if c in quotes else 1)
            opening[c]=o
            wealth+=o
        sold=requested=0.0
        buys={}
        if rebalance:
            for c in dict.fromkeys((*opening,*weights)):
                delta=weights.get(c,0)*wealth-opening.get(c,0)
                if abs(delta)<=1e-12*wealth:
                    continue
                raw=quotes[c][6]&3 if c in quotes else 0
                flags=at_open(c,raw)
                self.orders["unquoted" if not raw else "verified" if flags&4 else "estimated"]+=1
                if delta<0 and flags&2:
                    sold-=delta
                    opening[c]+=delta
                elif delta>0 and flags&1:
                    buys[c]=delta
                    requested+=delta
        self.cash+=sold*(1-fee)
        bought=min(requested,self.cash/(1+fee))
        scale=bought/requested if requested else 0
        for c,amt in buys.items():
            opening[c]=opening.get(c,0)+amt*scale
        self.cash=max(0,self.cash-bought*(1+fee))
        self.positions={c:v*(quotes[c][5] if c in quotes else 1) for c,v in opening.items() if v>0}
        self.nav=self.cash
        for amt in self.positions.values():
            self.nav+=amt
        self.peak=max(self.peak,self.nav)
        self.dd=min(self.dd,self.nav/self.peak-1)
        turnover=(bought+sold)/wealth
        self.turn+=turnover
        self.cost+=(bought+sold)*fee
        self.periods+=1
        self.cash_periods+=not self.positions
        self.curve.append([day,100*self.nav])
        return wealth,100*(self.nav/previous-1),100*turnover

    def metrics(self):
        return dict(total=100*(self.nav-1),dd=100*self.dd,cost=100*self.cost,turn=100*self.turn/self.periods,
                    cashPeriods=self.cash_periods,execution=self.orders,curve=self.curve)


def display_holdings(book,picks,weights,r):
    records={}
    for i,(code,score,_,alpha,_) in enumerate(picks):
        target=r.weights[i] if r.model=="manual" and r.weighting=="manual" else 100*weights[code]
        records[code]=dict(code=code,value=score,alpha=alpha,weight=target)
    for c in book.positions:
        records.setdefault(c,dict(code=c,value=None,alpha=None,weight=0))
    return records


def valuation(book,quotes,life,day):
    ended=[v for c,v in book.positions.items() if life.get(c,["",""])[1] and life[c][1]<=day]
    stale=sum(not (c in quotes and quotes[c][6]&4) for c in book.positions)
    return dict(endedHeld=len(ended),endedWeight=100*sum(ended)/book.nav,staleHeld=stale)


@lru_cache(maxsize=20)
def _cached_monthly_model(store,r,start,end,risk,snapshot):
    return _compute(store,r,start,end,risk,snapshot)

def run(store,r:Rules,start,end,risk=False,snapshot=None):
    if r.model == 'multi':
        if snapshot is None:
            snapshot = factor_snapshot(store)
    else:
        snapshot = None
    # Only shared model results on an immutable release enter this bounded cache.
    # Return a detached result so display code cannot alter another visitor's calculation.
    if getattr(store,'release_id',None) and not r.daily and r.model!='manual':
        return deepcopy(_cached_monthly_model(store,r,start,end,risk,snapshot))
    return _compute(store,r,start,end,risk,snapshot)

def _compute(store,r:Rules,start,end,risk=False,snapshot=None):
    validate(store,r,start,end)
    main=Book()
    equal=main if r.weighting=="equal" else Book()
    control=Book() if r.model=="pb" else None
    books=[main]+([equal] if equal is not main else [])+([control] if control else [])
    tb=main if r.weighting=='tb' else (Book() if risk else None)
    if tb is not None and tb is not main:
        books.append(tb)
    history=[]; holdings={}; paired_holdings={}
    seen=estimates=other_fits=0
    market_curve=[];market_base=0.;market_peak=100.;market_dd=0.;missing=0;gap=True;segment=None
    first_signal=last_signal=previous=""
    index=list(BENCHMARKS).index(r.bench)
    fee=r.fee/10000
    def state():
        return len(history),set().union(*(b.positions for b in books))
    for signal,day,stop,rows,market,rebalance,pair,ordered in frames(store,r,start,end,state,snapshot):
        if signal>=day or day>stop or previous>=day:
            raise ValueError("研究归档的交易日期顺序异常。")
        previous=stop
        q={v[0]:v for v in rows}
        picks=select(store,r,rows,q,day,pair[1] if pair else None,ordered) if rebalance else []
        peers=select(store,r,rows,q,day,pair[2],True) if control and rebalance else []
        weights=targets(picks,r,r.weighting)
        peer_weights=targets(peers,r,r.weighting)
        observed=sum(ok and a is not None and v is not None for _,_,ok,a,v in picks)
        seen+=sum(p[2] for p in picks)
        estimates+=observed
        other_fits+=sum(ok and a is not None and v is not None for _,_,ok,a,v in peers)
        if not first_signal and any(p[2] for p in picks):
            first_signal=day
        if not history and not r.daily:
            for b in books:
                b.curve.append([day,100.])
        at_open=opening_rules(store,day) if rebalance else None
        wealth,ret,turn=main.advance(q,weights,fee,rebalance,at_open,stop)
        if equal is not main:
            equal.advance(q,targets(picks,r,"equal"),fee,rebalance,at_open,stop)
        if tb is not None and tb is not main:
            tb.advance(q,targets(picks,r,"tb"),fee,rebalance,at_open,stop)
        paired_open=control.advance(q,peer_weights,fee,rebalance,at_open,stop)[0] if control else None
        quote=market[index] if index<len(market) else None
        if quote and min(quote)>0:
            if not market_base:
                market_base=quote[0]
                if not r.daily:
                    market_curve.append([day,100.])
            nav=100*quote[1]/market_base
            market_peak=max(market_peak,nav)
            market_dd=min(market_dd,(nav/market_peak-1)*100)
            market_curve.append([stop,nav])
            if gap:
                segment=dict(from_day=day,base=quote[0],opening=wealth,peer=paired_open)
            gap=False
            segment.update(to=stop,market=100*(quote[1]/segment["base"]-1),main=100*(main.nav/segment["opening"]-1),
                           control=100*(control.nav/segment["peer"]-1) if control else None)
        else:
            gap=True;missing+=1
        has=lambda c:bool(c in q and q[c][6]&4)
        log=dict(signal=signal,entry=day,end=stop,candidates=len(picks),held=len(main.positions),cash=100*main.cash/main.nav,
                 estimated=observed,rebalance=rebalance,filled=sum(p[0] in main.positions for p in picks),
                 stale=sum(not has(c) for c in main.positions),ret=ret,turn=turn)
        if pair:
            log["pool"]=pair[0]
        history.append(log)
        if rebalance:
            last_signal=signal
            holdings=display_holdings(main,picks,weights,r)
            if control:
                paired_holdings=display_holdings(control,peers,peer_weights,r)
    if not history:
        raise ValueError("区间没有可用交易日。" if r.daily else "区间没有完整的月度持有期。")
    if not any(p["rebalance"] for p in history):
        raise ValueError("区间没有覆盖所选的调仓月份。")
    if not seen and r.model!="manual":
        raise ValueError("调仓信号日没有符合条件的股票，请调整区间或市场。")
    def finalize(book,record):
        for code,h in record.items():
            w=100*book.positions.get(code,0)/book.nav
            ended=store.stock_life.get(code,["",""])[1]
            h.update(endWeight=w,ended=ended if w and ended and ended<=previous else "",stale=w>0 and not has(code))
        return list(record.values())
    mv=valuation(main,q,store.stock_life,previous)
    out=dict(months=history,main=main.metrics(),equal={**equal.metrics(),"valuation":valuation(equal,q,store.stock_life,previous)},
             market={"total":market_curve[-1][1]-100,"dd":market_dd} if market_curve and not missing else None,
             marketCurve=market_curve if not missing else [],holdings=finalize(main,holdings),valuation=mv,
             firstSelection=first_signal,lastSignal=last_signal,missingFits=r.weighting=="tb" and not estimates,
             overlap=None,limitCoverage=store.bands["coverage"])
    if missing and segment:
        out["overlap"]={"from":segment["from_day"],**{k:segment[k] for k in ("to","market","main","control")}}
    if risk:
        def proportions(book):
            return {c:v/book.nav for c,v in book.positions.items() if v>0}
        variants={'equal':equal,'tb':tb}
        if r.weighting=='manual':
            variants['manual']=main
        out['riskSnapshot']={'end':previous,'asOf':store.day,'books':{k:proportions(b) for k,b in variants.items()}}
    if control:
        out["control"]={**control.metrics(),"missingFits":r.weighting=="tb" and not other_fits,"holdings":finalize(control,paired_holdings),
                        "cash":100*control.cash/control.nav,"valuation":valuation(control,q,store.stock_life,previous)}
    return out
