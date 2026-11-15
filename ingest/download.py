"""Resumable first import from Tushare. The website never waits for this job."""
import argparse
import collections
import concurrent.futures
import datetime as dt
import json
import os
from pathlib import Path
import threading
from zoneinfo import ZoneInfo

import sync


def authenticate(rpm):
    local_key = sync.BASE / '.private' / 'tushare-token'
    sync.token = os.getenv('TUSHARE_TOKEN') or (local_key.read_text().strip() if local_key.exists() else '')
    if not sync.token:
        raise ValueError('请先配置 Tushare Token。')
    sync.frequency = 60 / rpm


def last_session(stop):
    start = (dt.date.fromisoformat(stop) - dt.timedelta(days=30)).strftime('%Y%m%d')
    dates = sync.api('trade_cal', {'exchange':'SSE', 'is_open':'1', 'start_date':start, 'end_date':stop}, 'cal_date')
    for day in sorted({r['cal_date'] for r in dates}, reverse=True):
        if sync.api('daily', {'trade_date':day, 'limit':1}, 'ts_code,trade_date'):
            return day
    raise ValueError('未找到已经公布收盘数据的交易日。')


def directory_and_snapshot(store, day):
    path = store / 'directory' / (day + '.gz')
    if not path.exists():
        sync.save(path, sync.inventory(day))
    directory = sync.read(path)
    snap = store / 'snapshot' / path.name
    if not snap.exists():
        quotes = sync.day_quotes(day, directory)
        if not {'000001.SH', '399001.SZ'}.issubset(quotes):
            raise ValueError('沪深基准的收盘数据尚未齐备。')
        sync.save(snap, sync.one_day(day, directory, quotes, pb_store=store))
    return directory


def histories(store, day, entries, workers=12):
    mapping = {r[0]:r for r in entries}
    ordered = list(dict.fromkeys([c for c in sync.PRIORITY if c in mapping] + sorted(mapping)))
    denied, lock = set(), threading.Lock()
    def pull(code):
        dest = store / 'series' / (code + '.gz')
        old = sync.read(dest) if dest.exists() else None
        if old and old['until'] == day:
            return old['status']
        item = mapping[code]
        family = code.rsplit('.',1)[1] if item[8] == 'industry' and code.endswith(('.SI','.CI')) else None
        with lock:
            blocked = family in denied
        try:
            if blocked:
                raise sync.Denied(family)
            result = sync.historical(item, day, old)
        except sync.Denied:
            if old and old['bars']:
                raise ValueError('已有行情的标的权限发生变化 ' + code)
            if family:
                with lock:
                    denied.add(family)
            result = dict(symbol=code, until=day, bars=[], status='denied')
        sync.save(dest, result)
        return result['status']
    counts, errors = collections.Counter(), []
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        pending = {pool.submit(pull, c):c for c in ordered}
        for i, fut in enumerate(concurrent.futures.as_completed(pending), 1):
            try:
                counts[fut.result()] += 1
            except (ValueError, RuntimeError, OSError) as exc:
                errors.append([pending[fut], str(exc)])
            if i % 250 == 0 or i == len(ordered):
                print(f'日线 {i}/{len(ordered)}', dict(counts), '待重试', len(errors), flush=True)
    if errors:
        (store / 'retry.json').write_text(json.dumps(errors, ensure_ascii=False))
        raise RuntimeError(f'{len(errors)} 个查询需要重试。')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--until',default=dt.datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d'))
    ap.add_argument('--rpm',type=int,default=180)
    args = ap.parse_args()
    authenticate(args.rpm)
    day = last_session(args.until)
    directory = directory_and_snapshot(sync.STORE,day)
    print(day,'独立 Tushare 目录', len(directory['items']), flush=True)
    histories(sync.STORE, day, directory['items'])


if __name__ == '__main__':
    main()
