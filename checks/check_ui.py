"""Exercise the deployed Streamlit entry, its browser message bridge and page URLs offline."""
import base64
import gzip
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
directory=os.environ.get("XUHENG_DATA_DIR",str(root/".private/walkthrough/database"))
os.environ.update(XUHENG_DATA_DIR=directory,XUHENG_PUBLIC_COURSE="1",XUHENG_CLOUD_ARCHIVE="0",TUSHARE_TOKEN="offline-test")
app=AppTest.from_file(str(root/"streamlit_app.py"),default_timeout=45)
app.query_params={"page":["stocks"],"symbol":["600000.SH"],"tracking":["preserve-me"]}
sequence=0


def browser(path, route, body=None, compress=False):
    global sequence
    sequence+=1
    element=app.get("component_instance")[0]
    states=app._tree.get_widget_states()
    widget=next((item for item in states.widgets if item.id==element.proto.id),None)
    if widget is None:
        widget=states.widgets.add(id=element.proto.id)
    widget.json_value=json.dumps(dict(id=str(sequence),path=path,route=route,body=body,gzip=compress))
    app._run(states)
    assert not app.exception
    props=json.loads(app.get("component_instance")[0].proto.json_args)
    reply=props["reply"]
    assert reply["id"]==str(sequence) and "error" not in reply,reply.get("error")
    return json.loads(gzip.decompress(base64.b64decode(reply["gz"]))) if "gz" in reply else reply["data"]


with patch("requests.sessions.Session.request",side_effect=AssertionError("unexpected network request")):
    app.run()
    assert not app.exception
    props=json.loads(app.get("component_instance")[0].proto.json_args)
    assert props["initialRoute"]=="stocks/600000.SH"
    assert "news_plotly" in props["newsPlots"]
    day=props["version"]["day"]
    password=secrets.token_urlsafe(18)
    with patch.dict(os.environ,{"AI_CHAT_PASSWORD":password,"DEEPSEEK_API_KEY":"offline-test"}):
        locked=browser("/api/assistant","assistant",{"action":"history"})
        assert locked["access"]=="locked" and app.query_params["page"]==["assistant"]
        assert browser("/api/assistant","assistant",{"action":"ask","question":"绕过界面","turnId":"unlocked-spoof","access":"unlocked"})["access"]=="locked"
        retry=browser("/api/assistant","assistant",{"action":"unlock","proof":"0"*64})
        proof=hmac.digest(password.encode(),("xuheng-ai:"+retry["challenge"]).encode(),"sha256").hex()
        assert browser("/api/assistant","assistant",{"action":"unlock","proof":proof})["ready"]
        browser("/route","overview")
        assert browser("/api/assistant","assistant",{"action":"history"})["access"]=="unlocked"
        assert browser("/api/assistant","assistant",{"action":"lock"})["access"]=="locked"
        assert browser("/api/assistant","assistant",{"action":"unlock","proof":proof})["access"]=="locked"
    assert browser("/api/workspace","overview",compress=True)["day"]==day
    with patch("xuheng.news_store.cache.get", return_value={"format":1,"articles":[]}) as get_news:
        assert browser("/api/news","news",{"refresh":True})["format"] == 1
        assert get_news.call_args.kwargs["refresh"] is True and app.query_params["page"] == ["news"]
    assert browser("/api/series?symbol=000300.SH","indices/000300.SH",compress=True)["rows"]
    assert app.query_params["symbol"]==["000300.SH"]
    assert browser("/api/workspace?view=factors","factors")["factors"]["latest"]
    assert browser("/api/strategy?factor=vol&from=20240101&to=20241231","backtest")["sim"]["curve"]
    assert app.query_params["page"]==["strategies"]
    rule=dict(model="mom",count=5,weighting="equal",interval=1,bench="000300.SH",fee=10,trainFrom="20240101",trainTo="20241231")
    assert browser("/api/portfolio","portfolio",{"action":"range","rules":rule})["result"]["main"]["curve"]
    browser("/route","portfolio/research")
    assert app.query_params["tab"]==["research"] and app.query_params["tracking"]==["preserve-me"]
    browser("/route","overview")
    assert "page" not in app.query_params and "symbol" not in app.query_params and "tab" not in app.query_params
from xuheng import desk_host
with tempfile.TemporaryDirectory() as temp:
    assets = Path(temp)
    script = assets / "view.js"
    script.write_text("version A")
    with patch.object(desk_host, "declare_component", side_effect=lambda name, path: name) as register:
        first = desk_host.current_desk(assets)
        assert desk_host.current_desk(assets) == first and register.call_count == 1
        script.write_text("version B")
        assert desk_host.current_desk(assets) != first and register.call_count == 2
print("PASS: desk routes, news refresh, AI access, gzip, market data, portfolios, deep links, and hot asset deployments.")
