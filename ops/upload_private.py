"""Upload and verify immutable archive objects. Optionally activate the verified index."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import getpass
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import warnings

import requests

ORIGIN = 'https://xuheng-course-archive-3582.alivetomato8.chatgpt.site'
WRITE_ENV = 'XUHENG_ARCHIVE_WRITE_KEY'
SHA = re.compile(r'[0-9a-f]{64}')
DAY = re.compile(r'20\d{6}')
MAX_SIZE = 16 * 1024**2


def auth_headers():
    key = os.environ.get(WRITE_ENV)
    service = None
    if not key:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            try:
                raw = getpass.getpass('Ready for private archive credentials on stdin (hidden): ')
                config = json.loads(raw)
                key, service = config['write'], config.get('service')
            except (getpass.GetPassWarning, EOFError, KeyError, TypeError, ValueError):
                raise ValueError('请使用终端隐藏输入或配置 XUHENG_ARCHIVE_WRITE_KEY。') from None
    if not isinstance(key, str) or not re.fullmatch(r'[!-~]{1,256}', key):
        raise ValueError('存储写入凭据格式无效。')
    headers = {'X-Archive-Write': key, 'Accept-Encoding': 'identity'}
    if service:
        if not isinstance(service, str) or not re.fullmatch(r'[!-~]+', service):
            raise ValueError('存储网关凭据格式无效。')
        headers['OAI-Sites-Authorization'] = 'Bearer ' + service
    return headers


def validate_pointer(data):
    if (not isinstance(data, dict) or set(data) != {'day', 'index', 'bars'}
            or not isinstance(data['day'], str) or not DAY.fullmatch(data['day'])
            or not isinstance(data['index'], str) or not SHA.fullmatch(data['index'])
            or type(data['bars']) is not int or not 0 < data['bars'] < 2**53):
        raise ValueError('行情版本指针格式无效。')
    return data


def local_release(folder):
    index_sha = (folder / 'index.sha256').read_text(encoding='ascii').strip()
    if not SHA.fullmatch(index_sha):
        raise ValueError('本地索引文件名无效。')
    path = folder / 'objects' / index_sha
    if not 0 < path.stat().st_size <= MAX_SIZE:
        raise ValueError('本地索引大小无效。')
    index = path.read_bytes()
    if hashlib.sha256(index).hexdigest() != index_sha:
        raise ValueError('本地索引 SHA-256 校验失败。')
    descriptor = json.loads(gzip.decompress(index))
    manifest, sizes = descriptor['manifest'], descriptor['sizes']
    if descriptor['version'] != 1 or manifest['format'] != 1 or manifest['sample'] is not False or not sizes:
        raise ValueError('只可发布完成校验的正式行情库。')
    for digest, size in sizes.items():
        if not SHA.fullmatch(digest) or type(size) is not int or not 0 < size <= MAX_SIZE:
            raise ValueError('本地索引的数据包清单无效。')
    items = descriptor['items']
    if not items or {entry[0] for entry in items.values()} != sizes.keys():
        raise ValueError('索引记录引用的数据包与大小清单不一致。')
    pointer = validate_pointer({'day': manifest['day'], 'index': index_sha, 'bars': manifest['bars']})
    return pointer, sizes, len(index)


class Publisher:
    def __init__(self, origin):
        if origin not in (ORIGIN, ORIGIN + '/'):
            raise ValueError('拒绝向未配置的服务发送凭据。')
        self.origin = ORIGIN
        self.headers = auth_headers()
        self.local = threading.local()

    def request(self, method, path, allowed, **kwargs):
        if not hasattr(self.local, 'session'):
            self.local.session = requests.Session()
            self.local.session.headers.update(self.headers)
        for attempt in range(7):
            try:
                # requests/urllib3 uses the connect timeout while writing the request body.
                # A short deadline here can repeatedly discard almost-finished uploads on a slow uplink.
                timeout = (120, 160) if method == 'PUT' and '/objects/' in path else (10, 40)
                response = self.local.session.request(method, self.origin + path, timeout=timeout,
                                                      allow_redirects=False, **kwargs)
            except requests.RequestException:
                if attempt == 6:
                    raise RuntimeError(f'私有存储 {method} {path} 网络请求失败。') from None
            else:
                status = response.status_code
                if status in allowed:
                    return response
                response.close()
                if (status not in (408, 425, 429) and status < 500) or attempt == 6:
                    raise RuntimeError(f'私有存储 {method} {path} 返回 HTTP {status}。')
            time.sleep(min(12, 2**attempt))

    def current(self):
        with self.request('GET', '/v1/current', {200, 404}) as r:
            return None if r.status_code == 404 else validate_pointer(r.json())

    def has_object(self, path, digest, size):
        with self.request('HEAD', path, {200, 404}) as r:
            if r.status_code == 404:
                return False
            if r.headers.get('X-Archive-SHA256') != digest or r.headers.get('Content-Length') != str(size):
                raise ValueError(f'云端数据包大小或 SHA-256 不符：{digest}')
            return True

    def transfer(self, folder, digest, size):
        source = folder / 'objects' / digest
        if source.stat().st_size != size:
            raise ValueError(f'本地数据包大小不符：{digest}')
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f'本地数据包 SHA-256 不符：{digest}')
        path = '/v1/objects/' + digest
        if self.has_object(path, digest, size):
            return size
        with self.request('PUT', path, {204}, data=data, headers={'Content-Type': 'application/octet-stream'}) as r:
            if r.headers.get('X-Archive-SHA256') != digest:
                raise ValueError(f'云端写入回执 SHA-256 不符：{digest}')
        if not self.has_object(path, digest, size):
            raise ValueError(f'云端写入后未找到数据包：{digest}')
        return size

    def activate(self, pointer):
        with self.request('PUT', '/v1/current', {204, 409}, json=pointer) as r:
            status = r.status_code
        if self.current() != pointer:
            raise RuntimeError(f'交易日 {pointer["day"]} 未生效，指针写入返回 HTTP {status}。')

    def publish(self, folder, threads, activate=False):
        pointer, sizes, index_size = local_release(folder)
        if activate:
            current = self.current()
            if current == pointer:
                print(f'{pointer["day"]} 的相同索引已经生效。', flush=True)
                return
            if current and current['day'] >= pointer['day']:
                raise ValueError(f'线上日期 {current["day"]} 已覆盖目标日期，不再发布该版本。')
        total, done = sum(sizes.values()), 0
        start = last = time.monotonic()
        with ThreadPoolExecutor(max_workers=threads) as pool:
            pending = [pool.submit(self.transfer, folder, digest, size)
                       for digest, size in sorted(sizes.items(), key=lambda item: -item[1])]
            for count, job in enumerate(as_completed(pending), 1):
                done += job.result()
                now = time.monotonic()
                if now - last >= 12 or count == len(pending):
                    print(f'{count}/{len(pending)} 已验证 {done/1e6:.1f}/{total/1e6:.1f} MB，'
                          f'用时 {now-start:.0f} 秒', flush=True)
                    last = now
        self.transfer(folder, pointer['index'], index_size)
        print('COMMITTED verified private release ' + pointer['index'], flush=True)
        if activate:
            self.activate(pointer)
            print(f'ACTIVE {pointer["day"]} {pointer["index"]}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', nargs='?', type=Path)
    parser.add_argument('origin')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--activate', action='store_true', help='Switch the active version after all objects verify.')
    modes.add_argument('--current', action='store_true', help='Read the active version as JSON.')
    parser.add_argument('--threads', type=int, default=10)
    args = parser.parse_args()
    if args.current == (args.folder is not None) or args.threads < 1:
        parser.error('上传时需要版本目录，查询 --current 时只需服务地址。并发数须为正整数。')
    publisher = Publisher(args.origin)
    if args.current:
        print(json.dumps(publisher.current(), separators=(',', ':')))
    else:
        publisher.publish(args.folder, args.threads, args.activate)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from None
