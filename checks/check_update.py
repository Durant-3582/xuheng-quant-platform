"""Replay a real two-day sample in an isolated directory: retries cannot publish a partial trading day."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'ingest'))
import sync,incremental

p=root/'.private/isolated-bootstrap/history'
if not p.is_dir():p=root/'.private/walkthrough/history'
day=sorted((p/'snapshot').glob('*.gz'))[-1].stem
latest=sync.read(p/'snapshot'/(day+'.gz'))
directory={**latest,'items':[r[:9] for r in latest['items']]}
truth={r[0]:sync.read(p/'series'/(r[0]+'.gz')) for r in latest['items']}
prev=truth['000001.SH']['bars'][-2][0]
quotes={c:q['bars'][-1] for c,q in truth.items() if q['bars'] and q['bars'][-1][0]==day}
pb=sync.read(p/'pb'/(day+'.gz'))
daily_basic=[{'ts_code':r[0],'trade_date':day,'pb':v,'pe_ttm':r[12],'total_mv':r[14],'turnover_rate':r[15]}
             for r in latest['items'] if r[0] in pb for v in [pb[r[0]]]]
def api(name,params,fields):
    if name=='trade_cal':return [{'cal_date':prev},{'cal_date':day}]
    if name=='daily':return [{'ts_code':'600000.SH'}]
    raise AssertionError(name)
def listing(name,params,fields,n):
    assert name=='daily_basic' and params['trade_date']==day
    return daily_basic
with TemporaryDirectory() as tmp:
    h=Path(tmp)
    for c,obj in truth.items():
        if c=='600036.SH':continue  # newly discovered relative to this archive
        bars=[b for b in obj['bars'] if b[0]<=prev]
        sync.save(h/'series'/(c+'.gz'),{**obj,'bars':bars,'until':prev})
    with patch.object(sync,'api',side_effect=api),patch.object(sync,'inventory',return_value=directory),patch.object(sync,'listing',side_effect=listing):
        with patch.object(sync,'day_quotes',return_value={c:q for c,q in quotes.items() if c!='399001.SZ'}):
            try:incremental.run(h,prev,day)
            except RuntimeError:pass
            else:raise AssertionError('缺少深市基准时错误地接受了当前交易日。')
        assert not (h/'last-incremental').exists() and not (h/'snapshot'/(day+'.gz')).exists()
        with patch.object(sync,'day_quotes',return_value=quotes) as request,patch.object(sync,'historical',side_effect=lambda row,cut:truth[row[0]]):
            incremental.run(h,prev,day);incremental.run(h,prev,day)
            assert request.call_count==1
        for c,obj in truth.items():
            rebuilt=sync.read(h/'series'/(c+'.gz'))
            assert rebuilt==obj,c
        assert (h/'last-incremental').read_text()==day
        assert sync.read(h/'snapshot'/(day+'.gz'))['items']==latest['items']
        assert sync.read(h/'pb'/(day+'.gz'))=={r['ts_code']:r['pb'] for r in daily_basic}
print('PASS: real-day quote replay, missing market benchmark, checkpoint integrity, discovery of new securities, complete current snapshot, and no duplicate bars on retry.')
