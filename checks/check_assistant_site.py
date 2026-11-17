"""Verify research queries, including parity with the stock page and dated financial reports."""
from datetime import date, timedelta
from math import isclose
from pathlib import Path
from statistics import covariance, correlation, variance
import unittest
from unittest.mock import patch

from xuheng.archive import Archive
from xuheng.assistant import request_answer
from xuheng.assistant_site import TABLES
from xuheng.assistant_tools import execute
from xuheng.factor_studies import analyze


def query(store, tables, sql, **params):
    return execute("query_site",dict(tables=tables,sql=sql,**params),store,None)


class Sample:
    def __init__(self):
        self.snapshot={"aliases":{}}
        self.catalog={}
        self.bars={}
        for code,name,kind in (("600519.SH","贵州茅台","stock"),("000300.SH","沪深300","index")):
            bars=[]
            close=20.
            for i in range(155):
                day=(date(2020,1,2)+timedelta(days=i)).strftime("%Y%m%d")
                ret=((i%7)-3)*.003+((i%3)-1)*.002
                multiplier=1.5 if kind=="stock" else 1
                ref=close*(.7 if i==66 and kind=="stock" else 1)
                close=ref*(1+multiplier*ret)
                bars.append([day,ref,max(close,ref),min(close,ref),close,ref,ret*100,100,200])
            if kind=="stock":
                bars.pop(55)  # suspension and first day back must both be excluded
                bars[75][7]=0
            self.bars[code]=bars
            self.catalog[code]=[code,name,kind,"SSE","行业","L",bars[0][0],None,"类别",close,0,200,10,2,3000,1]
        self.day=bars[-1][0]

    def series(self,code):
        return {"status":"ready","bars":self.bars[code]}


def oracle(store, code, bench):
    stock=store.series(code)["bars"]
    market=[r for r in store.series(bench)["bars"] if r[0]>=store.catalog[bench][6]]
    prior={b[0]:(a[0],b[4]/(b[5] if b[5] is not None else a[4])-1) for a,b in zip(market,market[1:])
           if b[4] and (b[5] if b[5] is not None else a[4])}
    sample=[(b[0],b[4]/b[5]-1,prior[b[0]][1]) for a,b in zip(stock,stock[1:])
            if b[0] in prior and a[0]==prior[b[0]][0] and a[7] and b[7] and b[4] and b[5]][-120:]
    days,y,x=zip(*sample)
    return days[0],days[-1],covariance(y,x)/variance(x),correlation(y,x)


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.store=Sample()

    def test_beta_with_suspension_and_ex_dividend(self):
        row=query(self.store,["stock_beta"],"SELECT * FROM stock_beta",symbols=["贵州茅台"])["rows"][0]
        start,end,beta,r=oracle(self.store,"600519.SH","000300.SH")
        self.assertEqual((row["window_start"],row["day"],row["observations"]),(start,end,120))
        self.assertAlmostEqual(row["beta"],beta)
        self.assertAlmostEqual(row["beta"],1.5)
        self.assertAlmostEqual(row["correlation"],r)
        history=query(self.store,["beta_history"],"SELECT * FROM beta_history ORDER BY day DESC LIMIT 1",symbols=["贵州茅台"])["rows"][0]
        self.assertEqual((history["day"],history["beta"]),(end,row["beta"]))
        short=query(self.store,["stock_beta"],"SELECT * FROM stock_beta",symbols=["贵州茅台"],as_of="20200115")["rows"][0]
        self.assertLess(short["observations"],120)
        self.assertIsNone(short["beta"])
        self.assertTrue(short["note"])

    def test_no_observation_and_constant_benchmark(self):
        with self.assertRaises(ValueError):
            query(self.store,["bars"],"SELECT * FROM bars")
        b=self.store.bars["000300.SH"]
        for row in b: row[4]=row[5]=20.
        missing=query(self.store,["stock_beta"],"SELECT * FROM stock_beta",symbols=["贵州茅台"])["rows"][0]
        self.assertIsNone(missing["beta"])
        self.assertIn("方差",missing["note"])
        self.assertEqual(query(self.store,["bars"],"SELECT close FROM bars WHERE day='20010101'",symbols=["贵州茅台"])["rows"],[])

    def test_sql_discovery_joins_and_limits(self):
        info=execute("describe_site_data",{},self.store,None)
        self.assertEqual({r["表"] for r in info["rows"]},set(TABLES))
        rows=query(self.store,["securities","bars"],
                   "WITH q AS (SELECT symbol,count(*) n FROM bars GROUP BY symbol) "
                   "SELECT s.name,q.n FROM q JOIN securities s USING(symbol)",symbols=["贵州茅台"])["rows"]
        self.assertEqual(rows,[{"name":"贵州茅台","n":154}])
        full=query(self.store,["bars"],"SELECT day,close FROM bars ORDER BY day",symbols=["贵州茅台"])
        self.assertEqual(len(full["rows"]),50)
        self.assertIn("后续",full["note"])
        for sql in ("DELETE FROM securities","PRAGMA database_list","SELECT * FROM sqlite_master",
                    "SELECT load_extension('/x') FROM securities","SELECT * FROM securities; SELECT 2",
                    "SELECT 3.5 AS beta","SELECT CAST(name AS BLOB) FROM securities"):
            with self.subTest(sql=sql),self.assertRaises(ValueError):
                query(self.store,["securities"],sql)
        self.assertEqual(query(self.store,["securities"],"SELECT count(*) AS n FROM securities")["rows"][0]["n"],2)

    def test_catalog_then_join_in_model_loop(self):
        import json
        def planned(name,args,i):
            return {"tool_calls":[{"id":str(i),"type":"function","function":{"name":name,"arguments":json.dumps(args)}}]}
        def model(messages,tools,choice):
            latest=messages[-1]
            if latest["role"]=="user": return planned("describe_site_data",{"tables":["stock_beta"]},1)
            packet=json.loads(latest["content"])
            if latest["tool_call_id"]=="1":
                self.assertIn("observations",packet["rows"][0]["列"])
                return planned("query_site",{"tables":["stock_beta"],"symbols":["贵州茅台"],
                                            "sql":"SELECT name,observations,beta FROM stock_beta"},2)
            return {"content":f"贵州茅台基于 {packet['rows'][0]['observations']} 对收益，Beta 为 {packet['rows'][0]['beta']:.3f}。"}
        answer,sources=request_answer("贵州茅台相对沪深300的Beta是多少？",[],self.store,None,model)
        self.assertIn("1.500",answer)
        self.assertEqual(len(sources),1)
        self.assertEqual(sources[0]["rows"][0]["observations"],120)


archive_dir=Path(__file__).resolve().parents[1]/".private"/"database"


@unittest.skipUnless((archive_dir/"manifest.json").is_file(),"requires an installed market archive")
class ArchiveParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store=Archive(archive_dir)

    def test_two_real_stocks_and_two_benchmarks(self):
        for bench in ("000300.SH","000905.SH"):
            for row in query(self.store,["stock_beta"],"SELECT * FROM stock_beta",
                             symbols=["贵州茅台","五粮液"],benchmark=bench)["rows"]:
                a,b,beta,r=oracle(self.store,row["symbol"],bench)
                self.assertEqual((a,b),(row["window_start"],row["day"]))
                self.assertTrue(isclose(beta,row["beta"],abs_tol=1e-10))
                self.assertTrue(isclose(r,row["correlation"],abs_tol=1e-10))

    def test_disclosures_and_quote_join(self):
        sym="600519.SH"
        rows=query(self.store,["stock_beta","reports","market_snapshot"],
                   "SELECT b.symbol,b.day,b.observations,b.beta,m.close,r.period,r.announced,r.roe FROM stock_beta b "
                   "JOIN reports r USING(symbol) JOIN market_snapshot m USING(symbol) ORDER BY r.period DESC LIMIT 1",
                   symbols=[sym])["rows"]
        head=analyze(self.store,{"action":"reports","code":sym})["rows"][0]
        self.assertEqual((rows[0]["period"],rows[0]["announced"],rows[0]["roe"]),(head[0],head[1],head[3]))
        self.assertEqual(rows[0]["close"],self.store.catalog[sym][9])
        before=(date.fromisoformat(head[1])-timedelta(days=1)).strftime("%Y%m%d")
        self.assertEqual(query(self.store,["reports"],"SELECT announced FROM reports WHERE period='"+head[0]+"'",
                               symbols=[sym],as_of=before)["rows"],[])

    def test_each_relation_shape_and_website_metrics(self):
        article={"id":"A","title":"测试标题","time":"2026-11-10 09:30:00","score":50,"stocks":["600519.SH"],"sectors":["消费"]}
        with patch("xuheng.news_store.cache.get",return_value={"checked":article["time"],"articles":[article]}):
            for table,(_,cols) in TABLES.items():
                args={"symbols":["000300.SH"]} if table=="index_members" else (
                    {"symbols":["600519.SH"]} if table in ("bars","stock_beta","beta_history","stock_study","valuations","reports") else {})
                with self.subTest(table=table):
                    out=query(self.store,[table],f"SELECT * FROM {table} LIMIT 1",**args)["rows"]
                    self.assertEqual(list(out[0]),cols.split())
        row=query(self.store,["stock_study"],"SELECT * FROM stock_study",symbols=["贵州茅台"])["rows"][0]
        self.assertEqual(row["close"],self.store.catalog["600519.SH"][9])
        self.assertEqual(row["sim_paths"],2000)
        self.assertLessEqual(row["sim_p05_pct"],row["sim_median_pct"])
        self.assertLessEqual(row["sim_median_pct"],row["sim_p95_pct"])


if __name__=="__main__":
    unittest.main()
