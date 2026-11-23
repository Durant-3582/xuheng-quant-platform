"""Exercise real tool routing with deterministic provider responses; never spend API credits."""
import hmac
import io
import json
import secrets
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from xuheng.assistant import handle
from xuheng.assistant_clients import ServiceError, rpc_message
from xuheng.assistant_tools import execute


STOCK = ["600519.SH", "贵州茅台", "stock"]
INDEX = ["000300.SH", "沪深300", "index"]
STORE = SimpleNamespace(day="20261113", snapshot={"aliases": {}},
                        catalog={s[0]: s for s in (STOCK, INDEX, ["399300.SZ","沪深300","index"], ["000001.SH","上证指数","index"],
                                                   ["000001.SZ","平安银行","stock"])})


class Provider:
    def __init__(self, _):
        self.calls = []

    def call(self, name, args):
        self.calls.append((name, args))
        if args.get("trade_date") == "20261114":
            return []
        fields = {"daily": {"close": 1435.26}, "index_daily": {"close": 4016.2897},
                  "daily_basic": {"pe_ttm": 21.8376, "pb": 6.6156}}
        return [{"ts_code": args["ts_code"], "trade_date": args["trade_date"], **fields[name]}]

    def close(self):
        pass


def planned(name, args, identifier="call-1"):
    return {"id": identifier, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.source = Provider("")
        self.args = {"symbol": "贵州茅台", "dataset": "prices", "end": "2026-11-13"}
        self.password = "测试-" + secrets.token_urlsafe(18)

    def access(self, state, action, **args):
        return handle(STORE, {"action": action, **args}, state, "example", "example", password=self.password)

    def proof(self, challenge, password=None):
        return hmac.digest((password or self.password).encode(), ("xuheng-ai:" + challenge).encode(), "sha256").hex()

    def unlocked(self, state):
        challenge = self.access(state, "history")["challenge"]
        result = self.access(state, "unlock", proof=self.proof(challenge))
        self.assertEqual(result["access"], "unlocked")
        return state

    def test_data(self):
        actual = execute("security_data", self.args, STORE, self.source)
        self.assertEqual(actual["rows"][0]["收盘"], 1435.26)
        self.assertEqual(actual["endpoint"], "daily")
        for key, name, expected in [("valuation", "贵州茅台", "daily_basic"), ("prices", "沪深 300", "index_daily")]:
            self.assertEqual(execute("security_data", {**self.args,"dataset":key,"symbol":name}, STORE, self.source)["endpoint"], expected)
        self.assertIsNone(actual["rows"][0]["开盘"])
        self.assertEqual(self.source.calls[-1][1]["ts_code"],"000300.SH")

    def test_mismatch_unsupported_ambiguity_and_dates(self):
        for args in [{"symbol":"000001"}, {"end":"20260231"}, {"start":"20240101"},
                     {"symbol":"沪深300","dataset":"valuation"}, {"unexpected": True}]:
            with self.assertRaises(ValueError):
                execute("security_data", {**self.args, **args}, STORE, self.source)
        with self.assertRaises(ServiceError):
            execute("security_data", self.args, STORE, SimpleNamespace(call=lambda *_:[{"ts_code": "000001.SZ"}]))
        self.assertEqual(len(self.source.calls), 0)

    def test_history_followup_and_idempotence(self):
        state, calls = self.unlocked({}), []
        def fake(messages, tools, choice):
            calls.append(choice)
            if messages[-1]["role"] == "user":
                if len(calls)>2:
                    self.assertIn("茅台", messages[-2]["content"])
                return {"tool_calls": [planned("security_data", self.args)]}
            info = json.loads(messages[-1]["content"])
            self.assertEqual(info["rows"][0]["收盘"],1435.26)
            return {"content":"贵州茅台当日收盘价为 1435.26 元。"}
        def send(id, text):
            return handle(STORE,{"action":"ask","question":text,"turnId":id},state,"example","example",fake,
                          client_factory=lambda _:self.source,password=self.password)
        first=send("test-turn-00001","茅台的收盘价？")
        self.assertEqual(first,send("test-turn-00001","茅台的收盘价？"))
        send("test-turn-00002","再查一次？")
        self.assertEqual(len(calls),4)
        self.assertEqual(len(state["turns"]),2)
        self.assertEqual(handle(STORE,{"action":"history"},{},None,None)["turns"],[])
        self.assertEqual(self.access(state,"clear")["turns"],[])

    def test_empty_exact_date_and_no_key(self):
        body={"action":"ask","question":"指定日期","turnId":"test-empty-0001"}
        state=self.unlocked({})
        with self.assertRaises(ServiceError):
            handle(STORE,body,state,"","example",password=self.password)
        model=Mock(side_effect=[{"tool_calls":[planned("security_data",{**self.args,"end":"20261114"})]},
                                {"content":"指定日期未返回行情记录。"}])
        out=handle(STORE,body,state,"example","example",model,client_factory=lambda _:self.source,password=self.password)
        self.assertIn("未返回", out["turn"]["answer"])
        self.assertEqual(out["turn"]["evidence"][0]["rows"],[])
        self.assertEqual(len(self.source.calls),1)

    def test_locked_requests_do_not_reach_billed_providers(self):
        old={"id":"existing-turn-01","question":"之前的问题","answer":"旧回答","evidence":[]}
        state={"turns":[old]}
        payload={"action":"ask","turnId":old["id"],"question":old["question"],"access":"unlocked","grant":True}
        model=Mock(side_effect=AssertionError("unauthorized model request"))
        factory=Mock(side_effect=AssertionError("unauthorized data request"))
        for password,status in [(None,"unconfigured"),("  ","unconfigured"),(self.password,"locked")]:
            result=handle(STORE,payload,state,"example","example",model,client_factory=factory,password=password)
            self.assertEqual(result["access"],status)
            self.assertEqual(result["turns"],[])
            self.assertNotIn("turn",result)
        self.assertEqual(self.access(state,"clear")["access"],"locked")
        model.assert_not_called()
        factory.assert_not_called()

    def test_wrong_replay_rotation_and_relock(self):
        state={}
        nonce=self.access(state,"history")["challenge"]
        bad=self.access(state,"unlock",proof=self.proof(nonce,"invalid"))
        self.assertIn("不正确",bad["message"])
        stale=self.access(state,"unlock",proof=self.proof(nonce))
        self.assertEqual(stale["access"],"locked")
        proof=self.proof(stale["challenge"])
        self.assertEqual(self.access(state,"unlock",proof=proof)["access"],"unlocked")
        self.assertEqual(self.access({},"unlock",proof=proof)["access"],"locked")
        state.update(turns=[{"question":"旧对话"}],recent=[1])
        self.assertEqual(self.access(state,"lock")["turns"],[])
        self.assertEqual(state["recent"],[1])
        self.assertEqual(self.access(state,"unlock",proof=proof)["access"],"locked")
        self.unlocked(state)
        self.password += "新"
        self.assertEqual(self.access(state,"ask",question="刷新后",turnId="reload-check-01")["access"],"locked")
        self.unlocked(state)

    def test_wrong_password_throttle_expires(self):
        state={}
        with patch("xuheng.assistant_access.time.monotonic",return_value=1000):
            for _ in range(6):
                self.access(state,"unlock",proof="bogus")
            nonce=self.access(state,"history")["challenge"]
            self.assertIn("频繁",self.access(state,"unlock",proof=self.proof(nonce))["message"])
        with patch("xuheng.assistant_access.time.monotonic",return_value=1061):
            self.unlocked(state)

    def test_stream_id_and_multiline(self):
        stream = b': keepalive\n\ndata: {"jsonrpc":"2.0","method":"notifications/message"}\n\nevent: message\ndata: {"id":2,\ndata: "result":{}}\n\n'
        response = SimpleNamespace(headers={"Content-Type":"text/event-stream"},
                                   iter_lines=lambda: io.BytesIO(stream).read().splitlines())
        self.assertEqual(rpc_message(response,2)["result"],{})


class SelectionTests(unittest.TestCase):
    def setUp(self):
        a,b,c,d="600001.SH","000001.SZ","920001.BJ","600002.SH"
        self.store=SimpleNamespace(day="20261116",catalog={
            code:[code, name, "stock", "", industry] for code,name,industry in
            [(a,"甲","银行"),(b,"乙","银行"),(c,"丙","电子"),(d,"丁","银行")]})
        self.current=[[a,9,5,0.5,8,12,2],[b,5,8,1.5,11,8,3],[c,2,7,1,14,10,4],[d,10,3,-1,12,9,4]]
        self.fin={a:["20260930","20261020",1,10,35,40,18,15],
                  b:["20260930","20261025",2,20,40,65,30,25],
                  c:["20260930","20261026",1,None,45,None,70,50]}
        index={"day":"20261113","defaultPeriod":"20260930","periods":["20260930"]}
        data={"current":self.current,"quality":{a:["20251231","20260315",8]},
              "fin/20260930":self.fin, "fin/latest":self.fin}
        self.enterContext(patch("xuheng.factor_studies.edition",return_value=index))
        self.enterContext(patch("xuheng.factor_studies.read",side_effect=lambda _,k,r:data[k]))

    def test_ranking_weights_scope_paging_and_dates(self):
        from xuheng.factor_studies import analyze
        args={"weights":{"pb":50,"vol":50},"industry":"银行","limit":1}
        actual=execute("rank_stocks",args,self.store,None)
        self.assertEqual(actual["rows"][0]["证券代码"],"600001.SH")
        self.assertEqual(actual["rows"][0]["综合分"],100)
        self.assertIn("2026-11-13",actual["scope"])
        self.assertIn("当日有报价 3 只，入选范围 2 只",actual["scope"])
        second=execute("rank_stocks",{**args,"page":2},self.store,None)
        self.assertEqual((second["rows"][0]["排名"],second["rows"][0]["证券代码"]),(2,"000001.SZ"))
        self.assertEqual(execute("rank_stocks",{**args,"page":3},self.store,None)["rows"],[])
        self.assertEqual(execute("rank_stocks",{**args,"venue":"BJ"},self.store,None)["rows"],[])
        defaults=execute("rank_stocks",{},self.store,None)
        web=analyze(self.store,{"action":"rank","weights":{"pb":40,"roe":35,"mom":25}})
        self.assertEqual([r["证券代码"] for r in defaults["rows"]],[r[0] for r in web["rows"]])
        self.assertEqual(next(r for r in defaults["rows"] if r["证券代码"]=="600001.SH")["年报公告日"],"2026-03-15")
        for invalid in ({"as_of":"20240105"},{"weights":{"pb":30}},{"weights":[]},{"limit":True},{"limit":0},
                        {"page":1.2},{"industry":"不存在的行业"}):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                execute("rank_stocks",invalid,self.store,None)

    def test_financial_filters_and_missing_unused_values(self):
        result=execute("screen_financials",{"sort":"revenue"},self.store,None)
        self.assertEqual(result["rows"][0]["证券名称"],"丙")
        self.assertIsNone(result["rows"][0]["资产负债率（%）"])
        filtered=execute("screen_financials",{"min_roe":10,"max_debt":40,"period":"2026-09-30","sort":"profit"},self.store,None)
        self.assertEqual([(r["证券代码"],r["公告日"]) for r in filtered["rows"]],[("600001.SH","2026-10-20")])
        self.assertIn("ROE ≥ 10%",filtered["scope"])
        self.assertEqual(execute("screen_financials",{"min_roe":100},self.store,None)["rows"],[])

    def test_open_ended_recommendation_tool_loop(self):
        from xuheng.assistant import request_answer
        model=Mock(side_effect=[{"tool_calls":[planned("rank_stocks",{"limit":2})]},{"content":"这两只可作为研究候选。"}])
        _,sources=request_answer("给我推荐两只 A 股",[],self.store,None,model)
        self.assertEqual(len(sources[0]["rows"]),2)
        sent=json.loads(model.call_args.args[0][-1]["content"])
        self.assertEqual(sent["rows"],sources[0]["rows"])
        self.assertIn("综合分",sent["rows"][0])

    def test_general_research_discussion_without_market_lookup(self):
        from xuheng.assistant import request_answer
        reply="可以从估值、盈利质量和流动性三个角度比较低市净率公司的风险。"
        model=Mock(return_value={"content":reply})
        self.assertEqual(request_answer("低估值策略有什么盲点？",[],self.store,None,model),(reply,[]))
        self.assertEqual(model.call_count,1)
        self.assertEqual(model.call_args.args[2],"auto")


if __name__ == "__main__":
    unittest.main()
