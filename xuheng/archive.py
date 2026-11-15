from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
import zlib
from functools import cached_property, lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import requests

YEAR = re.compile(r"(?:portfolio-|days-|(?:value|bench)-[dm])(20\d{2})")
CODE = re.compile(r"[A-Z0-9_-]{1,32}\.[A-Z]{2,6}")


class ArchiveError(ValueError):
    pass


class Archive:
    """Open immutable slices on demand, without exposing a data endpoint to browsers."""

    def __init__(self, directory, base="", token="", repo="", tag=""):
        self.root = Path(directory)
        self.base = base.rstrip("/")
        self.token = token
        self.release = None
        self.remote = bool(self.base or repo)
        self._lock = threading.Lock()
        if self.remote:
            if self.base and (repo or urlsplit(self.base).scheme != "https" or urlsplit(self.base).query or urlsplit(self.base).username):
                raise ArchiveError("私有数据源须使用 HTTPS 目录地址。")
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                if repo:
                    from .private_release import PrivateRelease
                    self.release = PrivateRelease(repo,tag,token)
                res = self._get("manifest.json")
                try:
                    self.manifest = res.json()
                finally:
                    res.close()
            except ArchiveError:
                raise
            except (requests.RequestException, KeyError, ValueError) as err:
                raise ArchiveError("未能读取私有行情目录，请检查数据源连接。") from err
        else:
            try:
                self.manifest = json.loads((self.root / "manifest.json").read_bytes())
            except (OSError, ValueError) as err:
                raise ArchiveError("尚未连接本期私有行情库。") from err
        if self.manifest.get("format") != 1 or not re.fullmatch(r"20\d{6}", self.manifest.get("day","")):
            raise ArchiveError("行情目录格式无效。")
        self.day = self.manifest["day"]

    def _get(self, name):
        if self.release:
            return self.release.get(name)
        headers = {"Authorization": "Bearer "+self.token} if self.token else {}
        response = requests.get(self.base+"/"+name, headers=headers, stream=True, timeout=(8,90))
        response.raise_for_status()
        return response

    @lru_cache(maxsize=128)
    def _path(self, shard):
        try:
            spec = self.manifest["files"][shard]
            filename, checksum = spec["file"], spec["sha256"]
            if not re.fullmatch(r"[a-z0-9-]+\.sqlite",filename) or not re.fullmatch(r"[a-f0-9]{64}",checksum):
                raise ArchiveError("分片文件名或校验值无效。")
            path = self.root / filename
            if not self.remote:
                if path.stat().st_size != spec["bytes"]:
                    raise ArchiveError("本地行情分片不完整。")
                return path
            with self._lock:
                if path.is_file() and path.stat().st_size == spec["bytes"]:
                    with path.open("rb") as cached:
                        if hashlib.file_digest(cached,"sha256").hexdigest()==checksum:
                            return path
                tmp = None
                try:
                    with self._get(filename) as response, tempfile.NamedTemporaryFile(dir=self.root, delete=False) as out:
                        tmp = Path(out.name)
                        sha = hashlib.sha256()
                        for block in response.iter_content(256 * 1024):
                            sha.update(block)
                            out.write(block)
                    if sha.hexdigest() != checksum or tmp.stat().st_size != spec["bytes"]:
                        raise ArchiveError("下载的行情分片与目录版本不一致。")
                    os.replace(tmp, path)
                finally:
                    if tmp:
                        tmp.unlink(missing_ok=True)
            return path
        except (KeyError,OSError,requests.RequestException) as err:
            raise ArchiveError("无法读取所需的私有数据分片。") from err

    def _blob(self, key, optional=False):
        if key.startswith("series/"):
            shard = f"quotes-{zlib.crc32(key[7:].encode()) % 32:02d}"
        else:
            match = YEAR.match(key.rsplit("/",1)[-1]) if key.startswith("research/") else None
            shard = "research-"+match[1] if match else "catalog"
        uri = self._path(shard).resolve().as_uri()+"?mode=ro&immutable=1"
        db = sqlite3.connect(uri,uri=True)
        try:
            row = db.execute("SELECT value FROM objects WHERE key=?",(key,)).fetchone()
        finally:
            db.close()
        if row:
            return gzip.decompress(row[0])
        if not optional:
            raise ArchiveError("该日期的行情或研究数据尚未就绪。")
        return None

    def json(self, key, optional=False):
        data = self._blob(key, optional)
        return json.loads(data) if data is not None else None

    def research(self, name):
        return self.json(f"research/{self.day}/{name}")

    @cached_property
    def snapshot(self):
        item = self.json("snapshot")
        if item["day"] != self.day:
            raise ArchiveError("行情目录日期不一致。")
        return item

    @cached_property
    def catalog(self):
        return {row[0]: row for row in self.snapshot["items"]}

    @cached_property
    def coverage(self):
        return self.json("coverage")

    @lru_cache(maxsize=12)
    def series(self, code):
        obj = self.json("series/"+code)
        if obj["until"] != self.day or obj["symbol"] != code:
            raise ArchiveError("证券日线与行情目录的代码或日期不一致。")
        return obj

    @cached_property
    def bands(self):
        obj = self.json("opening-execution")
        if obj["format"] != 1 or obj["cutoff"] != self.day:
            raise ArchiveError("开盘限价研究样本日期不一致。")
        return obj

    @cached_property
    def factor_index(self):
        return self.research("open-index")

    @cached_property
    def factors(self):
        obj = self.json(self.factor_index["factors"])
        if obj["day"] != self.day:
            raise ArchiveError("因子样本日期不一致。")
        return obj

    @cached_property
    def daily(self):
        obj = self.research("days-index")
        if obj["day"] != self.day or obj["format"] != 1 or len(obj["dates"]) != len(obj["market"]):
            raise ArchiveError("逐日交易日历不完整。")
        return obj

    @cached_property
    def months(self):
        obj = self.research("portfolio-index")
        if obj["day"] != self.day:
            raise ArchiveError("月度目录日期不一致。")
        return obj

    @cached_property
    def stock_life(self):
        return dict(zip(self.bands["codes"],self.bands["life"],strict=True))

    @cached_property
    def band_ids(self):
        return {c:i for i,c in enumerate(self.bands["codes"])}

    @cached_property
    def date_ids(self):
        return {day:i for i,day in enumerate(self.daily["dates"])}

    @lru_cache(maxsize=2)
    def supplement(self, group):
        obj = self.research(group+"-index")
        if obj["day"] != self.day or obj["base"] != self.daily["version"]:
            raise ArchiveError("研究扩展与交易日历的版本不一致。")
        return obj
