"""Restore the private inputs needed by a fresh post-close runner."""
import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ops.upload_private import MAX_SIZE, ORIGIN, SHA, Publisher, validate_pointer

SYMBOL = r"[A-Z0-9_-]{1,32}\.[A-Z]{2,6}"
SERIES = re.compile(rf"series/({SYMBOL})")
DETAIL = re.compile(rf"(financial|members)/({SYMBOL})/(20\d{{6}})")
VALUE_PART = re.compile(r"value-d20\d{4}-[a-f0-9]{64}")


def get_object(publisher, digest, size=None):
    if not isinstance(digest, str) or not SHA.fullmatch(digest):
        raise ValueError("行情对象编号无效。")
    with publisher.request("GET", "/v1/objects/" + digest, {200}, stream=True) as reply:
        length = int(reply.headers["Content-Length"])
        if (not 0 < length <= MAX_SIZE or (size is not None and size != length)
                or reply.headers.get("X-Archive-SHA256") != digest):
            raise ValueError("行情对象回执与索引不符。")
        data = reply.content
    if len(data) != length or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("云端行情对象未通过 SHA-256 校验。")
    return data


def input_path(key, cutoff):
    if match := SERIES.fullmatch(key):
        return Path("series", match[1] + ".gz")
    if match := DETAIL.fullmatch(key):
        if match[3] <= cutoff:
            return Path(match[1], match[2], match[3] + ".gz")
    if key in ("snapshot", "coverage"):
        return Path(key, cutoff + ".gz")
    if key == "opening-execution":
        return Path("research", cutoff, key + ".gz")
    prefix = f"research/{cutoff}/"
    if key.startswith(prefix):
        name = key[len(prefix):]
        if name in ("value-index", "days-index") or VALUE_PART.fullmatch(name):
            return Path("research", cutoff, name + ".gz")
    return None


def extract_records(publisher, descriptor, history, cutoff):
    groups = defaultdict(list)
    for key, record in descriptor["items"].items():
        path = input_path(key, cutoff)
        if path is None:
            continue
        pack, offset, length, digest = record
        size = descriptor["sizes"][pack]
        if (type(size) is not int or not 0 < size <= MAX_SIZE or type(offset) is not int
                or type(length) is not int or not 0 < length <= size or not 0 <= offset <= size-length
                or not SHA.fullmatch(digest)):
            raise ValueError("行情恢复索引含有无效位置。")
        groups[pack].append((path, offset, length, digest))
    for pack, entries in groups.items():
        data = get_object(publisher, pack, descriptor["sizes"][pack])
        for path, offset, length, digest in entries:
            record = memoryview(data)[offset:offset + length]
            if hashlib.sha256(record).hexdigest() != digest or record[:3] != b"\x1f\x8b\x08":
                raise ValueError(f"行情记录校验失败 {path}")
            destination = history / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(record)


def read_json(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def restore(publisher, pointer, private):
    day = pointer["day"]
    # A restore is only for disposable runners. Never merge a partially restored
    # cloud image into an existing administrator's local database.
    if any((private / name).exists() for name in ("history", "database")):
        raise ValueError("恢复云端基线需要空的行情工作目录。")
    index = json.loads(gzip.decompress(get_object(publisher, pointer["index"])))
    manifest = index["manifest"]
    if (index["version"] != 1 or manifest["format"] != 1 or manifest["sample"] is not False
            or manifest["day"] != day or manifest["bars"] != pointer["bars"]):
        raise ValueError("恢复索引与线上正式版本不符。")
    private.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=private) as tmp:
        history = Path(tmp) / "history"
        extract_records(publisher, index, history, day)
        snapshot = read_json(history / "snapshot" / (day + ".gz"))
        codes = {row[0] for row in snapshot["items"]}
        if (snapshot["day"] != day or len(codes) != manifest["securities"]
                or codes != {p.stem for p in (history / "series").glob("*.gz")}):
            raise ValueError("恢复的证券目录与正式库不一致。")
        research = history / "research" / day
        days = read_json(research / "days-index.gz")
        value = read_json(research / "value-index.gz")
        opening = read_json(research / "opening-execution.gz")
        coverage = read_json(history / "coverage" / (day + ".gz"))
        if (days["day"] != day or days["dates"][-1] != day or value["day"] != day
                or opening["cutoff"] != day or value["base"] != days["version"]
                or opening["base"] != days["version"] or opening["codes"] != days["codes"]
                or {row[0] for row in coverage} != codes
                or sum(row[3] for row in coverage) != manifest["bars"]
                or set(value["parts"]) != {date[:6] for date in days["dates"]}):
            raise ValueError("历史估值、限价或日线覆盖与正式库不一致。")
        for key in value["parts"].values():
            part = input_path(key, day)
            if part is None or not VALUE_PART.fullmatch(part.stem) or not (history / part).is_file():
                raise ValueError("恢复的低 PB 排名缺少月份。")
        history.rename(private / "history")
        (private / "database").mkdir()
        (private / "database/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    print(f"已从正式库恢复 {day} 的 {len(codes):,} 个标的、{len(value['parts'])} 个月排名和历史成交限制。", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointer", required=True)
    args = parser.parse_args()
    restore(Publisher(ORIGIN), validate_pointer(json.loads(args.pointer)), ROOT / ".private")
