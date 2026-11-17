"""Queryable research relations from the desk's archives and calculation modules."""
from contextlib import closing
from functools import cached_property, lru_cache
import json
import math
from pathlib import Path
import sqlite3
import time

from .assistant_tools import compact, day, evidence, resolve
from .disclosed import latest, revisions
from .factor_studies import analyze, read
from .stock_valuation import valuation_history
from .study_store import bucket, edition


# Column names are the contract presented to the model. Dates are YYYYMMDD except news timestamps.
TABLES = {
    "securities": ("证券目录，行业和名称为当前目录；status=L 上市、D 退市、P 暂停上市。", "symbol name kind exchange industry status listed delisted category"),
    "market_snapshot": ("市场总览最近盘后截面；当日有报价的在市 A 股条件为 kind='stock' AND status='L' AND close IS NOT NULL。涨跌、换手为百分数；成交额千元，总市值万元。", "day symbol name kind exchange industry status close pct amount_thousand pe_ttm pb market_cap_wan turnover_pct"),
    "coverage": ("全目录行情可用状态 ready/empty/denied 与真实覆盖首末日。", "symbol kind status bars first_day last_day"),
    "bars": ("指定 symbols 的全部归档个股和指数日线；个股不复权，参考前收盘用于除权日收益，成交额千元，成交量沿用原表。", "symbol day open high low close pre_close pct volume amount_thousand"),
    "stock_beta": ("指定股票，截至 as_of 最近一组 120 对实际配对单日收益。市场基准默认沪深300价格指数；Beta、相关系数无单位。精确日期加 WHERE day。", "symbol name benchmark window_start day observations beta correlation covariance_pp2 benchmark_variance_pp2 note"),
    "beta_history": ("指定股票相对 benchmark 的全部可估滚动 Beta 日期点，按 SQL 日期筛选；计算使用足够的前置历史。", "symbol name benchmark day beta"),
    "stock_study": ("指定股票，与个股研究共用算法。价格以元计，百分位、收益、回撤、模拟、仓位、波动率以百分数计，relative_median_pp 是百分点。历史非月末可能缺估值，position_basis 说明实际口径。一年相对表现用对应全收益指数。", "symbol name benchmark day close ma20 ma60 ma200 trend_score rating position_basis pe_ttm pe_percentile_pct pb pb_percentile_pct ref_low ref_high atr14 risk_line cap_pct volatility_1y_pct drawdown_1y_pct return_20d_pct relative_20d_pp amount_change_pct sim_win_pct sim_median_pct sim_paths relative_rating relative_months relative_wins relative_median_pp sim_p05_pct sim_p25_pct sim_p75_pct sim_p95_pct sim_drawdown_p05_pct valuation_samples valuation_start valuation_end relative_independent_periods note"),
    "valuations": ("指定股票的月末 PE_TTM / PB 归档，最新日估值见 market_snapshot。", "symbol day pe_ttm pb"),
    "reports": ("指定股票截至 as_of 已公告的各报告期财报。ROE 年初至期末累计，增速同比；eps 元，其余百分数。", "symbol name period announced eps roe gross_margin debt_ratio revenue_yoy profit_yoy"),
    "financial_snapshot": ("全市场当前研究截面，用于自由筛选、排序或与行情联查。period 参数指定报告期，默认各公司最新一期。ROE 为累计值，增速同比。", "symbol period announced eps roe gross_margin debt_ratio revenue_yoy profit_yoy"),
    "factor_values": ("全市场最近完整因子截面。60日动量与20日年化波动率、ROE、换手为百分数，PB和PE为倍。", "symbol day momentum volatility pb annual_roe pe_ttm turnover_pct"),
    "breadth": ("200 日均线市场宽度；above / eligible 为站上均线家数与有效样本数，quoted 为当日报价家数，hs300_close 为指数收盘点位。", "day above eligible quoted hs300_close"),
    "industries": ("31个申万一级行业轮动排名；12减1月动量、历史价格分位和动量分位均为百分数。", "symbol name day momentum price_percentile momentum_percentile observations"),
    "industry_bars": ("申万官方行业指数开盘和收盘，支持全31行业与逐日对比。", "symbol name day open close"),
    "index_members": ("指定指数截至 as_of 可查的最近一期成分及权重（%），day 为真实权重日期。", "index_code day symbol name weight_pct"),
    "news": ("东方财富快讯页面当前样本，时间为北京时间，score 为页面情绪分（>52.5正面，<47.5负面）。", "article_id published title score"),
    "news_stocks": ("快讯编号与网站识别的相关股票，多对多。", "article_id symbol"),
    "news_sectors": ("快讯编号与新闻行业标签，多对多。", "article_id industry"),
}
TEXT = set("symbol name kind exchange industry status listed delisted category day first_day last_day benchmark "
           "window_start valuation_start valuation_end note rating position_basis relative_rating period announced index_code article_id published title".split())
PERSONAL_SERIES = {"bars","stock_beta","beta_history","stock_study","valuations","reports","index_members"}
STUDY_DATE = {"financial_snapshot","factor_values","industries"}
NEWS = {"news","news_stocks","news_sectors"}
TOOLS_DIR = Path(__file__).parent


def catalog(names=None):
    selected = list(TABLES) if names is None else names
    if not isinstance(selected,list) or any(not isinstance(k,str) or k not in TABLES for k in selected):
        raise ValueError("请使用站内目录列出的数据表名称。")
    rows = [{"表": k, "含义": TABLES[k][0], "列": TABLES[k][1]} for k in selected]
    return evidence("序衡研究数据目录", "数据表与列", "各页面共用的只读数据", rows,
                    "多张表可在同一条 SELECT 中联查。金融日期为 YYYYMMDD 文本，NULL 表示缺失。")


@lru_cache(maxsize=1)
def metric_program():
    # Only repository-owned pure functions enter this runtime. Data is supplied as a function argument.
    modules = [(TOOLS_DIR / "desk" / f).read_text(encoding="utf8").replace("export ", "")
               for f in ("beta.js", "stock-analysis.js", "diagnosis.js")]
    return "\n".join([*modules,(TOOLS_DIR / "desk" / "assistant-metrics.js").read_text(encoding="utf8")])


class Sources:
    def __init__(self, store, client, args):
        self.store, self.client, self.params = store, client, args
        self.cutoff = compact(day(args["as_of"])) if "as_of" in args else store.day
        if self.cutoff > store.day:
            raise ValueError("所选日期晚于网站行情库截止日 "+store.day+"。")
        self.items = list({s[0]:s for s in (resolve(store,n) for n in args.get("symbols",[]))}.values())
        self.symbols = {item[0] for item in self.items}
        self.notes = []
        self.reader = getattr(store, "service", "")
        self._series = {}

    @cached_property
    def study(self):
        return edition(self.store)

    @cached_property
    def news(self):
        from .news_store import cache
        return cache.get(self.store)

    @cached_property
    def benchmark(self):
        item = resolve(self.store, self.params.get("benchmark", "000300.SH"))
        if item[2] != "index":
            raise ValueError("市场基准需要指数名称或完整指数代码。")
        return item

    @cached_property
    def js(self):
        import quickjs
        context = quickjs.Context()
        context.set_memory_limit(96 * 1024 * 1024)
        context.set_time_limit(15)
        context.eval(metric_program())
        return context

    def series(self, code, *, cache=False):
        if code not in self._series:
            series = self.store.series(code)
            selected = (series["status"], [b for b in series["bars"] if b[0] <= self.cutoff])
            if not cache:
                return selected
            self._series[code] = selected
        return self._series[code]

    def metrics(self, key, item):
        code,name = item[:2]
        bench = self.benchmark
        status,bars = self.series(code)
        market_status,market = self.series(bench[0],cache=True)
        mode = {"stock_beta":"beta", "beta_history":"beta_history", "stock_study":"study"}[key]
        payload = dict(mode=mode, code=code, bars=bars, index=market, launch=bench[6],
                       stockStatus=status, marketStatus=market_status)
        if mode == "study":
            ret = json.loads(self.js.eval("JSON.stringify(totalReturnCodes)")).get(bench[0])
            values = valuation_history(self.store,code)
            self.notes.append("月末估值版本 "+str(values["edition"] or "无"))
            historical = self.cutoff != self.store.day
            payload.update(listed=max(item[6] or "20000101","20211115" if code.endswith(".BJ") else "20000101"),
                last=item[7] or self.cutoff, asOf=self.cutoff, historical=historical,
                active=(not item[7] or self.cutoff < item[7]) if historical else item[5]=="L",
                calendar=[d for d in self.store.daily["dates"] if bars and bars[0][0] <= d <= bars[-1][0]],
                valuations=[r for r in values["rows"] if r[0]<=self.cutoff],
                quote=None if historical else dict(d=self.cutoff,close=item[9],pe=item[12],pb=item[13]),
                totalLaunch=self.store.catalog[ret][6] if ret in self.store.catalog else None,
                total=self.series(ret,cache=True)[1] if ret in self.store.catalog else [])
        result = self.js.get("assistantStockData")(json.dumps(payload,separators=(",",":"),allow_nan=False))
        for row in json.loads(result):
            yield (code,name,bench[0],*row)

    def selected_rows(self, key):
        if not self.items:
            raise ValueError(key+" 需要 symbols。可先用 securities、因子排名或财务筛选查找证券。")
        for item in self.items:
            code,name,kind = item[:3]
            if key not in ("bars","index_members") and kind != "stock":
                raise ValueError(key+" 适用于个股；"+name+" 的证券类别为 "+kind+"。")
            if key in ("stock_beta","beta_history","stock_study"):
                yield from self.metrics(key,item)
            elif key == "bars":
                status,bars = self.series(code)
                self.notes.append(code+" 日线状态 "+status)
                yield from ((code,*row) for row in bars)
            elif key == "valuations":
                values=valuation_history(self.store,code)
                self.notes.append("月末估值版本 "+str(values["edition"] or "无"))
                yield from ((code,*r) for r in values["rows"] if r[0]<=self.cutoff)
            elif key == "reports":
                raw=read(self.study,"reports/"+str(bucket(code)),self.reader).get(code,[])
                self.notes.append("财报归档 "+self.study["day"])
                yield from ((code,name,*r) for r in latest(revisions(raw),min(self.cutoff,self.study["day"])))
            else:
                from .details import extra
                if kind != "index":
                    raise ValueError("查询成分需要指数。")
                data=extra(self.store,"members",code,self.cutoff,getattr(self.client,"token",""))
                yield from ((code,data["day"],*r) for r in data["items"])

    def rows(self, key):
        if key in PERSONAL_SERIES:
            yield from self.selected_rows(key)
            return
        if key in STUDY_DATE:
            if "as_of" in self.params and self.cutoff != self.study["day"]:
                raise ValueError(key+" 为完整研究截面 "+self.study["day"]+"，不能用于其他日期的截面。")
            self.notes.append("研究截面 "+self.study["day"])
        if key == "securities":
            yield from (item[:9] for item in (self.items or self.store.catalog.values()))
        elif key == "coverage":
            if self.cutoff != self.store.day: raise ValueError("覆盖清单为当前库版本。")
            yield from (r for r in self.store.coverage if not self.symbols or r[0] in self.symbols)
        elif key == "market_snapshot":
            if self.cutoff != self.store.day: raise ValueError("市场快照仅对应 "+self.store.day+"。指定历史日请查 bars。")
            yield from ((self.cutoff,*r[:6],*r[9:16]) for r in (self.items or self.store.catalog.values()))
        elif key == "financial_snapshot":
            period=self.params.get("period","latest")
            if period != "latest":
                period=compact(day(period))
            if period not in ("latest",*self.study["periods"]): raise ValueError("研究库没有该报告期。")
            self.notes.append("报告期 "+period)
            yield from ((code,*r) for code,r in read(self.study,"fin/"+period,self.reader).items()
                        if not self.symbols or code in self.symbols)
        elif key == "factor_values":
            yield from ((r[0],self.study["day"],*r[1:]) for r in read(self.study,"current",self.reader)
                        if not self.symbols or r[0] in self.symbols)
        elif key == "breadth":
            yield from (r for r in analyze(self.store,{"action":"breadth"})["rows"] if r[0]<=self.cutoff)
        elif key == "industries":
            yield from ((code,name,self.study["day"],*rest) for code,name,*rest in analyze(self.store,{"action":"sectors"})["rows"])
        elif key == "industry_bars":
            self.notes.append("申万行业归档 "+self.study["day"])
            for sector in read(self.study,"industries",self.reader):
                yield from ((sector["code"],sector["name"],*r) for r in sector["bars"] if r[0]<=self.cutoff)
        elif key in NEWS:
            if "as_of" in self.params: raise ValueError("新闻页保存当前快讯批次。请按 published 筛选该批次内的发布时间。")
            self.notes.append("东方财富快讯采集于 "+self.news["checked"]+"，北京时间")
            for article in self.news["articles"]:
                if key=="news":
                    yield (article["id"],article["time"],article["title"],article["score"])
                else:
                    yield from ((article["id"],v) for v in article["stocks" if key=="news_stocks" else "sectors"])


SQL_FUNCTIONS = set(("abs avg coalesce count cume_dist date dense_rank first_value glob ifnull instr lag last_value "
                     "lead length like lower ltrim max min nullif ntile percent_rank rank replace round row_number "
                     "rtrim sign sqrt stdev substr substring sum total trim upper").split())


class Stddev:
    def __init__(self):
        self.n=0
        self.mean=self.m2=0.

    def step(self, value):
        if not isinstance(value,(int,float)):
            return
        self.n+=1
        delta=value-self.mean
        self.mean+=delta/self.n
        self.m2+=delta*(value-self.mean)

    def finalize(self):
        return math.sqrt(max(0,self.m2)/(self.n-1)) if self.n>1 else None


def select_rows(db,tables,sql):
    source_reads = set()
    def authorize(action, arg, column, database, trigger):
        if action==sqlite3.SQLITE_READ and arg in tables:
            source_reads.add(arg)
            return sqlite3.SQLITE_OK
        if action==sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action==sqlite3.SQLITE_FUNCTION and (column or "").lower() in SQL_FUNCTIONS:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    db.execute("PRAGMA query_only=ON")
    db.set_authorizer(authorize)
    deadline=time.monotonic()+3
    db.set_progress_handler(lambda:time.monotonic()>deadline,2000)
    try:
        cur=db.execute(sql)
        if not cur.description or not source_reads:
            raise ValueError("请用 FROM 引用已选择的站内研究表。")
        columns=[c[0] for c in cur.description]
        if len(set(columns))!=len(columns):
            raise ValueError("输出列名重复，请用 AS 指定不同名称。")
        rows=[]
        size=0
        for values in cur:
            if any(isinstance(v,bytes) for v in values):
                raise ValueError("查询结果须为数值、文本或空值。")
            row=dict(zip(columns,values))
            size+=len(json.dumps(row,ensure_ascii=False))
            if len(rows)==50 or size>24000:
                if not rows: raise ValueError("单行超出展示大小，请只选需要的列。")
                return rows, True
            if any(type(v) is float and not math.isfinite(v) for v in values):
                raise ValueError("结果包含无穷值，请检查运算或分母。")
            rows.append(row)
        return rows,False
    except sqlite3.Error as exc:
        raise ValueError("站内只读查询未完成："+str(exc)[:220]+"。可先查看数据目录，再调整 SQL。") from None


def query_site(store,client,p):
    names=p["tables"]
    if not names or any(not isinstance(k,str) or k not in TABLES for k in names):
        raise ValueError("请选择目录内的数据表。")
    names=list(dict.fromkeys(names))
    if not p["sql"].lstrip().lower().startswith(("select","with")):
        raise ValueError("站内数据查询使用 SELECT 或 WITH。")
    inputs=Sources(store,client,p)
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("PRAGMA temp_store=FILE")
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 128000)
        db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 80)
        db.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 60)
        db.create_aggregate("stdev",1,Stddev)
        for key in names:
            columns=TABLES[key][1].split()
            definitions=",".join('"'+c+'" '+("TEXT" if c in TEXT else "NUMERIC") for c in columns)
            db.execute(f'CREATE TABLE "{key}" ({definitions})')
            marks=",".join("?" for _ in columns)
            db.executemany(f'INSERT INTO "{key}" VALUES ({marks})',inputs.rows(key))
        rows,more=select_rows(db,names,p["sql"])
    scope="行情库 "+store.day+" · "+", ".join(names)
    if "as_of" in p: scope+=" · 截至 "+inputs.cutoff
    if inputs.items and (PERSONAL_SERIES | {"securities","coverage","market_snapshot","financial_snapshot","factor_values"}).intersection(names):
        scope+=" · "+", ".join(r[1]+" "+r[0] for r in inputs.items)
    if {"stock_beta","stock_study","beta_history"}.intersection(names):
        scope+=" · 基准 "+inputs.benchmark[1]+" "+inputs.benchmark[0]
    notes=list(dict.fromkeys(inputs.notes))
    if more: notes.append("结果还有后续行。需要全体统计时请在 SQL 内聚合，查看明细可用 ORDER BY 与 LIMIT/OFFSET。")
    notes.append("查询语句："+p["sql"])
    return evidence("序衡站内研究库","只读联查",scope,rows," · ".join(notes))
