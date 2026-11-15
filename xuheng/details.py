import json
import math
import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import requests

from .archive import ArchiveError, CODE


def tushare(api, params, fields, token):
    if not token:
        raise ArchiveError("本期归档没有这项记录，服务器尚未配置用于补查的 Tushare 权限。")
    try:
        with requests.post("https://api.tushare.pro", json={"api_name": api, "token": token,
                "params": params, "fields": ",".join(fields)}, timeout=(5,20), allow_redirects=False) as response:
            response.raise_for_status()
            obj = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ArchiveError("暂时无法连接 Tushare，请稍后重试。") from exc
    if obj.get("code") != 0:
        raise ArchiveError("Tushare 未返回可用数据，请检查该接口的权限或调用频率。")
    data = obj.get("data") or {}
    if set(data.get("fields", [])) != set(fields) or not isinstance(data.get("items"), list):
        raise ArchiveError("Tushare 返回的列与请求不一致。")
    try:
        return [dict(zip(data["fields"], row, strict=True)) for row in data["items"]]
    except (TypeError, ValueError) as exc:
        raise ArchiveError("Tushare 返回的数据列不完整。") from exc


def numeric(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def reported(rows, when):
    known = (r for r in rows if r[0] and r[1] and r[0] <= when and r[1] <= when)
    seen, latest = set(), []
    for row in sorted(known, key=lambda r: r[1], reverse=True):
        if row[0] in seen:
            continue
        latest.append([row[0], row[1], *(numeric(v) for v in row[2:])])
        seen.add(row[0])
        if len(latest) == 8:
            break
    return latest


def finance(code, when, token, fetch):
    fields = "ts_code ann_date end_date roe eps grossprofit_margin debt_to_assets".split()
    start = str(int(when[:4]) - 3) + when[4:]
    raw = fetch("fina_indicator", {"ts_code": code, "start_date": start, "end_date": when}, fields, token)
    cols = ("end_date", "ann_date", "eps", "roe", "grossprofit_margin", "debt_to_assets")
    return reported(([r[k] for k in cols] for r in raw if r["ts_code"] == code), when)


def members(store, code, when, token, fetch):
    start = (datetime.strptime(when, "%Y%m%d") - timedelta(days=95)).strftime("%Y%m%d")
    fields = "index_code con_code trade_date weight".split()
    latest, by_code, seen = "", {}, set()
    for i in range(90):
        batch = fetch("index_weight", {"index_code": code, "start_date": start, "end_date": when,
                                       "limit": 1000, "offset": 1000*i}, fields, token)
        marker = tuple((r["trade_date"], r["con_code"]) for r in batch)
        if batch and marker in seen:
            raise ArchiveError("指数成分分页重复，请稍后再试。")
        seen.add(marker)
        for r in batch:
            d, c = r["trade_date"], r["con_code"]
            if r["index_code"] != code or not (start <= d <= when) or not CODE.fullmatch(c):
                raise ArchiveError("成分的代码或日期与请求不一致。")
            if d > latest:
                latest, by_code = d, {}
            if d == latest:
                c = store.snapshot["aliases"].get(c, c)
                item = store.catalog.get(c)
                by_code[c] = [c, item[1] if item and item[2] == "stock" else None, numeric(r["weight"])]
        if len(batch) < 1000:
            break
    else:
        raise ArchiveError("未能读取全部指数成分。")
    return {"day": latest or None, "items": sorted(by_code.values(), key=lambda row: row[2] or 0, reverse=True)}


def extra(s, kind, code, when, token, *, fetch=tushare):
    if kind not in ("financial", "members"):
        raise ValueError("未知的查询类别。")
    item = s.catalog.get(code)
    try:
        day = datetime.strptime(when, "%Y%m%d").strftime("%Y%m%d")
    except (ValueError, TypeError):
        day = ""
    if (not item or item[2] != ("stock" if kind == "financial" else "index") or not CODE.fullmatch(code)
            or not day or day != when or not "20000101" <= day <= s.day):
        raise ValueError("证券或查询日期无效。")
    key = f"{kind}/{code}/{when}"
    cached = s.json(key, optional=True)
    if cached is not None:
        return reported(cached, when) if kind == "financial" else cached

    # Supplementary records belong to the catalogue revision that supplied symbols and names.
    # The archive writer also calls this function with an in-memory catalogue and saves its own files.
    version = getattr(s, "manifest", {}).get("files", {}).get("catalog", {}).get("sha256", "")
    path = None
    if hasattr(s, "root") and re.fullmatch("[0-9a-f]{64}", version):
        path = Path(s.root) / ".lookup-cache" / version / (key + ".json")
        try:
            return json.loads(path.read_bytes())
        except (OSError, ValueError):
            pass
    memory = getattr(s, "_lookup_results", {})
    if key in memory:
        return memory[key]
    result = finance(code, when, token, fetch) if kind == "financial" else members(s, code, when, token, fetch)
    if path:
        tmp = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
                tmp = Path(f.name)
                json.dump(result, f, ensure_ascii=False, allow_nan=False)
            os.replace(tmp, path)
            return result
        except OSError:
            pass
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
    if len(memory) >= 512:
        memory.pop(next(iter(memory)))
    memory[key] = result
    s._lookup_results = memory
    return result
