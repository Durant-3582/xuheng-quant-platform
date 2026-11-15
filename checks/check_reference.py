"""Compare independent ledger summaries to frozen outputs from the original site's implementation.
The reference is used only in this check and is never read by the website or the importer.
"""
import argparse
import json
import math
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from xuheng.archive import Archive
from xuheng.frames import Rules
from xuheng.portfolio import run

def compare(archive,report):
    store=Archive(archive);reference=json.loads(report.read_text())
    assert reference['cutoff']==store.day and not store.manifest['sample']
    rebuilt=[];errors=[]
    for i,case in enumerate(reference['cases'],1):
        params=case['settings'].copy()
        for k in ('weights','symbols'):params[k]=tuple(params.get(k,[]))
        out=run(store,Rules(**params),*case['requested']);rows=out['months'];m=out['main']
        fields={'first':rows[0]['entry'],'last':rows[-1]['end'],'periods':len(rows),
                'scheduled':sum(x['rebalance'] for x in rows),'return_pct':m['total'],
                'drawdown_pct':m['dd'],'cash_pct':rows[-1]['cash'],'fees_pct':m['cost']}
        for k,v in fields.items():
            ok=math.isclose(v,case[k],rel_tol=5e-10,abs_tol=1e-8) if isinstance(v,float) else v==case[k]
            if not ok:errors.append([i,k,case[k],v])
        rebuilt.append(len(rows))
    print(f'与原站冻结基准对照 {len(rebuilt)} 组，涉及 {sum(rebuilt):,} 个估值或调仓期；指标差异 {len(errors)} 个。')
    if errors:
        print('前 12 项差异',errors[:12]);raise SystemExit(1)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('archive',type=Path);ap.add_argument('reference',type=Path)
    args=ap.parse_args();compare(args.archive,args.reference)
