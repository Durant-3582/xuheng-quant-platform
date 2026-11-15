from collections import deque
from functools import lru_cache


def rolling_beta(stock,index,n=120):
    market={}
    for prev,bar in zip(index,index[1:]):
        ref=bar[5] if bar[5] is not None else prev[4]
        if bar[4] and ref and bar[4]>0 and ref>0:
            market[bar[0]]=(prev[0],bar[4]/ref-1)
    buf=deque(); sx=sy=sxx=sxy=0.;hits=0;result=[]
    for prev,b in zip(stock,stock[1:]):
        match=market.get(b[0])
        if not match or prev[0]!=match[0] or not all(v is not None and v>0 for v in (b[4],b[5],b[7],prev[7])):
            continue
        x,y=match[1],b[4]/b[5]-1
        buf.append((x,y));sx+=x;sy+=y;sxx+=x*x;sxy+=x*y;hits+=1
        if len(buf)>n:
            a,c=buf.popleft();sx-=a;sy-=c;sxx-=a*a;sxy-=a*c
        if len(buf)==n:
            var=sxx-sx*sx/n
            if var>1e-12*max(sxx,1e-10):result.append([b[0],(sxy-sx*sy/n)/var])
    return hits,result


@lru_cache(maxsize=2)
def coverage_by_code(store):
    return {r[0]:r for r in store.coverage}


@lru_cache(maxsize=4)
def codes(store,kind):
    return sorted(c for c,r in store.catalog.items() if r[2]==kind)


def common_series(rows1,rows2):
    index={r[0]:r[4] for r in rows2 if r[4] and r[4]>0}
    aligned=[(r[0],r[4],index[r[0]]) for r in rows1 if r[0] in index and r[4] and r[4]>0]
    if not aligned:return [],[]
    return ([(d,p/aligned[0][1]*100) for d,p,_ in aligned],[(d,v/aligned[0][2]*100) for d,_,v in aligned])
