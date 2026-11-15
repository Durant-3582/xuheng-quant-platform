"""Regress portfolio controls, winner selection, rule locking and held-out execution."""
import os
from pathlib import Path
import sys
from unittest.mock import patch

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from xuheng.archive import Archive
from xuheng.desk_api import dispatch

store=Archive(os.environ.get("XUHENG_DATA_DIR",root/".private/walkthrough/database"))
def call(action,**kwargs):
    return dispatch(store,"/api/portfolio",dict(action=action,**kwargs),b"offline-test")

def rejected(action,**kwargs):
    try:
        call(action,**kwargs)
    except ValueError:
        return
    raise AssertionError(action+" accepted invalid inputs")

base=dict(model="mom",count=3,interval=1,weighting="equal",fee=10,bench="000300.SH",trainFrom="20240101",trainTo="20241231")
with patch("requests.sessions.Session.request",side_effect=AssertionError("unexpected network request")):
    for model in ("mom","rev","pb","vol"):
        out=call("range",rules={**base,"model":model})["result"]
        assert out["main"]["curve"] and ("control" in out)==(model=="pb")
    roster=["600000.SH","000001.SZ"]
    assert all(c in store.catalog for c in roster)
    for weight in ("manual","equal","tb"):
        for cadence,period in (("hold",1),("days",17),("months",1)):
            r={**base,"model":"manual","symbols":roster,"count":2,"weighting":weight,
               "intervalUnit":cadence,"interval":period,"weights":[60.,30.] if weight=="manual" else []}
            ledger=call("range",rules=r)["result"]["months"]
            assert sum(row["rebalance"] for row in ledger)==(1 if cadence=="hold" else (len(ledger)+16)//17 if cadence=="days" else len(ledger))
    rejected("range",rules={**r,"weighting":"manual","weights":[70,40]})
    for criterion in ("return","drawdown","sharpe"):
        common={**base,"source":"factor","trainFrom":"20230101","trainTo":"20241231","testFrom":"20250101","testTo":"20251231"}
        candidates=[dict(model="mom",count=n,interval=1,weighting="equal") for n in (2,4)]
        plan=dict(common=common,candidates=candidates,criterion=criterion)
        ranked=call("compare",plan=plan)
        assert sorted(i["index"] for i in ranked["ranking"])==[0,1] and ranked["winner"]==ranked["ranking"][0]["index"]
        receipt=ranked["receipt"]
        rejected("test",token=receipt)
        token=call("lock",token=receipt)["token"]
        rejected("test",token=token,rules=base)
        rejected("test",token="bad signature")
        train=call("review",token=token);test=call("test",token=token)
        assert train["rules"]==test["rules"]==ranked["rules"]
        assert train["result"]["months"][-1]["end"]<test["result"]["months"][0]["entry"]
    rejected("compare",plan={**plan,"common":{**common,"testFrom":common["trainTo"]}})
print("PASS: four factors, TB, per-stock weights, holding frequencies, three criteria, valid signatures and separate windows.")
