"""Regressions for leaked calls, fallback research, evidence and provider contracts."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from xuheng.assistant import ProtocolError, model_message, protocol_text, request_answer, visible_turn
from xuheng.assistant_clients import ServiceError, deepseek
from xuheng.assistant_tools import TOOLS, execute
from xuheng.assistant_web import DeepSeekWeb


STORE = SimpleNamespace(day="20261123")
DSML = '<｜DSML｜calls><｜DSML｜invoke name="query_site"><｜DSML｜parameter name="sql" string="true">SELECT 99</｜DSML｜parameter></｜DSML｜invoke></｜DSML｜calls>'
PROMPT = [{"role": "system", "content": "研究伙伴"}, {"role": "user", "content": "查资料"}]


def call(name="query_site", args=None, identifier="test-call"):
    return {"id": identifier, "type": "function", "function": {"name": name,
            "arguments": json.dumps(args if args is not None else {"tables": ["securities"], "sql": "SELECT 1"})}}


def record(rows=None):
    return {"source": "测试资料", "endpoint": "query_site", "scope": "2026-11-23",
            "rows": [{"值": 1}] if rows is None else rows, "note": "测试样本"}


class ProtocolTests(unittest.TestCase):
    def test_shared_protocol_variants_and_normal_financial_answers(self):
        cases = json.loads(Path(__file__).with_name("assistant_protocol_cases.json").read_text())
        for text in cases["blocked"]:
            with self.subTest(text=text):
                self.assertTrue(protocol_text(text))
                model = Mock(side_effect=[{"content": text}, {"content": "已正常查询。"}])
                self.assertEqual(request_answer("继续查询", [], STORE, None, model)[0], "已正常查询。")
                self.assertEqual(model.call_count, 2)
                self.assertNotIn(text, str(model.call_args.args[0]))
                self.assertNotEqual(visible_turn({"answer": text})["answer"], text)
        for text in cases["allowed"]:
            with self.subTest(text=text):
                self.assertFalse(protocol_text(text))
                self.assertEqual(visible_turn({"answer": text})["answer"], text)

    def test_nov25_two_query_batch_recovers_without_claiming_unexecuted_sql(self):
        # Transcribed delimiter variant and two-query shape from the user's
        # Nov 25 screenshot. Only the corrected native calls may be executed.
        broken = '< | | DSML | | calls>< | | DSML | | invoke name="query_site">SELECT * FROM reports</ | | DSML | | invoke></ | | DSML | | calls>'
        queries = [{"tables": ["reports"], "symbols": ["600169.SH", "601718.SH"],
                    "sql": "SELECT symbol, period, announced, roe FROM reports WHERE period >= '20251231' ORDER BY symbol, period"},
                   {"tables": ["securities", "market_snapshot"],
                    "sql": "SELECT s.symbol, s.name, m.close FROM securities s JOIN market_snapshot m ON s.symbol=m.symbol WHERE s.name LIKE '%ST%'"}]
        model = Mock(side_effect=[{"content": broken},
                     {"tool_calls": [call(args=args, identifier=f"recovered-{i}") for i,args in enumerate(queries)]},
                     {"content": "已核对财报与行情，可以继续比较这些公司的情况。"}])
        with patch("xuheng.assistant.execute", return_value=record()) as run:
            answer, evidence = request_answer("推荐几个 ST 股，特别是国央企", [], STORE, None, model)
        self.assertEqual([item.args[1] for item in run.call_args_list], queries)
        self.assertEqual(len(evidence), 2)
        self.assertNotIn("DSML", answer)
        self.assertEqual(len([m for m in model.call_args.args[0] if m["role"] == "tool"]), 2)

    def test_double_pipe_never_replayed_from_history_or_clarify_or_native_comment(self):
        broken = DSML.replace("｜", " | | ")
        history = [{"answer": broken, "question": "之前", "evidence": [record()]}]
        model = Mock(side_effect=[{"tool_calls": [call("clarify", {"reply": broken})]},
                                  {"tool_calls": [call()], "content": broken}, {"content": "已核对。"}])
        with patch("xuheng.assistant.execute", return_value=record()) as run:
            answer, evidence = request_answer("你查询了吗", history, STORE, None, model)
        self.assertEqual(answer, "已核对。")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(len(evidence), 1)
        self.assertTrue(all(broken not in str(m.args[0]) for m in model.call_args_list))

    def test_text_call_is_retried_as_native_before_execution(self):
        messages = []
        replies = iter([{"content": DSML}, {"tool_calls": [call()]}, {"content": "查到 1 条记录。"}])
        def model(prompt, tools, choice):
            messages.append(deepcopy(prompt))
            self.assertTrue(tools)
            return next(replies)
        with patch("xuheng.assistant.execute", return_value=record()) as run:
            answer, evidence = request_answer("查询", [], STORE, None, model)
        self.assertEqual(answer, "查到 1 条记录。")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[1]["sql"], "SELECT 1")
        self.assertEqual(len(evidence), 1)
        self.assertTrue(all(DSML not in str(prompt) for prompt in messages))

    def test_screenshot_ten_sources_then_additional_queries(self):
        replies = []
        count = 0
        for batch in (2, 2, 2, 2, 1, 1):
            calls = []
            for _ in range(batch):
                count += 1
                calls.append(call(args={"tables": ["securities"], "sql": f"SELECT {count}"}, identifier=str(count)))
            replies.append({"tool_calls": calls})
        replies += [{"content": DSML}, {"tool_calls": [call(args={"tables": ["securities"], "sql": "SELECT 99"})]},
                    {"content": "查询完成，以下是核对后的结论。"}]
        model = Mock(side_effect=replies)
        with patch("xuheng.assistant.execute", return_value=record()) as run:
            answer, evidence = request_answer("继续查", [], STORE, None, model)
        self.assertNotIn("DSML", answer)
        self.assertEqual((run.call_count, len(evidence)), (11, 11))
        self.assertTrue(all(item.args[1] for item in model.call_args_list))

    def test_final_synthesis_keeps_definitions_and_explicitly_uses_none(self):
        choices = []
        def model(messages, tools, choice):
            choices.append(choice)
            self.assertEqual(tools, TOOLS)
            if choice == "none":
                self.assertIn("尚未查证", messages[0]["content"])
                return {"content": "已有资料的结论。"}
            return {"tool_calls": [call()]}
        with patch("xuheng.assistant.execute", return_value=record()) as run:
            self.assertEqual(request_answer("分析", [], STORE, None, model)[0], "已有资料的结论。")
        self.assertEqual(choices, ["auto"] * 12 + ["none"])
        self.assertEqual(run.call_count, 1)  # Identical queries are not re-billed.

    def test_bad_later_call_does_not_partially_execute_batch(self):
        malformed = {"id": "broken", "type": "function", "function": {"name": "query_site", "arguments": "{"}}
        model = Mock(side_effect=[{"tool_calls": [call(), malformed]}, {"content": "请补充条件。"}])
        with patch("xuheng.assistant.execute") as run:
            request_answer("分析", [], STORE, None, model)
        run.assert_not_called()

    def test_persistent_protocol_failure_is_not_a_fake_answer(self):
        for markup in (DSML, DSML.replace("｜", "|"), DSML.replace("｜", " | | "),
                       DSML.replace("<", "&lt;"), '<｜tool▁calls▁begin｜>bad'):
            with self.subTest(markup=markup), patch("xuheng.assistant.execute") as run:
                model = Mock(return_value={"content": markup})
                with self.assertRaises(ProtocolError):
                    request_answer("分析", [], STORE, None, model)
                self.assertEqual(model.call_count, 3)
                run.assert_not_called()

    def test_recovery_failure_retains_completed_evidence(self):
        model = Mock(side_effect=[{"tool_calls": [call()]}, *[{"content": DSML}] * 3])
        with patch("xuheng.assistant.execute", return_value=record()):
            answer, evidence = request_answer("分析", [], STORE, None, model)
        self.assertIn("未能生成", answer)
        self.assertNotIn("DSML", answer)
        self.assertEqual(len(evidence), 1)

    def test_native_calls_with_leaked_comment_execute_without_replaying_comment(self):
        model = Mock(side_effect=[{"tool_calls": [call()], "content": DSML}, {"content": "完成。"}])
        with patch("xuheng.assistant.execute", return_value=record()) as run:
            request_answer("分析", [], STORE, None, model)
        self.assertEqual(run.call_count, 1)
        self.assertNotIn(DSML, str(model.call_args.args[0]))

    def test_history_and_clarify_cannot_reintroduce_the_protocol(self):
        original = {"answer": DSML, "question": "之前", "evidence": [record()]}
        model = Mock(return_value={"content": "正常回答。"})
        request_answer("为什么乱码", [original], STORE, None, model)
        self.assertNotIn(DSML, str(model.call_args.args[0]))
        self.assertEqual(visible_turn(original)["evidence"], original["evidence"])
        self.assertEqual(original["answer"], DSML)
        model = Mock(side_effect=[{"tool_calls": [call("clarify", {"reply": DSML})]}, {"content": "正常回答。"}])
        self.assertEqual(request_answer("讨论", [], STORE, None, model)[0], "正常回答。")

    def test_empty_data_and_provider_failure_allow_external_research(self):
        for first in (record([]), ServiceError("接口暂时不可用")):
            model = Mock(side_effect=[{"tool_calls": [call()]},
                                     {"tool_calls": [call("search_web", {"query": "公司公告"})]},
                                     {"content": "站内未取得资料，参考公司公告。"}])
            web = Mock()
            with patch("xuheng.assistant.execute", side_effect=[first, record()]) as run:
                answer, evidence = request_answer("查公司公告", [], STORE, None, model, web=web)
            self.assertIn("公司公告", answer)
            self.assertEqual(len(evidence), 2)
            self.assertIs(run.call_args.kwargs["web"], web)
            self.assertEqual(run.call_args.args[0], "search_web")

    def test_budget_final_answer_rejects_new_tool_invocations(self):
        model = Mock(side_effect=[{"tool_calls": [call()]}, {"content": "现有资料不足。"}])
        message, calls = model_message(model, PROMPT, "none")
        self.assertEqual((message["content"], calls), ("现有资料不足。", []))

    def test_protocol_retry_stops_at_deadline(self):
        model = Mock(return_value={"content": DSML})
        with patch("xuheng.assistant.time.monotonic", return_value=10):
            with self.assertRaises(ProtocolError):
                model_message(model, PROMPT, "auto", retry_deadline=9)
        self.assertEqual(model.call_count, 1)

    def test_invalid_responses_retry_without_executing_tools(self):
        invalid = [None, {"content": ["not text"]}, {"tool_calls": "not a list"},
                   {"tool_calls": [call(), call()]},
                   {"tool_calls": [call(args=[1])]},
                   {"tool_calls": [call(args={"sql": float("nan")})]}]
        for bad in invalid:
            with self.subTest(bad=bad), patch("xuheng.assistant.execute") as run:
                model = Mock(side_effect=[bad, {"content": "规范回答。"}])
                self.assertEqual(request_answer("问题", [], STORE, None, model)[0], "规范回答。")
                run.assert_not_called()


def response(data, status=200):
    result = Mock(status_code=status)
    result.json.return_value = data
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


class WebAndClientTests(unittest.TestCase):
    def test_chat_payload_retains_tools_with_none(self):
        with patch("xuheng.assistant_clients.requests.post", return_value=response({"choices": [
                {"finish_reason": "stop", "message": {"content": "回答"}}]})) as post:
            deepseek("test-only", PROMPT, TOOLS, "none")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["tool_choice"], "none")
        self.assertEqual(payload["tools"], TOOLS)
        self.assertEqual(payload["thinking"]["type"], "disabled")

    def test_search_provenance_and_credentials_only_go_to_provider(self):
        data = {"results": [{"title": "公司公告", "url": "https://www.sse.com.cn/disclosure/example", "date": None,
                             "summary": "原始公告摘要", "site_name": "上海证券交易所"},
                            {"title": "坏链接", "url": "javascript:alert(1)"}]}
        with patch("xuheng.assistant_web.requests.post", return_value=response(data)) as post:
            result = execute("search_web", {"query": "公告", "count": 5}, STORE, None, web=DeepSeekWeb("test-only"))
        self.assertEqual(len(result["rows"]), 1)
        self.assertIsNone(result["rows"][0]["发布日期"])
        self.assertEqual(result["rows"][0]["摘要"], "原始公告摘要")
        self.assertEqual(post.call_args.args[0], "https://api.deepseek.com/v1/tools/search")
        self.assertNotIn("test-only", str(post.call_args.kwargs["json"]))
        self.assertNotIn("test-only", str(result))
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_long_page_can_be_read_in_contiguous_chunks(self):
        content = "甲" * 12000 + "后文"
        with patch("xuheng.assistant_web.requests.post", return_value=response({"title": "公告", "content": content})):
            web = DeepSeekWeb("test-only")
            first = execute("read_web", {"url": "https://example.com/notice"}, STORE, None, web=web)
            second = execute("read_web", {"url": "https://example.com/notice", "start": 12000}, STORE, None, web=web)
        self.assertIn("start=12000", first["note"])
        self.assertEqual(first["rows"][0]["正文"] + second["rows"][0]["正文"], content)

    def test_invalid_web_arguments_do_not_trigger_network(self):
        cases = [("search_web", {"query": " "}), ("search_web", {"query": "a", "count": True}),
                 ("search_web", {"query": "a", "count": 51}), ("read_web", {"url": "file:///etc/passwd"}),
                 ("read_web", {"url": "https://user:password@example.com"}),
                 ("read_web", {"url": "https://example.com", "start": -1})]
        with patch("xuheng.assistant_web.requests.post") as post:
            for name, args in cases:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    execute(name, args, STORE, None, web=DeepSeekWeb("test-only"))
        post.assert_not_called()

    def test_provider_errors_are_readable_without_echoing_credentials(self):
        for data, status in (({"error": "test-only"}, 401), ({"error": "test-only"}, 200), ({"results": ["bad"]}, 200)):
            with patch("xuheng.assistant_web.requests.post", return_value=response(data, status)):
                with self.assertRaises(ServiceError) as caught:
                    execute("search_web", {"query": "公告"}, STORE, None, web=DeepSeekWeb("test-only"))
            self.assertNotIn("test-only", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
