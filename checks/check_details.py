"""Offline disclosure parity and supplementary-cache checks."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xuheng.archive import ArchiveError
from xuheng.details import extra


stock, index = "600519.SH", "000300.SH"
as_of = "20251130"
def view(path):
    return SimpleNamespace(root=Path(path), day="20261113",
        catalog={stock:[stock, "贵州茅台", "stock"], index:[index, "沪深300", "index"]},
        snapshot={"aliases":{}}, manifest={"files":{"catalog":{"sha256":"a"*64}}},
        json=lambda key, optional: None)

def disclosure(period, announced, eps=1.):
    return dict(ts_code=stock, end_date=period, ann_date=announced, eps=eps, roe="9.25",
                grossprofit_margin=None, debt_to_assets="")

with TemporaryDirectory() as directory:
    archive = view(directory)
    calls = []
    def fetch(api, params, fields, token):
        calls.append(api)
        assert params["end_date"] == as_of
        if api == "index_weight":
            assert params["index_code"] == index
            return []
        assert params == {"ts_code":stock,"start_date":"20221130","end_date":as_of}
        rows = [disclosure(f"2024{i:02d}01", f"2024{i:02d}20") for i in range(1,11)]
        rows += [disclosure("20240101","20251128","2.5"), disclosure("20250701","20251201"),
                 disclosure("20261231","20251129"), dict(disclosure("20241101","20251129"),ts_code="000001.SZ")]
        return rows
    def forbidden(*_):
        raise AssertionError("unexpected provider call after successful lookup")
    result = extra(archive, "financial", stock, as_of, "offline-marker", fetch=fetch)
    assert [row[0] for row in result] == ["20240101", *(f"2024{i:02d}01" for i in range(10,3,-1))]
    assert result[0] == ["20240101","20251128",2.5,9.25,None,None]
    assert extra(view(directory),"financial",stock,as_of,None,fetch=forbidden) == result
    empty = extra(archive,"members",index,as_of,"offline-marker",fetch=fetch)
    assert empty == {"day":None,"items":[]}
    assert extra(view(directory),"members",index,as_of,None,fetch=forbidden) == empty
    assert calls == ["fina_indicator","index_weight"]
    for p in Path(directory).rglob("*.json"):
        assert "offline-marker" not in p.read_text()
    bad_day="20250831"
    def denied(*_):
        raise ArchiveError("denied")
    try:
        extra(archive,"financial",stock,bad_day,None,fetch=denied)
    except ArchiveError:
        pass
    else:
        raise AssertionError("provider failure was swallowed")
    retried=extra(archive,"financial",stock,bad_day,None,fetch=lambda *args:[disclosure("20250630","20250805")])
    assert retried[0][:2]==["20250630","20250805"]
    assert result != retried
    try:
        extra(archive,"financial",index,as_of,None,fetch=forbidden)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted the wrong security kind")
print("PASS: announcement order; restatement; cutoff; period deduplication; numeric normalization; disk cache; retry")
