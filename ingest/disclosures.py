"""Seed frequently opened disclosures and index members before a release; optional endpoints never block prices."""
from calendar import monthrange
from collections import Counter
from datetime import datetime
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from xuheng.details import extra
import sync


class LocalDirectory:
    def __init__(self, snapshot):
        self.snapshot=snapshot
        self.catalog={r[0]:r for r in snapshot["items"]}
        self.day=snapshot["day"]
    def json(self,*args,**kwargs):return None


def seed(store, day, *, sample=False):
    view=LocalDirectory(sync.read(store/'snapshot'/(day+'.gz')))
    hot=set(sync.PRIORITY.split()) if isinstance(sync.PRIORITY,str) else set(sync.PRIORITY)
    hot.update(['600036.SH','000858.SZ','601318.SH'])
    work=[(r[0], 'financial' if r[2]=='stock' else 'members') for r in view.catalog.values()
          if r[5]!='D' and (sample or r[0] in hot)]
    counts=Counter();denied=set()
    def fetch(name,params,fields,_):
        return sync.api(name,params,','.join(fields))
    for code,kind in work:
        path=store/kind/code/(day+'.gz')
        if path.exists():counts['cached']+=1;continue
        if kind in denied:continue
        try: result=extra(view,kind,code,day,None,fetch=fetch)
        except sync.Denied:denied.add(kind);counts['denied']+=1;continue
        sync.save(path,result)
        counts['ready' if (result if kind=='financial' else result['items']) else 'empty']+=1
    stamp=datetime.strptime(day,"%Y%m%d")
    end=stamp.replace(day=monthrange(stamp.year,stamp.month)[1]).strftime("%Y%m%d")
    closings=sync.api('trade_cal',{'exchange':'SSE','is_open':'1','start_date':day[:6]+'01','end_date':end},'cal_date')
    last=max((r['cal_date'] for r in closings),default='')
    if last<day or last>end:raise ValueError('交易所本月日历不完整。')
    sync.save(store/'calendar'/(day+'.gz'),{'lastScheduledSession':last})
    print('常用财报和成分：',dict(counts),'本月最后交易日',last,flush=True)

if __name__=='__main__':
    import argparse,download
    p=argparse.ArgumentParser();p.add_argument('--sample',action='store_true');args=p.parse_args()
    download.authenticate(72)
    path=sync.STORE.parent/'walkthrough/history' if args.sample else sync.STORE
    cutoff=sorted((path/'snapshot').glob('*.gz'))[-1].stem
    seed(path,cutoff,sample=args.sample)
