"""Verify the public research navigation, rule storage handshake and lazy history export."""
import csv
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from xuheng.archive import Archive
from xuheng.persistence import roster, transferable
from xuheng.ui_research import history_csv, strategy_run

directory = Path(os.environ.get("XUHENG_DATA_DIR", root/".private/database")).resolve()
os.environ.update(XUHENG_PUBLIC_COURSE="1", XUHENG_CLOUD_ARCHIVE="", XUHENG_DATA_DIR=str(directory),
                  XUHENG_GITHUB_REPO="", XUHENG_GITHUB_TAG="", XUHENG_ARCHIVE_BASE="",
                  XUHENG_ARCHIVE_TOKEN="", TUSHARE_TOKEN="offline-test")
patch("requests.sessions.Session.request", side_effect=AssertionError("offline UI made a network request")).start()
store = Archive(directory)


def open_app(**params):
    app = AppTest.from_file(str(root/"streamlit_app.py"), default_timeout=120)
    app.query_params.update(params)
    return clean(app.run())


def clean(app):
    assert not app.exception, [err.value for err in app.exception]
    return app


def click(app, key):
    return clean(app.button(key=key).click().run())


def send_widget(app, element, field, value):
    # AppTest exposes native frames and custom components as read-only elements.
    # Send the same widget value that a browser sends on a row click or storage reply.
    states = app._tree.get_widget_states()
    widget = next((w for w in states.widgets if w.id==element.proto.id), None)
    if widget is None:
        widget = states.widgets.add(id=element.proto.id)
    setattr(widget, field, json.dumps(value))
    return clean(app._run(states))


def click_row(app, key, row):
    element=next(item for item in app.dataframe if item.proto.id.endswith("-"+key))
    return send_widget(app,element,"string_value",{"selection":{"rows":[row],"columns":[],"cells":[]}})


def storage_reply(app, rules):
    element=next(item for item in app.get("component_instance") if item.proto.id.endswith("-factor_rule_storage"))
    return send_widget(app,element,"json_value",{"sid":app.session_state["_filter_sid"],"id":"refresh",
                       "rules":rules,"applied":[],"storageError":False})


app = open_app(course="legacy-placeholder", tracking="keep")
assert app.selectbox(key="cfg_overview-range").value=="126"
click_row(app,"overview_indices",2)
assert app.radio(key="cfg_nav").value=="indices" and app.selectbox(key="cfg_index_code").value=="000300.SH"
assert app.query_params["tracking"]==["keep"] and app.query_params["course"]==["legacy-placeholder"]
assert app.query_params["symbol"]==["000300.SH"]
assert app.selectbox(key="cfg_index_comp000300.SH").value=="000905.SH"

if "835185.BJ" in store.snapshot.get("aliases",{}):
    app = open_app(page="stocks",symbol="835185.BJ")
    assert app.selectbox(key="cfg_stock_code").value=="920185.BJ"
app = open_app(page="stocks",symbol="600000.SH")
clean(app.selectbox(key="cfg_stock_-range").set_value("all").run())
assert not app.get("download_button")
clean(app.toggle(key="cfg_stock_show_history").set_value(True).run())
assert app.get("download_button")
bars=store.series("600000.SH")["bars"]
rows=list(csv.DictReader(io.StringIO(history_csv(store,"600000.SH",bars[0][0],bars[-1][0]).decode("utf-8-sig"))))
assert len(rows)==len(bars) and float(rows[0]["收盘"])==bars[0][4] and float(rows[-1]["收盘"])==bars[-1][4]
click(app,"show_data_details")
assert any(item.value=="数据说明" for item in app.title)
clean(app.text_input(key="cfg_covquery").set_value("000001.SZ").run())
click_row(app,"coverage_rows",0)
assert app.query_params["symbol"]==["000001.SZ"] and app.selectbox(key="cfg_stock_code").value=="000001.SZ"

app=open_app(page="factors")
clean(app.selectbox(key="cfg_facv").set_value("SZ").run())
clean(app.text_input(key="factor_rule_name").set_value("深市因子").run())
click(app,"save_factor_rule")
clean(app.selectbox(key="cfg_fack").set_value("pb").run())
clean(app.text_input(key="factor_rule_name").set_value("深市因子").run())
click(app,"save_factor_rule")
rules=app.session_state["_factor_rules"]
assert list(rules)==["深市因子"] and rules["深市因子"]["factor"]=="pb"
app=open_app(page="factors")
storage_reply(app,[{"name":name,**values} for name,values in rules.items()])
click(app,"apply_factor_rule")
assert app.selectbox(key="cfg_fack").value=="pb" and app.selectbox(key="cfg_facv").value=="SZ"
click(app,"delete_factor_rule")
assert not app.session_state["_factor_rules"]
click_row(app,"factor_result_rows",0)
assert app.radio(key="cfg_nav").value=="stocks" and app.query_params["symbol"][0].endswith(".SZ")

strategy_run.cache_clear()
app=open_app(page="strategies")
assert "strategy_output" in app.session_state and strategy_run.cache_info().misses==1
if not store.manifest["sample"] and store.day=="20261113":
    assert [m.value for m in app.metric][:4]==["-94.88%","-96.06%","98.80%","319"]
clean(app.run())
assert strategy_run.cache_info().misses==1
clean(app.number_input(key="cfg_stratcount").set_value(13).run())
assert "strategy_output" not in app.session_state and strategy_run.cache_info().misses==1
click(app,"strategy_full_range")
assert "strategy_output" in app.session_state and strategy_run.cache_info().misses==2
assert roster(store,[["600000.SH",32.123456]])==[("600000.SH",32.123456)]
assert transferable(store,"cfg_range_rankweights","30,20,10",True)=="30,20,10"
assert transferable(store,"cfg_study_candidatesManual",3,True)==3
assert transferable(store,"cfg_study_1_daysmodel",17,True)==17
print("PASS: public routes and aliases, selectable security rows, full-history CSV, rule CRUD and browser restore, strategy auto-run and explicit reruns, six-decimal weights.")
