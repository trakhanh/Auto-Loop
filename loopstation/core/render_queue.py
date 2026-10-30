"""Hàng đợi xuất: nhiều dự án chạy lần lượt (ví dụ để chạy qua đêm), lưu lại khi đóng app."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .project import Project

STATUS_LABELS = {"pending": "Đang chờ", "running": "Đang chạy", "done": "Xong", "error": "Lỗi",
                 "cancelled": "Đã huỷ"}
KIND_LABELS = {"video": "Video", "audio": "Nhạc"}


@dataclass(eq=False)  # so sánh theo đối tượng, không theo nội dung
class QueueItem:
    project: Project
    output: str
    kind: str = "video"  # video | audio
    status: str = "pending"
    message: str = ""
    summary: str = ""  # "Tập 33 · tình huống 1 → 10 · 39 dòng · dài 1:05:00" (tính lúc thêm, hiện ở hàng đợi)
    seconds: float = 0.0  # độ dài file sẽ xuất — ước tính giờ xong của hàng đợi

    @property
    def finished(self) -> bool:
        return self.status in ("done", "error", "cancelled")

    def to_dict(self) -> dict:
        return {"project": self.project.to_dict(None), "output": self.output, "kind": self.kind,
                "status": self.status, "message": self.message, "summary": self.summary, "seconds": self.seconds}

    @classmethod
    def from_dict(cls, d: dict) -> "QueueItem":
        status = d.get("status", "pending")
        if status == "running":  # app bị tắt giữa chừng → chạy lại
            status = "pending"
        return cls(project=Project.from_dict(d["project"], None), output=d["output"],
                   kind=d.get("kind", "video"), status=status, message=d.get("message", ""),
                   summary=d.get("summary", ""), seconds=float(d.get("seconds", 0.0) or 0.0))


def eta_text(sec: float) -> str:
    """"~4 phút", "~1 giờ 20 phút" — ước tính, làm tròn cho dễ đọc."""
    m = max(1, int(round(sec / 60)))
    return f"~{m} phút" if m < 60 else f"~{m // 60} giờ" + (f" {m % 60} phút" if m % 60 else "")


def fmt_len(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def describe(project: Project, kind: str = "video", total: float = 0.0) -> str:
    """Tóm tắt một mục hàng đợi để biết bên trong có gì, không cần mở ra:
    "Tập 33 · tình huống 1 → 10 · 39 dòng · dài 1:05:00", "12 dòng · dài 3:00:00", "Nhạc · 8 bài · dài 1:00:00"."""
    from . import table_preset as tp
    parts: list[str] = []
    if kind == "audio":
        parts.append(f"Nhạc · {sum(1 for t in project.music.tracks if t.enabled)} bài")
    else:
        clips = [c for c in project.video.clips if c.enabled]
        paths = [c.path for c in clips]
        eps = tp.episodes(paths)
        if eps:
            parts.append("Tập " + ", ".join(map(str, eps)))
        stts = sorted({n for n in map(tp.stt_of, paths) if n is not None})
        if len(stts) > 1:
            parts.append(f"tình huống {stts[0]} → {stts[-1]}")
        parts.append(f"{len(clips)} dòng")
    if total > 0:
        parts.append(f"dài {fmt_len(total)}")
    return " · ".join(parts)


def signature(project: Project, kind: str = "video") -> tuple:
    """Nội dung chính của một mục (để báo khi lỡ thêm cùng một video hai lần)."""
    if kind == "audio":
        return ("audio", tuple(t.path.lower() for t in project.music.tracks if t.enabled))
    v = project.video
    return ("video", tuple((c.path.lower(), c.plays_mode, c.count, c.min, c.max, c.play_seconds)
                           for c in v.clips if c.enabled), v.intro.lower(), v.outro.lower())


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
