"""Build a compact, reproducible sentiment sample from Eastmoney's public news feed."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import unescape
import re
import time

import requests


CHINA = timezone(timedelta(hours=8))
LIMIT = 200
FEED = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
ARTICLE_ID = re.compile(r"[0-9]{12,24}")
STOCK_CODE = re.compile(r"(?<![0-9])[0-9]{6}(?![0-9])")
TAG = re.compile(r"([01])\.([0-9]{6})")

# Weighted indicators and cutoffs follow the reference news page. Each distinct
# keyword counts once, including when the same text appears in title and summary.
POSITIVE = {
    2.0: "利好 降准 降息 超预期 创新高", 1.5: "增持 回购 减税 涨停",
    1.2: "上涨 回暖 复苏 提振 中标 净流入 获批 新高",
    1.0: "增长 突破 盈利 放宽 补贴 扩产 上调 走强",
    0.8: "改善 支持 订单 签约 升温",
}
NEGATIVE = {
    2.0: "利空 暴跌 违约 退市 加息 低于预期 创新低 爆雷",
    1.5: "亏损 减持 处罚 衰退 跌停",
    1.2: "下跌 调查 收紧 裁员 停牌 净流出",
    1.0: "下滑 债务 下调 走弱 缩水",
    0.8: "承压 回落 解禁 问询", 0.6: "风险",
}
WORDS = [(word, sign * weight) for groups, sign in ((POSITIVE, 1), (NEGATIVE, -1))
         for weight, group in groups.items() for word in group.split()]
SECTOR_TERMS = {
    "农林牧渔": "农业 养殖 猪价 种业 饲料", "基础化工": "化工 化肥 农药 树脂 纯碱",
    "钢铁": "钢铁 钢材 铁矿石 螺纹钢", "有色金属": "有色 铜 铝 锂 黄金 稀土",
    "电子": "芯片 半导体 电子 PCB 面板 消费电子", "汽车": "汽车 新能源车 整车 零部件 智能驾驶",
    "家用电器": "家电 空调 冰箱 厨电", "食品饮料": "白酒 食品 饮料 乳业 调味品",
    "纺织服饰": "纺织 服装 鞋帽", "轻工制造": "造纸 包装 家居 轻工",
    "医药生物": "医药 创新药 医疗 疫苗 CXO 器械", "公用事业": "电力 燃气 水务 公用事业",
    "交通运输": "航运 航空 物流 港口 铁路", "房地产": "房地产 地产 楼市 房企",
    "商贸零售": "零售 电商 商超 免税", "社会服务": "旅游 酒店 餐饮 教育 服务消费",
    "银行": "银行 信贷 存款 净息差", "非银金融": "券商 保险 证券 基金 信托",
    "建筑材料": "建材 水泥 玻璃 玻纤", "建筑装饰": "建筑 基建 工程 装饰",
    "电力设备": "光伏 风电 储能 电池 电网", "机械设备": "机械 机器人 工程机械 机床",
    "国防军工": "军工 国防 航天 航空发动机", "计算机": "计算机 软件 云计算 信创 算力",
    "传媒": "传媒 游戏 影视 广告 出版", "通信": "通信 5G 光模块 运营商",
    "煤炭": "煤炭 焦煤 动力煤", "石油石化": "石油 原油 石化 天然气",
    "环保": "环保 污水 固废 碳中和", "美容护理": "美容 化妆品 护理",
}
SECTORS = {name: words.split() for name, words in SECTOR_TERMS.items()}


class NewsError(ValueError):
    pass


def sentiment(text):
    weights = [weight for word, weight in WORDS if word in text]
    return round(50 + 50 * sum(weights) / (sum(map(abs, weights)) + 1.5), 6)


def from_catalog(store):
    """Map known A-share codes and names. Exclude index codes with the same six digits."""
    names = defaultdict(set)
    numbers = defaultdict(set)
    for code, row in store.catalog.items():
        if row[2] == "stock":
            names[row[1].upper().replace(" ", "")].add(code)
            numbers[code.split(".")[0]].add(code)
    for old, current in store.snapshot.get("aliases", {}).items():
        if current in store.catalog and store.catalog[current][2] == "stock":
            numbers[old.split(".")[0]].add(current)
    return names, numbers


def mentions(text, tags, directory):
    names, numbers = directory
    upper = text.upper().replace(" ", "")
    matched = set()
    for name, codes in names.items():
        if name and name in upper:
            matched.update(codes)
    # A six-digit literal that is explicitly qualified as an index or a different
    # exchange must not accidentally match an A share on another exchange.
    for match in STOCK_CODE.finditer(text):
        value = match.group()
        suffix = re.match(r"\.(SH|SZ|BJ)\b", text[match.end():], re.I)
        if suffix:
            matched.update(c for c in numbers.get(value, ()) if c.endswith("." + suffix[1].upper()))
        else:
            matched.update(numbers.get(value, ()))
    for tag in tags if isinstance(tags, list) else ():
        m = TAG.fullmatch(str(tag))
        if m:
            for code in numbers.get(m[2], ()):
                if (m[1] == "1") == code.endswith(".SH"):
                    matched.add(code)
    return sorted(matched)


def fetch(directory):
    params = {"client": "web", "biz": "web_724", "fastColumn": "102", "sortEnd": "",
              "pageSize": str(LIMIT), "req_trace": str(time.time_ns() // 1_000_000)}
    try:
        with requests.get(FEED, params=params, headers={"User-Agent": "Mozilla/5.0"},
                          timeout=(3, 8)) as response:
            response.raise_for_status()
            body = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise NewsError("暂时无法读取东方财富快讯。") from exc
    if not isinstance(body, dict) or str(body.get("code")) != "1" or not isinstance(body.get("data"), dict):
        raise NewsError("东方财富没有返回有效的快讯列表。")
    raw = body["data"].get("fastNewsList")
    if not isinstance(raw, list) or not raw:
        raise NewsError("东方财富本次没有返回快讯。")
    articles = {}
    for item in raw[:LIMIT]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("code", ""))
        title = item.get("title")
        stamp = item.get("showTime")
        if not ARTICLE_ID.fullmatch(key) or not isinstance(title, str) or not title.strip():
            continue
        try:
            published = datetime.strptime(stamp, DATE_FORMAT)
        except (TypeError, ValueError):
            continue
        title = unescape(title.strip())
        summary = item.get("summary") or ""
        text = (title + " " + unescape(summary if isinstance(summary, str) else ""))[:300]
        articles.setdefault(key, {"id": key, "time": published.strftime(DATE_FORMAT),
                                  "title": title, "score": sentiment(text),
                                  "sectors": [s for s, words in SECTORS.items() if any(w in text for w in words)],
                                  "stocks": mentions(text, item.get("stockList"), directory)})
    if not articles:
        raise NewsError("快讯缺少可核对的编号、标题或发布时间。")
    return {"format": 1, "checked": datetime.now(CHINA).strftime(DATE_FORMAT),
            "articles": sorted(articles.values(), key=lambda a: (a["time"], a["id"]), reverse=True)}
