"""Đăng nhập trong app: cookie của trình duyệt riêng → file cookies.txt (định dạng Netscape) cho yt-dlp."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loopstation.core import downloader as dl  # noqa: E402
from loopstation.core import webcookies  # noqa: E402


def test_netscape_format(tmp_path):
    items = [{"domain": ".bilibili.com", "name": "SESSDATA", "value": "abc", "path": "/", "secure": True,
              "expires": 1900000000, "http_only": True},
             {"domain": "www.facebook.com", "name": "c_user", "value": "1", "path": "/", "secure": False,
              "expires": 0, "http_only": False}]
    f = tmp_path / "cookies.txt"
    webcookies.write(items, f)
    lines = f.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# Netscape HTTP Cookie File"
    assert "#HttpOnly_.bilibili.com\tTRUE\t/\tTRUE\t1900000000\tSESSDATA\tabc" in lines
    assert "www.facebook.com\tFALSE\t/\tFALSE\t0\tc_user\t1" in lines


def test_write_skips_bad_and_dedupes(tmp_path):
    items = [{"domain": ".a.com", "name": "x", "value": "1", "path": "/"},
             {"domain": ".a.com", "name": "x", "value": "2", "path": "/"},  # cùng khoá: lấy giá trị sau
             {"domain": "", "name": "y", "value": "1"},
             {"domain": ".a.com", "name": "z", "value": "tab\there"}]
    f = tmp_path / "c.txt"
    webcookies.write(items, f)
    body = f.read_text(encoding="utf-8")
    assert "\tx\t2" in body and "\tx\t1" not in body and "\ty\t" not in body and "\tz\t" not in body


def test_sites_logged_in():
    items = [{"domain": ".bilibili.com", "name": "SESSDATA", "value": "v"},
             {"domain": ".instagram.com", "name": "sessionid", "value": "v"},
             {"domain": ".facebook.com", "name": "datr", "value": "v"}]  # datr không phải đăng nhập
    assert webcookies.logged_in(items) == ["Bilibili", "Instagram"]


def test_login_args_app(tmp_path):
    assert ("app", "Trình duyệt trong app") in dl.LOGINS
    assert dl.login_args("app", str(tmp_path / "c.txt")) == ["--cookies", str(tmp_path / "c.txt")]
    assert dl.login_args("app", "") == []
