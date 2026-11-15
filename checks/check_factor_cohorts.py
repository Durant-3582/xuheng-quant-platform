"""Recalculate historical quintiles from per-stock daily bars and dated opening limits.

Run against the independent install's .private/history and .private/database.
Holds three cross-sections per month in memory and reads one stock at a time.
"""
from collections import defaultdict
import gzip
import json
from pathlib import Path
import sys

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xuheng.archive import Archive

HISTORY = ROOT / ".private/history"


def source(name):
    with gzip.open(HISTORY / (name + ".gz")) as file:
        return json.load(file)


def official_uppers(opens, codes, aliases):
    ids = {code: i for i, code in enumerate(codes)}
    upper = np.full((len(opens), len(codes)), np.nan)
    for month, day in enumerate(opens):
        if not (HISTORY / "open-bands" / (day + ".gz")).exists():
            continue
        for code, cap, floor in source("open-bands/" + day):
            idx = ids.get(aliases.get(code, code))
            if idx is not None and cap and floor and cap >= floor > 0:
                upper[month, idx] = cap
    return upper


def verify():
    archive = Archive(ROOT / ".private/database")
    snapshot = source("snapshot/" + archive.day)
    codes = sorted(row[0] for row in snapshot["items"] if row[2] == "stock")
    dates = [row[0] for row in source("series/000001.SH")["bars"]]
    d_index = {d: i for i, d in enumerate(dates)}
    firsts = np.array([i for i, d in enumerate(dates) if i == 0 or dates[i-1][:6] != d[:6]])
    entry = firsts[1:]
    signal = entry - 1
    end = np.r_[entry[1:] - 1, len(dates) - 1]
    caps = official_uppers([dates[i] for i in entry], codes, snapshot["aliases"])
    shape = (len(signal), len(codes))
    momentum, volatility = (np.full(shape, np.nan) for _ in range(2))
    forward = np.zeros(shape)

    for col, code in enumerate(codes):
        bars = [r for r in source("series/" + code)["bars"] if r[0] in d_index]
        if not bars:
            continue
        pos = np.array([d_index[r[0]] for r in bars])
        prices = np.asarray([[r[i] for i in (1, 2, 3, 4, 5, 7)] for r in bars], dtype=float)
        opening, _, _, close, reference, volume = prices.T
        good = (prices > 0).all(axis=1)
        ratios = close[good] / reference[good]
        valid_positions = pos[good]
        for window, out in ((60, momentum), (20, volatility)):
            if len(ratios) < window:
                continue
            lookback = sliding_window_view(ratios, window)
            obs = valid_positions[window-1:]
            slots = np.searchsorted(obs, signal).clip(max=len(obs)-1)
            present = obs[slots] == signal
            groups = lookback[slots[present]]
            values = (np.prod(groups, axis=1)-1)*100 if window == 60 else np.std(groups, axis=1, ddof=1)*np.sqrt(252)*100
            out[present, col] = np.round(values, 5)

        i = np.searchsorted(pos, entry).clip(max=len(pos)-1)
        can_buy = (pos[i] == entry) & (opening[i] > 0) & (volume[i] > 0) & (close[i] > 0) & (reference[i] > 0)
        for m in np.flatnonzero(can_buy):
            start = i[m]
            op, ref = opening[start], reference[start]
            if np.isfinite(caps[m, col]):
                blocked = round(op*10000) >= round(caps[m, col]*10000)
            else:
                cents, base = int(op*100 + .5000001), int(ref*100 + .5000001)
                blocked = cents > base and any(cents == (base*(100+b)+50)//100 for b in (5, 10, 20, 30))
            if blocked:
                continue
            last = np.searchsorted(pos, end[m], side="right")
            following = slice(start+1, last)
            marked = (close[following] > 0) & (reference[following] > 0)
            held_return = close[start]/op * np.prod(close[following][marked]/reference[following][marked])
            forward[m, col] = (held_return-1)*100

    expected = archive.bands["groups"]
    actual = defaultdict(list)
    venue = np.array([code[-2:] for code in codes])
    for label, scores, direction in (("mom", momentum, -1), ("vol", volatility, 1)):
        for market in ("all", "SH", "SZ", "BJ"):
            scope = np.ones(len(codes), dtype=bool) if market == "all" else venue == market
            key = label + "-" + market
            for period, row in enumerate(scores):
                idx = np.flatnonzero(scope & np.isfinite(row))
                if len(idx) < 5:
                    continue
                order = idx[np.argsort(direction*row[idx], kind="stable")]
                edges = len(order)*np.arange(6)//5
                actual[key].append([np.mean(forward[period, order[a:b]]) for a,b in zip(edges, edges[1:])])
            means = np.mean(actual[key], axis=0)
            assert all(n == len(actual[key]) for _,n in expected[key]), key
            assert np.max(np.abs(means - [v for v,_ in expected[key]])) < 1e-6, (key, means, expected[key])
    print("Verified 40 quintile results from raw histories. Number of holding periods per factor and market:",
          {k:len(v) for k,v in actual.items()})


if __name__ == "__main__":
    verify()
