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


SYMBOL = field("要核对的证券名称或代码，可以来自用户、你的研究判断或选股结果。六位代码有歧义时用全代码。")
DAY = field("指定日期 YYYYMMDD。")
FACTOR_LABELS = {"mom":"60 日动量（%）","vol":"20 日年化波动率（%）","pb":"市净率（倍）",
                 "roe":"最近年报 ROE（%）","pe":"滚动市盈率（倍）","turn":"当日换手率（%）"}
DEFAULT_WEIGHTS = {"mom":25,"pb":40,"roe":35}
SORT_LABELS = {"revenue":"营业总收入同比从高到低","profit":"归母净利润同比从高到低","roe":"ROE 从高到低",
               "gross":"毛利率从高到低","pe":"正滚动市盈率从低到高","debt":"资产负债率从低到高"}
VENUES = {"ALL":"沪深北 A 股","SH":"沪市 A 股","SZ":"深市 A 股","BJ":"北交所 A 股"}
SELECTION = {
    "venue": field("股票池，默认沪深北全部 A 股。", enum=list(VENUES)),
    "industry": field("可选，按股票目录行业在全池中先筛后排，例如银行、白酒、半导体。"),
    "as_of": field("仅当用户指定信号日时填写。工具提供最近完整研究截面，不以当前数据回填历史。"),
    "limit": {"type":"integer","minimum":1,"maximum":25,"description":"每页股票数，默认 5，可翻页。"},
    "page": {"type":"integer","minimum":1,"maximum":10001,"description":"结果页，从 1 开始。"},
}
TOOLS = [
    tool("search_web", "检索外部公开资料。优先用本站数据库和 Tushare 核对已有数据；缺少的公告、事件、业务资料或其他信息可搜索补充。"
         "可以自主选择搜索词，优先公司、交易所、监管机构等原始来源；结果含标题、链接、发布日期和摘要。",
         {"query": field("搜索词，支持 site: 和引号精确搜索，可拆分多次查询。", maxLength=128),
          "count": {"type":"integer","minimum":1,"maximum":50,"description":"返回结果数，默认5。"}}, ["query"]),
    tool("read_web", "读取外部资料原文并核对来源，可读取搜索结果或用户提供的链接。返回正文和链接；长文可指定 start 继续读取。",
         {"url": field("完整 HTTP 或 HTTPS 网页地址，不含凭据。", maxLength=8192),
          "start": {"type":"integer","minimum":0,"maximum":10000000,"description":"正文起始字符，默认0。"}}, ["url"]),
    tool("describe_site_data","发现序衡各页面的数据、列名和口径。可列出全部，或按表名查字段。跨数据集问题可先发现，再用 query_site 联查。",
         {"tables":{"type":"array","items":field("表名"),"maxItems":30}}, []),
    tool("query_site","自由查询序衡自己的研究数据，支持 SQLite SELECT、JOIN、GROUP BY、排序、窗口函数和样本标准差 stdev。"
         "先用 describe_site_data 看列。stock_beta 为最新120日配对（含基准、日期、相关系数）；beta_history 为历史；"
         "stock_study 为原网页诊断、均线、估值分位、模拟收益和一年相对判断；reports 为已披露财报。"
         "还可查日线、指数成分、新闻、行业和全市场截面。例：tables=[stock_beta]，symbols=[贵州茅台,五粮液]，"
         "sql=SELECT name,benchmark,day,observations,beta FROM stock_beta。输出列可用中文别名。"
         "不指定证券可对市场截面全量统计；指定证券的表用 symbols 选取源数据。不同来源日期以证据为准。",
         {"tables":{"type":"array","items":field("站内表名"),"maxItems":24},
          "sql":field("一条只读 SQLite SELECT。日期列为 YYYYMMDD 文本。查询某天时以 WHERE day= 精确匹配。",maxLength=7000),
          "symbols":{"type":"array","items":SYMBOL,"maxItems":50,"description":"个股/指数时间序列表的证券，可分批联查。"},
          "benchmark":field("Beta/相对研究选用的市场指数名称或代码，默认沪深300。"),
          "as_of":field("计算与财报的可得信息截止日。省略用本站最新版本。"),
          "period":field("全市场财报截面报告期 YYYYMMDD，或 latest。")},["tables","sql"]),
    tool("run_site_study","调用页面的因子检验（Rank IC、分组收益、因子相关）、申万行业轮动、策略回测或组合区间回测。"
         "采用用户给出的条件，省略可选参数时说明默认值。组合支持选股模型、自选、TB/等权/手动和按交易日调仓。",
         {"study":field("页面研究",enum=["factor_test","industry_rotation","portfolio","strategy"]),
          "start":DAY,"end":DAY,"benchmark":SYMBOL,
          "model":field("组合模型",enum=["mom","vol","pb","rev","multi","manual"]),
          "symbols":{"type":"array","items":SYMBOL,"maxItems":200},
          "weights":{"type":"object","description":"因子百分比，合计100；mom/vol/pb/roe/pe/turn。",
                     "properties":{k:{"type":"number"} for k in FACTOR_LABELS},"additionalProperties":False},
          "allocations":{"type":"array","items":{"type":"number"},"maxItems":200,"description":"手动持仓百分比，名单顺序或排名顺序。"},
          "weighting":field("配权",enum=["equal","tb","manual"]),
          "cadence":field("买入持有/交易日/按月",enum=["hold","days","months"]),
          "interval":{"type":"integer","minimum":1,"maximum":10000},
          "count":{"type":"integer","minimum":1,"maximum":200},
          "timing":{"type":"boolean","description":"行业轮动是否采用沪深300的200日趋势择时。"},
          "fee_bps":{"type":"number","description":"单边费率，基点。"},
          "venue":field("股票市场",enum=list(VENUES)),
          "view":field("结果类型",enum=["summary","months","annual","overlap","persistence","holdings","risk"]),
          "page":{"type":"integer","minimum":1,"maximum":10001,"description":"明细页，从1开始，每页30行。"}},
         ["study","start","end"]),
    tool("rank_stocks","从全市场或指定行业选股、推荐股票并比较候选。无需预先知道股票代码。"
         "可以自行设计权重，低波动、低正 PB、低正 PE 优先，动量、年报 ROE、换手按高值优先。"
         "省略权重使用网页默认的低 PB 40%、年报 ROE 35%、60 日动量 25%。",
         {**SELECTION, "weights":{"type":"object","description":"非零因子权重合计 100，各项可省略。",
          "additionalProperties":False,"properties":{k:{"type":"number","minimum":0,"maximum":100,
          "description":label} for k,label in FACTOR_LABELS.items()}}}, []),
    tool("screen_financials","按已披露财报筛选和推荐 A 股，可设盈利能力和负债门槛，按增长、盈利或估值排序。"
         "未给门槛就不设门槛，默认用最普遍的同一报告期，可指定季末或各公司最近一期。",
         {**SELECTION, "period":field("YYYYMMDD 季末，或 latest 表示各公司最近披露，省略采用共同报告期。"),
          "min_roe":{"type":"number","description":"累计 ROE 下限（%），10 代表 10%。"},
          "max_debt":{"type":"number","minimum":0,"maximum":1000,"description":"资产负债率上限（%）。"},
          "sort":field("排序指标，默认营业总收入同比。",enum=list(SORT_LABELS))}, []),
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
         "支持买入持有或每月调仓，区间按网站历史覆盖，自选最多200只。",
         {"symbols": {"type": "array", "items": SYMBOL, "maxItems": 200}, "start": DAY, "end": DAY,
          "weighting": field("等权或仅做多 TB", enum=["equal", "tb"]),
          "cadence": field("期初或每月配权", enum=["hold", "months"]),
          "fee_bps": {"type": "number", "description": "单边费率（基点）"}, "benchmark": SYMBOL},
         ["symbols", "start", "end", "weighting", "cadence", "fee_bps"]),
    tool("clarify", "自由讨论研究思路、解释概念或询问必要的澄清时，可在 reply 中直接回答。"
         "推荐具体股票、报告市场数值时先用对应的数据工具。", {
             "reply":field("不需要行情事实支撑的分析、设想或澄清问题。", maxLength=8000)}, []),
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


def stock_selection(name, p, store):
    from .factor_studies import analyze

    venue = p.get("venue", "ALL")
    size, page = p.get("limit", 5), p.get("page", 1)
    industry = p.get("industry", "").strip()
    query = {"venue": "" if venue == "ALL" else venue, "industry": industry, "pageSize": size, "page": page-1}
    if "as_of" in p:
        query["asOfDate"] = compact(day(p["as_of"]))
    ranked = name == "rank_stocks"
    if ranked:
        weights = p.get("weights", DEFAULT_WEIGHTS)
        query.update(action="rank", weights=weights)
    else:
        period = p.get("period", "common")
        if period not in ("common", "latest"):
            period = compact(day(period))
        order = p.get("sort", "revenue")
        query.update(action="screen", period=period, sort=order, minROE=p.get("min_roe"), maxDebt=p.get("max_debt"))
    data = analyze(store, query)
    coverage = VENUES[venue] + (" · "+industry if industry else "")
    scope = f"{day(data['cutoff']).isoformat()} · {coverage} · 当日有报价 {data['pool']} 只，入选范围 {data['total']} 只"
    if ranked:
        rule = "、".join(f"{FACTOR_LABELS[k].partition('（')[0]} {weights[k]:g}%" for k in data["keys"])
        scope += " · 因子权重为"+rule
        note = "仅纳入所选因子齐备的股票。综合分为同一股票池的百分位加权平均，满分 100。"
    else:
        report = data["period"]
        scope += " · "+("各公司最近披露" if report=="latest" else day(report).isoformat()+" 报告期")+" · "+SORT_LABELS[order]
        if "min_roe" in p:
            scope += f" · ROE ≥ {p['min_roe']:g}%"
        if "max_debt" in p:
            scope += f" · 资产负债率 ≤ {p['max_debt']:g}%"
        note = "ROE 为报告期累计值，滚动市盈率取研究截止日。缺少筛选或排序字段的公司不进入排名。"
    rows = []
    if data["page"] == page-1:
        for rank, result in enumerate(data["rows"], 1+(page-1)*size):
            code = result[0]
            security = store.catalog[code]
            row = {"排名":rank, "证券代码":code, "证券名称":security[1], "行业":security[4]}
            if ranked:
                _, score, values, percentiles, annual = result
                row["综合分"] = round(score, 4)
                for key, value, percentile in zip(data["keys"], values, percentiles):
                    row[FACTOR_LABELS[key]] = value
                    row[FACTOR_LABELS[key].partition("（")[0]+"百分位分"] = round(percentile, 4)
                if annual:
                    row["年报报告期"], row["年报公告日"] = day(annual[0]).isoformat(), day(annual[1]).isoformat()
            else:
                values = result[1]
                row.update({"报告期":day(values[0]).isoformat(), "公告日":day(values[1]).isoformat(),
                            "ROE（%）":values[3], "毛利率（%）":values[4], "资产负债率（%）":values[5],
                            "营业总收入同比（%）":values[6], "归母净利润同比（%）":values[7], "滚动市盈率（倍）":values[8]})
            rows.append(row)
    scope += f" · 第 {page} 页，每页 {size} 只"
    return evidence("序衡研究库（Tushare）", "多因子选股" if ranked else "财务条件选股", scope, rows, note)


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
    if any(row[2] != "stock" for row in codes) or not 1 <= len(codes) <= 200:
        raise ValueError("请提供 1 至 200 只不同的自选 A 股。")
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


def execute(name, p, store, client, *, web=None):
    spec = SCHEMAS.get(name)
    if not spec or not isinstance(p, dict) or set(p) - set(spec["properties"]) or set(spec["required"]) - set(p):
        raise ValueError("查询参数不完整或当前不支持这项查询。")
    for key, value in p.items():
        schema = spec["properties"][key]
        if schema["type"] == "string" and (not isinstance(value, str) or len(value) > schema.get("maxLength",64)):
            raise ValueError("查询字段格式无效。")
        if schema["type"] == "array" and (not isinstance(value, list) or len(value) > schema["maxItems"]):
            raise ValueError(f"{key} 需要一个最多 {schema['maxItems']} 项的列表。")
        if schema["type"] == "array" and schema["items"]["type"]=="string" and any(not isinstance(v,str) for v in value):
            raise ValueError("列表需要由名称或代码组成。")
        if schema["type"] == "array" and schema["items"]["type"]=="number" and any(type(v) not in (int,float) or not math.isfinite(v) for v in value):
            raise ValueError("权重列表的每项须为有限数字。")
        if schema["type"] == "boolean" and type(value) is not bool:
            raise ValueError("开关参数应为布尔值。")
        if schema["type"] == "number" and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError("请输入有效的数值参数。")
        if schema["type"] == "integer" and (type(value) != int or not schema["minimum"] <= value <= schema["maximum"]):
            raise ValueError(f"{key} 须为 {schema['minimum']} 至 {schema['maximum']} 以内的整数。")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError("请选择支持的查询选项。")
    if name in ("search_web", "read_web"):
        if web is None:
            raise ServiceError("外部资料检索尚未连接。")
        return web.execute(name, p)
    if name == "describe_site_data":
        from .assistant_site import catalog
        return catalog(p.get("tables"))
    if name == "query_site":
        from .assistant_site import query_site
        return query_site(store,client,p)
    if name == "run_site_study":
        from .assistant_studies import run_study
        return run_study(store,p)
    if name in ("rank_stocks", "screen_financials"):
        return stock_selection(name, p, store)
    if name == "security_data":
        return security_data(store, client, p)
    if name == "financial_report":
        return financial_report(store, client, p)
    if name == "market_breadth":
        return market_breadth(store, p)
    if name == "portfolio_backtest":
        return portfolio_backtest(store, p)
    return None
