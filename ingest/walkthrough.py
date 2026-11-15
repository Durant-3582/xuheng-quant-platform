"""Build a labelled development universe directly from the independent import."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import build
import download
import sync


STOCKS = '600000.SH 600519.SH 000001.SZ 300750.SZ 600036.SH 601318.SH 000858.SZ 920185.BJ 920002.BJ 600625.SH'.split()
INDICES = '000001.SH 399001.SZ 000300.SH 000905.SH 000852.SH 399006.SZ 899050.BJ 000016.SH'.split()


def prepare(source, sample, day, start, *, from_provider=False):
    snap = sync.read(source/'snapshot'/(day+'.gz'))
    chosen = set(STOCKS + INDICES)
    snap['items'] = [r for r in snap['items'] if r[0] in chosen]
    if {r[0] for r in snap['items']} != chosen:
        raise ValueError('试建目录未包含选定标的。')
    sync.save(sample/'snapshot'/(day+'.gz'), snap)
    def history(row):
        code = row[0]
        dest = sample/'series'/(code+'.gz')
        src = source/'series'/(code+'.gz')
        if from_provider:
            endpoint='daily' if row[2]=='stock' else 'index_daily'
            results=sync.listing(endpoint,{'ts_code':code,'start_date':start,'end_date':day},sync.FIELDS,4000)
            if any(r['ts_code']!=code or not start<=r['trade_date']<=day for r in results):
                raise ValueError('证券或日期与请求不符。')
            bars=sorted((bar for r in results if (bar:=sync.bar(r)) is not None),key=lambda r:r[0])
            if len({r[0] for r in bars})!=len(bars):raise ValueError('行情存在重复日。')
            series={'symbol':code,'bars':bars,'until':day,'status':'ready' if bars else 'empty'}
        else:series = sync.read(src) if src.is_file() else sync.historical(row,day)
        series['bars'] = [bar for bar in series['bars'] if start <= bar[0] <= day]
        if not series['bars'] and series['status'] == 'ready':series['status']='empty'
        sync.save(dest,series)
    with ThreadPoolExecutor(5) as pool:
        list(pool.map(history,snap['items']))
    days = [r[0] for r in sync.read(sample/'series/000001.SH.gz')['bars']]
    values = {d:{} for d in days}
    bands = {d:[] for d in days}
    for code in STOCKS:
        aliases = [a for a,c in snap['aliases'].items() if c == code and a != code]
        for symbol in [*aliases,code]:
            for api,fields in [('daily_basic','pb'),('stk_limit','up_limit,down_limit')]:
                params = {'ts_code':symbol,'start_date':start,'end_date':day}
                rows=sync.listing(api,params,'ts_code,trade_date,'+fields,4000)
                for r in rows:
                    date=r['trade_date']
                    if r['ts_code']!=symbol or not start<=date<=day:
                        raise ValueError('试建数据的证券或日期不匹配。')
                    if date not in values:continue
                    if api=='daily_basic':values[date][symbol]=sync.number(r['pb'])
                    else:bands[date].append([symbol,r['up_limit'],r['down_limit']])
    for d in days:
        if not values[d] or not bands[d]:raise ValueError('缺少试建市场截面 '+d)
        sync.save(sample/'pb'/(d+'.gz'),values[d]);sync.save(sample/'open-bands'/(d+'.gz'),bands[d])
    return days


def from_tushare(dest, token, day='20261113'):
    """Initialize a bounded private QA archive in this deployment's own storage."""
    import disclosures
    sync.token=token;sync.frequency=60/100
    hist=dest/'history'
    allfiles=sync.inventory(day)
    items=[r for r in allfiles['items'] if r[0] in set(STOCKS+INDICES)]
    directory={**allfiles,'items':items,'aliases':{k:v for k,v in allfiles['aliases'].items() if v in STOCKS}}
    snapshot=sync.one_day(day,directory)
    sync.save(hist/'snapshot'/(day+'.gz'),snapshot)
    prepare(hist,hist,day,'20230101',from_provider=True)
    disclosures.seed(hist,day,sample=True)
    build.build_database(hist,dest/'database',day,sample=True)


if __name__ == '__main__':
    download.authenticate(45)
    source=sync.STORE
    cutoff=sorted((source/'snapshot').glob('*.gz'))[-1].stem
    dest=source.parent/'walkthrough'
    days=prepare(source,dest/'history',cutoff,'20230101')
    build.build_database(dest/'history',dest/'database',cutoff,sample=True)
    print(f'验收样本已生成，{len(STOCKS)} 只股票、{len(INDICES)} 个指数、{len(days)} 个交易日。',flush=True)
