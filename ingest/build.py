"""Build and commit a complete research database from this project's private Tushare records."""
import argparse
import datetime as dt
import fcntl
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import download
import disclosures
import incremental
import opening_limits
import pack
import portfolio
import portfolio_inputs
import research
import sync
import trading_days
import supplement_history


def prepare_prices(store, day):
    folder = store / 'research' / day
    folder.mkdir(parents=True, exist_ok=True)
    research.build(store, day)
    portfolio.build(store, day)
    trading_days.build(store, day)
    daily = sync.read(folder / 'days-index.gz')
    portfolio_inputs.bench_build(store, day, daily, folder)


def finish_database(store, output, day, *, sample=False, previous=None):
    folder=store/'research'/day;daily=sync.read(folder/'days-index.gz')
    portfolio_inputs.value_build(store, day, daily, folder, previous=previous)
    opening_limits.build(store, day, folder / 'opening-summary.json', previous=previous)
    pack.pack(store, output, day, sample=sample)


def build_database(store, output, day, *, sample=False, previous=None):
    prepare_prices(store,day)
    finish_database(store,output,day,sample=sample,previous=previous)


def reusable_history(store, old, day, calendar):
    """Prices in an existing ready series are only appended by incremental.run."""
    previous = sync.read(store / 'research' / old / 'days-index.gz')
    before = sync.read(store / 'snapshot' / (old + '.gz'))
    after = sync.read(store / 'snapshot' / (day + '.gz'))
    new_codes = {r[0] for r in after['items'] if r[2] == 'stock'}
    old_codes = set(previous['codes'])
    if (calendar[:len(previous['dates'])] != previous['dates'] or previous['dates'][-1] != old
            or before['aliases'] != after['aliases'] or not old_codes.issubset(new_codes)):
        return False
    coverage = sync.read(store / 'coverage' / (old + '.gz'))
    empty = {r[0] for r in coverage if r[1] == 'stock' and not r[3]}
    for code in (new_codes - old_codes) | empty:
        bars = sync.read(store / 'series' / (code + '.gz'))['bars']
        if bars and bars[0][0] <= old:
            return False
    return True


def update(store, output, until, *, reuse_published=False):
    mark = output / 'manifest.json'
    old = json.loads(mark.read_bytes())['day'] if mark.is_file() else None
    day = download.last_session(until)
    if old and old >= day:
        print('已是最新完整交易日', old, flush=True)
        return
    if old:
        incremental.run(store, old, day)
    else:
        directory = download.directory_and_snapshot(store, day)
        download.histories(store, day, directory['items'])
    calendar = [r[0] for r in sync.read(store/'series/000001.SH.gz')['bars'] if sync.START <= r[0] <= day]
    if not calendar or calendar[-1] != day or not (store/'snapshot'/(day+'.gz')).is_file():
        raise ValueError('行情尚未更新至最新完整交易日。')
    previous = old if reuse_published and old and reusable_history(store, old, day, calendar) else None
    if reuse_published:
        print(f'复用截至 {previous} 的已核历史结果。' if previous else
              '证券历史发生回补或代码映射变化，本次通过 Tushare 重新计算受影响的历史。', flush=True)
    supplement_history.fill(store, [d for d in calendar if not previous or d >= previous])
    disclosures.seed(store,day)
    build_database(store,output,day,previous=previous)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--until', default=dt.datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d'))
    parser.add_argument('--rpm',type=int,default=180)
    parser.add_argument('--reuse-published', action='store_true')
    args = parser.parse_args()
    download.authenticate(args.rpm)
    root = sync.STORE.parent
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root/'update.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        update(sync.STORE,root/'database',args.until,reuse_published=args.reuse_published)
