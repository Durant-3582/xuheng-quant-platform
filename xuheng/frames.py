"""Decode the original stock-major market archive only for selected or held securities."""
from __future__ import annotations

import struct
from dataclasses import dataclass
from itertools import groupby

import numpy as np

from .archive import ArchiveError

MODELS = {"mom":"60 日动量","vol":"20 日低波动","rev":"20 日短期反转","pb":"低市净率（PB）","multi":"自定义多因子","manual":"使用自选名单"}
BENCHMARKS = {"000300.SH":"沪深 300","000001.SH":"上证指数","000905.SH":"中证 500","000852.SH":"中证 1000","899050.BJ":"北证 50"}
WEIGHTS = {"equal":"等权","tb":"TB 配权（仅做多）","manual":"手动权重"}
MARKETS = {"":"全 A 股","SH":"沪市","SZ":"深市","BJ":"北交所"}
COL = {"mom":1,"vol":2,"rev":3}


@dataclass(frozen=True)
class Rules:
    model: str = "mom"
    count: int = 10
    weighting: str = "equal"
    cadence: str = "months"
    interval: int = 1
    bench: str = "000300.SH"
    fee: float = 10
    exchange: str = ""
    symbols: tuple = ()
    weights: tuple = ()
    control: str = "mom"
    factor_weights: tuple = ()

    @property
    def daily(self):
        return self.cadence in ("hold","days")


def ranked_pair(ranks, codes, day, rule):
    if day not in ranks:
        raise ArchiveError("缺少所选日期的 PB 股票池。")
    counts, value, momentum, volatility, reversal = ranks[day]
    def take(group):
        out = []
        for i, score in group:
            code = codes[i]
            if not rule.exchange or code.endswith("."+rule.exchange):
                out.append((code,score))
            if len(out) == rule.count:
                break
        return out
    pool = counts[("SH","SZ","BJ").index(rule.exchange)] if rule.exchange else sum(counts)
    return pool, take(value), take({"mom":momentum,"vol":volatility,"rev":reversal}[rule.control])


class BenchFits:
    def __init__(self, buf, which, ticks, codes):
        n, count = struct.unpack_from("<HH",buf,4)
        start = (8+2*count+3)&~3
        if buf[:4]!=b"XHB1" or n!=len(ticks) or len(buf)!=start+count*n*24:
            raise ArchiveError("基准回归数据不完整。")
        ids=np.frombuffer(buf,"<u2",count,8)
        self.by_code={codes[i]:j for j,i in enumerate(ids)}
        self.by_date={d:i for i,d in enumerate(ticks)}
        self.array=np.frombuffer(buf,"<f4",offset=start).reshape(count,n,3,2)
        self.which=which

    def get(self, code, day):
        i = self.by_code.get(code)
        if i is not None:
            a,v=self.array[i,self.by_date[day],self.which]
            if v>0:
                return float(a),float(v)
        return None,None


class DailyBlock:
    def __init__(self, buf, dates, all_codes):
        days, stocks = struct.unpack_from("<HH",buf,4)
        if buf[:4]!=b"XHD1" or days!=len(dates) or not days:
            raise ArchiveError("逐日数据与交易日历不一致。")
        cells=days*stocks
        ids=np.frombuffer(buf,"<u2",stocks,8)
        self.codes=[all_codes[i] for i in ids]
        self.ids={c:i for i,c in enumerate(self.codes)}
        p=(8+2*stocks+3)&~3
        self.quotes=np.frombuffer(buf,"<i4",3*cells,p).reshape(3,stocks,days)
        p+=12*cells
        self.fits=np.frombuffer(buf,"<f4",4*cells,p).reshape(4,stocks,days)
        p+=16*cells
        self.flags=np.frombuffer(buf,"u1",cells,p).reshape(stocks,days)
        p=(p+cells+3)&~3
        self.ranks=[]
        for _ in dates:
            daily=[]
            for _ in range(3):
                n=struct.unpack_from("<H",buf,p)[0]
                daily.append((np.frombuffer(buf,"<u2",n,p+2),np.frombuffer(buf,"<f4",n,p+2+2*n)))
                p+=2+6*n
            self.ranks.append(daily)
        if p!=len(buf):
            raise ArchiveError("逐日研究分片长度异常。")

    def rows(self,t,rule,held,rebalance,pair):
        used={}
        if rebalance:
            if rule.model=="manual":
                used.update((self.ids[c],None) for c in rule.symbols if c in self.ids)
            elif pair:
                used.update((self.ids[c],None) for c,_ in pair[1]+pair[2])
            else:
                ids,values=self.ranks[t][COL[rule.model]-1]
                for idx,value in zip(ids,values):
                    if not rule.exchange or self.codes[idx].endswith("."+rule.exchange):
                        used[int(idx)]=float(value)
                        if len(used)==rule.count:
                            break
        for c in held:
            if c in self.ids:
                used.setdefault(self.ids[c],None)
        rows=[]
        for idx,score in used.items():
            op,cl,ref=map(int,self.quotes[:,idx,t])
            a,v,b,w=map(float,self.fits[:,idx,t])
            flags=int(self.flags[idx,t]) | (4 if cl>0 else 0)
            row=[self.codes[idx],None,None,None,op/ref if op>0 and ref>0 else 1,
                 cl/(op or ref) if cl>0 and (op or ref)>0 else 1,flags,
                 a if v>0 else None,v if v>0 else None,b if w>0 else None,w if w>0 else None]
            if score is not None:
                row[COL[rule.model]]=score
            rows.append(row)
        return rows


def frames(store, rule, start, end, book_state, factor_snapshot=None):
    warm=getattr(store,'prefetch',None)
    if warm:
        meta=['opening-execution','research/'+store.day+'/days-index']
        if not rule.daily:meta.append('research/'+store.day+'/portfolio-index')
        if rule.model=='pb':meta.append('research/'+store.day+'/value-index')
        if rule.bench not in ('000300.SH','000001.SH'):meta.append('research/'+store.day+'/bench-index')
        warm(meta)
    base=store.daily
    dates,codes=base["dates"],base["codes"]
    if rule.model=="multi":
        from .factor_studies import monthly_ranks
        multi_ranks=monthly_ranks(store,rule.exchange,rule.factor_weights,rule.count,factor_snapshot)
    value=store.supplement("value") if rule.model=="pb" else None
    need_proxy=rule.bench not in ("000300.SH","000001.SH")
    bench=store.supplement("bench") if need_proxy else None
    proxy=bench["benchmarks"].index(rule.bench) if bench else None
    width=6 if rule.daily else 4
    plan=[]
    if warm:
        keys=sorted(set(d[:width] for d in dates if start[:width]<=d[:width]<=end[:width]))
        for i,key in enumerate(keys):
            field='parts' if rule.daily else 'annual'
            paths=[base['parts'][key] if rule.daily else store.months['years'][key]]
            if rule.cadence!='hold' or i==0:
                if value:paths.append(value[field][key])
                if bench:paths.append(bench[field][key])
            plan.append((key,paths))
        if not rule.daily:warm(p for _,paths in plan for p in paths)
    fetch_at={k:i for i,(k,_) in enumerate(plan) if i%6==0} if rule.daily else {}
    groups=groupby(enumerate(dates),key=lambda p:p[1][:width])
    for key,group in groups:
        if not start[:width]<=key<=end[:width]:
            continue
        if key in fetch_at:
            pos=fetch_at[key];warm(k for _,paths in plan[pos:pos+6] for k in paths)
        points=list(group)
        if not rule.daily:
            points=[(i,d) for i,d in points if i==0 or dates[i-1][:6]!=d[:6]]
        elif points[-1][1]<start or points[0][1]>end:
            continue
        field="parts" if rule.daily else "annual"
        selection=rule.cadence!="hold" or book_state()[0]==0
        ranks=store.json(value[field][key]) if selection and value else None
        fits=BenchFits(store._blob(bench[field][key]),proxy,[d for _,d in points],codes) if bench and selection else None

        def decorate(day,stop,market,rows):
            if bench:
                a,b=store.date_ids[day],store.date_ids[stop]
                op,cl=bench["market"][a][2*proxy],bench["market"][b][2*proxy+1]
                market=market+[None]*3
                market[2+proxy]=[op,cl] if op>0 and cl>0 else None
                if fits:
                    for row in rows:
                        row.extend(fits.get(row[0],day))
            return market

        if rule.daily:
            block=DailyBlock(store._blob(base["parts"][key]),points,codes)
            for t,(i,day) in enumerate(points):
                if not start<=day<=end:
                    continue
                n,held=book_state()
                rebalance=(n==0 if rule.cadence=="hold" else n%rule.interval==0)
                pair=ranked_pair(ranks,codes,day,rule) if rebalance and ranks is not None else None
                rows=block.rows(t,rule,held,rebalance,pair)
                op,cl,o2,c2=base["market"][i]
                markets=[[op,cl] if op and cl else None,[o2,c2] if o2 and c2 else None]
                yield dates[i-1] if i else "",day,day,rows,decorate(day,day,markets,rows),rebalance,pair,True
        else:
            picks=multi_ranks(key) if rule.model=="multi" else None
            for m in store.json(store.months["years"][key]):
                day,stop=m["entry"],m["end"]
                if day<start or stop>end:
                    continue
                rebalance=(int(day[4:6])-1)%rule.interval==0
                pair=ranked_pair(ranks,codes,day,rule) if rebalance and ranks is not None else None
                if rebalance and picks is not None:
                    pair=picks(m["signal"])
                yield m["signal"],day,stop,m["rows"],decorate(day,stop,m["market"],m["rows"]),rebalance,pair,False
