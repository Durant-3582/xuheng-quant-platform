"""Package a dated release into private, immutable SQLite shards for Streamlit."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
import zlib
from collections import Counter
from pathlib import Path


def digest(path):
    with path.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest()


def read(path):
    with gzip.open(path, "rt") as src:
        return json.load(src)


def zipped(value):
    return gzip.compress(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(), mtime=0)


def pack(history, output, day, *, sample=False):
    snapshot = history / "snapshot" / (day + ".gz")
    market = read(snapshot)
    research = history / "research" / day
    bands = read(research / "opening-execution.gz")
    verified = {}
    for listing in ["digests.json", "portfolio-digests.json", "days-digests.json",
                    "bench-digests.json", "value-digests.json"]:
        for name, checksum in json.loads((research / listing).read_bytes()).items():
            if "/" in name or name in (".", ".."):
                raise ValueError("研究文件名无效。")
            key = f"research/{day}/{name}"
            if key in verified:
                raise ValueError("重复的研究文件 " + name)
            verified[key] = checksum
    if market["day"] != day or bands["cutoff"] != day:
        raise ValueError("行情目录与开盘成交规则的截止日不一致。")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir=output) as tmp:
        stage = Path(tmp)
        databases = {}
        def put(shard, key, value):
            if shard not in databases:
                db = sqlite3.connect(stage / (shard + ".sqlite"))
                db.execute("PRAGMA journal_mode=OFF")
                db.execute("CREATE TABLE objects (key TEXT PRIMARY KEY, value BLOB NOT NULL) WITHOUT ROWID")
                databases[shard] = db
            databases[shard].execute("INSERT INTO objects VALUES (?,?)", (key, value))
        try:
            put("catalog", "snapshot", snapshot.read_bytes())
            put("catalog", "opening-execution", zipped(bands))
            coverage = []
            stats = Counter()
            for row in sorted(market["items"], key=lambda item: item[0]):
                code, _, kind = row[:3]
                blob = (history / "series" / (code + ".gz")).read_bytes()
                item = json.loads(gzip.decompress(blob))
                bars = item["bars"]
                if item["symbol"] != code or item["until"] != day or (item["status"] == "ready") != bool(bars):
                    raise ValueError("日线归档不匹配："+code)
                coverage.append([code, kind, item["status"], len(bars), bars[0][0] if bars else None, bars[-1][0] if bars else None])
                stats["bars"] += len(bars)
                stats[item["status"]] += 1
                suffix = zlib.crc32(code.encode()) % 32
                put(f"quotes-{suffix:02d}", "series/"+code, blob)
            put("catalog", "coverage", zipped(coverage))
            print(f"日线目录 {len(coverage):,} 个标的，{stats['bars']:,} 条收盘记录。", flush=True)
            for key, checksum in sorted(verified.items()):
                if not key.startswith(f"research/{day}/"):
                    raise ValueError("研究数据日期不匹配。")
                blob = (history / (key + ".gz")).read_bytes()
                if hashlib.sha256(blob).hexdigest() != checksum:
                    raise ValueError("研究分片内容与本次构建记录不符："+key)
                short = key.rsplit("/", 1)[1]
                year = re.match(r"(?:portfolio-|days-|(?:value|bench)-[dm])(20\d{2})", short)
                put("research-"+year[1] if year else "catalog", key, blob)
            for group in ("financial", "members"):
                for path in sorted((history/group).glob("*/*.gz")):
                    put("catalog", str(path.relative_to(history).with_suffix("")), path.read_bytes())
        finally:
            for db in databases.values():
                db.commit()
                db.close()
        files = {}
        for path in sorted(stage.glob("*.sqlite")):
            sha = digest(path)
            name = path.stem+"-"+sha[:16]+".sqlite"
            files[path.stem] = {"file": name, "bytes": path.stat().st_size, "sha256": sha}
            path.replace(output/name)
        meta = {"format": 1, "day": day, "sample":sample, "bars": stats["bars"], "securities": len(coverage),
                "ready": stats["ready"], "empty": stats["empty"], "denied": stats["denied"],
                "research_parts": len(verified), "files": files}
        calendar=history/'calendar'/(day+'.gz')
        if calendar.is_file():
            meta.update(read(calendar))
        manifest = stage / "manifest.json"
        manifest.write_text(json.dumps(meta, sort_keys=True, separators=(",", ":"))+"\n")
        manifest.replace(output/"manifest.json")
        print(f"{len(files)} 个私有分片已生成，共 {sum(v['bytes'] for v in files.values())/2**30:.2f} GiB。",flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--day",required=True)
    args=parser.parse_args()
    if not re.fullmatch(r"20\d{6}",args.day):
        sys.exit("日线日期无效。")
    pack(args.history.resolve(),args.output.resolve(),args.day)
