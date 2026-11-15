"""Data and backtests for the browser workbench, using only this app's market release."""
import base64
from functools import lru_cache
import hmac
import json
import math
from urllib.parse import parse_qs, urlsplit

from .archive import CODE
from .comparison import compare
from .details import extra
from .frames import Rules
from .portfolio import check_window, run

BAR_FIELDS = ("day", "open", "high", "low", "close", "pre_close", "pct", "volume", "amount")


class SnapshotChanged(ValueError):
    pass


def release(store):
    return getattr(store, "release_id", None) or store.manifest["files"]["catalog"]["sha256"]


def security(store, code):
    canonical = store.snapshot.get("aliases", {}).get(code, code)
    if not CODE.fullmatch(canonical) or canonical not in store.catalog:
        raise ValueError("行情目录中没有这个证券代码。")
    return canonical, store.catalog[canonical]


def coverage(store, query):
    kind, state, term = (query.get(k, "") for k in ("kind", "status", "q"))
    page = int(query.get("page", 0))
    if not 0 <= page <= 2000 or len(term) > 64 or kind not in ("", "stock", "index") or state not in ("", "ready", "empty", "denied"):
        raise ValueError("筛选条件无效。")
    term = term.strip().lower()
    rows = [r for r in store.coverage if (not kind or kind == r[1]) and (not state or state == r[2])
            and (not term or term in (r[0] + " " + store.catalog[r[0]][1]).lower())]
    keys = ("code", "kind", "status", "bars", "first_day", "last_day")
    return dict(day=store.day, total=len(rows), page=page, rows=[dict(zip(keys, r)) for r in rows[page*12:page*12+12]])


def quotes(store, query):
    code, item = security(store, query.get("symbol", ""))
    data = store.series(code)
    if "days" in query:
        days = query["days"].split(",")
        first = query.get("quoteStart")
        if len(days) > 600 or any(not d.isdigit() or len(d) != 8 for d in days) or first and first != days[0]:
            raise ValueError("比较日期无效。")
        wanted = set(days)
        return dict(until=store.day, listed=item[6], closes=[
            [r[0], r[1] if r[0] == first else r[4]] for r in data["bars"] if r[0] in wanted])
    # Keep repeated column names off the wire. The browser expands rows for its charts.
    return dict(until=store.day, status=data["status"], fields=BAR_FIELDS, rows=data["bars"])


def strategy(store, q):
    k, exchange = q.get("factor", "mom"), q.get("exchange", "")
    if k not in ("mom", "vol") or exchange not in ("", "SH", "SZ", "BJ"):
        raise ValueError("请选择有效的策略和市场。")
    r = Rules(model=k, count=int(q.get("count", 30)), fee=float(q.get("fee", 10)), exchange=exchange, bench="000001.SH")
    if not 1 <= r.count <= 200 or not 0 <= r.fee <= 100:
        raise ValueError("请检查目标持股数和单边费率。")
    bounds = signals(store, k, exchange)
    if not bounds:
        raise ValueError("本市场尚无这个策略的有效信号。")
    start, end = q.get("from") or "20000101", q.get("to") or store.day
    check_window(start, end, store.day)
    periods = [(entry, last) for signal, entry, last in bounds if signal >= start and last <= end]
    result = dict(day=store.day, first=bounds[0][0], last=bounds[-1][2], sim=None)
    if periods:
        out = run(store, r, periods[0][0], periods[-1][1])
        sim = {key:out["main"][key] for key in ("curve", "total", "dd", "turn", "execution")}
        sim.update(valuation=out["valuation"], limitCoverage=out["limitCoverage"],
                   logs=[{**{k:p[k] for k in ("signal","entry","end","filled","held","stale","turn","ret")},
                          "n":p["candidates"]} for p in out["months"]])
        result["sim"] = sim
    return result


@lru_cache(maxsize=16)
def signals(store, model, exchange):
    key = store.factor_index["views"][model+"-"+(exchange or "all")]
    return [(row["signal"], row["entry"], row["end"]) for row in store.json(key)]


def parse_rules(data):
    if not isinstance(data, dict):
        raise ValueError("组合设置无效。")
    symbols, weights = data.get("symbols", []), data.get("weights", [])
    if (not isinstance(symbols, list) or not isinstance(weights, list) or len(symbols) > 200 or len(weights) > 200
        or any(not isinstance(c,str) or not CODE.fullmatch(c) for c in symbols)
        or any(type(w) not in (int,float) or not math.isfinite(w) for w in weights)):
        raise ValueError("请检查自选名单和权重。")
    r = Rules(model=data["model"], count=data["count"], weighting=data["weighting"], cadence=data.get("intervalUnit", "months"),
              interval=data["interval"], fee=data["fee"], bench=data["bench"], control=data.get("controlModel", "mom"),
              exchange=data.get("exchange",""), symbols=tuple(symbols), weights=tuple(weights))
    if type(r.count) is not int or type(r.interval) is not int or type(r.fee) not in (int,float):
        raise ValueError("请填写有效的持仓数、交易日和费率。")
    return r


def seal(payload, stage, version, signing_key):
    raw = json.dumps([stage, version, payload], ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()
    signature = hmac.digest(signing_key, raw, "sha256")
    return base64.urlsafe_b64encode(signature+raw).decode()


def unseal(token, stage, version, signing_key):
    try:
        if not isinstance(token,str) or len(token) > 40000:
            raise ValueError
        data = base64.b64decode(token, altchars=b"-_", validate=True)
        signature, raw = data[:32], data[32:]
        if not hmac.compare_digest(signature, hmac.digest(signing_key, raw, "sha256")):
            raise ValueError
        signed_stage, signed_version, payload = json.loads(raw)
        if signed_stage != stage:
            raise ValueError
    except (TypeError, ValueError, UnicodeError):
        raise ValueError("请先完成样本内参数比较并锁定第一名。") from None
    if signed_version != version:
        raise SnapshotChanged("行情版本已更新，请重新比较参数并锁定。")
    return payload


def portfolio(store, body, key):
    action = body.get("action")
    if action == "range":
        data = body["rules"]
        r = parse_rules(data)
        return dict(day=store.day, rules=data, result=run(store, r, data["trainFrom"], data["trainTo"]))
    if action == "compare":
        plan = body["plan"]
        common, candidates, criterion = plan["common"], plan["candidates"], plan["criterion"]
        if common.get("source") not in ("factor","manual") or not isinstance(candidates,list) or not 2 <= len(candidates) <= 8:
            raise ValueError("请设置 2 至 8 组候选参数。")
        windows = tuple(common[k] for k in ("trainFrom","trainTo","testFrom","testTo"))
        setups = []
        manual = common["source"] == "manual"
        for candidate in candidates:
            if manual != (candidate["model"] == "manual"):
                raise ValueError("候选必须使用同一股票来源。")
            setup = {**candidate, **{k:common[k] for k in ("bench","fee","trainFrom","trainTo","testFrom","testTo")},
                     "exchange":"" if manual else common.get("exchange",""), "controlModel":common.get("controlModel","mom"),
                     "symbols":common.get("symbols",[]) if manual else [],
                     "weights":(common.get("weights",[]) if manual else candidate.get("weights",[])) if candidate["weighting"]=="manual" else []}
            setups.append(setup)
        ranked, winner = compare(store, [parse_rules(s) for s in setups], windows, criterion)
        ranking = []
        for pos, row in enumerate(ranked, 1):
            metrics = {"from":row["start"],"to":row["end"],"total":row["return"],"dd":row["drawdown"],
                       "completeMonths":row["months"],"invested":row["invested"],"sharpe":row["sharpe"]}
            ranking.append(dict(index=row["index"], rank=pos if row[criterion] is not None else None, metrics=metrics))
        rules = setups[winner] if winner is not None else None
        receipt = seal(rules, "winner", release(store), key) if rules else None
        return dict(day=store.day, ranking=ranking, winner=winner, rules=rules, receipt=receipt)
    if action not in ("lock", "test", "review") or set(body) != {"action","token"}:
        raise ValueError("请使用已锁定的规则和区间。")
    data = unseal(body["token"], "winner" if action=="lock" else "locked", release(store), key)
    if action=="lock":
        return dict(token=seal(data,"locked",release(store),key))
    window = "test" if action=="test" else "train"
    return dict(day=store.day, rules=data, result=run(store,parse_rules(data),data[window+"From"],data[window+"To"]))


def live(store, query, token):
    from .live_quotes import _market_probe, cache_scope, recent
    if not token:
        raise ValueError("网站尚未配置 Tushare Token。")
    _, today = cache_scope(store)
    if not query.get("symbol"):
        a, b = _market_probe(today, token)
        common = {r["trade_date"] for r in a[0]} & {r["trade_date"] for r in b[0]}
        return dict(day=store.day, latest=max(common, default=None), checked=max(a[1], b[1]))
    code, row = security(store, query["symbol"])
    provider = "daily" if row[2] == "stock" else ("sw_daily" if row[8]=="industry" and code.endswith(".SI")
               else "ci_daily" if row[8]=="industry" and code.endswith(".CI") else "index_daily")
    rows, when = recent(provider,code,today,token)
    return dict(day=store.day, rows=rows[:5], checked=when)


def dispatch(store, path, body, signing_key, token=""):
    loc = urlsplit(path)
    if loc.scheme or loc.netloc:
        raise ValueError("无效的研究查询。")
    q = {k:v[-1] for k,v in parse_qs(loc.query,keep_blank_values=True,max_num_fields=20).items()}
    asof = (body or {}).get("asOf") or q.get("asOf")
    if asof and asof!=store.day:
        raise SnapshotChanged("页面与行情库交易日不同，请刷新。")
    if loc.path=="/route":
        return {}
    if loc.path=="/api/news":
        from .news_store import cache
        return cache.get(store, refresh=(body or {}).get("refresh") is True)
    if loc.path=="/api/studies" and isinstance(body,dict):
        from .factor_studies import analyze
        return analyze(store,body)
    if loc.path=="/api/workspace":
        if q.get("view")=="factors":
            return dict(day=store.day, factors={**store.factors,"groups":store.bands["groups"],"officialLimits":True})
        m=store.manifest
        return dict(day=store.day, rows=store.snapshot["items"], aliases=store.snapshot.get("aliases",{}),
                    progress={k:m[k] for k in ("ready","bars")}, sample=bool(m.get("sample")))
    if loc.path=="/api/series":
        return quotes(store,q)
    if loc.path=="/api/coverage":
        return coverage(store,q)
    if loc.path=="/api/research":
        kind=q.get("type")
        code,_=security(store,q.get("symbol",""))
        result=extra(store,kind,code,q.get("day") or store.day,token)
        return {"items":result} if kind=="financial" else result
    if loc.path=="/api/strategy":
        return strategy(store,q)
    if loc.path=="/api/portfolio" and isinstance(body,dict):
        return portfolio(store,body,signing_key)
    if loc.path=="/api/live":
        return live(store,q,token)
    raise ValueError("未知的研究查询。")
