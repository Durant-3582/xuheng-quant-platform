"""Build dated portfolio inputs. Selection and regressions are frozen at the signal close."""
from collections import defaultdict, deque
import gzip
import hashlib

import sync
from execution import opening_flags
from research import eligible, factor_values

BENCHMARKS = ("000300.SH", "000001.SH")
WINDOW = 120


class Regression:
    def __init__(self):
        self.pairs = deque()
        self.sx = self.sy = self.sxx = self.sxy = self.syy = 0.

    def add(self, x, y):
        self.pairs.append((x, y))
        self.sx += x
        self.sy += y
        self.sxx += x*x
        self.sxy += x*y
        self.syy += y*y
        if len(self.pairs) > WINDOW:
            a, b = self.pairs.popleft()
            self.sx -= a
            self.sy -= b
            self.sxx -= a*a
            self.sxy -= a*b
            self.syy -= b*b

    def estimate(self):
        if len(self.pairs) < WINDOW:
            return None, None
        xx = self.sxx - self.sx*self.sx/WINDOW
        xy = self.sxy - self.sx*self.sy/WINDOW
        if xx <= 1e-12:
            return None, None
        beta = xy / xx
        variance = (self.syy - self.sy*self.sy/WINDOW - beta*xy) / (WINDOW-2)
        if variance <= 1e-12:
            return None, None
        return round((self.sy-beta*self.sx)/WINDOW, 10), round(variance, 12)


def stock_months(code, bars, calendar, boundaries, opening_days, indexes):
    factors, months = {}, {}
    ratios, fits = deque(maxlen=60), [Regression() for _ in indexes]
    prev_session = None
    for bar in bars:
        day, opening, high, low, close, reference, _, volume, _ = bar
        if day not in calendar:
            continue
        session = calendar[day]
        executable = eligible(bar)
        if executable:
            ratio = close/reference
            ratios.append(ratio)
            if prev_session == session-1:
                for fit, returns in zip(fits, indexes):
                    x = returns.get(day)
                    if x is not None:
                        fit.add(x, ratio-1)
            prev_session = session
            if day in boundaries:
                scores = factor_values(ratios) if len(ratios) >= 20 else (None, None, None)
                fits_today = [v for fit in fits for v in fit.estimate()]
                factors[day] = (*scores, *fits_today)
        if not (close and reference and close > 0 and reference > 0):
            continue
        month = day[:6]
        mark = months.setdefault(month, [1., 1., 0])
        if day == opening_days[month] and opening and opening > 0 and volume and volume > 0:
            mark[0] = opening/reference
            mark[1] *= close/opening
            mark[2] = opening_flags(opening, reference)
        else:
            mark[1] *= close/reference
        if day in boundaries:
            mark[2] |= 4
    return factors, months


def build(store, cutoff):
    catalog = sync.read(store/"snapshot"/(cutoff+".gz"))
    metadata = {r[0]:r for r in catalog["items"]}
    def history(code):
        series = sync.read(store/"series"/(code+".gz"))
        if series["symbol"] != code or series["until"] < cutoff:
            raise ValueError("日线尚未就绪 " + code)
        return series["bars"]
    sh, sz = history("000001.SH"), history("399001.SZ")
    dates = [r[0] for r in sh if sync.START <= r[0] <= cutoff]
    if dates != [r[0] for r in sz if sync.START <= r[0] <= cutoff] or dates[-1] != cutoff:
        raise ValueError("沪深日历不一致")
    calendar = {d:i for i,d in enumerate(dates)}
    monthly = defaultdict(list)
    for d in dates:
        monthly[d[:6]].append(d)
    opening_days = {m:ds[0] for m,ds in monthly.items()}
    boundaries = {ds[-1] for ds in monthly.values()}
    proxies, market_returns = [], []
    for code in BENCHMARKS:
        listed = metadata[code][6]
        bars = {r[0]:r for r in history(code) if r[0] >= listed}
        returns = {}
        for i,d in enumerate(dates[1:],1):
            if d in bars and dates[i-1] in bars:
                b = bars[d]
                prior = b[5] or bars[dates[i-1]][4]
                if b[4] > 0 and prior > 0:
                    returns[d] = b[4]/prior-1
        market_returns.append(returns)
        proxies.append(bars)
    periods = []
    months = list(monthly.values())
    for previous, current in zip(months,months[1:]):
        signal, entry, end = previous[-1], current[0], current[-1]
        prices = [[bars[entry][1],bars[end][4]] if entry in bars and end in bars and bars[entry][1] else None for bars in proxies]
        periods.append(dict(signal=signal,entry=entry,end=end,market=prices,rows=[]))
    stocks = sorted(r[0] for r in metadata.values() if r[2]=="stock")
    for n,code in enumerate(stocks,1):
        factors, marks = stock_months(code,history(code),calendar,boundaries,opening_days,market_returns)
        for p in periods:
            stats, mark = factors.get(p["signal"]), marks.get(p["entry"][:6])
            if stats is None and mark is None:
                continue
            mom, vol, rev, a, v, a2, v2 = stats or (None,)*7
            gap, intramonth, flags = mark or (1.,1.,0)
            p["rows"].append([code,mom,vol,rev,round(gap,10),round(intramonth,10),flags|(8 if stats else 0),a,v,a2,v2])
        if n%1000==0:
            print("组合逐月样本",n,"/",len(stocks),flush=True)
    out = store/"research"/cutoff
    out.mkdir(parents=True,exist_ok=True)
    years = defaultdict(list)
    for p in periods:
        years[p["entry"][:4]].append(p)
    digests, shards = {}, {}
    for year, group in years.items():
        blob = gzip.compress(sync.js(group),compresslevel=5,mtime=0)
        digest = hashlib.sha256(blob).hexdigest()
        key = "portfolio-"+year+"-"+digest
        tmp = out/(key+".part")
        tmp.write_bytes(blob)
        tmp.replace(out/(key+".gz"))
        digests[key] = digest
        shards[year] = "research/"+cutoff+"/"+key
    version = hashlib.sha256(sync.js(shards)).hexdigest()
    index = dict(format=1,day=cutoff,version=version,years=shards,benchmarks=BENCHMARKS)
    sync.save(out/"portfolio-index.gz",index)
    digests["portfolio-index"] = hashlib.sha256((out/"portfolio-index.gz").read_bytes()).hexdigest()
    (out/"portfolio-digests.json").write_bytes(sync.js(digests))
    print("完成",len(stocks),"只股票",len(periods),"个持有期",len(shards),"个年度分片",flush=True)


if __name__ == "__main__":
    root = sync.STORE
    build(root,sorted((root/"snapshot").glob("*.gz"))[-1].stem)
