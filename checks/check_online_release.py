"""Time the actual remote data service behind Streamlit; the browser is measured separately."""
from __future__ import annotations

import argparse
from collections import Counter
import hmac
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from time import perf_counter
import sys

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xuheng.archive import Archive
from xuheng.frames import Rules
from xuheng.packed_archive import ORIGIN, PackedArchive
from xuheng.portfolio import run


class Meter(PackedArchive):
    def __init__(self, *args):
        self.counters = Counter()
        self.meter = Lock()
        super().__init__(*args)

    def _download(self, *args, **kwargs):
        data = super()._download(*args, **kwargs)
        with self.meter:
            self.counters.update(requests=1, bytes=len(data))
        return data


def check(output):
    token = os.getenv("TUSHARE_TOKEN") or (ROOT / ".private/tushare-token").read_text().strip()
    scope = b"xuheng/market-read/v1/appgprj_6af9102ba4608191addb0f2e49174e36"
    reader = hmac.digest(token.strip().encode(), scope, "sha256").hex()
    with requests.get(ORIGIN + "/v1/current", headers={"X-Archive-Read": reader},
                      allow_redirects=False, timeout=(5, 20)) as reply:
        reply.raise_for_status()
        pointer = reply.json()
    local = Archive(ROOT / ".private/database")
    assert pointer["day"] == local.day and pointer["bars"] == local.manifest["bars"], "数据版本与本机不符"
    result = {"release": pointer, "data_service": [], "history": {}, "cases": {}}

    def measured(label, cb):
        before = dict(store.counters) if store is not None else {}
        started = perf_counter()
        ret = cb()
        archive = store if store is not None else ret
        result["data_service"].append({"operation": label, "seconds": round(perf_counter()-started, 3),
              **{k: archive.counters[k] - before.get(k, 0) for k in ("requests", "bytes")}})
        print(result["data_service"][-1], flush=True)
        return ret

    with TemporaryDirectory() as cache:
        store = None
        def home():
            current = Meter(cache, ORIGIN, pointer["index"], reader)
            current.prefetch(["snapshot", "coverage", "series/000300.SH"])
            assert current.snapshot["day"] == local.day and current.coverage == local.coverage
            return current
        store = measured("cold home archive", home)
        for code in ("600000.SH", "000001.SZ", "920185.BJ", "000001.SH", "000300.SH"):
            bars = measured(code, lambda: store.series(code)["bars"])
            assert bars == local.series(code)["bars"]
            result["history"][code] = [len(bars), bars[0][0], bars[-1][0], bars[-1][4]]
        cases = [
            ("whole market since 2000", Rules(count=30), "20000508", store.day),
            ("low PB control", Rules(model="pb",count=5,interval=3), "20210101","20221130"),
            ("custom 17 trading days", Rules(model="vol",cadence="days",interval=17,bench="000905.SH"),"20230801","20231231"),
            ("manual buy-and-hold TB", Rules(model="manual",cadence="hold",count=2,symbols=("000001.SZ","600519.SH"),
                    weighting="tb",bench="000905.SH"), "20240101","20241130")]
        for name,rule,start,end in cases:
            calc = lambda: run(store,rule,start,end)
            res = measured(name, calc)
            assert res == run(local,rule,start,end)
            result["cases"][name] = {"periods":len(res["months"]), "return_pct":res["main"]["total"],"drawdown_pct":res["main"]["dd"]}
            assert res == measured(name+" repeat",calc) and result["data_service"][-1]["requests"] == 0
    if output:
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path)
    check(parser.parse_args().output)
