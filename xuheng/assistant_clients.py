"""Server-side clients for the course assistant. Provider credentials stay on their own origin."""
import json
from urllib.parse import quote

import requests


MODEL = "deepseek-flash"
PROTOCOL = "2025-06-18"


class ServiceError(ValueError):
    pass


def rpc_message(response, identifier):
    if "text/event-stream" in response.headers.get("Content-Type", ""):
        parts = []
        size = 0
        for line in response.iter_lines():
            size += len(line)
            if size > 512_000:
                break
            if line.startswith(b"data:"):
                parts.append(line[5:].lstrip())
            if not line and parts:
                message = json.loads(b"\n".join(parts))
                if message.get("id") == identifier:
                    return message
                parts.clear()
    else:
        message = response.json()
        if isinstance(message, dict) and message.get("id") == identifier:
            return message
    raise ServiceError("Tushare MCP 未返回对应查询的结果，请重试。")


class TushareMCP:
    def __init__(self, token):
        self.token = token
        self.session = requests.Session()
        self.headers = {"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream"}
        self.sequence = 0
        self.started = False

    def close(self):
        self.session.close()

    def request(self, method, params=None, notify=False):
        if not self.token:
            raise ServiceError("网站尚未配置 Tushare 数据权限。")
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notify:
            self.sequence += 1
            payload["id"] = self.sequence
        url = "https://api.tushare.pro/mcp/token=" + quote(self.token, safe="")
        try:
            with self.session.post(url, headers=self.headers, json=payload, stream=True,
                                   timeout=(5, 15), allow_redirects=False) as response:
                if response.status_code in (401, 403):
                    raise ServiceError("Tushare MCP 拒绝了本次访问，请检查网站的数据权限。")
                if response.status_code == 429:
                    raise ServiceError("Tushare MCP 当前调用过于频繁，请稍后再试。")
                if not 200 <= response.status_code < 300:
                    raise ServiceError("Tushare MCP 暂时未能完成查询，请重试。")
                if notify:
                    return {}
                if method == "initialize" and response.headers.get("Mcp-Session-Id"):
                    self.headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
                message = rpc_message(response, self.sequence)
                if "error" in message or not isinstance(message.get("result"), dict):
                    raise ServiceError("Tushare MCP 未接受本次查询。")
                return message["result"]
        except (requests.RequestException, json.JSONDecodeError, UnicodeError):
            raise ServiceError("未能读取 Tushare MCP 的回应，请稍后重试。") from None

    def call(self, name, arguments):
        if not self.started:
            hello = self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                                "clientInfo": {"name": "xuheng-research", "version": "1.0"}})
            version = hello.get("protocolVersion")
            if version not in (PROTOCOL, "2025-03-26", "2025-11-25"):
                raise ServiceError("Tushare MCP 使用了无法识别的协议版本。")
            self.headers["MCP-Protocol-Version"] = version
            self.request("notifications/initialized", notify=True)
            self.started = True
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise ServiceError("Tushare MCP 返回查询错误，请检查该数据接口权限或稍后重试。")
        try:
            rows = json.loads(next(item["text"] for item in result["content"] if item.get("type") == "text"))
            if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
                return rows
        except (KeyError, StopIteration, TypeError, ValueError):
            pass
        raise ServiceError("Tushare MCP 返回的数据格式无法核对。")


def deepseek(key, messages, tools=(), choice="auto"):
    payload = {"model": MODEL, "messages": messages, "thinking": {"type": "disabled"},
               "temperature": 0, "max_tokens": 850, "stream": False}
    if tools:
        payload.update(tools=tools, tool_choice=choice)
    try:
        with requests.post("https://api.deepseek.com/chat/completions", json=payload,
                           headers={"Authorization": "Bearer " + key}, timeout=(6, 45),
                           allow_redirects=False) as response:
            if response.status_code in (401, 403):
                raise ServiceError("DeepSeek 未接受网站的 API 密钥，请维护者检查 Secrets。")
            if response.status_code == 402:
                raise ServiceError("DeepSeek API 账户余额不足。")
            if response.status_code == 429:
                raise ServiceError("DeepSeek 当前调用过于频繁，请稍后重试。")
            if response.status_code != 200:
                raise ServiceError("DeepSeek 本次请求未成功（HTTP %d）。" % response.status_code)
            result = response.json()["choices"][0]
            if result.get("finish_reason") not in ("stop", "tool_calls"):
                raise ServiceError("DeepSeek 的回答未完成，请缩短问题后重试。")
            return result["message"]
    except (requests.RequestException, KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise ServiceError("未完整收到 DeepSeek 的回应，请重试。") from None
