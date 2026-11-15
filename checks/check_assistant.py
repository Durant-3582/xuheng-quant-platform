"""Exercise real tool routing with deterministic provider responses; never spend API credits."""
import io
import json
from types import SimpleNamespace
import unittest

from xuheng.assistant import handle
from xuheng.assistant_clients import ServiceError, rpc_message
from xuheng.assistant_tools import execute


STOCK = ["600519.SH", "贵州茅台", "stock"]
INDEX = ["000300.SH", "沪深300", "index"]
STORE = SimpleNamespace(day="20261113", snapshot={"aliases": {}},
                        catalog={s[0]: s for s in (STOCK, INDEX, ["000001.SH","上证指数","index"],
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

    def test_data(self):
        actual = execute("security_data", self.args, STORE, self.source)
        self.assertEqual(actual["rows"][0]["收盘"], 1435.26)
        self.assertEqual(actual["endpoint"], "daily")
        for key, name, expected in [("valuation", "贵州茅台", "daily_basic"), ("prices", "沪深 300", "index_daily")]:
            self.assertEqual(execute("security_data", {**self.args,"dataset":key,"symbol":name}, STORE, self.source)["endpoint"], expected)
        self.assertIsNone(actual["rows"][0]["开盘"])

    def test_mismatch_unsupported_ambiguity_and_dates(self):
        for args in [{"symbol":"000001"}, {"end":"20260231"}, {"start":"20240101"},
                     {"symbol":"沪深300","dataset":"valuation"}, {"unexpected": True}]:
            with self.assertRaises(ValueError):
                execute("security_data", {**self.args, **args}, STORE, self.source)
        with self.assertRaises(ServiceError):
            execute("security_data", self.args, STORE, SimpleNamespace(call=lambda *_:[{"ts_code": "000001.SZ"}]))
        self.assertEqual(len(self.source.calls), 0)

    def test_history_followup_and_idempotence(self):
        state, calls = {}, []
        def fake(messages, tools, choice):
            calls.append(choice)
            if choice == "required":
                if len(calls)>2:
                    self.assertIn("茅台", messages[-2]["content"])
                return {"tool_calls": [planned("security_data", self.args)]}
            info = json.loads(messages[-1]["content"])
            self.assertEqual(info["rows"][0]["收盘"],1435.26)
            return {"content":"贵州茅台当日收盘价为 1435.26 元。"}
        def send(id, text):
            return handle(STORE,{"action":"ask","question":text,"turnId":id},state,"example","example",fake,
                          client_factory=lambda _:self.source)
        first=send("test-turn-00001","茅台的收盘价？")
        self.assertEqual(first,send("test-turn-00001","茅台的收盘价？"))
        send("test-turn-00002","再查一次？")
        self.assertEqual(len(calls),4)
        self.assertEqual(len(state["turns"]),2)
        self.assertEqual(handle(STORE,{"action":"history"},{},None,None)["turns"],[])
        self.assertEqual(handle(STORE,{"action":"clear"},state,None,None)["turns"],[])

    def test_empty_exact_date_and_no_key(self):
        body={"action":"ask","question":"指定日期","turnId":"test-empty-0001"}
        with self.assertRaises(ServiceError):
            handle(STORE,body,{},"","example")
        out=handle(STORE,body,{},"example","example",lambda *_:{"tool_calls":[
            planned("security_data",{**self.args,"end":"20261114"})]},client_factory=lambda _:self.source)
        self.assertIn("未返回", out["turn"]["answer"])
        self.assertEqual(out["turn"]["evidence"][0]["rows"],[])
        self.assertEqual(len(self.source.calls),1)

    def test_stream_id_and_multiline(self):
        stream = b': keepalive\n\ndata: {"jsonrpc":"2.0","method":"notifications/message"}\n\nevent: message\ndata: {"id":2,\ndata: "result":{}}\n\n'
        response = SimpleNamespace(headers={"Content-Type":"text/event-stream"},
                                   iter_lines=lambda: io.BytesIO(stream).read().splitlines())
        self.assertEqual(rpc_message(response,2)["result"],{})


if __name__ == "__main__":
    unittest.main()
