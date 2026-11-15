from dataclasses import replace
from collections import defaultdict
import math
import re

import streamlit as st

from .comparison import CRITERIA,compare
from .frames import BENCHMARKS,MARKETS,MODELS,WEIGHTS,Rules
from .portfolio import run
from .persistence import restore,persist,DEFAULT
from .research import codes
from .ui_common import curve,dates,fmt,iso,label,option,pct,table,symbol_choices

FREQ={"hold":"买入并持有","months":"每月调仓","quarter":"每季调仓","half":"每半年调仓","days":"自定义交易日数"}
GROUPS={"all":"全部股票模型","manual":"使用自选名单"}
ss=st.session_state


def equal_weights(n):
    unit,remainder=divmod(100_000_000,n)
    return [(unit+(i<remainder))/1_000_000 for i in range(n)]


def seen_research(start,end):
    return any(a<=end and start<=z for a,z in ss.get("seen_performance_windows",[]))


def remember_research(start,end):
    history=sorted(set([*ss.get("seen_performance_windows",[]),(start,end)]))
    intervals=[]
    for a,z in history:
        if intervals and a<=intervals[-1][1]:intervals[-1]=(intervals[-1][0],max(z,intervals[-1][1]))
        else:intervals.append((a,z))
    ss["seen_performance_windows"]=intervals


def basket(s,p,locked):
    names=codes(s,"stock")
    rows=ss.get('study_locked_roster',[]) if locked else ss['portfolio_roster']
    key=p+"stocks";ss[key]=[r[0] for r in rows]
    def edit():
        old=dict(ss['portfolio_roster']);selected=ss[key];cash=max(0.,100.-sum(old.get(c,0.) for c in selected))
        if not selected:ss['roster_equal']=True
        if selected and ss.get('roster_equal',not bool(old)):
            ss['roster_equal']=True
            ss['portfolio_roster']=list(zip(selected,equal_weights(len(selected))));return
        new=[c for c in selected if c not in old]
        if new:old[new[0]]=round(cash,6)
        ss['portfolio_roster']=[(c,old.get(c,0.)) for c in selected]
    chosen=st.multiselect("自选股票（按名称或代码搜索，可增删）",names,
        format_func=lambda c:symbol_choices(s,c),key=key,disabled=locked,max_selections=200,on_change=edit)
    st.caption("区间回测和参数比较共用这份名单。名单和手动权重保存在此浏览器；锁定的方案单独保留。")
    if not chosen and not locked:
        def example():
            ss['portfolio_roster']=[row for row in DEFAULT if row[0] in s.catalog];ss['roster_equal']=False
        st.button('载入三只股票示例',key='example_'+p,on_click=example)
    return tuple(chosen)


def trading(p,r,locked):
    k=option("调仓方式",FREQ,p+("freqcustom" if r.model=="manual" else "freqmodel"),"hold" if r.model=="manual" else "months",locked)
    if k=="days":
        i=int(st.number_input("每隔多少个交易日调仓",1,10000,10,key=p+("days" if r.model=="manual" else "daysmodel"),disabled=locked))
    else: i={"months":1,"quarter":3,"half":6,"hold":1}[k]
    return replace(r,cadence=k if k in ("hold","days") else "months",interval=i)


def equalize(keys):
    if keys:
        for k,w in zip(keys,equal_weights(len(keys))):ss[k]=w
        ss['portfolio_roster']=[(c,ss[k]) for (c,_),k in zip(ss['portfolio_roster'],keys)]
        ss['roster_equal']=True


def allocation(s,p,r,locked):
    if r.weighting!="manual":
        if r.model=="manual" and r.symbols:
            if r.weighting=="equal":st.caption(f"{len(r.symbols)} 只股票，每只建仓目标为 {fmt(100/len(r.symbols))}%。")
            else:st.caption("TB 在实际建仓或调仓时估计每只股票的权重，可在结果中查看。")
        return r
    if r.model!="manual":
        key=p+"rankweights"
        # A previously saved version used one number field for each rank.
        prior=[ss.get(p+"weight_"+str(i)) for i in range(1,r.count+1)]
        if key not in ss and all(v is not None for v in prior):
            ss[key]=", ".join(f"{v:g}" for v in prior)
        text=st.text_input("按入选排名填写权重（%）",key=key,placeholder="例如 50, 30, 20",
                           max_chars=4000,disabled=locked)
        try:weights=tuple(float(v) for v in re.split(r"[,，、;；\s]+",text.strip()) if v)
        except ValueError:weights=()
        if len(weights)!=r.count or any(not math.isfinite(w) or not 0<=w<=100 for w in weights):
            st.caption(f"按排名填写 {r.count} 个 0 至 100 的权重，用逗号或空格分开。")
            return replace(r,weights=())
        if sum(weights)>100.0000001:st.error("目标权重合计超过 100%，请调低后再运行。")
        else:st.caption(f"目标权重合计 {sum(weights):.2f}%，计划保留现金 {max(0,100-sum(weights)):.2f}%。")
        return replace(r,weights=weights)
    members=list(r.symbols)
    keys=[p+"weight_"+str(c) for c in members]
    if not keys:return replace(r,weights=())
    st.button("等权分配",key="equalize_"+p,disabled=locked,on_click=equalize,args=(keys,))
    weights=[]
    old=dict(ss['study_locked_roster'] if locked else ss['portfolio_roster'])
    for k,c in zip(keys,members):ss[k]=old[c]
    for i in range(0,len(keys),3):
        cols=st.columns(3)
        for j,c in enumerate(members[i:i+3]):
            with cols[j]:
                def update(c=c,k=keys[i+j]):
                    ss['roster_equal']=False
                    ss['portfolio_roster']=[(sym,ss[k] if sym==c else w) for sym,w in ss['portfolio_roster']]
                weights.append(st.number_input(label(s,c)+" 权重（%）",0.,100.,step=0.1,format="%.6f",key=keys[i+j],disabled=locked,on_change=update))
    total=sum(weights)
    if total>100.0000001:st.error(f"目标权重合计 {total:.2f}%，请调低至 100% 以内。")
    else:st.caption(f"目标权重合计 {total:.2f}%，计划保留现金 {max(0,100-total):.2f}%。")
    if not locked:st.caption("增删股票时自动等分；修改任一权重后保留手动比例。" if ss.get('roster_equal',False) else "新增股票使用剩余现金，移除股票腾出的资金保留为现金。")
    return replace(r,weights=tuple(weights))


def editor(s,p,model,base,locked,study=False,default_count=10):
    r=replace(base,model=model)
    a,b,c=st.columns(3)
    with a:
        if model=="manual":
            r=replace(r,count=len(r.symbols))
            st.metric("名单股票数",str(r.count))
        else:r=replace(r,count=int(st.number_input("目标持股数",1,200,default_count,key=p+"count",disabled=locked)))
    with b:
        r=replace(r,weighting=option("配权方式",WEIGHTS,p+("manw" if model=="manual" else "sysw"),"manual" if model=="manual" else "equal",locked))
    with c:r=trading(p,r,locked)
    if model=="pb" and not study:
        compare_options={k:MODELS[k] for k in ("mom","vol","rev")}
        r=replace(r,control=option("同池对照因子",compare_options,p+"ctrl","mom",locked))
        st.caption("低 PB 与对照模型从同一批有正 PB 且有可用因子值的股票选取；调仓日、费用和配权规则相同。")
    if not study and model in ("mom","vol","rev"):
        st.caption({"mom":"按过去 60 个有效交易日的累计收益从高到低选股。",
                    "vol":"按过去 20 个有效交易日的波动率从低到高选股。",
                    "rev":"按过去 20 个有效交易日的累计收益从低到高选股。"}[model])
    if model=="manual" and r.weighting=="tb":
        st.caption("名单保持不变。买入并持有仅在建仓时估算一次 TB 权重；定期调仓会用调仓前的数据重新估算。")
    return r if study and model=='manual' else allocation(s,p,r,locked)


def setup(s,p,locked,study=False):
    c1,c2,c3=st.columns(3)
    with c1: bench=option("比较基准",BENCHMARKS,p+"benchmark","000300.SH",locked)
    with c2: fee=st.number_input("单边交易费用（基点）",min_value=0.,max_value=100.,value=10.,step=0.1,key=p+"fee",disabled=locked)
    with c3:
        if study: source=option("股票来源",GROUPS,p+"source","all",locked)
        else:source=option("选股方式",MODELS,p+"model","mom",locked)
    if bench in s.catalog and s.catalog[bench][6]:
        st.caption(f"{BENCHMARKS[bench]}的发布日期为 {iso(s.catalog[bench][6])}，基准收益与 TB 估计从发布后有报价的日期起计算。")
    venue="";syms=()
    if source=="manual":syms=basket(s,p,locked)
    else:venue=option("股票范围",MARKETS,p+"exchange","",locked)
    return source,Rules(bench=bench,fee=fee,exchange=venue,symbols=syms)


def descriptor(r):
    cadence="买入并持有" if r.cadence=="hold" else f"每 {r.interval} 个交易日" if r.cadence=="days" else FREQ[{1:"months",3:"quarter",6:"half"}[r.interval]]
    stock_range="" if r.model=="manual" else " · "+MARKETS[r.exchange]
    control="（对照 "+MODELS[r.control]+"）" if r.model=="pb" else ""
    return f"{MODELS[r.model]}{control}{stock_range} · {r.count} 只 · {WEIGHTS[r.weighting]} · {cadence}"


def holdings_table(store, positions, cash, pb):
    rows, sectors = [], defaultdict(float)
    for h in positions:
        security = store.catalog[h['code']]
        rows.append({'股票':security[1], '代码':h['code'], '信号日因子值':
                     fmt(h['value'],4)+' 倍' if pb and h['value'] is not None else pct(h['value']),
                     '估计日 α':pct(h['alpha']*100,4) if h['alpha'] is not None else '—',
                     '目标权重':fmt(h['weight'])+'%', '期末实际权重':fmt(h['endWeight'])+'%',
                     '估值说明':'已退市 '+iso(h['ended'])+'，沿用末次估值' if h['ended'] else '沿用上次报价' if h['stale'] else '—'})
        if h['endWeight'] > 0:
            sectors[security[4] or '未分类'] += h['endWeight']
    rows.append({'股票':'现金','代码':'—','信号日因子值':'—','估计日 α':'—',
                 '目标权重':fmt(max(0.,100-sum(h['weight'] for h in positions)))+'%',
                 '期末实际权重':fmt(cash)+'%','估值说明':'—'})
    table(rows)
    if sectors:
        st.caption('行业按当前分类汇总，权重按期末持仓计算。')
        table([{'行业':k,'期末权重':fmt(v)+'%'} for k,v in sorted(sectors.items(), key=lambda x:-x[1])]
              + [{'行业':'现金','期末权重':fmt(cash)+'%'}])


def valuation_notes(name, values, total):
    if values['staleHeld']:
        st.caption(f"{name}期末有 {values['staleHeld']} 只持仓缺收盘报价，采用末次可得价格。")
    if values['endedHeld']:
        weight=values['endedWeight']
        written_off=(100+total)*(1-weight/100)-100
        st.info(f"{name}期末有 {values['endedHeld']} 只退市股票，账面权重 {fmt(weight)}%。"
                f"清偿款未知。若最终回收为零，该组合累计收益为 {pct(written_off)}。")


def result(s,r,res,title="回测结果",strategy_benchmark=None,benchmark_name=None):
    m=res["main"];rows=res["months"];end=rows[-1];mark=benchmark_name or BENCHMARKS[r.bench]
    st.subheader(title)
    st.caption(f"实际持有区间 {iso(rows[0]['entry'])} 至 {iso(end['end'])}　·　{descriptor(r)}　·　单边 {r.fee:g} 基点　·　基准 {mark}")
    c=st.columns(4)
    c[0].metric("组合累计收益",pct(m["total"]))
    c[1].metric("最大回撤",pct(m["dd"]))
    if strategy_benchmark is None:c[2].metric("交易费用 / 初始资金",fmt(m["cost"],3)+"%")
    else:c[2].metric("平均双边换手",fmt(m["turn"])+"%")
    c[3].metric("调仓次数",str(sum(x["rebalance"] for x in rows)))
    name=("低 PB · " if 'control' in res else "")+{"equal":"等权组合","manual":"手动配权组合","tb":"TB 组合"}[r.weighting]
    names=[(name,m)]
    if "control" in res:names.append((MODELS[r.control]+"对照",res["control"]))
    if r.weighting!="equal":names.append(("同批候选股等权",res["equal"]))
    lines=[(n,o["curve"]) for n,o in names]
    if strategy_benchmark is not None:
        if strategy_benchmark:lines.append((mark,strategy_benchmark))
    elif res["market"]:lines.append((mark,res["marketCurve"]))
    curve(lines,"组合与比较基准","净值（期初 = 100）",100)
    if strategy_benchmark is not None:
        if len(strategy_benchmark)>=2:
            first=strategy_benchmark[0][0]
            st.caption(f"{mark} 从 {iso(first)} 的首个可比时点与策略对齐；仅显示指数发布后有报价的日期。")
        else:st.info(f"{mark} 在该区间没有足够的可比报价。")
    elif res["market"]:
        st.caption(f"{mark} 同期收益 {pct(res['market']['total'])}。")
    elif res["overlap"]:
        q=res["overlap"]
        paired=f"，{MODELS[r.control]}对照收益 {pct(q['control'])}" if q['control'] is not None else ""
        st.info(f"{mark} 未覆盖整个回测区间。最近连续可比区间为 {iso(q['from'])} 至 {iso(q['to'])}，组合收益 {pct(q['main'])}{paired}，基准收益 {pct(q['market'])}。")
    else:st.info(f"{mark} 在这段区间没有可比记录。")
    st.caption(("逐日收盘估值。" if r.daily else "按月末收盘估值；表中回撤由月末净值计算，无法反映所有月内波动。")+"收益和净值已扣除所设费用。")
    comparisons = list(names)
    if res['market']:
        comparisons.append((mark,res['market']))
    table([{'序列':n,'累计收益':pct(o['total']), '相对基准（百分点）':fmt(o['total']-res['market']['total']) if res['market'] else '—',
            '最大回撤':pct(o['dd']), '交易费用 / 初始资金':fmt(o['cost'],3)+'%' if 'cost' in o else '—'} for n,o in comparisons])
    if res["missingFits"]:st.info("区间内没有可用的 TB 回归估计，相应资金保留现金。")
    if 'control' in res and res['control']['missingFits']:
        st.info(f"{MODELS[r.control]}对照在调仓日没有可用的 TB 回归估计，相应资金保留现金。")
    if r.cadence=='hold' and r.model=='manual' and rows[0]['held']<r.count:
        st.info(f"期初名单 {r.count} 只，实际建仓 {rows[0]['held']} 只。期初未买入的股票，买入并持有模式下不会在以后补买。")
    if not any(x["held"] for x in rows):st.warning("该区间没有实际持仓，组合保持现金。请查看名单上市时间、可交易性和 TB 输入。")
    elif m['cashPeriods']:
        unit="个交易日收盘" if r.daily else "个持有期期末"
        st.caption(f"其中 {m['cashPeriods']} {unit}全部为现金。")
    if 'control' in res and res['firstSelection'] and res['firstSelection']!=rows[0]['entry']:
        st.caption("首次有共同候选股票的调仓日为 "+iso(res['firstSelection'])+"，此前两个组合均持有现金。")
    with st.expander("期末持仓与现金",expanded=True):
        st.caption(f"最近信号日 {iso(res['lastSignal'])}。截至 {iso(end['end'])} 实际持有 {end['held']} 只，现金 {fmt(end['cash'])}%。")
        holdings_table(s,res['holdings'],end['cash'],r.model=='pb')
    if 'control' in res:
        with st.expander('查看同池对照持仓与行业权重'):
            holdings_table(s,res['control']['holdings'],res['control']['cash'],False)
    for n,account in names:
        valuation_notes(n, res['valuation'] if account is m else account['valuation'], account['total'])
    with st.expander("交易记录与成交口径"):
        only = r.daily and st.checkbox('只看建仓或调仓日',value=True,key='ledger_filter_'+title)
        ledger=[x for x in reversed(rows) if not only or x['rebalance']]
        pages=max(1,(len(ledger)+39)//40); key='ledger_page_'+title
        if ss.get(key,1)>pages:ss[key]=1
        page=st.number_input('交易记录页码',1,pages,1,key=key) if pages>1 else 1
        table([{"信号日":iso(x["signal"]) if x['rebalance'] else '—',"交易起日":iso(x["entry"]),"估值截止":iso(x["end"]),"调仓":"是" if x["rebalance"] else "否",
                **({'共同股票池':x.get('pool') if x['rebalance'] else None} if r.model=='pb' else {}),"候选数":x["candidates"] if x['rebalance'] else None,
                "实际持有的候选":x['filled'] if x['rebalance'] else None,"持仓数":x["held"],"缺收盘报价持仓":x['stale'],
                "可估计 α 的候选":x['estimated'] if x['rebalance'] else None,
                "现金":fmt(x["cash"])+"%","本期收益":pct(x["ret"]),"双边换手":fmt(x["turn"])+"%"} for x in ledger[(page-1)*40:page*40]])
        st.caption("实际持有的候选是当期入选且期末仍持有的股票，全部持仓还包括当时未能卖出的旧仓。")
        for n,account in names:
            if account is res["equal"] and account is not m:continue
            e=account["execution"]
            st.caption(f"{n}开盘买卖意向中，逐股限价可核对 {e['verified']} 笔，按近似规则判断 {e['estimated']} 笔，无有效开盘报价 {e['unquoted']} 笔。次数包含未成交意向。")
        cover=res.get('limitCoverage') or {}
        if any(account['execution']['estimated'] for _,account in names) and 'vendorDays' in cover:
            st.caption(f"2007 年以来已入库逐股限价的交易日为 {cover['verifiedDays']:,} / {cover['vendorDays']:,} 天，其余日期用近似规则估计。")


def range_view(s):
    p="cfg_range_"
    source,base=setup(s,p,False)
    r=editor(s,p,source,base,False)
    d1,d2=st.columns(2)
    with d1:a=dates("回测起日",str(int(s.day[:4])-1)+s.day[4:6]+"01",s.day,p+"a")
    with d2:b=dates("回测截止日",s.day,s.day,p+"b")
    ident=(s.day,r,a,b)
    if ss.get("range_sig")!=ident:
        ss["range_sig"]=ident;ss.pop("range_output",None)
    if st.button("运行区间回测",type="primary",key="run_interval"):
        ss.pop("range_output",None)
        if r.model=="manual" and not r.symbols:
            st.info("请先添加自选股票或载入示例。")
            return
        with st.spinner("正在使用历史行情计算…"):
            try:
                ss["range_output"]=run(s,r,a,b)
                rows=ss["range_output"]["months"];remember_research(rows[0]["entry"],rows[-1]["end"])
            except ValueError as exc:st.error(str(exc))
    if "range_output" in ss:result(s,r,ss["range_output"])
    else:st.caption("设好参数后运行，即可查看净值、持仓、费用和逐期交易记录。")


def edit_candidates(prefix, source, count_key, remove=None):
    count=ss[count_key]
    if (remove is None and count>=8) or (remove is not None and count<=2):
        return
    manual=source=="manual"
    def defaults(i):
        if manual:
            return {"manw":"equal" if not i else "tb","freqcustom":"hold","days":10}
        return {"model":"mom","count":min(200,10*(i+1)),"sysw":"equal",
                "freqmodel":"months","daysmodel":10,"rankweights":""}
    plans=[]
    for i in range(count):
        fields=defaults(i)
        for field in fields:
            fields[field]=ss.get(f"{prefix}{i}_{field}",fields[field])
        plans.append(fields)
    if remove is None:
        new=plans[-1].copy()
        if manual:new['freqcustom']="months" if new['freqcustom']=="hold" else "hold"
        else:new['count']=min(200,int(new['count'])+10)
        plans.append(new)
    else:plans.pop(remove)
    for i in range(max(count,len(plans))):
        for field in defaults(i):
            key=f"{prefix}{i}_{field}"
            if i<len(plans):ss[key]=plans[i][field]
            else:ss.pop(key,None)
    ss[count_key]=len(plans)


def resize_candidates(prefix,source,key,before):
    wanted=ss[key]
    ss[key]=before
    while ss[key]<wanted:edit_candidates(prefix,source,key)
    while ss[key]>wanted:edit_candidates(prefix,source,key,ss[key]-1)


def study_view(s):
    p="cfg_study_";locked="frozen_study" in ss
    current_release=s.manifest['files']['catalog']['sha256']
    if locked and ss.get('study_release')!=current_release:
        for key in ('frozen_study','study_train','study_review','study_test','study_sig','study_locked_roster'):ss.pop(key,None)
        st.info('行情版本已更新，请用新版本重新比较候选参数。');locked=False
    restoring=ss.get('restore_locked_roster')
    if restoring is not None and not locked:
        ss['study_locked_roster']=restoring
    st.caption("先用样本内数据比较候选参数，锁定排名第一的方案，再单独检验样本外表现。")
    if locked:
        st.success("方案已锁定，候选参数、评价标准和两个区间均不可更改。")
        if st.button("解锁并重新比较",key="unlock_study"):
            for key in ("frozen_study","study_train","study_review","study_test","study_sig","study_locked_roster","restore_locked_roster","study_release"): ss.pop(key,None)
            st.rerun()
    source,base=setup(s,p,locked or restoring is not None,True)
    sample=s.manifest.get('sample')
    left,right=st.columns(2)
    with left:
        st.markdown("**样本内 · 选参数**")
        a=dates("样本内起日","20230101" if sample else "20100101",s.day,p+"trainA",locked)
        b=dates("样本内截止日","20241231" if sample else "20191231",s.day,p+"trainB",locked)
    with right:
        st.markdown("**样本外 · 检验锁定方案**")
        c=dates("样本外起日","20250101" if sample else "20200101",s.day,p+"testA",locked)
        d=dates("样本外截止日",s.day,s.day,p+"testB",locked)
    if seen_research(c,d):
        st.info("本浏览器标签页已查看过与此样本外区间重叠的业绩，这段结果可用于复验。")
    left,right=st.columns(2)
    count_key=p+("candidatesManual" if source=="manual" else "candidates")
    with left:count=int(st.number_input("候选方案数",2,8,2,key=count_key,disabled=locked,
                         on_change=resize_candidates,args=(p,source,count_key,ss.get(count_key,2))))
    with right:criterion=option("样本内评价标准",CRITERIA,p+"criterion","return",locked)
    recipes=[]
    for i in range(count):
        tag=p+str(i)+"_"
        with st.expander(f"候选 {i+1} 的参数",expanded=i<2 and not locked):
            model="manual" if source=="manual" else option("选股模型",{k:v for k,v in MODELS.items() if k!="manual"},tag+"model","mom",locked)
            defaultkey=tag+("manw" if model=="manual" else "sysw")
            if model=="manual" and defaultkey not in ss: ss[defaultkey]=["equal","tb","manual"][i%3]
            recipes.append(editor(s,tag,model,base,locked,True,min(200,10*(i+1))))
            if not locked:
                st.button(f"移除候选 {i+1}",key="drop_"+tag,disabled=count<=2,
                          on_click=edit_candidates,args=(p,source,count_key,i))
    if not locked:
        st.button("添加一组候选",key="study_add",disabled=count>=8,
                  on_click=edit_candidates,args=(p,source,count_key))
    if source=='manual' and any(r.weighting=='manual' for r in recipes):
        st.markdown('**共同的自选权重**')
        weights=allocation(s,'cfg_study_shared_',replace(base,count=len(base.symbols),model='manual',weighting='manual'),locked or restoring is not None).weights
        recipes=[replace(r,weights=weights) if r.weighting=='manual' else r for r in recipes]
    if any(r.model=='pb' for r in recipes):
        ctrl=option('低 PB 的共同对照因子',{k:MODELS[k] for k in ('mom','vol','rev')},p+'ctrl','mom',locked)
        recipes=[replace(r,control=ctrl) if r.model=='pb' else r for r in recipes]
    rules=tuple(recipes);win=(a,b,c,d);sig=(s.day,rules,win,criterion)
    if not locked and ss.get("study_sig")!=sig:
        ss["study_sig"]=sig
        for key in ("study_train","study_review","study_test"):ss.pop(key,None)
    if not locked and restoring is not None:
        ss.pop('restore_locked_roster',None)
        try:
            ss['study_train']=compare(s,rules,win,criterion)
            winner=ss['study_train'][1]
            if winner is None:raise ValueError('无法重新确定胜出组。')
            ss['frozen_study']=(rules[winner],win,criterion,s.day,winner);ss['study_release']=current_release
            st.rerun()
        except ValueError as exc:st.warning('未能恢复锁定方案，请重新比较。'+str(exc))
    if not locked and st.button("比较样本内表现",type="primary",key="train"):
        for key in ("study_train","study_review","study_test"):ss.pop(key,None)
        if source=="manual" and not base.symbols:
            st.info("请先添加自选股票或载入示例。")
            return
        with st.spinner("只用样本内行情比较候选…"):
            try:
                ss["study_train"]=compare(s,rules,win,criterion)
                row=ss["study_train"][0][0];remember_research(row["start"],row["end"])
            except ValueError as exc:st.error(str(exc))
    if "study_train" not in ss:return
    ranking,winner=ss["study_train"]
    st.markdown("**样本内排名**")
    st.caption(f"实际区间 {iso(ranking[0]['start'])} 至 {iso(ranking[0]['end'])} · 行情版本 {iso(s.day)} · {CRITERIA[criterion]}")
    table([{"排名":str(j+1) if row[criterion] is not None else "不参与","候选":f"候选 {row['index']+1}","参数":descriptor(rules[row["index"]]),"扣费收益":pct(row["return"]),"月度最大回撤":pct(row["drawdown"]),
            "年化夏普":fmt(row["sharpe"],3),"完整月数":row["months"],"实际持仓":"是" if row["invested"] else "否"} for j,row in enumerate(ranking)])
    for i,rule in enumerate(rules):
        if rule.model!="manual" and rule.weighting=="manual":
            st.caption(f"候选 {i+1} 按入选排名配权　"+"、".join(f"{w:g}%" for w in rule.weights))
    st.caption("回撤按相同的月度估值频率比较。夏普比率采用完整月份的扣费收益，月无风险利率取 0，以 √12 年化；不足两个完整月或收益无波动时不参与夏普排名。")
    if winner is None:st.warning("样本不足以计算所选评价指标，无法锁定胜出方案。");return
    st.caption(f"样本内胜出：候选 {winner+1}。评价标准：{CRITERIA[criterion]}；同分时按候选顺序。")
    if not locked:
        if st.button("锁定样本内胜出方案",key="lock_study"):
            ss['study_locked_roster']=list(ss['portfolio_roster']);ss['study_release']=current_release
            ss["frozen_study"]=(rules[winner],win,criterion,s.day,winner);st.rerun()
        return
    chosen,saved_win,_,release,_=ss["frozen_study"]
    if release!=s.day:st.error("行情版本已变化，请解锁并重新比较。");return
    if st.button("查看胜出方案的样本内明细",key="review_study",disabled="study_review" in ss):
        with st.spinner("正在读取样本内持仓与净值…"):
            try:ss["study_review"]=run(s,chosen,saved_win[0],saved_win[1])
            except ValueError as exc:st.error(str(exc))
    if "study_review" in ss:result(s,chosen,ss["study_review"],"样本内回测结果")
    if st.button("运行样本外检验",type="primary",key="test_study"):
        with st.spinner("正在独立计算样本外表现…"):
            try:
                ss["study_test"]=run(s,chosen,saved_win[2],saved_win[3])
                rows=ss["study_test"]["months"];remember_research(rows[0]["entry"],rows[-1]["end"])
            except ValueError as exc: st.error(str(exc))
    if "study_test" in ss:result(s,chosen,ss["study_test"],"样本外检验结果")
    st.caption("如果看过样本外结果后再调参数，这段区间就不再是独立检验。")


def portfolio_page(s):
    restore(s)
    # A changing number of controls must not move and remount the browser bridge.
    settings_slot=st.container()
    st.title("组合表现")
    st.write("构建组合，比较历史收益、回撤和持仓。")
    mode=st.radio("研究方式",["区间回测","参数比较与样本外检验"],horizontal=True,key="cfg_portfolio_tab",label_visibility="collapsed")
    if mode=="区间回测":range_view(s)
    else:study_view(s)
    with st.expander('查看计算口径'):
        st.markdown('**成交与估值。** 信号在收盘形成，下一个交易日的开盘口径执行。不使用当天稍后的最高、最低价决定能否成交。开盘涨停不买、跌停不卖；无有效开盘报价不成交。2007 年前或缺少官方限价时按 5%、10%、20%、30% 常见幅度保守估计。收盘缺价的持仓沿用末次估值，退市后没有假定清偿款。')
        st.markdown('**持有与费用。** 买入并持有仅在期初尝试一次，不补买；自定义天数按交易日计。月、季、半年调仓分别在指定月份首个交易日执行，季初为 1、4、7、10 月，半年初为 1、7 月。现金收益为零，按实际买卖金额分别扣除设定费率，期末不强制卖出。按连续权重模拟，未计整手、排队及市场冲击。')
        st.markdown('**TB 与 PB。** TB 使用截至信号日的最近 120 个有效配对交易日，日无风险收益取零，按正 α 除以残差方差分配主动权重；没有正分的资金留作现金。低 PB 与对照使用同一批有正 PB 且三个价格因子齐备的股票，按信号日历史 PB 排名。用今天选的自选名单回看过去，可能引入事后选择。')
    with settings_slot:
        persist(s)
