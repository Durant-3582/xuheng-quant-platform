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


def finish_database(store, output, day, *, sample=False):
    folder=store/'research'/day;daily=sync.read(folder/'days-index.gz')
    portfolio_inputs.value_build(store, day, daily, folder)
    opening_limits.build(store, day, folder / 'opening-summary.json')
    pack.pack(store, output, day, sample=sample)


def build_database(store, output, day, *, sample=False):
    prepare_prices(store,day)
    finish_database(store,output,day,sample=sample)


def update(store, output, until):
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
    supplement_history.fill(store, calendar)
    disclosures.seed(store,day)
    build_database(store,output,day)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--until', default=dt.datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d'))
    parser.add_argument('--rpm',type=int,default=180)
    args = parser.parse_args()
    download.authenticate(args.rpm)
    root = sync.STORE.parent
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root/'update.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        update(sync.STORE,root/'database',args.until)
