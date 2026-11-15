"""Build and publish point-in-time research tables. No visitor makes a bulk API request."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'ingest'))
import download
import sync
from study_sources import FIN_FORMAT, fetch_financials, fetch_industries, fetch_valuations
from ops.publish_after_close import writer_environment
from ops.upload_private import ORIGIN, Publisher, WRITE_ENV
from xuheng.archive import Archive
from xuheng.disclosed import annual_roe, latest, revisions
from xuheng.packed_archive import PackedArchive, current_release, market_reader
from xuheng.portfolio import opening_rules
from xuheng.study_store import PRIVATE, MAX_BYTES, atomic, bucket, content, encode, security_id, valid


def build(store, home, out):
    day = store.day
    signals = [d for d, nxt in zip(store.daily['dates'], store.daily['dates'][1:]) if d[:6] != nxt[:6]]
    index = {'format':1, 'day':day, 'files':{}, 'years':{}, 'periods':[]}
    def put(key, data):
        if not 0 < len(data) <= MAX_BYTES:
            raise ValueError('研究包大小异常 ' + key)
        digest = hashlib.sha256(data).hexdigest()
        path = out / 'objects' / digest
        if not path.exists():
            atomic(path, data)
        index['files'][key] = digest
    by_bucket = defaultdict(list)
    for s in store.catalog.values():
        if s[2] == 'stock':
            by_bucket[bucket(s[0])].append(s[0])
    by_period = defaultdict(dict)
    current_fin, quality, roe_history = {}, {}, defaultdict(dict)
    queried, found, reports, vintages = 0, 0, 0, 0
    recent_periods = {f'{y}{q}' for y in range(int(day[:4])-3, int(day[:4])+1) for q in ('0331','0630','0930','1231')}
    for shard, codes in sorted(by_bucket.items()):
        archive = {}
        for code in sorted(codes):
            raw = sync.read(home / 'financial' / (code+'.gz'))
            if raw.get('format')!=FIN_FORMAT or raw['through'] != day:
                raise ValueError('财报尚未检查到数据库截止日 ' + code)
            archive[code] = raw['rows']
            resolved = revisions(raw['rows'])
            latest_rows = latest(resolved, day)
            queried += 1
            found += bool(latest_rows)
            reports += len(latest_rows)
            vintages += len(resolved)
            if latest_rows:
                current_fin[code] = latest_rows[0]
            for r in latest_rows:
                if r[0] in recent_periods:
                    by_period[r[0]][code] = r
            for d, r in annual_roe(resolved, signals + [day]).items():
                if d == day:
                    quality[code] = r[:2]+[r[3]]
                else:
                    roe_history[d][code] = r[3]
        put('reports/'+str(shard), encode(archive))
    index['counts'] = dict(queried=queried, withReports=found, periods=reports, vintages=vintages)
    if queried != len([s for s in store.catalog.values() if s[2]=='stock']) or not found:
        raise ValueError('未完成全市场财报检查')
    index['periods'] = sorted(by_period, reverse=True)[:12]
    common_periods=Counter(row[0] for c,row in current_fin.items()
                          if store.catalog[c][5]=='L' and store.catalog[c][9] is not None and row[0] in index['periods'])
    index['defaultPeriod']=max(common_periods,key=lambda p:(common_periods[p],p)) if common_periods else 'latest'
    for p in index['periods']:
        put('fin/'+p, encode(by_period[p]))
    put('fin/latest', encode(current_fin))
    factors = {r[0]:r[1:] for r in store.factors['latest']}
    current = []
    for c, r in sorted(store.catalog.items()):
        if r[2]!='stock' or r[5]!='L' or r[9] is None:
            continue
        mom, vol = factors.get(c, [None, None])
        # These columns are identical to the monthly panel used by the IC test.
        current.append([c, mom, vol, r[13], quality.get(c,[None,None,None])[2], r[12], r[15]])
    put('current', encode(current))
    put('quality', encode(quality))
    aliases = store.snapshot.get('aliases', {})
    for year, key in sorted(store.months['years'].items()):
        months, arrays, valuations = [], {}, {}
        for p in store.json(key):
            sig, entry, end = p['signal'], p['entry'], p['end']
            source = sync.read(home / 'values' / (sig+'.gz'))
            valuations[sig] = source
            values = {aliases.get(c,c):v for c,v in source.items()}
            # Prefer the canonical security where the provider returns both codes.
            values.update({c:v for c,v in source.items() if c not in aliases})
            if end == day and end != store.manifest.get('lastScheduledSession'):
                continue
            flags_at = opening_rules(store,entry)
            matrix, realized = [], []
            for r in p['rows']:
                c, mom, vol = r[:3]
                raw = r[6]
                observed = bool((raw & 3) and (raw & 4))
                ret = 100*(r[5]-1)
                if observed:
                    realized.append([security_id(c),ret])
                if not raw & 8:
                    continue
                security=store.catalog[c]
                if ((security[6] and sig < security[6]) or (security[7] and sig > security[7]) or
                        (c.endswith('.BJ') and sig<'20211115')):
                    continue
                pb, pe, turn = values.get(c, (None,None,None))
                buyable = bool(flags_at(c,raw & 3) & 1)
                matrix.append([security_id(c),mom,vol,pb,roe_history[sig].get(c),pe,turn,
                               ret if observed else None, ret if buyable else 0.0])
            arrays[sig] = np.asarray(matrix,dtype='float64').reshape(-1,9)
            arrays['returns_'+sig] = np.asarray(realized,dtype='float64').reshape(-1,2)
            months.append([sig,entry,end])
        if months:
            index['years'][year] = months
            buf = io.BytesIO()
            np.savez_compressed(buf, **arrays)
            put('panel/'+year, buf.getvalue())
        put('values/'+year, encode(valuations))
    industries = [sync.read(path) for path in sorted((home/'industries').glob('*.gz'))]
    if len(industries)!=31 or any(x['through']!=day for x in industries):
        raise ValueError('行业历史未齐备')
    put('industries', encode(industries))
    index['sessions'] = len(signals)
    return index


def restore(previous, reader, home, out):
    for key in previous['files']:
        if not key.startswith(('reports/','values/')):
            continue
        data = json.loads(gzip.decompress(content(previous,key,reader,out)))
        if key.startswith('reports/'):
            for code, rows in data.items():
                sync.save(home/'financial'/(code+'.gz'), {'format':FIN_FORMAT,'through':previous['day'],'rows':rows})
        else:
            for day, rows in data.items():
                sync.save(home/'values'/(day+'.gz'), rows)
    (home/'restored').touch()


def publish(index, out):
    os.environ[WRITE_ENV] = writer_environment(sync.token)[WRITE_ENV]
    publisher = Publisher(ORIGIN)
    def upload(digest):
        size = (out/'objects'/digest).stat().st_size
        return publisher.transfer(out,digest,size)
    with ThreadPoolExecutor(max_workers=4) as pool:
        sizes = list(pool.map(upload, sorted(set(index['files'].values()))))
    print('已校验私有研究数据包', len(sizes), round(sum(sizes)/2**20,1), 'MiB', flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cloud',action='store_true')
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--pointer',type=Path, default=PRIVATE/'release.json')
    args=parser.parse_args()
    download.authenticate(155)
    home, out = ROOT/'.private/study-sources', PRIVATE
    if args.cloud:
        reader=market_reader(sync.token)
        seed=json.loads((ROOT/'static/full-release.json').read_bytes())
        cache=Path(tempfile.gettempdir())/'xuheng-study-prices'
        active=current_release(seed,reader,cache)
        store=PackedArchive(cache,ORIGIN,active['index'],reader)
        base=args.pointer if args.pointer.is_file() else ROOT/'static/study-release.json'
        previous=json.loads(base.read_bytes())
        if not valid(previous,store.day):
            raise ValueError('研究库版本与行情版本不兼容')
        if previous['day']==store.day:
            if not args.pointer.exists():
                atomic(args.pointer,base.read_bytes())
            print('研究库与行情库交易日一致')
            return
        restore(previous,reader,home,out)
        fetch_financials(store.snapshot,home,store.day,4)
        fetch_valuations(store,home,3)
        fetch_industries(home,store.day)
    else:
        store=Archive(ROOT/'.private/database')
    index=build(store,home,out)
    if args.publish:
        publish(index,out)
    atomic(args.pointer, json.dumps(index,ensure_ascii=True,separators=(',',':'),sort_keys=True).encode())
    print(store.day,index['counts'],len(index['files']),'份数据表',flush=True)


if __name__ == '__main__':
    main()
