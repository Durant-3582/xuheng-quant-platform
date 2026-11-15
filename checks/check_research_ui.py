"""Check the data contracts used by the security charts, lookup dialog and factor table."""
import os
from pathlib import Path
import sys
from unittest.mock import patch

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from xuheng.archive import Archive
from xuheng.desk_api import dispatch,SnapshotChanged

store=Archive(os.environ.get("XUHENG_DATA_DIR",root/".private/walkthrough/database"))
def query(path):
    return dispatch(store,path,None,b"offline-test")

with patch("requests.sessions.Session.request",side_effect=AssertionError("unexpected network request")):
    workspace=query("/api/workspace")
    assert workspace["rows"]==store.snapshot["items"] and workspace["progress"]["bars"]==store.manifest["bars"]
    for code in ("000300.SH","600000.SH"):
        chart=query("/api/series?symbol="+code)
        assert tuple(chart["fields"])==("day","open","high","low","close","pre_close","pct","volume","amount")
        assert chart["rows"]==store.series(code)["bars"]
        start,end=chart["rows"][0],chart["rows"][-1]
        cmp=query("/api/series?symbol="+code+"&days="+start[0]+","+end[0]+"&quoteStart="+start[0])
        assert cmp["closes"]==[[start[0],start[1]],[end[0],end[4]]]
    for old,new in [(a,b) for a,b in workspace["aliases"].items() if b in store.catalog][:2]:
        assert query("/api/series?symbol="+old)["rows"]==store.series(new)["bars"]
    assert query("/api/coverage?kind=stock&q=600000")["rows"][0]["code"]=="600000.SH"
    assert not query("/api/coverage?q=doesnotexist")["rows"]
    assert query("/api/workspace?view=factors")["factors"]["groups"]==store.bands["groups"]
    for model in ("vol","mom"):
        sim=query("/api/strategy?factor="+model+"&from=20240101&to=20241231")["sim"]
        assert sim["logs"] and sim["curve"] and all(r["signal"]<r["entry"]<=r["end"] for r in sim["logs"])
    try:
        query("/api/series?symbol=600000.SH&asOf=19990101")
    except SnapshotChanged:
        pass
    else:
        raise AssertionError("stale release unexpectedly accepted")
print("PASS: catalogue, stocks and indices, full-history chart and CSV columns, benchmark openings, coverage, factor groups and ledger.")
