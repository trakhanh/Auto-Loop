"""Hàng đợi xuất: nhiều dự án chạy lần lượt (ví dụ để chạy qua đêm), lưu lại khi đóng app."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .project import Project

STATUS_LABELS = {"pending": "Chờ", "running": "Đang chạy", "done": "Xong", "error": "Lỗi",
                 "cancelled": "Đã huỷ"}
KIND_LABELS = {"video": "Video", "audio": "Nhạc"}


@dataclass(eq=False)  # so sánh theo đối tượng, không theo nội dung
class QueueItem:
    project: Project
    output: str
    kind: str = "video"  # video | audio
    status: str = "pending"
    message: str = ""

    @property
    def finished(self) -> bool:
        return self.status in ("done", "error", "cancelled")

    def to_dict(self) -> dict:
        return {"project": self.project.to_dict(None), "output": self.output, "kind": self.kind,
                "status": self.status, "message": self.message}

    @classmethod
    def from_dict(cls, d: dict) -> "QueueItem":
        status = d.get("status", "pending")
        if status == "running":  # app bị tắt giữa chừng → chạy lại
            status = "pending"
        return cls(project=Project.from_dict(d["project"], None), output=d["output"],
                   kind=d.get("kind", "video"), status=status, message=d.get("message", ""))


def save(items: list[QueueItem], path: Path) -> None:
    from .project import atomic_write
    atomic_write(path, json.dumps([i.to_dict() for i in items], ensure_ascii=False, indent=1))


def load(path: Path) -> list[QueueItem]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = None
    items, bad = [], data is None or not isinstance(data, list)
    for d in data if isinstance(data, list) else []:
        try:
            items.append(QueueItem.from_dict(d))
        except Exception:  # noqa: BLE001
            bad = True
    if bad:  # giữ lại bản gốc để không mất dữ liệu khi lưu đè
        try:
            path.with_name(path.stem + ".hong.json").write_bytes(path.read_bytes())
        except OSError:
            pass
    return items


def unique_output(path: str, taken: set[str]) -> str:
    """Thêm hậu tố _2, _3… nếu đường dẫn đã có trên đĩa hoặc trong hàng đợi."""
    p = Path(path)
    cand, n = p, 2
    while str(cand).lower() in taken or cand.exists():
        cand = p.with_name(f"{p.stem}_{n}{p.suffix}")
        n += 1
    return str(cand)
