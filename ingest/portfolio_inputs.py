"""Build independent, versioned PB ranks and benchmark regressions on the existing exchange calendar."""
from collections import defaultdict
from pathlib import Path
import argparse
import gzip
import hashlib
import struct
import tempfile

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

import sync
from trading_days import previous_window, LIMIT

EXTRA = ("000905.SH", "000852.SH", "899050.BJ")


def save_part(output, name, data, hashes):
    blob = gzip.compress(data, compresslevel=4, mtime=0)
    if len(blob) > 6_000_000:
        raise ValueError("研究分片超过上限 " + name)
    digest = hashlib.sha256(blob).hexdigest()
    name += "-" + digest
    path = output/(name+".gz")
    temp = path.with_suffix(".part")
    temp.write_bytes(blob)
    temp.replace(path)
    hashes[name] = digest
    return "research/"+output.name+"/"+name


def finish(output, name, obj, hashes):
    obj["version"] = hashlib.sha256(sync.js(obj)).hexdigest()
    path = output/(name+"-index.gz")
    sync.save(path, obj)
    hashes[name+"-index"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output/(name+"-digests.json")).write_bytes(sync.js(hashes))
    print(name, len(hashes), "个研究分片已校验", flush=True)


def fit_on_signals(g, ratio, market, count):
    result = np.zeros((count, 2), dtype="<f4")
    paired = np.r_[False, np.diff(g) == 1] & np.isfinite(market[g])
    x, y = market[g[paired]], ratio[paired] - 1
    if len(x) < 120:
        return result
    sx, sy = previous_window(x, 120), previous_window(y, 120)
    xx = previous_window(x*x, 120) - sx*sx/120
    xy = previous_window(x*y, 120) - sx*sy/120
    beta = np.divide(xy, xx, out=np.zeros_like(xy), where=xx>1e-12)
    variance = (previous_window(y*y, 120)-sy*sy/120-beta*xy)/118
    valid = (xx>1e-12) & (variance>1e-12)
    alpha = np.where(valid, np.round((sy-beta*sx)/120, 10), 0)
    variance = np.where(valid, np.round(variance, 12), 0)
    last = np.searchsorted(g[paired][119:], g, side="right")-1
    usable = (last>=0) & (g+1<count)
    result[g[usable]+1] = np.column_stack((alpha[last[usable]], variance[last[usable]]))
    return result


def calendar_groups(dates):
    months, years = defaultdict(list), defaultdict(list)
    for i, d in enumerate(dates):
        if not months[d[:6]]:
            years[d[:4]].append(i)
        months[d[:6]].append(i)
    return months, years


def bench_build(store, day, base, output):
    dates, codes = base["dates"], base["codes"]
    keys = {d:i for i,d in enumerate(dates)}
    size = len(dates)
    metadata = {r[0]:r for r in sync.read(store/"snapshot"/(day+".gz"))["items"]}
    def history(c):
        s = sync.read(store/"series"/(c+".gz"))
        if s["symbol"] != c or s["until"] < day:
            raise ValueError("日线未就绪 "+c)
        return s["bars"]
    prices = np.zeros((size, 2*len(EXTRA)))
    idx = []
    for j, c in enumerate(EXTRA):
        bars = {b[0]:b for b in history(c) if b[0]>=metadata[c][6]}
        returns = np.full(size, np.nan)
        for i,d in enumerate(dates):
            b = bars.get(d)
            if b and b[1] and b[4]:
                prices[i,j*2:j*2+2] = b[1], b[4]
            if i and b and dates[i-1] in bars and b[4] and (prev:=b[5] or bars[dates[i-1]][4]):
                returns[i] = b[4]/prev-1
        idx.append(returns)
    months, years = calendar_groups(dates)
    hashes = {}
    cache = output/"signal-factors.npy"
    with tempfile.TemporaryDirectory(dir=store) as folder:
        # The ranking and fits stored at entry t use only quotes up to close t-1.
        scores = np.lib.format.open_memmap(cache.with_suffix(".part"), mode="w+", dtype="<f8", shape=(3,len(codes),size))
        fits = np.memmap(Path(folder)/"fits", mode="w+", dtype="<f4", shape=(len(codes), size, 6))
        for i,c in enumerate(codes):
            bars = [b for b in history(c) if b[0] in keys and all(b[k] is not None and b[k]>0 for k in (1,2,3,4,5,7))]
            scores[:,i,:] = np.nan
            if not bars:
                continue
            g = np.array([keys[b[0]] for b in bars])
            if np.any(np.diff(g)<=0):
                raise ValueError("重复或乱序日线 "+c)
            ratio = np.array([b[4]/b[5] for b in bars])
            if len(g)>=60:
                dest = g[59:] + 1
                ok = dest<size
                scores[0,i,dest[ok]] = np.round((np.prod(sliding_window_view(ratio,60),axis=1)[ok]-1)*100,5)
            if len(g)>=20:
                recent=sliding_window_view(ratio,20)
                dest=g[19:]+1
                ok=dest<size
                scores[1,i,dest[ok]]=np.round(np.std(recent,axis=1,ddof=1)[ok]*np.sqrt(252)*100,5)
                scores[2,i,dest[ok]]=np.round((np.prod(recent,axis=1)[ok]-1)*100,5)
            for j,mkt in enumerate(idx):
                fits[i,:,2*j:2*j+2] = fit_on_signals(g,ratio,mkt,size)
            if (i+1)%1000==0:
                print("基准与动量",i+1,"/",len(codes),flush=True)
        scores.flush()
        del scores
        cache.with_suffix(".part").replace(cache)
        def encode(label, groups):
            refs = {}
            for key, ticks in groups.items():
                f = fits[:,ticks,:]
                active = np.flatnonzero(np.any(f[:,:,1::2]>0,axis=(1,2)))
                header = struct.pack("<4sHH",b"XHB1", len(ticks),len(active))+active.astype("<u2").tobytes()
                blob = header + bytes((-len(header))%4) + f[active].astype("<f4").tobytes(order="C")
                refs[key] = save_part(output,"bench-"+label+key,blob,hashes)
            return refs
        parts, annual = encode("d", months), encode("m", years)
    finish(output,"bench",dict(format=1,day=day,base=base["version"],benchmarks=EXTRA,
                               market=prices.tolist(),parts=parts,annual=annual),hashes)


def value_build(store, day, base, output):
    dates, codes = base["dates"], base["codes"]
    scores = np.load(output/"signal-factors.npy",mmap_mode="r")
    if scores.shape!=(3,len(codes),len(dates)):
        raise ValueError("因子矩阵与目录不符")
    aliases = sync.read(store/"snapshot"/(day+".gz"))["aliases"]
    ids = {c:i for i,c in enumerate(codes)}
    venues = np.array([("SH","SZ","BJ").index(c[-2:]) for c in codes])
    months,_ = calendar_groups(dates)
    hashes, parts, annual, year_rows = {}, {}, {}, {}
    first, last, observations = None, None, 0
    for d in dates:
        if not (store/"pb"/(d+".gz")).is_file():
            raise ValueError("缺少历史 PB "+d+"，请先补齐每日指标。")
    for ym,ticks in months.items():
        rows = {}
        for t in ticks:
            counts = [0,0,0]
            if t==0:
                rows[dates[t]] = [counts,[],[],[],[]]
                continue
            signal = dates[t-1]
            v = sync.read(store/"pb"/(signal+".gz"))
            if not v:
                raise ValueError("缺历史 PB "+signal)
            pb = np.full(len(codes),np.nan)
            for c,p in v.items():
                k=ids.get(aliases.get(c,c))
                if k is not None and p is not None and p>0:
                    if np.isfinite(pb[k]) and pb[k]!=p:
                        raise ValueError("北交所新旧代码 PB 冲突 "+signal+" "+c)
                    pb[k]=p
            active=np.flatnonzero(np.isfinite(pb)&np.isfinite(scores[:,:,t]).all(axis=0))
            counts=np.bincount(venues[active],minlength=3).tolist()
            if len(active):
                first=first or signal
                last=signal
            observations+=len(active)
            result=[counts]
            for values,descending in ((pb,False),(scores[0,:,t],True),(scores[1,:,t],False),(scores[2,:,t],False)):
                ordered=active[np.argsort(-values[active] if descending else values[active],kind="stable")]
                take=np.zeros(len(codes),dtype=bool)
                for venue in range(3):
                    take[ordered[venues[ordered]==venue][:LIMIT]]=True
                ranked=ordered[take[ordered]]
                result.append([[int(i),float(values[i])] for i in ranked])
            rows[dates[t]]=result
        parts[ym]=save_part(output,"value-d"+ym,sync.js(rows),hashes)
        year_rows[dates[ticks[0]]]=rows[dates[ticks[0]]]
        if ym.endswith("12") or ym==dates[-1][:6]:
            year=ym[:4]
            annual[year]=save_part(output,"value-m"+year,sync.js(year_rows),hashes)
            year_rows={}
    finish(output,"value",dict(format=1,day=day,base=base["version"],parts=parts,annual=annual,
                               firstSignal=first,lastSignal=last,observations=observations),hashes)


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("kind",choices=("bench","value"))
    p.add_argument("--date",required=True)
    args=p.parse_args()
    output=sync.STORE/"research"/args.date
    base=sync.read(output/"days-index.gz")
    (bench_build if args.kind=="bench" else value_build)(sync.STORE,args.date,base,output)
