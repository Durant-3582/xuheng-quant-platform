"""Fill only missing valuation and exchange-limit dates in the project's private archive."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import download
import opening_limits
import sync
import value


def fill(store, days, workers=8):
    tasks=[]
    for day in reversed(days):
        if not (store/'pb'/(day+'.gz')).exists():tasks.append(('pb',day))
        if day>=opening_limits.FIRST and not (store/'open-bands'/(day+'.gz')).exists():tasks.append(('bands',day))
    def one(task):
        kind, day=task
        if kind=='pb':
            value.fetch_day(store,day)
            return
        rows=sync.listing('stk_limit',{'trade_date':day},'ts_code,trade_date,up_limit,down_limit',5800)
        if not rows or len({r['ts_code'] for r in rows})!=len(rows) or any(r['trade_date']!=day for r in rows):
            raise ValueError('逐股限价截面不完整 '+day)
        sync.save(store/'open-bands'/(day+'.gz'), [[r['ts_code'],r['up_limit'],r['down_limit']] for r in rows])
    with ThreadPoolExecutor(workers) as pool:
        for n,_ in enumerate(pool.map(one,tasks),1):
            if n%300==0 or n==len(tasks):print(f'历史 PB / 开盘限价 {n}/{len(tasks)}',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--rpm',type=int,default=120)
    p.add_argument('--from-day',default=sync.START);p.add_argument('--to-day',default='99999999')
    args=p.parse_args()
    download.authenticate(args.rpm)
    calendar=sync.read(sync.STORE/'series/000001.SH.gz')
    fill(sync.STORE,[r[0] for r in calendar['bars'] if args.from_day<=r[0]<=args.to_day])
