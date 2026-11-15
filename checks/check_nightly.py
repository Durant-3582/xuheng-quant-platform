"""Compare a cloud-style incremental update to a full rebuild on a bounded real fixture."""
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "ingest")]
import build
import opening_limits
import portfolio_inputs
import sync
from ops import publish_after_close as job


def price_inputs(history, day):
    build.prepare_prices(history, day)
    folder = history / "research" / day
    return folder, sync.read(folder / "days-index.gz")


def check_calendars():
    import datetime as dt
    assert job.market_cutoff(dt.datetime.fromisoformat('2026-11-15T16:00:00+00:00')) == '20261115'
    assert job.market_cutoff(dt.datetime.fromisoformat('2026-11-16T06:59:59+00:00')) == '20261115'
    assert job.market_cutoff(dt.datetime.fromisoformat('2026-11-16T07:00:00+00:00')) == '20261116'
    pointer = {"day": "20261113", "bars": 35304971, "index": "a" * 64}
    from subprocess import CompletedProcess
    state = CompletedProcess([], 0, stdout=json.dumps(pointer))
    with (patch.object(job.download, "authenticate"), patch.object(sync, "token", "test-only"),
          patch.object(job, "command", return_value=state) as call,
          patch.object(job, "restore_base") as restore,
          patch.object(sync, "api", return_value=[{"cal_date": "20261113"}])):
        job.publish("20261115", 120, 4, cloud=True)
        assert call.call_count == 1 and not restore.called
    with (patch.object(job.download, "authenticate"), patch.object(sync, "token", "test-only"),
          patch.object(job, "command", return_value=state) as call,
          patch.object(job, "scheduled_session", return_value="20261116"),
          patch.object(job.download, "last_session", return_value="20261113")):
        try:
            job.publish("20261116", 120, 4, cloud=True)
        except RuntimeError as exc:
            assert "尚未就绪" in str(exc)
        else:
            raise AssertionError("不应将交易日尚未到达的数据记为更新成功。")
        assert call.call_count == 1


def check_reuse(source, store):
    latest = max((source / "snapshot").glob("*.gz")).stem
    original = sync.read(source / "snapshot" / (latest + ".gz"))
    days = [r[0] for r in sync.read(source / "series/000001.SH.gz")["bars"]][-180:]
    old = max(d for d in days if d[:6] != latest[:6])
    assert 1 < days.index(old) < len(days) - 1
    for d in days:
        for group in ("pb", "open-bands"):
            folder = store / group
            folder.mkdir(exist_ok=True)
            shutil.copyfile(source / group / (d + ".gz"), folder / (d + ".gz"))
    added = "000002.SZ"
    template = next(r for r in original["items"] if r[0] == "000001.SZ")
    new_row = [added, "测试新增证券", *template[2:6], days[days.index(old) + 1], None, *template[8:]]
    for d in (old, latest):
        rows = original["items"] + ([new_row] if d == latest else [])
        sync.save(store / "snapshot" / (d + ".gz"), dict(original, day=d, items=rows))
        coverage = []
        for row in rows:
            code = row[0]
            security = sync.read(source / "series" / ((template[0] if code == added else code) + ".gz"))
            bars = [r for r in security["bars"] if days[0] <= r[0] <= d and (code != added or old < r[0])]
            status = "ready" if bars else "empty"
            sync.save(store / "series" / (code + ".gz"), dict(symbol=code, until=d, status=status, bars=bars))
            coverage.append([code, row[2], status, len(bars), bars[0][0] if bars else None, bars[-1][0] if bars else None])
        sync.save(store / "coverage" / (d + ".gz"), coverage)
        folder, base = price_inputs(store, d)
        portfolio_inputs.value_build(store, d, base, folder)
        opening_limits.build(store, d, folder / "opening.json")
    expected_values = (folder / "value-digests.json").read_bytes()
    expected_opening = (folder / "opening-execution.gz").read_bytes()
    for d in days:
        if d < old:
            for group in ("pb", "open-bands"):
                (store / group / (d + ".gz")).unlink()
    assert build.reusable_history(store, old, latest, days)
    portfolio_inputs.value_build(store, latest, base, folder, previous=old)
    opening_limits.build(store, latest, folder / "opening.json", previous=old)
    assert (folder / "value-digests.json").read_bytes() == expected_values
    assert (folder / "opening-execution.gz").read_bytes() == expected_opening
    backfill = sync.read(store / "series" / (added + ".gz"))
    backfill["bars"].insert(0, [old, *backfill["bars"][0][1:]])
    sync.save(store / "series" / (added + ".gz"), backfill)
    assert not build.reusable_history(store, old, latest, days)
    print(f"PASS: {len(days)} sessions through {latest}, new symbol and code-index remap; all PB rankings and opening constraints exactly match a full rebuild.")


if __name__ == "__main__":
    check_calendars()
    with TemporaryDirectory() as tmp:
        check_reuse(ROOT / ".private/walkthrough/history", Path(tmp))
