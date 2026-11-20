"""Danh sách tải video: các dòng (video lẻ hoặc thuộc một nhóm danh sách phát / kênh), tick, trạng thái, lưu ra
<thư mục dữ liệu>/downloads.json để mở lại app vẫn còn."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .downloader import Group, Item

QUEUE_FILE = "downloads.json"
GROUP_PAGE = 50
STATUSES = ("pending", "running", "done", "exists", "error")


@dataclass
class Entry:
    url: str
    vid: str
    title: str
    platform: str
    duration: float
    thumbnail: str
    group: str = ""  # url nhóm ("" = video lẻ)
    checked: bool = True
    status: str = "pending"
    message: str = ""
    path: str = ""
    codec: str = ""
    section: str = ""  # "60-150" = chỉ tải đoạn 1:00–2:30


@dataclass
class GroupInfo:
    url: str
    title: str
    count: int
    loaded: int


@dataclass
class DownloadQueue:
    entries: list[Entry] = field(default_factory=list)
    groups: dict[str, GroupInfo] = field(default_factory=dict)

    def _has(self, item: Item) -> bool:
        return any(e.vid == item.vid and e.platform == item.platform for e in self.entries)

    def _entry(self, item: Item, group: str, checked: bool) -> Entry:
        return Entry(url=item.url, vid=item.vid, title=item.title, platform=item.platform, duration=item.duration,
                     thumbnail=item.thumbnail, group=group, checked=checked)

    def add_item(self, item: Item, group: str = "", checked: bool = True) -> Entry | None:
        if self._has(item):
            return None
        e = self._entry(item, group, checked)
        self.entries.append(e)
        return e

    def add_group(self, g: Group) -> list[Entry]:
        self.groups[g.url] = GroupInfo(g.url, g.title, g.count, len(g.items))
        return [e for e in (self.add_item(i, g.url, True) for i in g.items) if e is not None]

    def extend_group(self, url: str, items: list[Item]) -> list[Entry]:
        gi = self.groups.get(url)
        if gi is not None:
            gi.loaded += len(items)
        return [e for e in (self.add_item(i, url, False) for i in items) if e is not None]

    def next_pending(self) -> Entry | None:
        return next((e for e in self.entries if e.checked and e.status == "pending"), None)

    def running(self) -> list[Entry]:
        return [e for e in self.entries if e.status == "running"]

    def remaining(self) -> int:
        return sum(1 for e in self.entries if e.checked and e.status in ("pending", "running"))

    def done_count(self) -> int:
        return sum(1 for e in self.entries if e.status in ("done", "exists"))

    def counter_text(self) -> str:
        left = self.remaining()
        return f"{self.done_count()}/{self.done_count() + left}" if left else ""

    def stop_all(self) -> None:
        for e in self.running():
            e.status = "pending"

    def retry(self, e: Entry) -> None:
        e.status, e.message, e.checked = "pending", "", True

    def remove(self, e: Entry) -> None:
        self.entries.remove(e)
        if e.group and not any(x.group == e.group for x in self.entries):
            self.groups.pop(e.group, None)

    def clear(self) -> None:
        self.entries.clear()
        self.groups.clear()

    def to_json(self) -> dict:
        return {"entries": [asdict(e) for e in self.entries], "groups": [asdict(g) for g in self.groups.values()]}

    def save(self, path: Path) -> None:
        tmp = Path(path).with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_json(), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> "DownloadQueue":
        q = cls()
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            names = {f.name for f in fields(Entry)}
            for raw in data.get("entries", []):
                e = Entry(**{k: v for k, v in raw.items() if k in names})
                if e.status == "running" or e.status not in STATUSES:
                    e.status = "pending"
                q.entries.append(e)
            for raw in data.get("groups", []):
                g = GroupInfo(**raw)
                q.groups[g.url] = g
        except (OSError, ValueError, TypeError, AttributeError):
            return cls()
        return q
