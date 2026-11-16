"""Read one stock's month-end valuations from the same Tushare archive as the factor desk."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from functools import lru_cache
import gzip
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading

from .study_store import content, edition


_workers = ThreadPoolExecutor(max_workers=3, thread_name_prefix="stock-valuations")
_locks = [threading.Lock() for _ in range(16)]


def year_records(key, digest, reader, folder, symbols):
    path = folder / (digest + ".sqlite")
    with _locks[int(digest[:2], 16) % len(_locks)]:
        if not path.is_file():
            # Populate the server's local index once per immutable source file.
            # Other visitors subsequently read only their selected stock's row.
            raw = content({"files": {key: digest}}, key, reader)
            groups = defaultdict(list)
            for day, market in sorted(json.loads(gzip.decompress(raw)).items()):
                for symbol, (pb, pe, _) in market.items():
                    groups[symbol].append([day, pe, pb])
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=folder, delete=False) as tmp:
                temp = Path(tmp.name)
            try:
                with closing(sqlite3.connect(temp)) as db:
                    db.execute("CREATE TABLE history(code TEXT PRIMARY KEY, rows TEXT) WITHOUT ROWID")
                    db.executemany("INSERT INTO history VALUES (?,?)", (
                        (symbol, json.dumps(rows, separators=(",", ":"), allow_nan=False))
                        for symbol, rows in groups.items()))
                    db.commit()
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
    merged = {}
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro&immutable=1", uri=True)) as db:
        for sym in symbols:  # canonical code last, including Beijing renumberings
            record = db.execute("SELECT rows FROM history WHERE code=?", (sym,)).fetchone()
            if record:
                merged.update((r[0], r) for r in json.loads(record[0]))
    return [merged[d] for d in sorted(merged)]


@lru_cache(maxsize=128)
def history(files, reader, folder, symbols, start, end):
    pending = [_workers.submit(year_records, key, digest, reader, folder, symbols) for key, digest in files]
    return [r for f in pending for r in f.result() if start <= r[0] <= end]


def valuation_history(store, code):
    if store.manifest.get("sample"):
        return dict(day=store.day, edition=None, rows=[])
    index = edition(store)
    security = store.catalog[code]
    start = max(security[6] or "20000101", "20211115" if code.endswith(".BJ") else "20000101")
    end = min(security[7] or store.day, index["day"])
    files = tuple(sorted((k, v) for k, v in index["files"].items()
                         if k.startswith("values/") and start[:4] <= k.split("/")[1] <= end[:4]))
    aliases = tuple(sorted(c for c, target in store.snapshot.get("aliases", {}).items() if c != code and target == code))
    reader = getattr(store, "service", "")
    folder = Path(tempfile.gettempdir()) / "xuheng-stock-values-v1" if reader else store.root / ".stock-values-v1"
    return dict(day=store.day, edition=index["day"], rows=history(files, reader, folder, (*aliases, code), start, end))
