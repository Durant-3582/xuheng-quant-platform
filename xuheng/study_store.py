"""Versioned, read-only research tables stored alongside the private market objects."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time

import requests

from .archive import ArchiveError
from .packed_archive import ORIGIN

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / '.private/studies'
POINTER = 'https://raw.githubusercontent.com/Durant-3582/xuheng-quant-platform/study-data/release.json'
MAX_BYTES = 16 * 1024**2
lock = threading.Lock()
_checked = {}


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        f.write(data)
    os.replace(f.name, path)


def encode(value):
    return gzip.compress(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode(),
                         compresslevel=5, mtime=0)


def valid(index, day):
    return (isinstance(index, dict) and index.get('format') == 1 and
            isinstance(index.get('day'), str) and re.fullmatch(r'20\d{6}', index['day']) and index['day'] <= day and
            isinstance(index.get('files'), dict) and bool(index['files']) and
            all(isinstance(h,str) and re.fullmatch('[0-9a-f]{64}', h) for h in index['files'].values()))


def edition(store, refresh=True):
    if store.manifest.get('sample'):
        raise ArchiveError('这项研究使用正式全市场数据库。')
    local = PRIVATE / 'release.json'
    if not getattr(store, 'remote', False) and local.exists():
        index = json.loads(local.read_bytes())
        if valid(index, store.day):
            return index
    baseline = ROOT / 'static/study-release.json'
    seed = json.loads(baseline.read_bytes()) if baseline.is_file() else None
    if not valid(seed, store.day):
        raise ArchiveError('当前行情版本没有对应的研究数据库。')
    with lock:
        now = time.monotonic()
        old, checked = _checked.get(store.day, (seed, 0))
        if not refresh and old['day'] == store.day:
            return old
        if checked and now - checked < 180:
            return old
        try:
            response = requests.get(POINTER, timeout=(3, 6))
            response.raise_for_status()
            newer = response.json()
            if valid(newer, store.day) and newer['day'] >= old['day']:
                old = newer
        except (ValueError, requests.RequestException):
            pass
        _checked.clear()
        _checked[store.day] = old, now
        return old


def factor_snapshot(store):
    index = edition(store)
    panels = tuple(sorted((key, digest) for key, digest in index['files'].items() if key.startswith('panel/')))
    if not panels:
        raise ArchiveError('多因子研究库暂未发布可用的月末数据。')
    return index['day'], panels


def snapshot_digest(snapshot):
    return hashlib.sha256(json.dumps(snapshot, separators=(',', ':')).encode()).hexdigest()


def content(index, key, reader='', directory=None):
    digest = index['files'][key]
    root = Path(directory) if directory else (PRIVATE if not reader else Path(tempfile.gettempdir()) / 'xuheng-study-v1')
    path = root / 'objects' / digest
    if path.is_file():
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() == digest:
            return data
    if not reader:
        raise ArchiveError('本地研究数据未通过校验。')
    try:
        with requests.get(ORIGIN + '/v1/objects/' + digest, headers={'X-Archive-Read':reader,'Accept-Encoding':'identity'},
                          timeout=(6,35), allow_redirects=False) as r:
            r.raise_for_status()
            data = r.content
            if r.status_code != 200 or len(data)>MAX_BYTES or hashlib.sha256(data).hexdigest()!=digest:
                raise ArchiveError('研究数据包校验失败，请重试。')
    except requests.RequestException as e:
        raise ArchiveError('暂时无法读取研究库，请重试。') from e
    atomic(path, data)
    return data


def bucket(code):
    return hashlib.sha256(code.encode()).digest()[0] % 32


def security_id(code):
    number, venue = code.split('.')
    return int(number) + {'SH':1000000, 'SZ':2000000, 'BJ':3000000}[venue]
