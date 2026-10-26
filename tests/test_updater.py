import hashlib
import io

import pytest

from loopstation.core import updater


def test_is_newer():
    assert updater.is_newer("1.8.0", "1.7.0")
    assert updater.is_newer("v1.10.0", "1.9.3")
    assert updater.is_newer("1.7.1", "1.7")
    assert not updater.is_newer("1.7.0", "1.7.0")
    assert not updater.is_newer("v1.6.9", "1.7.0")


def _api(body="", digest=None):
    asset = {"name": updater.ASSET, "size": 3, "browser_download_url": "https://github.com/x/y/releases/download/v1.8.0/a.exe"}
    if digest:
        asset["digest"] = digest
    return {"tag_name": "v1.8.0", "body": body, "html_url": "https://github.com/x/y/releases/tag/v1.8.0",
            "assets": [{"name": "other.exe", "size": 1}, asset]}


def test_parse_release_digest_and_notes_fallback():
    rel = updater.parse_release(_api(digest="sha256:" + "ab" * 32))
    assert rel.version == "1.8.0" and rel.size == 3 and rel.sha256 == "ab" * 32
    notes = "```\n" + "CD" * 32 + "  " + updater.ASSET + "\n```"
    assert updater.parse_release(_api(body=notes)).sha256 == "cd" * 32
    assert updater.parse_release({"tag_name": "v2.0.0"}).url == ""


class _Resp(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_download_checks_sha(tmp_path, monkeypatch):
    data = b"abc"
    rel = updater.parse_release(_api(digest="sha256:" + hashlib.sha256(data).hexdigest()))
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda req, timeout=0: _Resp(data, rel.url))
    seen = []
    out = updater.download(rel, tmp_path, lambda d, t: seen.append((d, t)))
    assert out.read_bytes() == data and seen[-1] == (3, 3)
    assert updater.download(rel, tmp_path) == out  # đã có sẵn: không tải lại

    bad = updater.parse_release(_api(digest="sha256:" + "00" * 32))
    bad.version = "1.8.1"
    with pytest.raises(ValueError):
        updater.download(bad, tmp_path)
    assert not list(tmp_path.glob("*1.8.1*"))  # không để lại file hỏng


def test_download_rejects_foreign_url(tmp_path):
    rel = updater.Release("1.8.0", "", "", url="https://example.com/a.exe", sha256="00" * 32)
    with pytest.raises(ValueError):
        updater.download(rel, tmp_path)
