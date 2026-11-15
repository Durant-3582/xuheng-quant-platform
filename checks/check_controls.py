"""Operate the remaining research controls using real archive records with all external responses blocked."""
from datetime import date
import math,os,sys
from pathlib import Path
from unittest.mock import patch

root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));os.chdir(root)
from streamlit.testing.v1 import AppTest
from xuheng.archive import Archive
from xuheng.frames import BENCHMARKS,MODELS
from xuheng.ui_research import MARKET_INDICES
from xuheng.research import codes

store=Archive(os.environ.get('XUHENG_DATA_DIR',root/'.private/walkthrough/database'))
os.environ['XUHENG_PUBLIC_COURSE']='1'
os.environ['XUHENG_DATA_DIR']=str(store.root.resolve())
def reject(*args,**kwargs):raise AssertionError('浏览器操作期间请求外部数据。')
patch('requests.sessions.Session.request',reject).start()
a=AppTest.from_file('streamlit_app.py',default_timeout=120)
checks=0
def rr():
    global checks
    a.run();assert not a.exception,[e.message for e in a.exception];checks+=1
def select(key,v):
    a.selectbox(key=key).set_value(v);rr()
def number(key,v):
    a.number_input(key=key).set_value(v);rr()
def nav(v):
    a.radio(key='cfg_nav').set_value(v);rr()
def click(n):
    next(b for b in a.button if b.label==n).click();rr()
def dates(k,v):
    a.date_input(key=k).set_value(date.fromisoformat(v))
def sub(k):return a.session_state[k]

rr()
select('cfg_covkind','stock');select('cfg_covstatus','empty')
a.text_input(key='cfg_covquery').input('不存在的证券');rr()
assert any('0 条' in v.value for v in a.caption)
for mode in ('60','126','252','all','custom'):select('cfg_overview-range',mode)
number('cfg_overview-days',1);assert a.get('plotly_chart')
nav('indices');select('cfg_indexscope','review')
a.text_input(key='cfg_indexquery').input('没有这样的指数');rr()
assert any('0 条' in c.value for c in a.caption)
select('cfg_index_comp000300.SH','000001.SH');select('cfg_index_-range','custom');number('cfg_index_-days',2)
assert not a.get('download_button')
a.toggle(key='cfg_index_show_history').set_value(True);rr()
assert len(a.get('plotly_chart'))==1 and len(a.get('download_button'))==1
nav('stocks');select('cfg_stock_code','600000.SH')
for bench in MARKET_INDICES:select('cfg_stock_betabench',bench)
assert any('Beta' in x.label for x in a.metric)
empty=next((v[0] for v in store.coverage if v[1]=='stock' and v[2]=='empty'),None)
if empty:
    select('cfg_stock_code',empty);assert not a.get('plotly_chart') and any('未返回' in i.value for i in a.info)
nav('factors')
for k in ('pe','pb','turn','vol','mom'):select('cfg_fack',k)
for venue in ('SH','SZ','BJ',''):select('cfg_facv',venue)
nav('strategies');dates('cfg_stratstartmom','2024-01-01');dates('cfg_stratend','2024-12-31');rr()
for bench in ('399001.SZ','399006.SZ','000300.SH'):
    select('cfg_stratbench',bench);click('运行策略回测')
    assert sub('strategy_output')['main']['curve'] and a.get('plotly_chart')
nav('portfolio');dates('cfg_range_a','2024-01-01');dates('cfg_range_b','2024-12-31');rr()
for k in ('mom','vol','rev','pb'):
    select('cfg_range_model',k);click('运行区间回测');out=sub('range_output')
    assert out['months'] and ('control' in out)==(k=='pb')
for bench in BENCHMARKS:
    select('cfg_range_benchmark',bench);click('运行区间回测');out=sub('range_output')
    assert out['market'] or out['overlap'] or not out['marketCurve']
select('cfg_range_model','manual');select('cfg_range_manw','manual')
assert not a.multiselect(key='cfg_range_stocks').value
click('载入三只股票示例')
number('cfg_range_weight_600519.SH',100.);click('运行区间回测')
assert a.error and any('权重' in e.value for e in a.error)
a.multiselect(key='cfg_range_stocks').set_value([]);rr();click('载入三只股票示例')
assert list(a.multiselect(key='cfg_range_stocks').value)==['600519.SH','000001.SZ','300750.SZ']
number('cfg_range_weight_600519.SH',32.)
a.radio(key='cfg_portfolio_tab').set_value('参数比较与样本外检验');rr()
select('cfg_study_source','manual');select('cfg_study_0_manw','manual')
assert a.number_input(key='cfg_study_shared_weight_600519.SH').value==32.
dates('cfg_study_trainA','2023-02-01');dates('cfg_study_trainB','2024-12-31')
dates('cfg_study_testA','2025-01-01');dates('cfg_study_testB','2025-12-31');rr()
for criterion in ('sharpe','drawdown','return'):
    select('cfg_study_criterion',criterion);click('比较样本内表现')
    assert sub('study_train')[1] is not None
click('锁定样本内胜出方案')
a.radio(key='cfg_portfolio_tab').set_value('区间回测');rr()
number('cfg_range_weight_600519.SH',23.)
a.radio(key='cfg_portfolio_tab').set_value('参数比较与样本外检验');rr()
assert a.number_input(key='cfg_study_shared_weight_600519.SH').value==32.
click('运行样本外检验');assert sub('study_test')['months'][0]['entry']>='20250101'
print('PASS:',checks,'offline UI reruns. Covered directory/empty data, one-day/long charts, CSV availability, all beta reference indices, factor filters, two extra strategy benchmarks, four selection models, five portfolio benchmarks, invalid weights, example restoration, three scoring criteria, and frozen weights.')
