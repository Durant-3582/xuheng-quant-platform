"""Build monthly factor samples from the private, per-security daily archive, starting in 2000."""
from bisect import bisect_right
from collections import defaultdict, deque
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

import sync
from execution import opening_flags


def eligible(bar):
    _, opening, high, low, close, reference, _, volume, _ = bar
    return all(v is not None and v > 0 for v in (opening, high, low, close, reference, volume))


def factor_values(ratios):
    momentum = round((math.prod(ratios) - 1) * 100, 5) if len(ratios) == 60 else None
    recent = list(ratios)[-20:]
    mean = sum(recent) / 20
    volatility = round(math.sqrt(sum((x - mean) ** 2 for x in recent) * 252 / 19) * 100, 5)
    reversal = round((math.prod(recent) - 1) * 100, 5)
    return momentum, volatility, reversal


def stock_samples(bars, bounds, entries, calendar):
    """Signal uses only prices through that session. Fill and mark it over the following period."""
    bars = [bar for bar in bars if bar[0] in calendar and bar[4] and bar[4] > 0 and bar[5] and bar[5] > 0]
    days = [bar[0] for bar in bars]
    ratios = deque(maxlen=60)
    signals = []
    for i, bar in enumerate(bars):
        day = bar[0]
        if not eligible(bar):
            continue
        ratios.append(bar[4] / bar[5])
        if day not in bounds or len(ratios) < 20:
            continue
        momentum, vol, _ = factor_values(ratios)
        if day not in entries:
            signals.append((day, momentum, vol, 0, 0, 0))
            continue
        entry, end = entries[day]
        held = i + 1 < len(bars) and days[i + 1] == entry
        if held:
            _, opening, _, _, close, prior, _, volume, _ = bars[i + 1]
            held = bool(opening and opening > 0 and volume and volume > 0 and opening_flags(opening, prior) & 1)
        if not held:
            signals.append((day, momentum, vol, 0, 0, 0))
            continue
        last = bisect_right(days, end)
        growth = close / opening
        for row in bars[i + 2:last]:
            growth *= row[4] / row[5]
        signals.append((day, momentum, vol, round((growth - 1) * 100, 6), 1, int(days[last - 1] != end)))
    return signals


def build(store, day):
    catalog = sync.read(store / "snapshot" / (day + ".gz"))
    stocks = sorted(r[0] for r in catalog["items"] if r[2] == "stock")
    def series(code):
        archive = sync.read(store / "series" / (code + ".gz"))
        if archive["until"] < day or archive["symbol"] != code:
            raise ValueError("日线归档未就绪 " + code)
        return archive["bars"]
    calendars = [[r[0] for r in series(code) if sync.START <= r[0] <= day] for code in ("000001.SH", "399001.SZ")]
    if not calendars[0] or calendars[0] != calendars[1] or calendars[0][-1] != day:
        raise ValueError("上证综指、深证成指交易日历未对齐")
    dates = calendars[0]
    calendar = set(dates)
    ends = [i for i, d in enumerate(dates) if i == len(dates) - 1 or d[:6] != dates[i + 1][:6]]
    bounds = {dates[i] for i in ends}
    entries = {dates[a]: (dates[a + 1], dates[b]) for a, b in zip(ends, ends[1:])}
    periods = defaultdict(list)
    latest = []
    for n, code in enumerate(stocks, 1):
        for signal, mom, vol, ret, filled, stale in stock_samples(series(code), bounds, entries, calendar):
            if signal == day:
                latest.append([code, mom, vol])
            else:
                periods[signal].append([code, mom, vol, ret, filled, stale])
        if n % 1000 == 0:
            print("已计算", n, "/", len(stocks), flush=True)

    out = store / "research" / day
    out.mkdir(parents=True, exist_ok=True)
    manifest = {}
    def save(label, contents):
        blob = gzip.compress(sync.js(contents), compresslevel=6, mtime=0)
        digest = hashlib.sha256(blob).hexdigest()
        name = label + "-" + digest
        tmp = out / (name + ".tmp")
        tmp.write_bytes(blob)
        tmp.replace(out / (name + ".gz"))
        manifest[name] = digest
        return "research/" + day + "/" + name

    views, groups = {}, {}
    for rule, column in (("mom", 1), ("vol", 2)):
        for venue in ("all", "SH", "SZ", "BJ"):
            sample, quintiles = [], []
            view = rule + "-" + venue
            for signal, (entry, end) in entries.items():
                rows = [r for r in periods[signal] if r[column] is not None and (venue == "all" or r[0].endswith("." + venue))]
                rows.sort(key=lambda r: ((-1 if rule == "mom" else 1) * r[column], r[0]))
                if not rows:
                    continue
                sample.append(dict(signal=signal, entry=entry, end=end, rows=rows[:200]))
                if len(rows) >= 5:
                    quintiles.append([statistics.fmean(r[3] for r in rows[len(rows)*i//5:len(rows)*(i+1)//5]) for i in range(5)])
            groups[view] = [[statistics.fmean(values), len(values)] for values in zip(*quintiles)]
            views[view] = save(view, sample)
            print(view, len(sample), sample[0]["signal"] if sample else None, sample[-1]["end"] if sample else None, flush=True)
    factors = save("factors", dict(latest=latest, groups=groups, day=day))
    index = dict(format=3, day=day, from_day=dates[0], sessions=len(dates), views=views, factors=factors)
    sync.save(out / "open-index.gz", index)
    manifest["open-index"] = hashlib.sha256((out / "open-index.gz").read_bytes()).hexdigest()
    # Publication verifies compressed object digests and publishes the index after all referenced objects.
    (out / "digests.json").write_bytes(sync.js(manifest))
    print("已生成", len(latest), "只股票的当期因子，", len(dates), "个交易日。", flush=True)


if __name__ == "__main__":
    root = sync.STORE
    build(root, sorted((root / "snapshot").glob("*.gz"))[-1].stem)
