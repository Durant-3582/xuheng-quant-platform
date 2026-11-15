"""Current financial screening, percentile scoring and next-month factor tests."""
from collections import defaultdict
from datetime import date
import gzip
import io
import json
import math

import numpy as np

from .disclosed import latest, revisions
from .study_store import bucket, content, edition, security_id

FACTORS = ('mom','vol','pb','roe','pe','turn')
DIRECTIONS = np.asarray([1,-1,-1,1,-1,1])
EXCHANGES = ('','SH','SZ','BJ')


def read(index,key,reader):
    return json.loads(gzip.decompress(content(index,key,reader)))


def weights(settings):
    values = settings.get('weights')
    if not isinstance(values,dict) or not values or set(values)-set(FACTORS):
        raise ValueError('请选择有效的因子。')
    result = [values.get(k,0) for k in FACTORS]
    if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=100 for v in result):
        raise ValueError('每项因子权重须为 0 至 100。')
    if not math.isclose(sum(result),100,abs_tol=0.005):
        raise ValueError('因子权重之和须为 100%。')
    return np.array(result,dtype=float)


def percentile(a):
    if len(a)==1:
        return np.array([50.])
    unique, inverse, counts = np.unique(a,return_inverse=True,return_counts=True)
    middle = np.cumsum(counts)-(counts+1)/2
    return 100*middle[inverse]/(len(a)-1)


def scored(matrix, w, venue):
    chosen=np.flatnonzero(w)
    keep=np.all(np.isfinite(matrix[:,1+chosen]),axis=1)
    for value_col in (2,4):  # PB and PE
        if w[value_col]:
            keep &= matrix[:,value_col+1]>0
    if venue:
        keep &= matrix[:,0]//1000000==EXCHANGES.index(venue)
    rows=matrix[keep]
    if not len(rows):
        return rows, np.empty(0), np.empty((0,len(chosen)))
    parts=np.column_stack([percentile(rows[:,i+1]*DIRECTIONS[i]) for i in chosen])
    # Equivalent weighted ranks can differ by a floating-point ulp. Keep
    # mathematical ties together for both stock ordering and Spearman IC.
    score=np.round((parts*(w[chosen]/w.sum())).sum(axis=1),11)
    return rows, score, parts


def window(body, maximum):
    start,end=body.get('from',''),body.get('to','')
    try:
        if any(type(v)!=str or len(v)!=8 or date.fromisoformat(v).strftime('%Y%m%d')!=v for v in (start,end)):
            raise ValueError
    except ValueError:
        raise ValueError('请填写有效的起止日期。') from None
    if not '20000101'<=start<=end<=maximum:
        raise ValueError('请检查日期顺序，并使用研究库截止日以内的区间。')
    return start,end


def rho(a,b):
    if len(a)<5 or np.ptp(a)==0 or np.ptp(b)==0:
        return None
    x,y=percentile(a),percentile(b)
    x-=x.mean()
    y-=y.mean()
    return float(np.dot(x,y)/(np.linalg.norm(x)*np.linalg.norm(y)))


def score_order(rows, score):
    ids = rows[:, 0].astype(np.int64)
    suffix_order = np.array([0, 1, 2, 0])  # A code sorts by its digits, then BJ, SH, SZ.
    return np.lexsort((suffix_order[ids // 1000000], ids % 1000000, -score))


def monthly_ranks(store, venue, factor_weights, count, snapshot):
    index = {'day': snapshot[0], 'files': dict(snapshot[1])}
    reader = getattr(store,'service','')
    codes = {security_id(c):c for c in store.stock_life}
    w = np.asarray(factor_weights,dtype=float)
    def year_picker(year):
        key = 'panel/'+year
        if key not in index['files']:
            raise ValueError('多因子研究库尚未覆盖该年份，截止日为 '+index['day']+'。')
        data = content(index,key,reader)
        def choose(day):
            with np.load(io.BytesIO(data),allow_pickle=False) as archive:
                if day not in archive:
                    raise ValueError('该月末的因子数据尚未入库，请缩短区间或待盘后更新。')
                # Future holding returns are deliberately excluded from the selection input.
                rows, scores, _ = scored(archive[day][:,:7],w,venue)
            top = score_order(rows,scores)[:count]
            return len(rows), [(codes[int(rows[i,0])],float(scores[i])) for i in top], []
        return choose
    return year_picker


def factor_overlap(panel, venue):
    fields = panel[:, 1:7]
    usable = np.isfinite(fields).all(axis=1) & (fields[:, 2] > 0) & (fields[:, 4] > 0)
    if venue:
        usable &= panel[:, 0] // 1000000 == EXCHANGES.index(venue)
    common = fields[usable] * DIRECTIONS
    if len(common) < 5:
        return None
    ranks = np.column_stack([percentile(col) for col in common.T])
    centered = ranks - ranks.mean(axis=0)
    norms = np.linalg.norm(centered, axis=0)
    scale = np.outer(norms, norms)
    correlations = np.full(scale.shape, np.nan)
    np.divide(centered.T @ centered, scale, out=correlations, where=scale > 0)
    return correlations, len(common)


def test_factors(index,reader,w,venue,body):
    start,end=window(body,index['day'])
    months=[]
    prior = {}
    horizons = {h: [] for h in (1,2,3,6)}
    shape = (len(FACTORS), len(FACTORS))
    corr_sum, corr_months = np.zeros(shape), np.zeros(shape, dtype=int)
    common_pairs = 0
    for year,periods in sorted(index['years'].items()):
        use=[p for p in periods if p[1]>=start and p[2]<=end]
        if not use:
            continue
        with np.load(io.BytesIO(content(index,'panel/'+year,reader)),allow_pickle=False) as block:
            for sig,entry,last in use:
                panel = block[sig]
                rows,score,_=scored(panel,w,venue)
                serial = int(entry[:4])*12 + int(entry[4:6])
                prior.pop(serial-6, None)
                if len(rows)>=5 and np.ptp(score)>0:
                    prior[serial] = (rows[:,0], score)
                realized = block['returns_'+sig]
                for horizon, correlations in horizons.items():
                    previous = prior.get(serial-horizon+1)
                    if previous is None:
                        continue
                    ids, original = previous
                    _, left, right = np.intersect1d(ids,realized[:,0],assume_unique=True,return_indices=True)
                    value = rho(original[left],realized[right,1])
                    if value is not None:
                        correlations.append((value,len(left)))
                overlap = factor_overlap(panel,venue)
                if overlap is not None:
                    matrix, n_common = overlap
                    common_pairs += n_common
                    valid = np.isfinite(matrix)
                    corr_sum[valid] += matrix[valid]
                    corr_months[valid] += 1
                if len(rows)<5 or np.ptp(score)==0:
                    continue
                paired=np.isfinite(rows[:,-2])
                ic=rho(score[paired],rows[paired,-2])
                order=score_order(rows,score)
                cohorts=[rows[order[len(rows)*i//5:len(rows)*(i+1)//5],-1] for i in range(5)]
                months.append(dict(signal=sig,entry=entry,end=last,n=len(rows),paired=int(paired.sum()),ic=ic,
                                   groups=[float(g.mean()) for g in cohorts],medians=[float(np.median(g)) for g in cohorts]))
    years=defaultdict(list)
    for m in months:
        years[m['end'][:4]].append(m)
    def stats(items):
        ics=[m['ic'] for m in items if m['ic'] is not None]
        return dict(months=len(items),nIC=len(ics),meanIC=float(np.mean(ics)) if ics else None,
                    positive=100*sum(v>0 for v in ics)/len(ics) if ics else None,
                    groups=np.mean([m['groups'] for m in items],axis=0).tolist() if items else [],
                    medians=np.mean([m['medians'] for m in items],axis=0).tolist() if items else [],
                    pairs=sum(m['paired'] for m in items))
    persistence = [[h,len(ic),float(np.mean([v for v,_ in ic])) if ic else None,sum(n for _,n in ic)] for h,ic in horizons.items()]
    overlap_rows = [[FACTORS[i],FACTORS[j],float(corr_sum[i,j]/corr_months[i,j]) if corr_months[i,j] else None,
                     int(corr_months[i,j])] for i in range(len(FACTORS)) for j in range(i+1,len(FACTORS))]
    return dict(summary=stats(months),annual=[[y,stats(ms)] for y,ms in years.items()],months=months,
                persistence=persistence,overlap=overlap_rows,commonPairs=common_pairs)


def paging(body,count):
    page=body.get('page',0)
    if type(page)!=int or not 0<=page<=10000:
        raise ValueError('结果页码无效。')
    page=min(page,max(0,(count-1)//25))
    return page,slice(page*25,(page+1)*25)


def screen(index,reader,current,body):
    period=body.get('period','latest')
    if period not in ['latest',*index['periods']]:
        raise ValueError('请选择有数据的报告期。')
    low,high=body.get('minROE'),body.get('maxDebt')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (low,high)) or not 0<=high<=1000:
        raise ValueError('请填写有效的 ROE 下限和负债率上限。')
    col={'roe':3,'gross':4,'debt':5,'revenue':6,'profit':7,'pe':8}.get(body.get('sort','revenue'))
    if col is None:
        raise ValueError('排序指标无效。')
    lookup=read(index,'fin/'+period,reader)
    base=[r for r in current if not body.get('venue') or r[0].endswith('.'+body['venue'])]
    rows=[]
    available=0
    for item in base:
        row=lookup.get(item[0])
        if not row or row[3] is None or row[5] is None:
            continue
        extended=[*row,item[5]]
        if extended[col] is None or col==8 and extended[col]<=0:
            continue
        available+=1
        if row[3]>=low and row[5]<=high:
            rows.append((item[0],extended))
    sign=1 if col in (5,8) else -1
    rows.sort(key=lambda v:(sign*v[1][col],v[0]))
    page,sl=paging(body,len(rows))
    return dict(rows=rows[sl],total=len(rows),page=page,pool=len(base),available=available,periods=index['periods'])


def analyze(store,body):
    index=edition(store)
    reader=getattr(store,'service','')
    action=body.get('action')
    venue=body.get('venue','')
    if venue not in EXCHANGES:
        raise ValueError('交易市场无效。')
    if action=='meta':
        result={'counts':index['counts'],'periods':index['periods'],'defaultPeriod':index['defaultPeriod']}
    elif action=='breadth':
        if 'breadth' not in index['files']:
            raise ValueError('该期研究库的均线宽度尚未更新。')
        result={'rows':read(index,'breadth',reader)}
    elif action=='reports':
        code=body.get('code')
        if code not in store.catalog or store.catalog[code][2]!='stock':
            raise ValueError('请选择个股。')
        raw=read(index,'reports/'+str(bucket(code)),reader).get(code,[])
        result={'rows':latest(revisions(raw),index['day'])[:12]}
    elif action=='screen':
        result=screen(index,reader,read(index,'current',reader),body)
    elif action=='rank':
        w=weights(body)
        current=read(index,'current',reader)
        codes={security_id(r[0]):r[0] for r in current}
        matrix=np.asarray([[security_id(r[0]),*r[1:]] for r in current],dtype=float)
        rows,score,parts=scored(matrix,w,venue)
        order=score_order(rows,score)
        page,sl=paging(body,len(order))
        cols=np.flatnonzero(w)
        years=read(index,'quality',reader) if w[3] else {}
        result=dict(page=page,total=len(rows),pool=sum(not venue or r[0].endswith('.'+venue) for r in current),
                    keys=[FACTORS[i] for i in cols],rows=[])
        for pos in order[sl]:
            code=codes[int(rows[pos,0])]
            result['rows'].append([code,float(score[pos]),rows[pos,1+cols].tolist(),parts[pos].tolist(),years.get(code)])
    elif action=='test':
        result=test_factors(index,reader,weights(body),venue,body)
    elif action in ('sectors','rotation'):
        from .industry_study import industry_request
        result=industry_request(store,index,reader,body)
    else:
        raise ValueError('研究操作无效。')
    return {**result, 'cutoff':index['day']}
