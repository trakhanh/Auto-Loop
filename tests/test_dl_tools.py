"""Công cụ tải video (yt-dlp + Deno): đọc bản phát hành, cài có kiểm SHA-256, tự cập nhật, gỡ. Không gọi mạng thật."""
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loopstation.core import dl_tools  # noqa: E402

GH = "https://github.com/"


@pytest.fixture(autouse=True)
def iso(tmp_path, monkeypatch):
    monkeypatch.setenv("KTLS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KTLS_NO_UPDATE", "1")
    return tmp_path


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def deno_zip(payload: bytes = b"DENO") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("deno.exe", payload)
    return buf.getvalue()


class Resp(io.BytesIO):
    def __init__(self, data: bytes, url: str):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def serve(monkeypatch, files: dict[str, bytes]) -> list[str]:
    calls: list[str] = []

    def fake(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        calls.append(url)
        if url not in files:
            raise OSError(f"không có {url}")
        return Resp(files[url], url)

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return calls


def yt_api(tag="2026.11.19.233012", data=b"YT", digest=True):
    a = {"name": "yt-dlp.exe", "size": len(data), "browser_download_url": GH + "yt/yt-dlp.exe"}
    if digest:
        a["digest"] = "sha256:" + sha(data)
    return {"tag_name": tag, "assets": [{"name": "yt-dlp", "size": 1, "browser_download_url": GH + "yt/yt-dlp"},
                                        a, {"name": "SHA2-256SUMS", "size": 1,
                                            "browser_download_url": GH + "yt/SHA2-256SUMS"}]}


def deno_api(tag="v2.5.6", data=None):
    data = data if data is not None else deno_zip()
    return {"tag_name": tag, "assets": [
        {"name": "deno-x86_64-apple-darwin.zip", "size": 1, "browser_download_url": GH + "d/mac.zip"},
        {"name": dl_tools.DENO_ASSET, "size": len(data), "browser_download_url": GH + "d/win.zip",
         "digest": "sha256:" + sha(data)}]}


def test_parse_ytdlp_digest_and_sums_fallback():
    rel = dl_tools.parse_ytdlp_release(yt_api())
    assert rel.version == "2026.11.19.233012" and rel.sha256 == sha(b"YT") and rel.url == GH + "yt/yt-dlp.exe"
    rel2 = dl_tools.parse_ytdlp_release(yt_api(digest=False), sums_text=("cd" * 32) + "  yt-dlp.exe\n" +
                                        ("ef" * 32) + "  yt-dlp\n")
    assert rel2.sha256 == "cd" * 32


def test_parse_deno_picks_windows_zip():
    rel = dl_tools.parse_deno_release(deno_api())
    assert rel.url == GH + "d/win.zip" and rel.version == "2.5.6" and rel.name == "deno"
    rel2 = dl_tools.parse_deno_release({"tag_name": "v2", "assets": [
        {"name": dl_tools.DENO_ASSET, "size": 3, "browser_download_url": GH + "d/win.zip"}]},
        sha_text=("ab" * 32) + "  " + dl_tools.DENO_ASSET)
    assert rel2.sha256 == "ab" * 32


def test_install_verifies_and_places(monkeypatch):
    z = deno_zip()
    serve(monkeypatch, {GH + "yt/yt-dlp.exe": b"YT", GH + "d/win.zip": z})
    rels = [dl_tools.parse_ytdlp_release(yt_api()), dl_tools.parse_deno_release(deno_api(data=z))]
    seen = []
    dl_tools.install(rels, progress=lambda d, t: seen.append((d, t)))
    assert dl_tools.ytdlp_path().read_bytes() == b"YT"
    assert dl_tools.deno_path().read_bytes() == b"DENO"
    assert dl_tools.installed()
    assert dl_tools.versions()["yt-dlp"] == "2026.11.19.233012" and dl_tools.versions()["deno"] == "2.5.6"
    assert seen and seen[-1][0] == seen[-1][1] == 2 + len(z)
    assert not list(dl_tools.tools_dir().glob("*.part"))


def test_install_rejects_bad_sha_and_foreign_host(monkeypatch):
    serve(monkeypatch, {GH + "yt/yt-dlp.exe": b"XX"})
    with pytest.raises(ValueError):
        dl_tools.install([dl_tools.parse_ytdlp_release(yt_api())])  # SHA của b"YT"
    assert not dl_tools.ytdlp_path().exists()
    assert not [p for p in dl_tools.tools_dir().iterdir() if p.suffix != ".json"]
    bad = dl_tools.ToolRelease("yt-dlp", "1", "https://evil.example/yt-dlp.exe", 2, sha(b"YT"))
    with pytest.raises(ValueError):
        dl_tools.install([bad])


def _installed(monkeypatch, ver="2026.01.01"):
    serve(monkeypatch, {GH + "yt/yt-dlp.exe": b"OLD"})
    dl_tools.install([dl_tools.parse_ytdlp_release(yt_api(tag=ver, data=b"OLD"))])


def test_update_skips_when_busy(monkeypatch):
    _installed(monkeypatch)
    monkeypatch.delenv("KTLS_NO_UPDATE")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    serve(monkeypatch, {dl_tools.YTDLP_API: json.dumps(yt_api(data=b"NEW")).encode(), GH + "yt/yt-dlp.exe": b"NEW",
                        dl_tools.DENO_API: json.dumps(deno_api()).encode()})
    assert dl_tools.update_if_newer(lambda: True, date.today(), force=True) == []
    assert dl_tools.ytdlp_path().read_bytes() == b"OLD"
    done = dl_tools.update_if_newer(lambda: False, date.today(), force=True)
    assert any(s.startswith("yt-dlp") for s in done) and dl_tools.ytdlp_path().read_bytes() == b"NEW"


def test_update_offline_noop(monkeypatch):
    _installed(monkeypatch)
    calls = serve(monkeypatch, {})
    assert dl_tools.update_if_newer(lambda: False, date.today(), force=True) == []
    assert calls == []


def test_update_network_error_silent(monkeypatch):
    _installed(monkeypatch)
    monkeypatch.delenv("KTLS_NO_UPDATE")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    serve(monkeypatch, {})  # mọi link đều lỗi
    assert dl_tools.update_if_newer(lambda: False, date.today(), force=True) == []
    assert dl_tools.ytdlp_path().read_bytes() == b"OLD"


def test_due_days():
    today = date(2026, 11, 20)
    assert dl_tools.due("yt-dlp", today) and dl_tools.due("deno", today)
    dl_tools.mark_checked("deno", today - timedelta(days=6))
    dl_tools.mark_checked("yt-dlp", today - timedelta(days=1))
    assert not dl_tools.due("deno", today)
    assert dl_tools.due("yt-dlp", today)
    dl_tools.mark_checked("deno", today - timedelta(days=7))
    assert dl_tools.due("deno", today)


def test_uninstall(monkeypatch):
    _installed(monkeypatch)
    dl_tools.uninstall()
    assert not dl_tools.ytdlp_path().exists() and not dl_tools.installed()
