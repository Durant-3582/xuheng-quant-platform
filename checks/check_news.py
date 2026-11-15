"""Regression cases for news scoring, stock identity, and recovery from upstream failures."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xuheng import news
from xuheng.news_store import NewsCache, checked, read_file, write_file
from ops import update_news

store = SimpleNamespace(catalog={
    "600519.SH": [None, "贵州茅台", "stock"], "000001.SZ": [None, "平安银行", "stock"],
    "000001.SH": [None, "上证指数", "index"], "920001.BJ": [None, "测试北股", "stock"],
}, snapshot={"aliases": {"830001.BJ": "920001.BJ"}})
directory = news.from_catalog(store)
assert news.sentiment("天气晴朗") == 50
assert news.sentiment("回购 回购") == news.sentiment("公司暂无回购计划") == 75
assert news.sentiment("下跌") < 47.5 and news.sentiment("获批") == news.sentiment("中标")
assert news.mentions("000001.SH", ["90.BK0150", "1.000001"], directory) == []
assert news.mentions("提及贵州茅台和830001", ["0.000001", "116.00001"], directory) == [
    "000001.SZ", "600519.SH", "920001.BJ"]

source = {"code": "20261115000001", "title": "公司获批", "summary": "贵州茅台 白酒",
          "showTime": "2026-11-15 09:00:00", "stockList": ["90.BK0150"]}
response = MagicMock()
response.__enter__.return_value = response
response.json.return_value = {"code":"1", "data":{"fastNewsList":[source, source, {"title":"缺编号"}]}}
with patch.object(news.requests, "get", return_value=response):
    edition = news.fetch(directory)
assert len(edition["articles"]) == 1
item = edition["articles"][0]
assert item["stocks"] == ["600519.SH"] and "食品饮料" in item["sectors"]
assert "summary" not in item and "贵州茅台" not in json.dumps(item, ensure_ascii=False)
assert checked(edition) == edition
response.json.return_value = {"code":"0", "data":{"fastNewsList":[]}}
with patch.object(news.requests, "get", return_value=response):
    try:
        news.fetch(directory)
        raise AssertionError("HTTP 200 with an upstream error was accepted")
    except news.NewsError:
        pass

with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / "latest.json"
    write_file(path, edition)
    stale = NewsCache(path)
    with patch("xuheng.news_store.archive_edition", side_effect=news.NewsError("同步失败")), \
         patch("xuheng.news_store.fetch", side_effect=news.NewsError("请求失败")) as remote:
        assert stale.get(store)["articles"] == [item]
        assert stale.get(store, refresh=True)["notice"]
        assert stale.get(store, refresh=True)["articles"] == [item]
        assert remote.call_count == 1
    assert read_file(path) == edition
    path.write_text('{"format":1}', encoding="utf8")
    recovered = NewsCache(path)
    with patch("xuheng.news_store.archive_edition", return_value=edition):
        assert recovered.get(store)["articles"] == [item] and read_file(path) == edition
    first = {**edition, "checked": "2026-11-15 09:09:00"}
    second = {**edition, "checked": "2026-11-15 09:39:00"}
    older_feed = {**second, "checked": "2026-11-15 10:09:00",
                  "articles": [{**item, "time": "2026-11-15 08:00:00"}]}
    write_file(path, first)
    with (patch.object(update_news, "Archive", return_value=store),
          patch.object(update_news.time, "sleep") as sleep,
          patch.object(update_news, "fetch", side_effect=[news.NewsError("暂时无法取数"), second, older_feed])):
        update_news.update(path, database=path.parent)
        assert read_file(path) == second and sleep.call_count == 1
        update_news.update(path, database=path.parent)
        assert read_file(path) == second
print("PASS news scoring, source validation, identity, deduplication, and stale-cache recovery")
