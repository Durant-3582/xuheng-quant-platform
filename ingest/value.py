"""Cache each Tushare daily_basic cross section before building point-in-time PB ranks."""
from concurrent.futures import ThreadPoolExecutor
import argparse
from collections import Counter
import os
import sys

import sync


def fetch_day(store, day):
    path = store / "pb" / (day + ".gz")
    if path.exists():
        return
    rows = sync.listing("daily_basic", {"trade_date": day}, "ts_code,trade_date,pb", 6000)
    values = {}
    for row in rows:
        code = row["ts_code"]
        if not isinstance(code,str) or not code or row["trade_date"] != day or code in values:
            raise ValueError("PB 日期或代码重复 " + day)
        values[code] = sync.number(row["pb"])
    if not values:
        raise ValueError("交易日整张 PB 表为空 " + day)
    sync.save(path, values)


def run(store, cutoff):
    dates = [r[0] for r in sync.read(store/"series/000001.SH.gz")["bars"] if sync.START <= r[0] <= cutoff]
    probes = [d for d in (dates[0],"20001229","20040901","20211115",cutoff) if d in dates]
    ends = {d[:6]: d for d in dates}
    ordered = list(dict.fromkeys(probes + list(ends.values()) + dates))
    def sync_date(d):
        fetch_day(store,d)
        return d
    with ThreadPoolExecutor(8) as pool:
        for n, day in enumerate(pool.map(sync_date, ordered), 1):
            if day in probes:
                v = sync.read(store/"pb"/(day+".gz"))
                print("PB 核验", day, dict(Counter(c[-2:] for c in v)), "正值", sum(p is not None and p > 0 for p in v.values()),
                      {c:v[c] for c in ("000001.SZ","600000.SH","600625.SH","000013.SZ","920185.BJ","835185.BJ","920002.BJ") if c in v}, flush=True)
            if n % 250 == 0 or n == len(ordered):
                print("PB 逐日核验", n, "/", len(ordered), flush=True)

