"""Bounded research queries with the same labels and units in the answer and its evidence."""
from datetime import date, datetime, timedelta
import math
import re
from zoneinfo import ZoneInfo

from .assistant_clients import ServiceError
from .frames import BENCHMARKS, Rules


def field(description, **options):
    return {"type": "string", "description": description, **options}


def tool(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "additionalProperties": False,
                           "properties": properties, "required": required}}}


SYMBOL = field("用户提供的证券名称、代码或前文已确认的证券。六位代码有歧义时询问全代码。")
DAY = field("指定日期 YYYYMMDD。")
TOOLS = [
    tool("security_data", "通过 Tushare MCP 查一只股票或指数的未复权日线，或一只股票的历史估值。"
         "给定某天时只填 end；最新时省略起止日期；明确区间可查最多31个自然日。多证券分别调用。",
         {"symbol": SYMBOL, "dataset": field("行情或估值", enum=["prices", "valuation"]),
          "start": DAY, "end": DAY}, ["symbol", "dataset"]),
    tool("financial_report", "按用户指定的报告期查 Tushare 财务指标及公告日。报告期为季末日期。"
         "若指定当时可知的日期则填写 known_by，只能核对此接口当前返回的版本。",
         {"symbol": SYMBOL, "period": DAY, "known_by": DAY}, ["symbol", "period"]),
    tool("market_breadth", "查询序衡市场宽度，计数和占比为全A股站上各自200日均线的股票，省略日期取研究库最新。",
         {"day": DAY}, []),
    tool("portfolio_backtest", "调用序衡现有组合回测。仅适用于用户明确提出的自选股票组合、区间、"
         "配权方式、调仓规则，费率单位是单边基点；参考基准可省略（默认沪深300）。"
         "支持买入持有或每月调仓。单次问答最多12只、区间一年。缺少重要设置时先询问。",
         {"symbols": {"type": "array", "items": SYMBOL, "maxItems": 12}, "start": DAY, "end": DAY,
          "weighting": field("等权或仅做多 TB", enum=["equal", "tb"]),
          "cadence": field("期初或每月配权", enum=["hold", "months"]),
          "fee_bps": {"type": "number", "description": "单边费率（基点）"}, "benchmark": SYMBOL},
         ["symbols", "start", "end", "weighting", "cadence", "fee_bps"]),
    tool("clarify", "问题缺少关键信息、有歧义、超出可查范围或仅需解释本平台概念时使用。", {}, []),
]
SCHEMAS = {t["function"]["name"]: t["function"]["parameters"] for t in TOOLS}
LABELS = {"ts_code": "证券代码", "trade_date": "交易日", "ann_date": "公告日", "end_date": "报告期",
          "open": "开盘", "high": "最高", "low": "最低", "close": "收盘", "pre_close": "参考前收盘",
          "pct_chg": "日涨跌幅（%）", "pct_change": "日涨跌幅（%）", "pe": "静态市盈率（倍）",
          "pe_ttm": "滚动市盈率（倍）", "pb": "市净率（倍）", "turnover_rate": "换手率（%）",
          "roe": "净资产收益率 ROE（%）", "grossprofit_margin": "销售毛利率（%）",
          "debt_to_assets": "资产负债率（%）", "netprofit_yoy": "归母净利润同比（%）"}


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}|\d{4}-\d{2}-\d{2}", value):
        raise ValueError("日期需为有效的年月日。")
    try:
        dt = date.fromisoformat(value.replace("-", ""))
    except ValueError:
        raise ValueError("日期不存在，请核对年月日。") from None
    if dt.year < 2000:
        raise ValueError("本平台的研究范围从 2000 年开始。")
    return dt


def compact(value):
    return value.strftime("%Y%m%d")


def resolve(store, value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 48:
        raise ValueError("请提供证券名称或代码。")
    name = re.sub(r"\s+", "", value).upper()
    aliases = store.snapshot.get("aliases", {})
    if name in aliases or name in store.catalog:
        return store.catalog[aliases.get(name, name)]
    candidates = {r[0]: r for r in store.catalog.values()
                  if name in (r[0].split(".")[0], re.sub(r"\s+", "", r[1]).upper())}
    for old, code in aliases.items():
        if old.split(".")[0] == name:
            candidates[code] = store.catalog[code]
    if len(candidates) == 1:
        return next(iter(candidates.values()))
    if candidates:
        # The same named benchmark can be published under both exchange codes.
        # Preserve explicit suffixes and never resolve a colliding six-digit code this way.
        if not name.isdigit() and all(row[2] == "index" for row in candidates.values()):
            preferred = [candidates[code] for code in BENCHMARKS if code in candidates]
            if len(preferred) == 1:
                return preferred[0]
        options = "、".join(r[1] + " " + r[0] for r in list(candidates.values())[:5])
        raise ValueError("证券有重名或重号，请确认完整代码：" + options)
    raise ValueError("序衡证券目录中未找到该名称或代码，请提供带交易所后缀的代码。")


def evidence(source, endpoint, scope, rows, note=""):
    return {"source": source, "endpoint": endpoint, "scope": scope, "rows": rows, "note": note}


def number(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ServiceError("上游数值字段格式异常。")
    try:
        n = float(value)
    except (ValueError, TypeError):
        raise ServiceError("上游数值字段格式异常。") from None
    return n if math.isfinite(n) else None


def verified_rows(rows, code, fields, date_key, lo, hi):
    result = []
    for row in rows:
        stamp = row.get(date_key)
        if row.get("ts_code") != code or not isinstance(stamp, str) or not lo <= stamp <= hi:
            raise ServiceError("Tushare 返回的证券或日期与请求不符。")
        record = {}
        for k in fields:
            v = row.get(k)
            if k in ("trade_date", "ann_date", "end_date"):
                if v is not None:
                    v = day(v).isoformat()
            elif k != "ts_code":
                v = number(v)
            record[LABELS[k]] = v
        result.append(record)
    return result


def security_data(store, client, p):
    item = resolve(store, p["symbol"])
    code, name, kind = item[:3]
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    latest = not p.get("start") and not p.get("end")
    hi = day(p["end"]) if p.get("end") else today
    lo = day(p["start"]) if p.get("start") else hi - timedelta(days=30) if latest else hi
    if hi < lo or (hi - lo).days > 30:
        raise ValueError("一次日线查询可覆盖 1 至 31 个自然日，请缩短区间。")
    if p["dataset"] == "valuation":
        if kind != "stock":
            raise ValueError("个股估值接口仅覆盖股票。指数估值需另行核对。")
        endpoint = "daily_basic"
        fields = ["ts_code", "trade_date", "pe", "pe_ttm", "pb", "turnover_rate"]
        note = "估值单位为倍，缺值表示该指标未披露或不适用。"
    else:
        endpoint = ("daily" if kind == "stock" else "sw_daily" if code.endswith(".SI") else
                    "ci_daily" if code.endswith(".CI") else "index_daily")
        change = "pct_change" if endpoint in ("sw_daily", "ci_daily") else "pct_chg"
        fields = ["ts_code", "trade_date", "open", "high", "low", "close", change]
        note = "个股未复权价格，单位为元。" if kind == "stock" else "指数价格单位为点。"
    scope = f"{name} {code} · {lo.isoformat()}" + (" 至 " + hi.isoformat() if hi != lo else "")
    args = {"trade_date": compact(hi)} if hi == lo else {"start_date": compact(lo), "end_date": compact(hi)}
    raw = client.call(endpoint, {"ts_code": code, **args, "fields": fields})
    rows = verified_rows(raw, code, fields, "trade_date", compact(lo), compact(hi))
    if len({r["交易日"] for r in rows}) != len(rows):
        raise ServiceError("Tushare 返回重复交易日，暂时无法给出唯一结果。")
    rows.sort(key=lambda r: r["交易日"], reverse=True)
    if latest:
        rows = rows[:1]
        note += " 返回查询窗口内最新一条已公布记录。"
    return evidence("Tushare MCP", endpoint, scope, rows, note)


def financial_report(store, client, p):
    code, name, kind = resolve(store, p["symbol"])[:3]
    period = compact(day(p["period"]))
    if kind != "stock" or period[4:] not in ("0331", "0630", "0930", "1231"):
        raise ValueError("财务指标需要 A 股个股及有效季末报告期。")
    known = day(p["known_by"]).isoformat() if p.get("known_by") else None
    fields = ["ts_code", "end_date", "ann_date", "roe", "grossprofit_margin", "debt_to_assets", "netprofit_yoy"]
    raw = client.call("fina_indicator", {"ts_code": code, "period": period, "fields": fields})
    rows = verified_rows(raw, code, fields, "end_date", period, period)
    if known:
        rows = [r for r in rows if r["公告日"] and r["公告日"] <= known]
    rows.sort(key=lambda r: r["公告日"] or "", reverse=True)
    scope = f"{name} {code} · 报告期 {day(period).isoformat()}" + (" · 截至 " + known if known else "")
    return evidence("Tushare MCP", "fina_indicator", scope, rows, "列出接口返回的版本及公告日，各指标沿用报告期口径。")


def market_breadth(store, p):
    from .factor_studies import analyze
    data = analyze(store, {"action": "breadth"})
    stamp = compact(day(p["day"])) if p.get("day") else data["cutoff"]
    values = [{"交易日": day(r[0]).isoformat(), "站上均线（只）": r[1], "有效样本（只）": r[2],
               "当日报价（只）": r[3], "站上均线占比（%）": round(100*r[1]/r[2], 4) if r[2] else None}
              for r in data["rows"] if r[0] == stamp]
    return evidence("序衡研究库（Tushare 日线计算）", "200 日均线市场宽度", day(stamp).isoformat(), values,
                    "分母仅含当日有有效报价、且已有 200 个有效收盘的股票。")


def portfolio_backtest(store, p):
    from .portfolio import run
    start, end = day(p["start"]), day(p["end"])
    codes = [resolve(store, s) for s in p["symbols"]]
    if any(row[2] != "stock" for row in codes) or not 1 <= len(codes) <= 12:
        raise ValueError("请明确提供 1 至 12 只自选 A 股。")
    if (end-start).days > 366:
        raise ValueError("问答区间回测最多覆盖一年，较长区间请使用组合表现页面。")
    bench = resolve(store, p.get("benchmark", "000300.SH"))[0]
    if bench not in BENCHMARKS:
        raise ValueError("请选择组合表现支持的比较基准。")
    rule = Rules(model="manual", count=len(codes), symbols=tuple(r[0] for r in codes), weighting=p["weighting"],
                 cadence=p["cadence"], fee=p["fee_bps"], bench=bench)
    result = run(store, rule, compact(start), compact(end))
    periods = result["months"]
    row = {"回测首个交易日": day(periods[0]["entry"]).isoformat(), "实际估值截止": day(periods[-1]["end"]).isoformat(),
           "组合累计收益（%）": round(result["main"]["total"], 4), "最大回撤（%）": round(result["main"]["dd"], 4),
           "基准累计收益（%）": round(result["market"]["total"], 4) if result["market"] else None,
           "期末持股数": periods[-1]["held"], "期末现金（%）": round(periods[-1]["cash"], 4)}
    rule_text = ("等权" if rule.weighting == "equal" else "仅做多 TB") + " · " + ("买入并持有" if rule.daily else "每月调仓")
    scope = f"{', '.join(rule.symbols)} · {start.isoformat()} 至 {end.isoformat()}"
    return evidence("序衡组合回测（Tushare 归档）", "区间回测", scope, [row],
                    f"{rule_text} · {BENCHMARKS[bench]} · 单边 {rule.fee:g} 个基点，已计交易成本。")


def execute(name, p, store, client):
    spec = SCHEMAS.get(name)
    if not spec or not isinstance(p, dict) or set(p) - set(spec["properties"]) or set(spec["required"]) - set(p):
        raise ValueError("查询参数不完整或当前不支持这项查询。")
    for key, value in p.items():
        schema = spec["properties"][key]
        if schema["type"] == "string" and (not isinstance(value, str) or len(value) > 64):
            raise ValueError("查询字段格式无效。")
        if schema["type"] == "array" and (not isinstance(value, list) or len(value) > schema["maxItems"]):
            raise ValueError("证券数量超出本次问答范围。")
        if schema["type"] == "number" and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError("请输入有效的数值参数。")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError("请选择支持的查询选项。")
    if name == "security_data":
        return security_data(store, client, p)
    if name == "financial_report":
        return financial_report(store, client, p)
    if name == "market_breadth":
        return market_breadth(store, p)
    if name == "portfolio_backtest":
        return portfolio_backtest(store, p)
    return None
