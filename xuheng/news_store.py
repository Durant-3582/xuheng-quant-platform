"""Keep the latest valid news edition available across visitors and failed updates."""
from datetime import datetime
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time

import requests

from .news import ARTICLE_ID, DATE_FORMAT, LIMIT, SECTORS, NewsError, fetch, from_catalog


ARCHIVE = "https://raw.githubusercontent.com/Durant-3582/xuheng-quant-platform/news-data/latest.json"


def checked(edition):
    try:
        if edition["format"] != 1 or not 0 < len(edition["articles"]) <= LIMIT:
            raise ValueError
        datetime.strptime(edition["checked"], DATE_FORMAT)
        seen = set()
        for row in edition["articles"]:
            if not ARTICLE_ID.fullmatch(row["id"]) or row["id"] in seen:
                raise ValueError
            seen.add(row["id"])
            datetime.strptime(row["time"], DATE_FORMAT)
            if (not isinstance(row["title"], str) or not row["title"].strip()
                    or not math.isfinite(row["score"]) or not 0 <= row["score"] <= 100
                    or not isinstance(row["sectors"], list) or not all(s in SECTORS for s in row["sectors"])
                    or not isinstance(row["stocks"], list) or not all(isinstance(s, str) for s in row["stocks"])):
                raise ValueError
        edition["articles"].sort(key=lambda row: (row["time"], row["id"]), reverse=True)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise NewsError("新闻库中的样本未通过校验。") from exc
    return edition


def read_file(path):
    try:
        return checked(json.loads(path.read_bytes()))
    except (OSError, ValueError):
        return None


def write_file(path, edition):
    checked(edition)
    path.parent.mkdir(exist_ok=True, parents=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
            tmp = Path(out.name)
            json.dump(edition, out, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def archive_edition():
    try:
        with requests.get(ARCHIVE, params={"v": int(time.time()) // 300}, timeout=(3, 5)) as response:
            response.raise_for_status()
            return checked(response.json())
    except (requests.RequestException, ValueError) as exc:
        raise NewsError("暂时无法同步已归档的新闻。") from exc


def edition_key(edition):
    return edition["articles"][0]["time"], edition["checked"]


class NewsCache:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.edition = None
        self.next_sync = 0
        self.next_refresh = 0
        self.notice = ""

    def get(self, store, refresh=False):
        with self.lock:
            now = time.monotonic()
            if self.edition is None:
                self.edition = read_file(self.path)
            due = self.next_refresh if refresh else self.next_sync
            if now < due:
                if self.edition:
                    return {**self.edition, "notice": self.notice}
                raise NewsError(self.notice)
            try:
                if refresh:
                    fresh = fetch(from_catalog(store))
                else:
                    try:
                        fresh = archive_edition()
                    except NewsError:
                        if self.edition:
                            raise
                        fresh = fetch(from_catalog(store))
                if not self.edition or edition_key(fresh) >= edition_key(self.edition):
                    self.edition = fresh
                    try:
                        write_file(self.path, fresh)
                    except OSError:
                        pass  # The shared memory cache and the scheduled archive remain usable.
                self.notice = ""
                self.next_sync = now + 300
            except NewsError as exc:
                if refresh and not self.edition:
                    try:
                        self.edition = archive_edition()
                    except NewsError:
                        pass
                self.notice = str(exc)
                self.next_sync = now + 30
            if refresh:
                self.next_refresh = now + 30
            if not self.edition:
                raise NewsError(self.notice)
            return {**self.edition, "notice": self.notice}


cache = NewsCache(Path(tempfile.gettempdir()) / "xuheng-news-v1" / "latest.json")
