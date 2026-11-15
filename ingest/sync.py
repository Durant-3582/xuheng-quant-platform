"""Direct Tushare client and normalized daily bars for the independent website."""
import argparse
import collections
import concurrent.futures
import csv
import datetime as dt
import getpass
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import threading
import tempfile
import time
from zoneinfo import ZoneInfo

import requests

BASE = Path(__file__).resolve().parents[1]
STORE = BASE / ".private" / "history"
START = "20000101"
PRIORITY = "000001.SH 399001.SZ 000300.SH 000905.SH 000852.SH 000016.SH 399006.SZ 899050.BJ 000688.SH 000985.CSI 399303.SZ 931847.CSI H00300.CSI 399238.SZ 399249.SZ 600000.SH 600519.SH 000001.SZ 300750.SZ 920185.BJ 920002.BJ 600625.SH 000013.SZ".split()
FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount"
BASIC = "ts_code,trade_date,pe_ttm,pb,total_mv,turnover_rate"
seats = threading.Lock()
next_call = 0.0
local = threading.local()
token = ""
frequency = 0.42


def session():
    if not hasattr(local, "http"):
        local.http = requests.Session()
    return local.http


class Denied(Exception):
    pass


def api(name, params, fields):
    global next_call
    for tries in range(7):
        with seats:
            delay = max(0, next_call - time.monotonic())
            next_call = time.monotonic() + delay + frequency
        time.sleep(delay)
        try:
            res = session().post("https://api.tushare.pro", json=dict(api_name=name, token=token, params=params, fields=fields),
                                 timeout=(12, 65), allow_redirects=False)
            res.raise_for_status()
            body = res.json()
        except (requests.RequestException, ValueError) as exc:
            if tries == 6:
                status = getattr(getattr(exc, 'response', None), 'status_code', None)
                raise RuntimeError(f'{name} upstream {type(exc).__name__} {status or ""}') from None
            time.sleep(2 ** tries)
            continue
        if body.get("code") != 0:
            msg = str(body.get("msg", ""))
            if any(x in msg for x in ("每分钟", "频率", "频次", "too many", "每小时")):
                if tries == 6:
                    raise RuntimeError(name + " frequency limit")
                with seats:
                    next_call = max(next_call, time.monotonic() + 61)
                continue
            if any(x in msg for x in ("权限", "积分", "访问此接口")) or body.get("code") in (2002, 40203):
                raise Denied(name)
            raise RuntimeError(f"{name} status {body.get('code')}")
        table = body["data"]
        return [dict(zip(table["fields"], row, strict=True)) for row in table["items"]]


def listing(name, params, fields, page):
    rows, seen = [], set()
    while True:
        group = api(name, dict(params, limit=page, offset=len(rows)), fields)
        marker = hashlib.sha256(js(group)).digest()
        if group and marker in seen:
            raise RuntimeError(name + " pagination repeated")
        seen.add(marker)
        rows.extend(group)
        if len(group) < page:
            return rows


def number(value, positive=False):
    try:
        n = float(value)
        if math.isfinite(n) and (not positive or n > 0):
            return n
    except (ValueError, TypeError):
        pass
    return None


def js(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def save(path, obj):
    path.parent.mkdir(exist_ok=True, parents=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False,suffix=".part") as f:
        tmp=Path(f.name)
        try:f.write(gzip.compress(js(obj), compresslevel=4, mtime=0))
        except Exception:tmp.unlink(missing_ok=True);raise
    try:tmp.replace(path)
    finally:tmp.unlink(missing_ok=True)


def read(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def bar(row, endpoint="daily"):
    vals = [number(row.get(k), positive=True) for k in ("open", "high", "low", "close")]
    if vals[3] is None:
        return None
    if all(v is not None for v in vals) and not vals[2] <= min(vals[0], vals[3]) <= max(vals[0], vals[3]) <= vals[1]:
        vals[:3] = [None] * 3
    volume, amount = number(row.get("vol")), number(row.get("amount"))
    if endpoint in ("sw_daily", "ci_daily"):
        # Provider units are ten thousand shares and ten thousand yuan; store lots and thousand yuan.
        volume = None if volume is None else volume * 100
        amount = None if amount is None else amount * 10
    return [row["trade_date"], *vals, number(row.get("pre_close"), True), number(row.get("pct_chg")), volume, amount]


def scope(row):
    name = " ".join(str(row.get(k) or "") for k in ("name", "fullname"))
    category = row.get("category") or ""
    # Investable equity indices tracking bond themes can include words such as 银行; use clear exclusions only.
    if re.search("债券|国债|公司债|信用债|转债|利率债|城投债|金融债|债指数|货币市场|商品期货|基金指数|黄金现货|多资产|恒生|港股|沪港|深港|港通|港美|标普|纳斯达克|全球|美国|欧洲|印度|日本|巴西|韩国|亚太|海外|离岸|美元|B股|Ｂ股", name + category, re.I):
        return "excluded"
    if row["ts_code"] in PRIORITY or row["ts_code"] in ("000510.SH","399005.SZ","399106.SZ","399107.SZ","000002.SH","000009.SH","899601.BJ","000906.SH","000903.SH","000932.SH","000922.CSI","000985.SH"):
        return "benchmark"
    if row.get("market") in ("SW","CICC","CI"):
        return "industry"
    description = str(row.get("desc") or "")
    if re.search("跨境|中国香港|香港(上市|交易)|港股|海外|境外上市|美国上市|B股|Ｂ股|债券|基金份额|可转债|商品期货", description):
        return "review"
    if re.search(r"(沪深(京|北)?|沪市|深市|北交所|境内|上海证券交易所|深圳证券交易所|北京证券交易所|创业板|科创板)[^。；]{0,32}(A股|股票|上市公司证券|上市公司股价)|从.{0,8}(沪深300|中证500|中证800|中证1000|中证全指|中证A500|上证180|深证成指).{0,8}(指数)?(的)?(样本|成[份分]股)|以.{0,8}(沪深300|中证500|中证800|中证1000|中证全指|中证A500).{0,9}(样本|成[份分]股)", description.replace(" ", "")):
        return "equity"
    return "review"


def inventory(day):
    entries = {}
    for venue in ("SSE", "SZSE", "BSE"):
        for state in ("L", "D", "P"):
            for row in listing("stock_basic", dict(exchange=venue, list_status=state),
                               "ts_code,name,industry,market,exchange,list_date,delist_date", 4000):
                code = row["ts_code"]
                if not valid_stock(code) or (row.get("delist_date") or day) < START:
                    continue
                entries[code] = [code, row["name"], "stock", venue, row.get("industry") or "", state, row.get("list_date"), row.get("delist_date"), "stock"]
    try:
        aliases = {r["o_code"]: r["n_code"] for r in listing("bse_mapping", {}, "o_code,n_code", 2000) if r.get("o_code") and r.get("n_code")}
    except Denied:
        aliases = {}
    for old,new in aliases.items():
        if old in entries and new in entries:
            del entries[old]
    for market in ("SSE", "SZSE", "BSE", "CSI", "CNI", "OTH", "SW", "CICC", "CI", "MSCI", "CSRC"):
        try:
            rows = listing("index_basic", dict(market=market), "ts_code,name,fullname,market,publisher,category,list_date,exp_date,desc", 4000)
        except Denied:
            continue
        for row in rows:
            code = row["ts_code"]
            if not re.fullmatch(r"[0-9A-Z_-]{1,32}\.[A-Z]{2,6}", code) or (row.get("exp_date") or day) < START:
                continue
            group = scope(row)
            if market == 'MSCI' and not any(x in (row.get('fullname') or '') for x in ('A股', 'A 股', 'A50', '中国A')):
                continue
            if group == "excluded" or code in entries:
                continue
            entries[code] = [code, row.get("name") or code, "index", market, row.get("category") or "", "D" if row.get("exp_date") and row["exp_date"] <= day else "L", row.get("list_date"), row.get("exp_date"), group]
    return {"day":day, "items":list(entries.values()), "aliases":aliases}


def valid_stock(code):
    return bool(re.fullmatch(r"(?:6\d{5}\.SH|[03]\d{5}\.SZ|[489]\d{5}\.BJ)", code or ""))


def day_quotes(day, directory):
    rows = {}
    families = [(name,FIELDS) for name in ("daily","index_daily")]
    for endpoint,suffix in (("sw_daily",".SI"),("ci_daily",".CI")):
        if any(r[8]=="industry" and r[0].endswith(suffix) for r in directory["items"]):
            families.append((endpoint,FIELDS.replace("pre_close,pct_chg","pct_change")))
    for name,fields in families:
        try:
            data=listing(name, {"trade_date":day}, fields, 4000)
        except Denied:
            if name in ("daily","index_daily"):raise
            continue
        for r in data:
            if r["trade_date"] != day:
                raise RuntimeError(name + " unexpected date")
            code = r["ts_code"]
            if name == "daily":
                code = directory.get("aliases",{}).get(code,code)
            if "pct_change" in r:r["pct_chg"]=r["pct_change"]
            if (v := bar(r,name)) is not None:
                rows[code] = v
    return rows


def one_day(day, directory, rows=None, pb_store=None):
    if rows is None:rows=day_quotes(day,directory)
    basics = {}
    values = {}
    try:
        for r in listing("daily_basic", {"trade_date":day}, BASIC, 5000):
            if r["trade_date"]!=day:raise RuntimeError("daily_basic unexpected date")
            if r["ts_code"] in values:raise RuntimeError("daily_basic duplicate code")
            values[r["ts_code"]]=number(r.get("pb"))
            code=directory.get("aliases",{}).get(r["ts_code"],r["ts_code"])
            basics[code] = [number(r.get(k)) for k in ("pe_ttm","pb","total_mv","turnover_rate")]
    except Denied:
        if pb_store is not None:raise
    if pb_store is not None:
        if not values:raise ValueError("当天每日指标尚未发布，保留上次完整快照。")
        save(pb_store/"pb"/(day+".gz"),values)
    items = []
    for entry in directory["items"]:
        symbol = entry[0]
        b = rows.get(symbol)
        items.append([*entry, b[4] if b else None, b[6] if b else None, b[8] if b else None, *basics.get(symbol,[None]*4)])
    return {"day":day, "items":items, "aliases":directory["aliases"]}


def historical(item, day, previous=None):
    code, _, kind, _, _, _, first, last, group = item[:9]
    api_name = "daily" if kind == "stock" else ("sw_daily" if group == "industry" and code.endswith(".SI") else "ci_daily" if group == "industry" and code.endswith(".CI") else "index_daily")
    f = FIELDS
    if api_name in ("ci_daily","sw_daily"):
        f = "ts_code,trade_date,open,high,low,close,pct_change,vol,amount"
    # BJ trading begins on 2021-11-15. Keep Tushare's back series for indices when they have one.
    lo = max(START, first or START, "20211115" if code.endswith(".BJ") else START) if kind == "stock" else START
    hi = min(day, last or day)
    prior = (previous or {}).get("bars", [])
    if prior:
        lo = max(lo, previous["until"])
    byday = {r[0]:r for r in prior}
    while hi >= lo:
        group_rows = api(api_name, {"ts_code":code,"start_date":lo,"end_date":hi}, f)
        if not group_rows:
            break
        dates = []
        for r in group_rows:
            date = r["trade_date"]
            if r["ts_code"] != code or not (lo <= date <= hi) or not re.fullmatch(r"\d{8}",date):
                raise RuntimeError(code + " invalid date or symbol")
            dates.append(date)
            if "pct_change" in r:
                r["pct_chg"] = r["pct_change"]
            v = bar(r,api_name)
            if v:
                byday[date] = v
        earliest = min(dates)
        # Request the preceding part whenever the provider filled a page, data are newest first.
        limit = 6000 if kind == 'stock' else 8000 if api_name == 'index_daily' else 4000
        if len(group_rows) < limit and len(group_rows) % 500 != 0:
            break
        if len(group_rows) < limit and kind == 'stock' and first and earliest == first:
            break
        hi = (dt.datetime.strptime(earliest,"%Y%m%d").date()-dt.timedelta(days=1)).strftime("%Y%m%d")
    return {"symbol":code,"until":day,"bars":[byday[x] for x in sorted(byday)],"status":"ready" if byday else "empty"}

