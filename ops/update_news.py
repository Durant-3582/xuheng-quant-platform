"""Publishable news edition. The market archive supplies stock names only."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xuheng.archive import Archive
from xuheng.news import CHINA, DATE_FORMAT, NewsError, fetch, from_catalog
from xuheng.news_store import edition_key, read_file, write_file
from xuheng.packed_archive import PackedArchive, current_release, market_reader


def update(destination, database=None, if_due=False):
    old = read_file(destination)
    if if_due and old:
        from ops.cloud_clock import scheduled_slots
        news_slot, _ = scheduled_slots(datetime.now(CHINA))
        stamp = datetime.strptime(old['checked'], DATE_FORMAT).replace(tzinfo=CHINA).timestamp()
        if stamp >= news_slot:
            print(f'本轮已于 {old["checked"]} 完成采集。')
            return
    with tempfile.TemporaryDirectory() as directory:
        if database:
            store = Archive(database)
        else:
            config = json.loads((ROOT / "static/full-release.json").read_bytes())
            key = market_reader(os.environ["TUSHARE_TOKEN"])
            live = current_release(config, key, directory)
            store = PackedArchive(directory, config["origin"], live["index"], key)
        directory_map = from_catalog(store)
        try:
            edition = fetch(directory_map)
        except NewsError:
            time.sleep(5)
            edition = fetch(directory_map)
    if old and edition_key(old) >= edition_key(edition):
        print(f'Preserved the edition through {old["articles"][0]["time"]}.')
        return
    write_file(destination, edition)
    print(f'Checked at {edition["checked"]} Shanghai time: {len(edition["articles"])} unique headlines through {edition["articles"][0]["time"]}.')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--if-due", action="store_true")
    args = parser.parse_args()
    update(args.destination, args.database, args.if_due)
