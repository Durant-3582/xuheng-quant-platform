"""Build a small server-side map of opening decisions, without publishing the vendor's prices.
Run fetch (with TUSHARE_TOKEN), then build after generating the portfolio and daily archives.
Only the official dated limit and the opening print enter a trading decision.
"""
import argparse
import base64
from collections import Counter, defaultdict
import gzip
import hashlib
import os
from pathlib import Path
import struct
import numpy as np
import sync

FIRST = "20070104"


def flags_at(open_scaled, upper, lower):
    if not(open_scaled and upper and lower and upper >= lower > 0):
        return None
    # Quotes in the daily archive have 4 decimals. Comparing in that precision avoids
    # a false touch from rounding the opening price to a whole cent.
    up, down = round(upper*10000), round(lower*10000)
    return int(open_scaled < up) | (int(open_scaled > down) << 1)


def fetch_dates(store, day):
    idx=sync.read(store/'research'/day/'days-index.gz')
    for d in (x for x in idx['dates'] if x>=FIRST):
        path=store/'open-bands'/(d+'.gz')
        if path.exists():continue
        rows=sync.listing('stk_limit',{'trade_date':d},'ts_code,trade_date,up_limit,down_limit',5800)
        if not rows or len({r['ts_code'] for r in rows})!=len(rows) or any(r['trade_date']!=d for r in rows):
            raise ValueError('逐股限价不完整 '+d)
        sync.save(path,[[r['ts_code'],r['up_limit'],r['down_limit']] for r in rows])


def build(store, day, target, require_complete=True):
    rd=store/'research'/day
    idx=sync.read(rd/'days-index.gz');codes=idx['codes'];codeset=set(codes);codeid={c:i for i,c in enumerate(codes)}
    if len(codes)>=8192:raise ValueError('目录已超出限价稀疏编码范围')
    catalog=sync.read(store/'snapshot'/(day+'.gz'));aliases=catalog['aliases'];stats=Counter()
    lifetime={r[0]:[r[6] or '',r[7] or ''] for r in catalog['items'] if r[2]=='stock'}
    ym_days=defaultdict(list)
    for d in idx['dates']:
        if d>=FIRST:ym_days[d[:6]].append(d)
    byday={};month_changes={};missing=[]
    for ym,dates in ym_days.items():
        if all(not (store/'open-bands'/(d+'.gz')).exists() for d in dates):
            missing.extend(dates);continue
        data=gzip.decompress((store/(idx['parts'][ym]+'.gz')).read_bytes())
        magic,nd,n=struct.unpack_from('<4sHH',data)
        assert magic==b'XHD1' and len(dates)==nd
        ids=np.frombuffer(data,'<u2',n,offset=8);pos=(8+2*n+3)&~3;cells=nd*n
        opening=np.frombuffer(data,'<i4',cells,offset=pos).reshape(n,nd)
        origin=np.frombuffer(data,'u1',cells,offset=pos+28*cells).reshape(n,nd)
        for t,d in enumerate(dates):
            file=store/'open-bands'/(d+'.gz')
            if not file.exists():missing.append(d);continue
            prices={}
            for name,up,down in sync.read(file):
                c=aliases.get(name,name)
                if c not in codeset:continue
                a=codeid[c]
                if a in prices and prices[a]!=(up,down):
                    raise ValueError('同一交易日发生代码映射冲突 '+d+' '+c)
                prices[a]=(up,down)
            pairs=[];over={}
            for i in np.flatnonzero(opening[:,t]>0):
                a=int(ids[i]);old=int(origin[i,t])&3
                if not old:raise ValueError('有开盘价而没有原始方向标记 '+d)
                exact=flags_at(int(opening[i,t]),*prices.get(a,(None,None)))
                if exact is None:
                    stats['unknown']+=1;pairs.append((a<<3)|(4|old))
                else:
                    stats['confirmed']+=1
                    if exact!=old:
                        stats['changed']+=1
                        if old&1!=exact&1:stats['buyChanges']+=1
                        if old&2!=exact&2:stats['sellChanges']+=1
                        pairs.append((a<<3)|exact);over[codes[a]]=exact
            packed=np.asarray(pairs,dtype='<u2').tobytes()
            byday[d]=base64.b64encode(packed).decode()
            if t==0:month_changes[d]=over
    if require_complete and missing:raise ValueError('逐股限价日期尚未补齐：'+str(len(missing))+'；首个 '+missing[0])
    required_months={ds[0] for ds in ym_days.values()}
    if not required_months.issubset(byday):raise ValueError('月初建仓日的限价档案不完整')
    # These are independently formed equal-weight cohorts, not a carried portfolio.
    q=defaultdict(list)
    periods=sync.read(rd/'portfolio-index.gz')
    for k in periods['years'].values():
        for m in sync.read(store/(k+'.gz')):
            fixes=month_changes.get(m['entry'],{})
            for name,col,sgn in [('mom',1,-1),('vol',2,1)]:
                rows=sorted((r for r in m['rows'] if r[6]&8 and r[col] is not None),key=lambda r:(sgn*r[col],r[0]))
                for venue in ('all','SH','SZ','BJ'):
                    group=rows if venue=='all' else [r for r in rows if r[0].endswith('.'+venue)]
                    if len(group)<5:continue
                    for i in range(5):
                        gs=group[len(group)*i//5:len(group)*(i+1)//5]
                        sub=[round(100*(r[5]-1),6) if fixes.get(r[0],r[6])&1 else 0 for r in gs]
                        q[(name+'-'+venue,i)].append(sum(sub)/len(sub))
    groups={k:[[sum(q[k,i])/len(q[k,i]),len(q[k,i])] for i in range(5)] for k,_ in q}
    core=dict(format=1,cutoff=day,coverage=dict(verifiedDays=len(byday),vendorDays=len(byday)+len(missing),monthlyDays=len(required_months)),base=idx['version'],codes=codes,life=[lifetime[c] for c in codes],days=byday,groups=groups,stats=dict(stats))
    core['version']=hashlib.sha256(sync.js(core)).hexdigest()
    raw=sync.js(core);out=target.with_suffix('.new');out.write_bytes(raw);out.replace(target)
    sync.save(rd/'opening-execution.gz',core)
    print('session coverage',len(byday),'missing dates',len(missing),'classified',dict(stats),'bytes',target.stat().st_size,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['fetch','build']);p.add_argument('--store',type=Path,default=sync.STORE)
    p.add_argument('--day');p.add_argument('--allow-missing-days',action='store_true',help='Allow a disclosed partial daily release only when every calendar-month opening is archived');p.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'db/opening-release.json');args=p.parse_args()
    cutoff=args.day or sorted((args.store/'snapshot').glob('*.gz'))[-1].stem
    if args.action=='fetch':
        sync.token=os.environ['TUSHARE_TOKEN'];fetch_dates(args.store,cutoff)
    else:build(args.store,cutoff,args.output,require_complete=not args.allow_missing_days)
