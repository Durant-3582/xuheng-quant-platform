"""Expose the desk's existing study engines to the assistant, with their original units."""
import math

from .assistant_tools import DEFAULT_WEIGHTS, compact, day, evidence, resolve
from .factor_studies import analyze, weights
from .frames import BENCHMARKS, MODELS, WEIGHTS, Rules
from .portfolio import run
from .portfolio_risk import risk_view


def factor_test(store, p, window, view):
    mix = p.get("weights", {"mom": 100})
    venue = p.get("venue", "ALL")
    data = analyze(store, {**window, "action": "test", "weights": mix, "venue": "" if venue == "ALL" else venue})
    if view == "months":
        rows = data["months"]
    elif view == "annual":
        rows = [{"year": year, **stats} for year, stats in data["annual"]]
    elif view == "overlap":
        rows = [dict(factor_a=a, factor_b=b, mean_rank_correlation=r, months=n) for a,b,r,n in data["overlap"]]
    elif view == "persistence":
        rows = [dict(horizon_months=h, months=n, mean_rank_ic=ic, pairs=pairs) for h,n,ic,pairs in data["persistence"]]
    else:
        rows = [data["summary"]]
    note = (f"因子百分比 {mix}，市场 {venue}，研究库 {data['cutoff']}。meanIC 为各有效月 Rank IC 均值，"
            "positive 为正 IC 月份占比（%）。groups 和 medians 按得分从高到低列五组，单位为 %。")
    return "因子检验", rows, note


def rotation(store, p, window, view):
    count, fee, timing = p.get("count",5), p.get("fee_bps",10), p.get("timing",True)
    data = analyze(store, {**window, "action":"rotation", "top":count, "fee":fee, "timing":timing})
    if view == "months":
        rows = [{**m, "names":"、".join(m["names"]),
                 "market": m["market"] if math.isfinite(m["market"]) else None,
                 "ma": m["ma"] if math.isfinite(m["ma"]) else None} for m in data["log"]]
    else:
        rows = [dict(组合=label, 累计收益_pct=total, 最大回撤_pct=dd, 累计费用_pct=cost,
                     实际估值首日=data["curve"][0][0], 实际估值末日=data["curve"][-1][0])
                for label,(total,dd,cost) in zip(("行业轮动","可选行业等权"),data["summary"]) if data["curve"]]
    note = (f"申万一级行业，选择前 {count} 个，沪深300的200日均线择时{'开启' if timing else '关闭'}，"
            f"每月调仓，单边 {fee:g} 基点，缺少估值的交易日 {len(data['missing'])} 个。")
    return "行业轮动回测", rows, note


def portfolio(store, p, window, view):
    codes = tuple(resolve(store,s)[0] for s in p.get("symbols",[]))
    model = p.get("model", "manual" if codes else "mom")
    weighting = p.get("weighting", "manual" if "allocations" in p else "equal")
    if codes and model != "manual" or model == "manual" and p.get("venue","ALL") != "ALL":
        raise ValueError("自选名单须使用 manual 模型，名单本身决定股票市场。")
    if "weights" in p and model != "multi" or "allocations" in p and weighting != "manual":
        raise ValueError("因子百分比须用于 multi 模型，持仓百分比须用于 manual 配权。")
    venue = p.get("venue","ALL")
    rule = Rules(model=model, count=p.get("count",len(codes) if model=="manual" else 10),
                 weighting=weighting, cadence=p.get("cadence","hold" if model=="manual" else "months"),
                 interval=p.get("interval",1), bench=resolve(store,p.get("benchmark","000300.SH"))[0],
                 exchange="" if venue=="ALL" else venue, fee=p.get("fee_bps",10),
                 symbols=codes, weights=tuple(p.get("allocations",[])),
                 factor_weights=tuple(weights({"weights":p.get("weights",DEFAULT_WEIGHTS)}).tolist()) if model=="multi" else ())
    data = run(store,rule,window["from"],window["to"],risk=view=="risk")
    periods,main = data["months"],data["main"]
    if view == "months":
        rows = periods
    elif view == "holdings":
        rows = [{"股票":h["code"],"名称":store.catalog[h["code"]][1],"目标权重_pct":h["weight"],
                 "期末实际权重_pct":h["endWeight"],"末日估值沿用旧价":h["stale"]} for h in data["holdings"]]
    elif view == "risk":
        risk = risk_view(store,data["riskSnapshot"])
        book = risk["books"][rule.weighting]
        rows = [dict(状态=book["state"],估值日=risk["end"],共同观测日数=risk["common"],现金_pct=book["cash"],
                     组合年化波动率_pct=book["vol"])]
        for code,w,share,vol in book["rows"]:
            rows.append(dict(股票=code,实际权重_pct=w,波动风险贡献_pct=share,贡献的年化波动_百分点=vol))
        # The web evidence table uses the first row's columns for every row.
        for row in rows:
            for k in ("状态","估值日","共同观测日数","现金_pct","组合年化波动率_pct","股票","实际权重_pct","波动风险贡献_pct","贡献的年化波动_百分点"):
                row.setdefault(k,None)
    else:
        rows = [dict(首个成交估值日=periods[0]["entry"],估值末日=periods[-1]["end"],组合累计收益_pct=main["total"],
                     最大回撤_pct=main["dd"],平均双边换手_pct=main["turn"],累计交易成本_pct=main["cost"],
                     基准累计收益_pct=data["market"]["total"] if data["market"] else None,
                     期末持股数=periods[-1]["held"],期末现金_pct=periods[-1]["cash"])]
    schedule = {"days":f"每 {rule.interval} 个交易日","months":f"每 {rule.interval} 个月","hold":"买入并持有"}[rule.cadence]
    note = (f"{MODELS[model]}，{WEIGHTS[weighting]}，{schedule}，单边 {rule.fee:g} 基点，"
            f"基准 {BENCHMARKS[rule.bench]}，持股目标 {rule.count}，市场 {venue}。")
    if codes: note += " 名单 "+"、".join(codes)+"。"
    if rule.weights: note += " 持仓百分比 "+str(rule.weights)+"。"
    if rule.factor_weights: note += " 因子百分比 "+str(p.get("weights",DEFAULT_WEIGHTS))+"。"
    return "组合区间回测", rows, note


def strategy(store, p, window, view):
    from .desk_api import strategy as desk_strategy
    model,venue = p.get("model","mom"),p.get("venue","ALL")
    count,fee = p.get("count",30),p.get("fee_bps",10)
    data = desk_strategy(store,{**window,"factor":model,"exchange":"" if venue=="ALL" else venue,"count":count,"fee":fee})
    sim = data["sim"]
    rows = [] if not sim else sim["logs"] if view=="months" else [dict(
        累计收益_pct=sim["total"],最大回撤_pct=sim["dd"],平均双边换手_pct=sim["turn"],
        首个信号日=sim["logs"][0]["signal"],实际估值末日=sim["logs"][-1]["end"],调仓期数=len(sim["logs"]))]
    return "策略回测",rows,f"{MODELS[model]}，市场 {venue}，目标 {count} 只，月末信号，单边 {fee:g} 基点。"


STUDIES = {
    "factor_test": (factor_test, {"venue","weights"}, {"summary","months","annual","overlap","persistence"}),
    "industry_rotation": (rotation, {"count","fee_bps","timing"}, {"summary","months"}),
    "portfolio": (portfolio, {"count","fee_bps","venue","weights","allocations","symbols","model","weighting",
                              "cadence","interval","benchmark"}, {"summary","months","holdings","risk"}),
    "strategy": (strategy, {"model","venue","count","fee_bps"}, {"summary","months"}),
}


def run_study(store, p):
    engine, options, views = STUDIES[p["study"]]
    extra = set(p)-options-{"study","start","end","view","page"}
    if extra:
        raise ValueError("该页面研究不使用下列设置："+"、".join(sorted(extra))+"。")
    view = p.get("view","summary")
    if view not in views:
        raise ValueError("可选的结果为 "+"、".join(sorted(views))+"。")
    start,end = (compact(day(p[key])) for key in ("start","end"))
    title,rows,note = engine(store,p,{"from":start,"to":end},view)
    page = p.get("page",1)
    offset = (page-1)*30
    return evidence("序衡研究工作台",title,start+" 至 "+end+" · "+view,rows[offset:offset+30],
                    f"{note} 第 {page} 页，共 {len(rows)} 行。")
