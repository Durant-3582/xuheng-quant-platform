"""Checkpoint Tushare disclosures by security and official SW2021 level-one daily prices."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
import argparse
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'ingest'))
import download
import sync

FIELDS = 'ts_code ann_date end_date update_flag eps roe grossprofit_margin debt_to_assets tr_yoy netprofit_yoy'.split()
SOURCE = 'https://www.swsresearch.com/institute-sw/api/index_publish/trend/'
FIN_FORMAT = 2


def report_pages(codes, cutoff, announcement=None):
    """Tushare sorts by fiscal period; offset pages can skip tied filings."""
    until = cutoff
    base = {'ts_code': ','.join(codes),'limit':100,'start_date':'19900101'}
    if announcement:
        base['ann_date'] = announcement
    while until >= base['start_date']:
        group = sync.api('fina_indicator', dict(base,end_date=until), ','.join(FIELDS))
        if len(group)<100:
            yield from group
            break
        periods = [r['end_date'] for r in group]
        if periods != sorted(periods,reverse=True) or periods[0]>until:
            raise ValueError('财务接口未按报告期返回，无法验证分页完整性')
        boundary = periods[-1]
        yield from (r for r in group if r['end_date']>boundary)
        if periods[0] != boundary:
            until = boundary
            continue
        # More than a page shares one fiscal period. Partition the securities
        # at that boundary, then continue the original group before the boundary.
        if len(codes)==1:
            raise ValueError('单个证券同一报告期达到 100 个版本，需进一步拆分')
        def exact(part):
            rows=sync.api('fina_indicator',dict(base,ts_code=','.join(part),start_date=boundary,end_date=boundary),','.join(FIELDS))
            if len(rows)<100:
                yield from rows
            elif len(part)>1:
                half=len(part)//2
                yield from exact(part[:half])
                yield from exact(part[half:])
            else:
                raise ValueError('单一证券报告期超过分页上限')
        half=len(codes)//2
        yield from exact(codes[:half])
        yield from exact(codes[half:])
        until=(date.fromisoformat(boundary)-timedelta(days=1)).strftime('%Y%m%d')


def fetch_financials(snapshot, home, day, workers):
    aliases = snapshot.get('aliases', {})
    stocks = sorted(r[0] for r in snapshot['items'] if r[2] == 'stock')
    old_codes = {}
    for old, new in aliases.items():
        if old != new:
            old_codes.setdefault(new, []).append(old)
    folder = home / 'financial'
    def pull(group):
        records = {}
        for code in group:
            path = folder / (code + '.gz')
            cache = sync.read(path) if path.exists() else {}
            if cache.get('format')!=FIN_FORMAT:
                cache={}
            if cache.get('through', '') < day:
                records[code] = cache
        if not records:
            return
        query = {c: c for c in records}
        for c in records:
            query.update({old: c for old in old_codes.get(c, ())})
        since=min((v.get('through','') for v in records.values()),default='')
        if since:
            beginning=date.fromisoformat(since)-timedelta(days=6)
            days=[(beginning+timedelta(days=i)).strftime('%Y%m%d') for i in range((date.fromisoformat(day)-beginning).days+1)]
            rows=(r for announced in days for r in report_pages(list(query),day,announced) if r['ann_date']==announced)
        else:
            rows=report_pages(list(query),day)
        collected={c:set() for c in records}
        for r in rows:
            code = query.get(r['ts_code'])
            ann, period = r['ann_date'], r['end_date']
            if not code:
                raise ValueError('财务接口返回了查询范围以外的证券')
            if not ann or not period or not sync.START <= ann <= day or period > ann:
                continue
            collected[code].add((period, ann, str(r['update_flag'] or '0'), *(sync.number(r[k]) for k in FIELDS[4:])))
        for code, cache in records.items():
            changed={r[:2] for r in collected[code]}
            retained={tuple(r) for r in cache.get('rows',[]) if tuple(r[:2]) not in changed} if since else set()
            rows = sorted(collected[code] | retained, key=lambda r: (r[0], r[1], r[2], repr(r[3:])))
            sync.save(folder / (code + '.gz'), {'format':FIN_FORMAT,'through': day, 'rows': rows})
    size=64 if (home/'restored').is_file() else 8
    groups = [stocks[i:i+size] for i in range(0, len(stocks), size)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = [pool.submit(pull, g) for g in groups]
        for n, job in enumerate(as_completed(pending), 1):
            job.result()
            if n % 40 == 0 or n == len(groups):
                print(f'全市场财报 {n}/{len(groups)} 批', flush=True)


def fetch_industries(home, day):
    # The publisher sends its leaf certificate without the intermediate CA.
    directory = sync.api('index_classify', {'src': 'SW2021', 'level': 'L1'}, 'index_code,industry_name')
    if len(directory) != 31 or len({r['index_code'] for r in directory}) != 31:
        raise ValueError('申万 2021 一级行业目录未返回 31 个独立指数')
    folder = home / 'industries'
    def fetch(item):
        code, name = item['index_code'], item['industry_name']
        path = folder / (code + '.gz')
        if path.is_file() and sync.read(path)['through'] == day:
            return
        verify = issuer_bundle()
        for attempt in range(4):
            try:
                res = requests.get(SOURCE, params={'swindexcode': code.split('.')[0], 'period': 'DAY'},
                                   headers={'User-Agent': 'Mozilla/5.0'}, verify=verify, timeout=(7, 30))
                res.raise_for_status()
                bars = {}
                for r in res.json()['data']:
                    if r['swindexcode'] != code.split('.')[0]:
                        raise ValueError('申万返回的代码不符')
                    session = str(r['bargaindate'])[:10].replace('-', '')
                    if session > day:
                        continue
                    opening, close = (sync.number(r[k], positive=True) for k in ('openindex', 'closeindex'))
                    if session in bars or not close:
                        raise ValueError('申万行情日期重复或缺收盘')
                    bars[session] = [session, opening, close]
                if not bars or max(bars) != day:
                    raise ValueError(f'{name}行业日线尚未更新到 {day}')
                sync.save(path, {'code': code, 'name': name, 'through': day, 'bars': [bars[d] for d in sorted(bars)]})
                return
            except (requests.RequestException, ValueError, KeyError):
                if attempt == 3:
                    raise
                time.sleep(2**attempt)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(fetch, directory))
    print('申万官方一级行业日线已校验 31/31', flush=True)


def issuer_bundle():
    import tempfile
    ca = ROOT / 'ingest' / 'sw-intermediate.pem'
    if not ca.is_file():
        return True
    bundle = Path(tempfile.gettempdir()) / 'xuheng-sw-ca.pem'
    if not bundle.exists():
        import os
        with tempfile.NamedTemporaryFile(dir=bundle.parent, delete=False) as f:
            f.write(Path(requests.certs.where()).read_bytes() + b'\n' + ca.read_bytes())
        os.replace(f.name, bundle)
    return str(bundle)


def fetch_valuations(store, home, workers):
    sessions = store.daily['dates']
    month_ends = [d for d, following in zip(sessions, sessions[1:]) if d[:6] != following[:6]]
    def fetch(d):
        path = home / 'values' / (d + '.gz')
        if path.exists():
            return
        fields = 'ts_code,trade_date,pb,pe_ttm,turnover_rate'
        rows = sync.listing('daily_basic', {'trade_date': d}, fields, 6000)
        if not rows or any(r['trade_date'] != d for r in rows):
            raise ValueError('月末估值缺失或日期不符 ' + d)
        result = {r['ts_code']: [sync.number(r[f]) for f in fields.split(',')[2:]] for r in rows}
        if len(rows) != len(result):
            raise ValueError('日估值证券代码重复')
        sync.save(path, result)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(fetch, month_ends))
    print('已校验月末全市场估值', len(month_ends), flush=True)


if __name__ == '__main__':
    from xuheng.archive import Archive
    parser = argparse.ArgumentParser()
    parser.add_argument('part', choices=['financial', 'industries', 'values'])
    parser.add_argument('--rpm', type=int, default=175)
    parser.add_argument('--workers', type=int, default=5)
    args = parser.parse_args()
    download.authenticate(args.rpm)
    store = Archive(ROOT / '.private/database')
    home = ROOT / '.private/study-sources'
    if args.part == 'financial':
        fetch_financials(store.snapshot, home, store.day, args.workers)
    elif args.part == 'industries':
        fetch_industries(home, store.day)
    else:
        fetch_valuations(store, home, args.workers)
