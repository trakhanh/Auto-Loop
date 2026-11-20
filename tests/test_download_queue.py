"""Danh sách tải video: tick, nhóm kênh, hàng chờ, dừng, lưu / khôi phục downloads.json."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loopstation.core.download_queue import DownloadQueue  # noqa: E402
from loopstation.core.downloader import Group, Item  # noqa: E402


def it(i, platform="YouTube"):
    return Item(url=f"https://y/v{i}", vid=f"v{i}", title=f"V{i}", platform=platform, duration=10, thumbnail="")


def test_add_dedupe_and_order():
    q = DownloadQueue()
    assert q.add_item(it(1)) is not None and q.add_item(it(2)) is not None
    assert q.add_item(it(1)) is None
    assert q.add_item(it(1, "TikTok")) is not None  # cùng id khác nền tảng: khác video
    assert [e.vid for e in q.entries] == ["v1", "v2", "v1"]


def test_group_first_page_ticked_extend_unticked():
    q = DownloadQueue()
    added = q.add_group(Group(url="https://y/@k", title="Kênh", count=120, items=[it(i) for i in range(50)]))
    assert len(added) == 50 and all(e.checked and e.group == "https://y/@k" for e in added)
    gi = q.groups["https://y/@k"]
    assert (gi.title, gi.count, gi.loaded) == ("Kênh", 120, 50)
    more = q.extend_group("https://y/@k", [it(i) for i in range(50, 100)])
    assert len(more) == 50 and not any(e.checked for e in more) and q.groups["https://y/@k"].loaded == 100


def test_next_pending_skips_unticked_done_error():
    q = DownloadQueue()
    a, b, c, d = (q.add_item(it(i)) for i in range(4))
    a.status = "done"
    b.checked = False
    c.status = "error"
    assert q.next_pending() is d
    d.status = "running"
    assert q.next_pending() is None and q.running() == [d]


def test_stop_all_back_to_pending():
    q = DownloadQueue()
    a, b = q.add_item(it(1)), q.add_item(it(2))
    a.status = b.status = "running"
    q.stop_all()
    assert a.status == b.status == "pending" and a.checked and b.checked


def test_retry_and_remove_and_clear():
    q = DownloadQueue()
    a = q.add_item(it(1))
    a.status, a.message, a.checked = "error", "Lỗi", False
    q.retry(a)
    assert a.status == "pending" and a.checked and a.message == ""
    q.remove(a)
    assert q.entries == []
    q.add_group(Group(url="g", title="G", count=1, items=[it(5)]))
    q.clear()
    assert q.entries == [] and q.groups == {}


def test_counter_text():
    q = DownloadQueue()
    assert q.counter_text() == ""
    es = [q.add_item(it(i)) for i in range(5)]
    es[0].status = "done"
    es[1].status = "exists"
    es[2].status = "running"
    es[4].checked = False
    assert q.remaining() == 2 and q.counter_text() == "2/4"


def test_save_load_roundtrip(tmp_path):
    q = DownloadQueue()
    q.add_group(Group(url="g", title="G", count=3, items=[it(1), it(2)]))
    e = q.add_item(it(9))
    e.status, e.path, e.codec, e.section = "done", "D:/x.mp4", "AV1", "60-150"
    f = tmp_path / "downloads.json"
    q.save(f)
    r = DownloadQueue.load(f)
    assert [x.vid for x in r.entries] == ["v1", "v2", "v9"]
    assert r.entries[2].path == "D:/x.mp4" and r.entries[2].section == "60-150" and r.entries[2].codec == "AV1"
    assert r.groups["g"].loaded == 2 and r.groups["g"].count == 3


def test_load_running_becomes_pending(tmp_path):
    q = DownloadQueue()
    q.add_item(it(1)).status = "running"
    f = tmp_path / "downloads.json"
    q.save(f)
    assert DownloadQueue.load(f).entries[0].status == "pending"


def test_load_corrupt_file_empty(tmp_path):
    f = tmp_path / "downloads.json"
    f.write_text("{hỏng", encoding="utf-8")
    assert DownloadQueue.load(f).entries == []
    assert DownloadQueue.load(tmp_path / "khong-co.json").entries == []


def test_unread_rows_never_downloaded():
    """I4 (soát cuối): dòng "đọc link lỗi" giữ link gốc (có thể là cả kênh) — không bao giờ được đem đi tải."""
    q = DownloadQueue()
    e = q.add_unread("https://y/@kenh", "Cần đăng nhập")
    assert e.unread and e.status == "error" and not e.checked and e.message == "Cần đăng nhập"
    e.checked, e.status = True, "pending"
    assert q.next_pending() is None and q.remaining() == 0
    assert q.add_unread("https://y/@kenh", "x") is None  # cùng link: không thêm trùng


def test_group_complete_unknown_count():
    """I6 (soát cuối): không biết tổng số video → còn "Hiện thêm" khi lượt đọc trả đủ một trang."""
    q = DownloadQueue()
    q.add_group(Group(url="g", title="G", count=0, items=[it(i) for i in range(50)]), page=50)
    assert not q.groups["g"].complete
    q.extend_group("g", [it(i) for i in range(50, 60)], page=50)
    assert q.groups["g"].complete
    q.add_group(Group(url="h", title="H", count=3, items=[it(i) for i in range(100, 103)]), page=50)
    assert q.groups["h"].complete
