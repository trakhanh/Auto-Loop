"""Giữ máy thức theo từng việc (xuất / tải video): chỉ nhả khi không còn việc nào giữ."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loopstation.core import power  # noqa: E402


def test_hold_refcounts(monkeypatch):
    calls = []
    monkeypatch.setattr(power, "keep_awake", lambda on: calls.append(on) or True)
    power.release_all()
    calls.clear()
    power.hold("export", True)
    power.hold("download", True)
    power.hold("export", False)
    assert power.holders() == frozenset({"download"}) and calls == [True]
    power.hold("download", False)
    assert power.holders() == frozenset() and calls == [True, False]
    power.hold("download", False)  # nhả hai lần không gọi thêm
    assert calls == [True, False]
