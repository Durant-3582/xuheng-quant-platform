"""Recover missed cloud data runs using a GitHub-hosted deployment wait timer."""
from datetime import datetime, timedelta, timezone
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPOSITORY = 'Durant-3582/xuheng-quant-platform'
BASE = f'https://api.github.com/repos/{REPOSITORY}/actions'
CLOCK = 'cloud-clock.yml'
WAIT = 30 * 60


def api(path, body=None):
    request = Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                               'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'xuheng-cloud-clock'})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=12) as response:
                data = response.read()
            return json.loads(data) if data else None
        except (HTTPError, URLError, TimeoutError) as exc:
            if body is not None or attempt == 2 or (isinstance(exc, HTTPError) and exc.code < 500 and exc.code not in (408, 429)):
                raise
            time.sleep(2 ** attempt)


def runs(workflow):
    return api(f'/workflows/{workflow}/runs?branch=main&per_page=15')['workflow_runs']


def created(run):
    return datetime.fromisoformat(run['created_at'].replace('Z', '+00:00')).timestamp()


def scheduled_slots(now):
    # UTC shares the same minute boundaries as Asia/Shanghai.
    epoch = int(now.timestamp())
    news = (epoch - 9 * 60) // WAIT * WAIT + 9 * 60
    evening = now.astimezone(timezone(timedelta(hours=8)))
    first = evening.replace(hour=19, minute=17, second=0, microsecond=0)
    last = first + timedelta(hours=3)
    market = last if evening >= last else first if evening >= first else last - timedelta(days=1)
    return news, int(market.timestamp())


def covered(history, slot):
    if any(run['status'] != 'completed' for run in history):
        return True
    attempts = [run for run in history if created(run) >= slot]
    return any(run['conclusion'] == 'success' for run in attempts) or len(attempts) >= 2


def next_waiting(history, own):
    prefix = 'cloud-clock '
    return any(run['id'] != own and run['status'] != 'completed' and run['display_title'].startswith(prefix)
               and run['display_title'][len(prefix):].isdigit() for run in history)


def check_wait(raw_due, opened, current):
    if raw_due:
        # A missing or bypassed environment timer must never cause an immediate loop.
        if (not raw_due.isascii() or not raw_due.isdigit() or len(raw_due) > 12
                or not WAIT - 180 <= int(raw_due) - opened <= WAIT + 60
                or current < int(raw_due) - 60 or current - opened < WAIT - 90):
            raise ValueError('云端等待时间不符，已停止接续任务。请核对环境的 30 分钟等待规则。')


def dispatch_once(workflow, inputs, exists):
    body = {'ref': 'main', 'inputs': inputs}
    for attempt in range(3):
        if exists(runs(workflow)):
            return False
        try:
            api(f'/workflows/{workflow}/dispatches', body)
            return True
        except (HTTPError, URLError, TimeoutError) as exc:
            if isinstance(exc, HTTPError) and exc.code < 500 and exc.code not in (408, 429):
                raise
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def main():
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY or os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise ValueError('仅在课程仓库的正式分支运行。')
    own = int(os.environ['GITHUB_RUN_ID'])
    if api('/workflows/' + CLOCK)['state'] != 'active':
        return
    now = datetime.now(timezone.utc)
    epoch = int(now.timestamp())
    check_wait(os.getenv('CLOCK_DUE', ''), created(api(f'/runs/{own}')), epoch)
    # Queue the next check first. An unavailable data source cannot stop the clock.
    armed = dispatch_once(CLOCK, {'due': str(epoch + WAIT)}, lambda history: next_waiting(history, own))
    print('下一次检查已交给 GitHub 等待计时器。' if armed else '已有下一次云端检查。', flush=True)
    news, market = scheduled_slots(now)
    failed = []
    for workflow, slot, inputs in [('news.yml', news, {'cloud_check': 'true'}), ('after-close.yml', market, {})]:
        try:
            started = dispatch_once(workflow, inputs, lambda history: covered(history, slot))
            print(workflow, datetime.fromtimestamp(slot, timezone.utc).isoformat(),
                  '已补跑' if started else '已有运行记录', flush=True)
        except (HTTPError, URLError, TimeoutError) as exc:
            print(workflow, type(exc).__name__, flush=True)
            failed.append(workflow)
    if failed:
        raise SystemExit('当前检查未完成：' + ', '.join(failed))


if __name__ == '__main__':
    main()
