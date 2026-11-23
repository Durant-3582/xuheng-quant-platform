"""Public web research using the same DeepSeek account, with inspectable source text."""
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests

from .assistant_clients import ServiceError


def public_url(value):
    if not isinstance(value, str) or len(value) > 8192:
        return False
    try:
        url = urlsplit(value)
        return url.scheme in ("https", "http") and bool(url.hostname) and not url.username and not url.password
    except ValueError:
        return False


class DeepSeekWeb:
    def __init__(self, key):
        self.key = key

    def request(self, endpoint, payload):
        if not self.key:
            raise ServiceError("网站尚未配置 DeepSeek，暂时无法检索外部资料。")
        try:
            with requests.post("https://api.deepseek.com/v1/tools/" + endpoint, json=payload,
                               headers={"Authorization": "Bearer " + self.key},
                               timeout=(6, 30), allow_redirects=False) as response:
                if response.status_code != 200:
                    raise ServiceError(f"外部资料接口暂未完成请求（HTTP {response.status_code}），可继续使用站内数据或稍后重试。")
                data = response.json()
                if not isinstance(data, dict) or "error" in data:
                    raise ServiceError("外部资料接口未返回有效结果。")
                return data
        except (requests.RequestException, ValueError) as error:
            if isinstance(error, ServiceError):
                raise
            raise ServiceError("外部资料暂时读取失败，可继续使用已核验数据。") from None

    def execute(self, name, args):
        stamp = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
        if name == "search_web":
            query = args["query"].strip()
            if not 1 <= len(query) <= 128:
                raise ValueError("搜索词需为 1 至 128 字，可分多次搜索。")
            data = self.request("search", {"query": query, "count": args.get("count", 5), "need_content": False})
            results = data.get("results")
            if not isinstance(results, list) or any(not isinstance(row, dict) for row in results):
                raise ServiceError("外部搜索返回的资料格式无法核对。")
            rows = [{"标题": row.get("title") or "未提供标题", "站点": row.get("site_name"),
                     "发布日期": row.get("date"), "链接": row["url"],
                     "摘要": row.get("summary") or row.get("snippet") or ""}
                    for row in results if public_url(row.get("url"))]
            note = "外部搜索摘要，非本站或 Tushare 数据；关键结论可继续 read_web 核对原文。发布日期缺失时不推断。"
            scope = query
        else:
            url = args["url"]
            if not public_url(url):
                raise ValueError("请提供不含账户密码的完整 HTTP 或 HTTPS 网页链接。")
            data = self.request("fetch", {"url": url})
            content = data.get("content")
            if not isinstance(content, str):
                raise ServiceError("外部网页未返回可读取的正文。")
            start = args.get("start", 0)
            end = min(start + 12000, len(content))
            excerpt = content[start:end]
            rows = [{"标题": data.get("title") or "未提供标题", "链接": url, "正文": excerpt}] if excerpt else []
            note = f"外部网页原文第 {min(start, len(content))} 至 {end} 字符，共 {len(content)} 字符。"
            if end < len(content):
                note += f" 还有后文，可用 read_web 的 start={end} 继续读取。"
            scope = url
        return {"source": "外部公开资料（DeepSeek）", "endpoint": name, "scope": scope,
                "rows": rows, "note": note + " 检索时间：" + stamp}
