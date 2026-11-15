"""Publish the latest complete trading day of the independent Xuheng archive."""
import argparse
import datetime as dt
import fcntl
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / '.private'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'ingest'))
import download
from ops.upload_private import DAY, ORIGIN, WRITE_ENV, local_release, validate_pointer

IMPORT_SCOPE = b'xuheng/market-import/v1/appgprj_6af9102ba4608191addb0f2e49174e36'
UPLOAD = ROOT / 'ops' / 'upload_private.py'


def writer_environment(tushare_token):
    env = os.environ.copy()
    env.pop('TUSHARE_TOKEN', None)
    if not env.get(WRITE_ENV):
        env[WRITE_ENV] = hmac.digest(tushare_token.strip().encode(), IMPORT_SCOPE, 'sha256').hex()
    return env


def command(script, *args, env, capture=False):
    return subprocess.run([sys.executable, str(script), *map(str, args)], cwd=ROOT, env=env,
                          stdout=subprocess.PIPE if capture else None, text=True, check=True)


def staging_folder(day):
    dated = PRIVATE / 'cloud-releases' / day
    seed = PRIVATE / 'cloud-release'
    if not dated.exists() and (seed / 'index.sha256').is_file():
        if local_release(seed)[0]['day'] == day:
            return seed
    return dated


def publish(until, rpm, threads):
    download.authenticate(rpm)
    day = download.last_session(until)
    if not DAY.fullmatch(day) or day > until:
        raise ValueError('交易日历返回了无效日期。')
    writer_env = writer_environment(download.sync.token)
    current = json.loads(command(UPLOAD, '--current', ORIGIN, env=writer_env, capture=True).stdout)
    if current is not None and validate_pointer(current)['day'] >= day:
        print(f'最新可发布交易日为 {day}，线上日期为 {current["day"]}，本次无需更新。')
        return

    source_env = os.environ.copy()
    source_env.pop(WRITE_ENV, None)
    mark = PRIVATE / 'database' / 'manifest.json'
    local = json.loads(mark.read_bytes()) if mark.is_file() else None
    if local and (local.get('sample') is not False or local['day'] > day):
        raise ValueError('本地正式库类型或日期与待发布交易日不符。')
    if not local or local['day'] < day:
        command(ROOT / 'ingest' / 'build.py', '--until', day, '--rpm', rpm, env=source_env)
    manifest = json.loads(mark.read_bytes())
    if manifest['day'] != day or manifest.get('sample') is not False:
        raise ValueError('正式库尚未完成目标交易日的构建。')

    folder = staging_folder(day)
    source_env.pop('TUSHARE_TOKEN', None)
    command(ROOT / 'scripts' / 'pack_cloud.py', '--output', folder, env=source_env)
    packed, _, _ = local_release(folder)
    if packed['day'] != day or packed['bars'] != manifest['bars']:
        raise ValueError('打包期间本地库版本发生变化，请重新执行发布。')
    command(UPLOAD, folder, ORIGIN, '--threads', threads, '--activate', env=writer_env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    today = dt.datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
    parser.add_argument('--until', default=today, help='Latest date to consider (YYYYMMDD, Shanghai time).')
    parser.add_argument('--rpm', type=int, default=180, help='Tushare query limit per minute.')
    parser.add_argument('--threads', type=int, default=10, help='Concurrent object uploads.')
    args = parser.parse_args()
    if not DAY.fullmatch(args.until) or args.rpm < 1 or args.threads < 1:
        parser.error('日期须为 YYYYMMDD，查询频率及并发数须为正整数。')
    dt.datetime.strptime(args.until, '%Y%m%d')
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (PRIVATE / 'post-close.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('本机已有盘后发布正在运行。') from None
        publish(args.until, args.rpm, args.threads)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from None
