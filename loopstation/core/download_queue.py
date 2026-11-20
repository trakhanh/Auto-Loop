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
    index: int = 0  # vị trí trong nhóm (1, 2, 3…; 0 = video lẻ) — cho tên file "Số thứ tự – Tiêu đề"
    unread: bool = False  # dòng "đọc link lỗi": url là link gốc (có thể cả kênh) — chỉ được đọc lại, không tải


@dataclass
class GroupInfo:
    url: str
    title: str
    count: int  # 0 = chưa biết (kênh đọc lười không báo tổng)
    loaded: int
    complete: bool = False  # đã đọc hết (không còn "Hiện thêm")


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

    @staticmethod
    def _complete(gi: GroupInfo, got: int, page: int) -> bool:
        return (gi.count > 0 and gi.loaded >= gi.count) or got < page

    def _add_numbered(self, items: list[Item], url: str, start: int, tick: bool, max_sec: float) -> list[Entry]:
        out = []
        for n, i in enumerate(items, start):
            e = self.add_item(i, url, tick and not (max_sec and i.duration > max_sec))
            if e is not None:
                e.index = n
                out.append(e)
        return out

    def add_group(self, g: Group, page: int = GROUP_PAGE, max_sec: float = 0) -> list[Entry]:
        """Nhóm mới: tick sẵn lượt đọc đầu, trừ video dài hơn `max_sec` (gợi ý — người dùng tick lại được)."""
        gi = GroupInfo(g.url, g.title, g.count, len(g.items))
        gi.complete = self._complete(gi, len(g.items), page)
        self.groups[g.url] = gi
        return self._add_numbered(g.items, g.url, 1, True, max_sec)

    def extend_group(self, url: str, items: list[Item], page: int = GROUP_PAGE, max_sec: float = 0) -> list[Entry]:
        gi = self.groups.get(url)
        start = (gi.loaded + 1) if gi is not None else 1
        if gi is not None:
            gi.loaded += len(items)
            gi.complete = self._complete(gi, len(items), page)
        return self._add_numbered(items, url, start, False, max_sec)

    def add_unread(self, link: str, message: str) -> Entry | None:
        """Dòng báo "đọc link lỗi" (không tick, không bao giờ được tải; Thử lại = đọc lại link)."""
        if any(e.unread and e.url == link for e in self.entries):
            return None
        e = Entry(url=link, vid=link, title=link, platform="", duration=0, thumbnail="", checked=False,
                  status="error", message=message, unread=True)
        self.entries.append(e)
        return e

    def next_pending(self) -> Entry | None:
        return next((e for e in self.entries if e.checked and e.status == "pending" and not e.unread), None)

    def running(self) -> list[Entry]:
        return [e for e in self.entries if e.status == "running"]

    def remaining(self) -> int:
        return sum(1 for e in self.entries if e.checked and e.status in ("pending", "running") and not e.unread)

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
