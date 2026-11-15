"""Ex-post contribution to volatility at actual closing weights on a common sample."""
from itertools import groupby
import math

import numpy as np

from .frames import DailyBlock


def estimate(codes,returns,books):
    complete=np.isfinite(returns).all(axis=1)
    sample=returns[complete]
    ix={c:i for i,c in enumerate(codes)}
    result={}
    for key,weights in books.items():
        ranked=sorted(weights,key=lambda c:(-weights[c],c))
        pos=[ix[c] for c in ranked]
        w=np.array([weights[c] for c in ranked])
        item=dict(cash=max(0.,100*(1-w.sum())),rows=[],matrix=[],codes=[],vol=None)
        result[key]=item
        if not ranked:
            item.update(state='cash',vol=0.)
            continue
        item['state']='short'
        if len(sample)<60:
            continue
        x=sample[:,pos]
        x=x-x.mean(axis=0)
        portfolio=x@w
        var=float(portfolio@portfolio/(len(x)-1))
        item['vol']=100*math.sqrt(252*var)
        if var<=1e-24:
            item['state']='constant'
            continue
        cov=x.T@portfolio/(len(x)-1)
        shares=100*w*cov/var
        item.update(state='ok',rows=sorted([[c,float(100*f),float(s),float(s*item['vol']/100)]
                                            for c,f,s in zip(ranked,w,shares)],key=lambda r:(-r[2],r[0])))
        names=ranked[:12]
        subset=x[:,:len(names)]
        scale=np.linalg.norm(subset,axis=0)
        denominator=np.outer(scale,scale)
        corr=np.full(denominator.shape,np.nan)
        np.divide(subset.T@subset,denominator,out=corr,where=denominator>0)
        item['codes']=names
        item['matrix']=[[float(np.clip(v,-1,1)) if np.isfinite(v) else None for v in row] for row in corr]
    return result,complete


def risk_view(store,body):
    end,books=body.get('end'),body.get('books')
    if not isinstance(end,str) or end not in store.date_ids or not isinstance(books,dict) or not books or set(books)-{'manual','equal','tb'}:
        raise ValueError('请使用本次回测生成的期末持仓。')
    for positions in books.values():
        if (not isinstance(positions,dict) or any(c not in store.stock_life or type(w) not in (int,float)
                or not math.isfinite(w) or not 0<w<=1.00000001 for c,w in positions.items())
                or sum(positions.values())>1.00000001):
            raise ValueError('实际持仓权重无效。')
    dates=store.daily['dates']
    stop=store.date_ids[end]+1
    window=dates[max(0,stop-120):stop]
    codes=sorted(set().union(*books.values()))
    returns=np.full((len(window),len(codes)),np.nan)
    dst={d:i for i,d in enumerate(window)}
    months={d[:6] for d in window}
    if codes:
        warm=getattr(store,'prefetch',None)
        if warm:
            warm(store.daily['parts'][m] for m in sorted(months))
        for month,g in groupby(dates,key=lambda d:d[:6]):
            if month not in months:
                continue
            trading=list(g)
            block=DailyBlock(store._blob(store.daily['parts'][month]),trading,store.daily['codes'])
            tick=[i for i,d in enumerate(trading) if d in dst]
            dest=[dst[trading[i]] for i in tick]
            for j,c in enumerate(codes):
                if c not in block.ids:
                    continue
                op,close,ref=block.quotes[:,block.ids[c],:][:,tick]
                listed,ended=store.stock_life[c]
                first=max(listed or '', '20211115' if c.endswith('.BJ') else '')
                valid=(op>0)&(close>0)&(ref>0)&np.array([first<=trading[i] and (not ended or trading[i]<=ended) for i in tick])
                returns[np.array(dest)[valid],j]=close[valid]/ref[valid]-1
    items, complete=estimate(codes,returns,books)
    used=[d for d,ok in zip(window,complete) if ok] if codes else []
    return dict(day=store.day,end=end,start=window[0],sessions=len(window),common=len(used),
                first=used[0] if used else None,last=used[-1] if used else None,books=items)
