"""Publishable news edition. The market archive supplies stock names only."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xuheng.archive import Archive
from xuheng.news import fetch, from_catalog
from xuheng.news_store import edition_key, read_file, write_file
from xuheng.packed_archive import PackedArchive, current_release, market_reader


def update(destination, database=None):
    with tempfile.TemporaryDirectory() as directory:
        if database:
            store = Archive(database)
        else:
            config = json.loads((ROOT / "static/full-release.json").read_bytes())
            key = market_reader(os.environ["TUSHARE_TOKEN"])
            live = current_release(config, key, directory)
            store = PackedArchive(directory, config["origin"], live["index"], key)
        edition = fetch(from_catalog(store))
    old = read_file(destination)
    if old and (edition_key(old) > edition_key(edition) or old["articles"] == edition["articles"]):
        print("No newer edition.")
        return
    write_file(destination, edition)
    print(f'Validated {len(edition["articles"])} unique headlines through {edition["articles"][0]["time"]} CST.')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    update(args.destination, args.database)
