from collections import defaultdict
from functools import lru_cache

import pandas as pd
import streamlit as st

from .details import extra
from .frames import MARKETS,Rules
from .navigation import navigate,security_table,select_security
from .persistence import edit_filter,filter_settings
from .portfolio import run
from .research import codes,common_series,coverage_by_code,rolling_beta
from .ui_common import STATUS,provider_token,curve,dates,day,fmt,iso,label,option,pct,rangebars,table,symbol_choices
from .ui_portfolio import remember_research,result

VENUE={"SSE":"上交所","SZSE":"深交所","BSE":"北交所","CSI":"中证","CNI":"国证","SW":"申万","CI":"中信","CICC":"中信","OTH":"其他"}
SCOPES={"benchmark":"基准 / 已核","equity":"境内股票指数","industry":"行业系列","review":"范围待核"}
BAR_HEADERS=["交易日","开盘","最高","最低","收盘","参考前收盘","涨跌幅（%）","成交量（手）","成交额（千元）"]
FACTORS={"mom":"60 日动量","vol":"20 日低波动","pe":"低市盈率","pb":"低市净率（PB）","turn":"换手率"}


MARKET_INDICES = {
    "000001.SH":"上证指数", "399001.SZ":"深证成指", "000300.SH":"沪深 300",
    "000905.SH":"中证 500", "000852.SH":"中证 1000", "399006.SZ":"创业板指", "899050.BJ":"北证 50",
}


def page_slice(items, key, size=40):
    pages = max(1, (len(items) + size - 1) // size)
    if pages == 1:
        return items
    if st.session_state.get(key, 1) > pages:
        st.session_state[key] = 1
    page = st.number_input("页码", 1, pages, 1, key=key)
    st.caption(f"共 {len(items):,} 条，第 {page} / {pages} 页。")
    return items[(page-1)*size:page*size]


def active(s):
    return [r for r in s.snapshot["items"] if r[2]=="stock" and r[5]=="L" and r[9] is not None]


def coverage(s,expanded=False):
    with st.expander("查看历史覆盖与数据权限",expanded=expanded):
        a,b,c=st.columns(3)
        with a:kind=option("证券类别",{"":"全部","stock":"个股","index":"指数"},"cfg_covkind")
        with b:status=option("日线状态",{"":"全部",**STATUS},"cfg_covstatus")
        with c:query=st.text_input("搜索名称或代码",key="cfg_covquery").strip().lower()
        items=[r for r in s.coverage if (not kind or kind==r[1]) and (not status or status==r[2]) and (not query or query in (r[0]+" "+s.catalog[r[0]][1]).lower())]
        st.caption(f"共有 {len(items):,} 条符合条件的记录。每个标的按实际行情起止日统计。")
        page=page_slice(items, f"cfg_coverage_{kind}_{status}_{query}", 30)
        security_table(s,[{"证券":label(s,r[0]),"状态":STATUS[r[2]],"日线数":r[3],"最早交易日":iso(r[4]),"最近交易日":iso(r[5])} for r in page],
                       [r[0] for r in page],"coverage_rows")



def data_details(s):
    st.title("数据说明")
    st.write("行情来自 Tushare Pro。日线从 2000 年起按各证券实际返回的有效收盘统计，覆盖存续和已退市股票。表中个股价格为未复权元价，指数单位为点，日线成交额单位为千元。")
    st.write("动量与波动率用每日收盘与当日除权参考前收盘计算。市场涨跌以当日有报价的股票计数，行业采用当前目录分类。指数回溯行情可供查看，参与策略比较和 Beta 估计的行情从发布日期起算。")
    st.button("返回研究页面",on_click=st.session_state.pop,args=("_show_data_details",None))
    coverage(s,expanded=True)


def overview(s):
    st.title("市场总览");st.write(iso(s.day)+" 收盘 · 沪、深、北 A 股")
    stocks=active(s);rec=[r for r in stocks if r[10] is not None]
    ups=sum(r[10]>0 for r in rec);downs=sum(r[10]<0 for r in rec)
    c=st.columns(4)
    c[0].metric("当日有报价",fmt(len(stocks),0)+" 只");c[1].metric("上涨家数",fmt(ups,0));c[2].metric("下跌家数",fmt(downs,0));c[3].metric("成交额（万亿元）",fmt(sum(r[11] or 0 for r in stocks)/1e9))
    st.caption(f"当日平盘 {len(rec)-ups-downs:,} 只。")
    b=option("主要指数",MARKET_INDICES,"cfg_overviewindex","000300.SH")
    st.session_state.setdefault("cfg_overview-range","126")
    bars=rangebars(s.series(b)["bars"],"cfg_overview");curve([(MARKET_INDICES[b],[(r[0],r[4]) for r in bars])],"主要指数走势","收盘点位")
    st.button("查看指数详情",key="overview_open_index",on_click=navigate,args=("indices",b))
    left, right = st.columns(2)
    with left:
        st.markdown("**主要指数收盘**")
        listed=[code for code in MARKET_INDICES if code in s.catalog]
        security_table(s,[{"指数":MARKET_INDICES[code],"收盘点位":fmt(s.catalog[code][9]),"日涨跌":pct(s.catalog[code][10])}
                       for code in listed],listed,"overview_indices")
    with right:
        st.markdown("**市场宽度**")
        breadth=[]
        for venue in ("SSE","SZSE","BSE"):
            changes=[r[10] for r in rec if r[3] == venue]
            breadth.append({"交易所":VENUE[venue],"上涨":sum(c>0 for c in changes),
                            "平盘":sum(c==0 for c in changes),"下跌":sum(c<0 for c in changes)})
        table(breadth)
    groups=defaultdict(list)
    for r in rec:
        if r[4]:groups[r[4]].append(r[10])
    sector=st.selectbox("行业",["全部行业",*sorted(groups)],key="cfg_ovsector")
    c=st.columns(2)
    with c[0]:
        st.markdown("**个股涨幅前十**")
        tops=sorted((r for r in rec if sector=="全部行业" or r[4]==sector),key=lambda r:(-r[10],r[0]))[:10]
        security_table(s,[{"证券":label(s,r[0]),"行业":r[4],"收盘":fmt(r[9]),"涨跌幅":pct(r[10])} for r in tops],
                       [r[0] for r in tops],"overview_top_stocks")
    with c[1]:
        st.markdown("**行业表现（个股等权）**")
        table([{"行业":k,"平均涨跌":pct(sum(v)/len(v)),"股票数":len(v)} for k,v in sorted(groups.items(),key=lambda t:-sum(t[1])/len(t[1]))])
    st.caption(f"行情来自 Tushare Pro，包含历史退市证券。已校验 {s.manifest['ready']:,} 个有日线的标的，共 {s.manifest['bars']:,} 条记录。")
    from .live_quotes import market_api_panel
    market_api_panel(s)
    coverage(s)


def directory(s):
    with st.expander("浏览指数目录"):
        c,d=st.columns(2)
        with c:scope=option("指数范围",{"":"全部目录",**SCOPES},"cfg_indexscope")
        with d:query=st.text_input("搜索代码、名称或类别",key="cfg_indexquery").strip().lower()
        found=sorted((r for r in s.catalog.values() if r[2]=="index" and (not scope or scope==r[8]) and query in (" ".join(str(v or "") for v in (r[0],r[1],r[4]))).lower()),key=lambda r:(r[8]!="benchmark",r[0]))
        st.caption(f"找到 {len(found):,} 条。目录中包括范围待核及权限受限的系列。")
        page=page_slice(found,f"cfg_index_directory_{scope}_{query}")
        security_table(s,[{"证券":label(s,r[0]),"发布市场":VENUE.get(r[3],r[3]),"类别":r[4],"范围":SCOPES.get(r[8],r[8]),
                       "日线":STATUS[coverage_by_code(s)[r[0]][2]]} for r in page],
                       [r[0] for r in page],"index_directory_rows")



def security(s,index=False):
    kind="index" if index else "stock";p="cfg_"+kind+"_";st.title("指数中心" if index else "个股研究")
    st.write("查询指数历史，并在共同交易日比较走势。" if index else "查询个股收盘行情、估值及相对市场的 120 日滚动 Beta。")
    options=codes(s,kind);default="000300.SH" if index else "600519.SH"
    code=st.selectbox("搜索指数名称或代码" if index else "搜索股票名称或代码",options,index=options.index(default),format_func=lambda c:symbol_choices(s,c),key=p+"code",
                      on_change=select_security,args=("indices" if index else "stocks",p+"code"))
    if st.session_state.get("_unknown_symbol"):
        st.info("没有找到链接指定的证券，请在上方按名称或代码选择。")
        return
    row=s.catalog[code]
    cov = coverage_by_code(s)[code]
    n = cov[3]
    bars = s.series(code)["bars"] if n else []
    last = bars[-1] if bars and row[9] is None else None
    st.subheader(row[1]);st.caption(f"{code}　·　{VENUE.get(row[3],row[3])}　·　{row[4] or '未分类'}　·　{('已退市 / 已终止' if row[5]=='D' else SCOPES.get(row[8],'A 股'))}")
    c=st.columns(4);c[0].metric("末次收盘" if last else "当日收盘",fmt(last[4] if last else row[9]));c[1].metric("日涨跌幅",pct(last[6] if last else row[10]))
    c[2].metric("发布日期" if index else "滚动市盈率",iso(row[6]) if index else fmt(row[12]))
    c[3].metric("成交额（亿元）" if index else "市净率（PB）",fmt(row[11]/1e5 if row[11] is not None else None) if index else fmt(row[13]))
    if last:st.caption("末次报价日期为 "+iso(last[0])+"，当前交易日没有收盘报价。")
    if not n:st.info(f"日线状态：{STATUS[cov[2]]}。")
    else:
        st.caption(f"有 {n:,} 条历史日线，{iso(cov[4])} 至 {iso(cov[5])}。")
        if index and row[6] and cov[4] < row[6]:st.caption("指数发布日期以前的行情属于回溯序列。")
        view=rangebars(bars,p)
        if index:
            choices={"":"单独查看",**{c:v for c,v in MARKET_INDICES.items() if c!=code and c in s.catalog}}
            other=option("走势对比",choices,p+"comp"+code,"000905.SH" if "000905.SH" in choices else "")
            if other:
                pair=common_series(view,s.series(other)["bars"])
                if pair[0]:curve([(row[1],pair[0]),(MARKET_INDICES[other],pair[1])],"共同交易日走势","共同起日 = 100",100)
                else:
                    st.info("所选区间没有共同交易日，以下显示当前指数的收盘点位。")
                    curve([(row[1],[(q[0],q[4]) for q in view])],"指数收盘走势","收盘点位")
            else:curve([(row[1],[(r[0],r[4]) for r in view])],"指数收盘走势","收盘点位")
        else:
            curve([(row[1],[(r[0],r[4]) for r in view])],"历史收盘走势","元 / 股（未复权）")
            bench=option("滚动 Beta 的市场基准",MARKET_INDICES,p+"betabench","000300.SH")
            idx=s.series(bench)["bars"];launch=s.catalog[bench][6] or ""
            hits,points=rolling_beta(bars,[r for r in idx if r[0]>=launch])
            visible=[pair for pair in points if pair[0]>=view[0][0]]
            if visible:
                st.metric("120 日滚动 Beta",fmt(visible[-1][1],3))
                st.caption("估计截至 "+iso(visible[-1][0])+"，市场基准为 "+MARKET_INDICES[bench]+"。")
                curve([("滚动 Beta",visible)],"120 日滚动 Beta","Beta",1)
            else:st.info("所选区间没有可报告的 Beta；每个估计需要 120 对有效单日收益。")
            st.caption("用同一交易日的股票与基准收益估计；基准自发布日期起纳入，个股采用参考前收盘，跳过停牌和复牌后的跨日收益。")
        if st.toggle("历史记录与 CSV 导出",key=p+"show_history"):
            first,last_day=view[0][0],view[-1][0]
            key=p+"history_page"
            if st.session_state.get(key+"_range")!=(code,first,last_day):
                st.session_state[key+"_range"]=(code,first,last_day)
                st.session_state.pop(key,None)
            page=page_slice(view[::-1],key,40)
            frame=pd.DataFrame(page,columns=BAR_HEADERS);frame["交易日"]=frame["交易日"].map(iso)
            st.dataframe(frame,use_container_width=True,hide_index=True)
            st.download_button("导出所选区间 CSV",history_csv(s,code,first,last_day),
                               f"{code}_{first}_{last_day}.csv","text/csv",key="download_"+kind)
    from .live_quotes import security_api_panel
    security_api_panel(s,code,row[2],row[8])
    with st.expander("历史成分与权重" if index else "财务披露"):
        cutoff=dates("查询截至日期",s.day,s.day,p+"md") if index else s.day
        request=(s.day,code,cutoff)
        key=kind+"_last_extra"
        if st.button("查询最近一期成分" if index else "查看财报指标",key="extra_"+kind):
            st.session_state.pop(key,None)
            try:st.session_state[key]=(request,extra(s,"members" if index else "financial",code,cutoff,provider_token()))
            except ValueError as exc:st.info(str(exc))
        if key in st.session_state and st.session_state[key][0]==request:
            data=st.session_state[key][1]
            if index:
                if data["items"]:
                    st.caption(f"最近一期成分日期 {iso(data['day'])}，共 {len(data['items']):,} 只。")
                    members=page_slice(data["items"],p+"members_page_"+code+"_"+cutoff,30)
                    security_table(s,[{"股票代码":c,"股票名称":name,"权重（%）":v} for c,name,v in members],
                                   [r[0] for r in members],"members_rows")
                else:st.info("所选日期之前 95 天内，数据源未返回这个指数的成分。")
            elif data:table([dict(zip(["报告期","公告日","每股收益","净资产收益率（%）","毛利率（%）","资产负债率（%）"],[iso(r[0]),iso(r[1]),*r[2:]])) for r in data])
            else:st.info("近三年未返回财报指标。")
    if index:directory(s)


@lru_cache(maxsize=8)
def history_csv(store,code,first,last):
    bars=[r for r in store.series(code)["bars"] if first<=r[0]<=last]
    frame=pd.DataFrame(bars,columns=BAR_HEADERS)
    frame["交易日"]=frame["交易日"].map(iso)
    frame.insert(0,"名称",store.catalog[code][1])
    frame.insert(0,"代码",code)
    return frame.to_csv(index=False).encode("utf-8-sig")


def saved_filters(k,v,sector):
    state=st.session_state
    rules=filter_settings()
    with st.expander("保存与调用选股规则"):
        suggestion=" · ".join(x for x in (FACTORS[k],MARKETS[v] if v else "",sector if sector!="全部行业" else "") if x)
        if state.get("_rule_suggestion")!=suggestion:
            state["_rule_suggestion"]=suggestion
            state["factor_rule_name"]=suggestion
        name=st.text_input("规则名称",max_chars=40,key="factor_rule_name").strip()
        st.button("保存规则",key="save_factor_rule",disabled=not name,on_click=edit_filter,
                  args=("save",name,{"factor":k,"market":v,"sector":sector}))
        if rules:
            names=list(rules)
            if state.get("factor_rule_choice") not in names:
                state["factor_rule_choice"]=names[0]
            selected=st.selectbox("已保存的规则",names,key="factor_rule_choice")
            def apply():
                rule=rules[selected]
                state.update(cfg_fack=rule["factor"],cfg_facv=rule["market"],cfg_facsec=rule["sector"])
            a,b=st.columns(2)
            a.button("应用规则",on_click=apply,key="apply_factor_rule")
            b.button("删除规则",on_click=edit_filter,args=("delete",selected,None),key="delete_factor_rule")
        if state.get("_filter_storage_error"):
            st.warning("浏览器未允许保存，当前规则仅在本次会话有效。")
        else:st.caption("命名规则保存在此浏览器。再次保存同名规则会更新其筛选条件。")


def factors(s):
    st.title("因子选股");st.write("在当期有报价的 A 股中按市场、行业和因子排序。")
    a,b,c=st.columns(3);stocks=active(s)
    with a:k=option("排序因子",FACTORS,"cfg_fack")
    with b:v=option("市场",MARKETS,"cfg_facv")
    sectors={r[4] for r in s.snapshot["items"] if r[2]=="stock" and r[4]}
    previous=st.session_state.get("cfg_facsec")
    if previous and previous!="全部行业":sectors.add(previous)
    with c:sector=st.selectbox("行业",["全部行业",*sorted(sectors)],key="cfg_facsec")
    sig={r[0]:r[1:] for r in s.factors["latest"]};items=[]
    for r in stocks:
        if (v and not r[0].endswith("."+v)) or (sector!="全部行业" and r[4]!=sector):continue
        val=sig.get(r[0],(None,None))[0 if k=="mom" else 1] if k in ("vol","mom") else r[{"pe":12,"pb":13,"turn":15}[k]]
        if val is not None and (k not in ("pb","pe") or val>0):items.append((val,r))
    items.sort(key=lambda t:(t[0] if k in ("vol","pb","pe") else -t[0],t[1][0]))
    st.caption(f"{iso(s.day)} 收盘 · {len(items):,} 只入选。市盈率、市净率剔除非正值；缺失因子值不参与排名。")
    if items:
        pages=(len(items)+49)//50
        pg=st.number_input("结果页码",1,pages,1,key=f"cfg_facpage_{k}_{v}_{sector}")
        off=(pg-1)*50;visible=items[off:off+50]
        security_table(s,[{"排名":i,"证券":label(s,r[0]),"行业":r[4],"因子值":fmt(val)+("%" if k in ("vol","mom","turn") else ""),"市值（亿元）":None if r[14] is None else round(r[14]/10000,2),"日涨跌":pct(r[10])} for i,(val,r) in enumerate(visible,off+1)],
                       [r[0] for _,r in visible],"factor_result_rows")
    saved_filters(k,v,sector)
    if k in ("vol","mom") and sector=="全部行业":
        groups=s.bands["groups"].get(k+"-"+(v or "all"),[])
        st.subheader("分组后的下期平均收益")
        table([{"因子组":("第 1 组 · 排名靠前" if i==1 else "第 5 组 · 排名靠后" if i==5 else f"第 {i} 组"),"平均持有期收益":pct(avg),"调仓期数":n} for i,(avg,n) in enumerate(groups,1)])
        st.caption("每月末按因子排名将当时有行情的股票分为五组，下一交易日开盘等权建仓。开盘涨停或无有效成交的份额保留现金。表中为各期持有收益的算术平均，未计费用。")
        def use():
            st.session_state.update(cfg_stratmodel=k,cfg_stratvenue=v,_strategy_requested=True)
            navigate("strategies")
        st.button("用此规则做策略回测",on_click=use)
    elif k=="pb":st.caption("长期历史 PB 可在「组合表现」选择低市净率，并用同一股票池比较。")


@lru_cache(maxsize=12)
def signals(s,k,v):
    return [(p["signal"],p["entry"],p["end"]) for p in s.json(s.factor_index["views"][k+"-"+(v or "all")])]


@lru_cache(maxsize=12)
def strategy_run(store,rules,start,end):
    return run(store,rules,start,end)


def strategy(s):
    st.title("策略回测");st.write("按月末已知信息选股，下一交易日开盘等权建仓，比较扣费后的历史表现。")
    a,b,c=st.columns(3)
    with a:k=option("选股规则",{i:FACTORS[i] for i in ("mom","vol")},"cfg_stratmodel")
    with b:v=option("股票范围",MARKETS,"cfg_stratvenue")
    with c:count=int(st.number_input("持股数",1,200,30,key="cfg_stratcount"))
    bounds=signals(s,k,v)
    if not bounds:
        st.info("这个市场和因子尚无可回测的调仓期。");return
    q,w=st.columns(2)
    with q:aa=dates("信号起日",bounds[0][0],s.day,"cfg_stratstart"+k+v)
    with w:zz=dates("截止日",s.day,s.day,"cfg_stratend")
    q,w=st.columns(2)
    with q:fee=st.number_input("单边费用（基点）",0.,100.,10.,step=0.5,key="cfg_stratfee")
    with w:bench=option("比较基准",MARKET_INDICES,"cfg_stratbench","000300.SH")
    def reset_range():
        st.session_state['cfg_stratstart'+k+v]=day(bounds[0][0])
        st.session_state['cfg_stratend']=day(s.day)
        st.session_state['_strategy_requested']=True
    st.button('使用完整可用区间',key='strategy_full_range',on_click=reset_range)
    # Both strategy models hold equal weights. The comparison index cannot affect their trades.
    r=Rules(model=k,count=count,bench='000001.SH',fee=fee,exchange=v)
    sig=(r,bench,aa,zz,s.day)
    first_visit="strategy_sig" not in st.session_state
    requested=st.session_state.pop("_strategy_requested",False)
    if st.session_state.get("strategy_sig")!=sig:
        st.session_state["strategy_sig"]=sig;st.session_state.pop("strategy_output",None)
    submitted=st.button("运行策略回测",type="primary")
    if (first_visit or requested or submitted) and "strategy_output" not in st.session_state:
        periods=[d for d in bounds if d[0]>=aa and d[2]<=zz]
        if aa>zz:st.error("截止日早于信号起日，请调整日期。")
        elif not periods:st.error("该区间没有完整的月度调仓样本。")
        else:
            with st.spinner("正在计算月度交易记录…"):
                try:
                    st.session_state["strategy_output"]=strategy_run(s,r,periods[0][1],periods[-1][2])
                    remember_research(periods[0][1],periods[-1][2])
                except ValueError as exc:st.error(str(exc))
    if "strategy_output" in st.session_state:
        output=st.session_state["strategy_output"];equity=output["main"]["curve"]
        first=equity[0][0];launch=s.catalog[bench][6] or ""
        values={bar[0]:bar[1] if bar[0]==first else bar[4] for bar in s.series(bench)["bars"] if bar[0]>=launch}
        common=[(d,nav,values[d]) for d,nav in equity if values.get(d) and values[d]>0]
        index_points=[(d,common[0][1]*price/common[0][2]) for d,_,price in common] if len(common)>=2 else []
        market=None
        if len(common)==len(equity) and len(common)>=2:
            peak=100.;dd=0.
            for _,nav in index_points:
                peak=max(peak,nav);dd=min(dd,100*(nav/peak-1))
            market={'total':index_points[-1][1]-100.,'dd':dd}
        result(s,r,{**output,'market':market},strategy_benchmark=index_points,benchmark_name=MARKET_INDICES[bench])
    else:st.caption("最早有效信号日 "+iso(bounds[0][0])+"。修改参数后点击「运行策略回测」查看结果。")
