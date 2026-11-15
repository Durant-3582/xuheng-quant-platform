"""Independent accounting, market microstructure, paired-sample, and holdout boundary checks."""
from dataclasses import replace
import math,os,sys
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from xuheng.archive import Archive
from xuheng.frames import Rules
from xuheng.portfolio import Book,run,targets
from xuheng.comparison import compare,score
from xuheng.research import rolling_beta

s=Archive(os.getenv('XUHENG_DATA_DIR',root/'.private/walkthrough/database'))
ticker='600000.SH';r=Rules(model='manual',count=1,weighting='manual',weights=(100.,),symbols=(ticker,),cadence='hold')
bars=[r for r in s.series(ticker)['bars'] if '20240102'<=r[0]<='20240105']
assert len(bars)==4
expected=bars[0][4]/bars[0][1]/1.001
for b in bars[1:]:expected*=b[4]/b[5]
customer=run(s,r,'20240101','20240105')
assert abs(customer['main']['total']-100*(expected-1))<1e-8
assert sum(x['rebalance'] for x in customer['months'])==1
assert abs(customer['main']['cost']-100*.001/1.001)<1e-12
assert customer['months'][0]['signal']<customer['months'][0]['entry']
# A buy limit or a suspension cannot spend cash; a sell limit cannot liquidate an existing position.
b=Book()
def step(q,w,flag,reb=True):return b.advance(q,w,.001,reb,lambda code,raw:flag,'20240102')
q={ticker:[ticker,None,None,None,1.,1.,2]}
step(q,{ticker:1.},2);assert b.cash==1 and not b.positions
step({},{ticker:1.},0);assert b.cash==1 and not b.positions
q[ticker][6]=3;step(q,{ticker:1.},3);assert math.isclose(b.positions[ticker],1/1.001)
q[ticker][6]=1;step(q,{},1);assert ticker in b.positions
step({}, {},0,False);assert math.isclose(b.nav,1/1.001)
q[ticker][6]=3;step(q,{},3);assert not b.positions and math.isclose(b.cash,.999/1.001)
pre=replace(r,symbols=('920002.BJ',))
if '920002.BJ' in s.catalog:
    assert not any(x['held'] for x in run(s,pre,'20230104','20230131')['months'])
picks=[('a',None,True,-.01,.002),('b',None,True,None,None)]
assert not any(targets(picks,r,'tb').values())
pb=Rules(model='pb',count=3,bench='000300.SH')
result=run(s,pb,'20240101','20241231')
assert len(result['main']['curve'])==len(result['control']['curve']) and all(m['pool']>=0 for m in result['months'])
assert [v[0] for v in result['control']['curve']]==[v[0] for v in result['main']['curve']]
cal=s.daily['dates']; good=[('20240506',100),('20240531',101),('20240603',101),('20240628',105)]
record={'months':[{'entry':good[0][0],'end':good[-1][0],'held':1}],'main':{'curve':good,'total':5}}
assert score(record,[x[0] for x in good],'20240628')['months']==2
assert score(record,[x[0] for x in good],'20240630')['months']==1
seen=[]
def restricted(s,rr,a,b):
    assert b<'20250101';seen.append((a,b));return run(s,rr,a,b)
rules=[Rules(count=2),Rules(count=3)]
with patch('xuheng.comparison.run',side_effect=restricted):
    cmp,winner=compare(s,rules,('20240101','20241231','20250101','20251231'),'return')
assert len(seen)==2 and winner==cmp[0]['index'] and cmp[0]['return']>=cmp[1]['return']
# β=2 on exactly 120 paired daily returns; one suspended session removes both adjacent pairs.
xs=[((i*17)%13-6)/1000 for i in range(123)]
from datetime import date,timedelta
def synth(xs,mult):
    out=[];px=100.
    for i,x in enumerate([0]+xs):
        prev=px;px*=1+mult*x;out.append([(date(2023,1,1)+timedelta(i)).strftime('%Y%m%d'),px,px,px,px,prev,0,100,1])
    return out
idx=synth(xs,1);stock=synth(xs,2)
assert not rolling_beta(stock[:120],idx[:120])[1]
assert math.isclose(rolling_beta(stock[:121],idx[:121])[1][-1][1],2,abs_tol=1e-10)
hits,points=rolling_beta(stock[:50]+stock[51:],idx);assert hits==len(xs)-2 and all(abs(v-2)<1e-10 for _,v in points)
print(f'PASS: hand-calculated single trade {100*(expected-1):+.6f}%, fees, buy/sell restrictions, stale marks, listing date, TB cash, PB control alignment, trading month-end, training-only calls, and beta.')
