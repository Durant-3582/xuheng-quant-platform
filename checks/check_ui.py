"""Exercise the Streamlit form, including reruns and lock invalidation, on real private data."""
from datetime import date
from pathlib import Path
import os,sys,time
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
os.chdir(root)
app=root/"streamlit_app.py"
os.environ['XUHENG_PUBLIC_COURSE']='1'
if os.getenv('XUHENG_OFFLINE_TEST') == '1':
    def no_network(*args,**kwargs):
        raise AssertionError('断网验收期间出现外部请求。')
    patch('requests.sessions.Session.request', no_network).start()
a=AppTest.from_file(str(app),default_timeout=90)
def clean():
    assert not a.exception,[e.message for e in a.exception]
def launch():
    a.run();clean()
def click(caption):
    next(x for x in a.button if x.label==caption).click();launch()
def select(key,value):
    a.selectbox(key=key).set_value(value);launch()
def num(key,value):
    a.number_input(key=key).set_value(value);launch()
def switch(page):
    a.radio(key="cfg_nav").set_value(page);launch()
def out(key):return a.session_state[key]
def tab(value):
    a.radio(key="cfg_portfolio_tab").set_value(value);launch()
def setdays(mapping):
    for key,value in mapping.items():a.date_input(key=key).set_value(date.fromisoformat(value))
    launch()
def has(key):
    try:a.session_state[key];return True
    except KeyError:return False
def buttons():return {x.label for x in a.button}

a.query_params["page"]="portfolio"
launch();assert a.radio(key="cfg_portfolio_tab").value=="区间回测"
click("运行区间回测");assert len(out("range_output")["months"])>0
select("cfg_range_model","manual")
assert a.selectbox(key="cfg_range_freqcustom").value=="hold" and not has("range_output")
assert not a.multiselect(key="cfg_range_stocks").value
click("载入三只股票示例")
names=a.multiselect(key="cfg_range_stocks")
names.set_value(["600519.SH","000001.SZ","300750.SZ","600036.SH"]);launch()
assert a.number_input(key="cfg_range_weight_600036.SH").value==0
num("cfg_range_weight_600519.SH",35.);num("cfg_range_weight_600036.SH",5.)
click("等权分配");assert [a.number_input(key="cfg_range_weight_"+c).value for c in a.multiselect(key="cfg_range_stocks").value]==[25.]*4
a.multiselect(key="cfg_range_stocks").set_value(["600519.SH","000001.SZ","300750.SZ"]);launch()
select("cfg_range_manw","tb")
setdays({"cfg_range_a":"2024-01-01","cfg_range_b":"2024-12-31"})
click("运行区间回测")
hold=out("range_output");assert sum(m["rebalance"] for m in hold["months"])==1 and abs(hold["main"]["total"]+7.96979976)<1e-7
select("cfg_range_freqcustom","months");click("运行区间回测")
monthly=out("range_output");assert sum(m["rebalance"] for m in monthly["months"])==12 and abs(monthly["main"]["total"]-36.59630072)<1e-7
select("cfg_range_freqcustom","days");num("cfg_range_days",17);click("运行区间回测")
assert sum(x["rebalance"] for x in out("range_output")["months"])==15
tab("参数比较与样本外检验")
assert "运行样本外检验" not in buttons()
setdays({"cfg_study_trainA":"2023-01-01","cfg_study_trainB":"2023-12-31","cfg_study_testA":"2024-01-01","cfg_study_testB":"2024-12-31"})
click("比较样本内表现");assert len(out("study_train")[0])==2
num("cfg_study_0_count",7);assert not has("study_train") and "锁定样本内胜出方案" not in buttons()
click("比较样本内表现");click("锁定样本内胜出方案");assert a.number_input(key="cfg_study_0_count").disabled and not has("study_test")
switch("stocks")
assert a.selectbox(key="cfg_stock_code").value=="600519.SH"
assert any(m.label=="120 日滚动 Beta" for m in a.metric)
click("查看财报指标");reports=out("stock_last_extra")[1]
assert reports and all(r[0]<=r[1]<=out("stock_last_extra")[0][2] for r in reports)
select("cfg_stock_-range","custom");num("cfg_stock_-days",37)
switch("indices")
click("查询最近一期成分");members=out("index_last_extra")[1]
assert len(members["items"])==300 and abs(sum(r[2] for r in members["items"])-100)<0.1
if not os.getenv('XUHENG_SAMPLE_TEST'):
    select("cfg_index_code","801001.SI");assert any("权限受限" in x.value for x in a.info)
switch("overview");assert any("当日有报价"==m.label for m in a.metric)
switch("factors");select("cfg_fack","vol");select("cfg_facv","BJ");click("用此规则做策略回测")
assert a.radio(key="cfg_nav").value=="strategies" and a.selectbox(key="cfg_stratmodel").value=="vol" and a.selectbox(key="cfg_stratvenue").value=="BJ"
setdays({"cfg_stratstartvolBJ":"2024-01-01","cfg_stratend":"2024-12-31"});click("运行策略回测");assert out("strategy_output")["months"]
switch("portfolio")
assert a.radio(key="cfg_portfolio_tab").value=="参数比较与样本外检验" and not has("study_test")
click("运行样本外检验");assert out("study_test")["months"][0]["entry"]>="20240101"
click("查看胜出方案的样本内明细");assert out("study_review")["months"][-1]["end"]<"20240101"
assert {s.value for s in a.subheader}>={"样本内回测结果","样本外检验结果"}
winner,win,criterion,release,index=out("frozen_study")
assert winner==(out("study_sig")[1][index]) and win==out("study_sig")[2]
click("解锁并重新比较");assert not has("study_test") and not has("study_train")
assert any("已查看过" in x.value for x in a.info)
setdays({"cfg_study_testA":"2023-12-01"})
click("比较样本内表现");assert a.error and "早于" in a.error[0].value and not has("study_train")
tab("区间回测");assert a.selectbox(key="cfg_range_freqcustom").value=="days" and a.number_input(key="cfg_range_days").value==17
print("PASS: access, all six pages, custom periods, manual weights, TB hold/monthly, comparison, change invalidation, lock, navigation retention, independent test, unlock and overlapping intervals.")
