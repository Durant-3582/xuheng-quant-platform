from __future__ import annotations

from calendar import monthrange
from itertools import groupby
from math import sqrt
from statistics import mean, stdev

from .portfolio import run, validate
from .study_store import factor_snapshot


CRITERIA={"return":"扣费后累计收益最高","drawdown":"最大回撤最小（月度估值）","sharpe":"月收益夏普比率最高"}


def month_ends(dates):
    result={}
    for month,group in groupby(dates,key=lambda d:d[:6]):
        days=list(group)
        result[month]=(days[0],days[-1])
    return result


def calendar_check(store,rules,start,end,label):
    dates=store.daily["dates"]
    sessions=[d for d in dates if start<=d<=end]
    if not sessions:
        raise ValueError(label+"区间没有交易日。")
    monthly=[r for r in rules if not r.daily]
    if monthly:
        periods=[(a,b) for a,b in list(month_ends(dates).values())[1:] if start<=a and b<=end]
        if not periods:
            raise ValueError(label+"区间没有完整的月度持有期。")
        for rule in monthly:
            if not any((int(a[4:6])-1)%rule.interval==0 for a,_ in periods):
                raise ValueError(label+"区间未覆盖所选调仓月份。")
        if len(monthly)!=len(rules) and (periods[0][0],periods[-1][1])!=(sessions[0],sessions[-1]):
            raise ValueError(label+"的逐日与按月方案实际区间不同，请选择相同的完整交易月份。")


def score(result,dates,last_scheduled=None):
    start,end=result["months"][0]["entry"],result["months"][-1]["end"]
    endpoints=month_ends(dates)
    closes={d[:6]:(d,v) for d,v in result["main"]["curve"]}
    prev=peak=100.;dd=0.;returns=[]
    for month,(day,nav) in closes.items():
        first,last=endpoints[month]
        complete=(month<dates[-1][:6] or day==last_scheduled or
                  int(day[6:])==monthrange(int(day[:4]),int(day[4:6]))[1])
        if complete and start<=first and day==last:
            returns.append(nav/prev-1)
        peak=max(peak,nav);dd=min(dd,100*(nav/peak-1));prev=nav
    sd=stdev(returns) if len(returns)>=2 else 0
    return {"start":start,"end":end,"return":result["main"]["total"],"drawdown":dd,
            "sharpe":mean(returns)/sd*sqrt(12) if sd>1e-12 else None,"months":len(returns),
            "invested":any(x["held"] for x in result["months"])}


def compare(store,rules,windows,criterion,snapshot=None):
    a,b,c,d=windows
    if b>=c:
        raise ValueError("样本内截止日须早于样本外起日。")
    if not 2<=len(rules)<=8 or len(set(rules))!=len(rules) or criterion not in CRITERIA:
        raise ValueError("请设置 2 至 8 组不同的候选参数，并选择评价标准。")
    for rule in rules:
        validate(store,rule,a,b)
        validate(store,rule,c,d)
    calendar_check(store,rules,a,b,"样本内")
    calendar_check(store,rules,c,d,"样本外")
    if snapshot is None and any(rule.model == 'multi' for rule in rules):
        snapshot = factor_snapshot(store)
    ranking=[]
    for index,rule in enumerate(rules):
        try:
            row=score(run(store,rule,a,b,snapshot=snapshot),store.daily["dates"],store.manifest.get('lastScheduledSession'))
        except ValueError as exc:
            raise ValueError(f"候选 {index+1} · {exc}") from exc
        ranking.append(dict(index=index,**row))
    if len({(r["start"],r["end"]) for r in ranking})!=1:
        raise ValueError("候选的样本内实际交易区间不同。")
    ranking.sort(key=lambda r:(r[criterion] is None,-(r[criterion] or 0),r["index"]))
    winner=ranking[0]["index"] if ranking[0][criterion] is not None else None
    return ranking,winner
