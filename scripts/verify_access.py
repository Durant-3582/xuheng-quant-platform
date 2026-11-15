"""Check real entitlements with small queries to Tushare's official HTTPS endpoint."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import sys
import requests

ROOT = Path(__file__).resolve().parents[1]


def credential():
    env = os.getenv('TUSHARE_TOKEN', '').strip()
    return env or (ROOT / '.private' / 'tushare-token').read_text().strip()


def main():
    token = credential()
    probes = [
        ('daily', '600000.SH', '20000104'), ('daily', '000001.SZ', '20000104'),
        ('daily', '920185.BJ', '20261113'), ('index_daily', '000001.SH', '20000104'),
        ('daily_basic', '600000.SH', '20000104'), ('index_daily', '899050.BJ', '20261113'),
    ]
    def probe(query):
        name, code, day = query
        field = 'pb' if name == 'daily_basic' else 'close'
        try:
            with requests.post('https://api.tushare.pro', json={'api_name': name, 'token': token,
                'params': {'ts_code': code, 'trade_date': day}, 'fields': f'ts_code,trade_date,{field}'},
                timeout=(6, 18), allow_redirects=False) as response:
                response.raise_for_status()
                body = response.json()
        except (requests.RequestException, ValueError) as error:
            return name, code, day, '连接失败 ' + type(error).__name__
        if body.get('code') != 0:
            return name, code, day, 'Tushare 错误码 ' + str(body.get('code'))
        rows = [dict(zip(body['data']['fields'], row, strict=True)) for row in body['data']['items']]
        match = [r for r in rows if r['ts_code'] == code and r['trade_date'] == day and r[field] is not None]
        return name, code, day, '已核对' if len(match) == len(rows) == 1 else '没有符合的记录'
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(probe, probes))
    for result in results:
        print(*result, flush=True)
    return 0 if all(r[-1] == '已核对' for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
