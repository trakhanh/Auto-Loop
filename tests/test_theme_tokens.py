"""Design tokens: every palette builds a complete token set + gradient-free QSS, contrast stays readable,
and UI code outside theme.py does not hard-code colours (it must read tokens / QSS properties)."""
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("KTLS_DATA_DIR", os.path.join(tempfile.mkdtemp(prefix="ktls_theme_"), "data"))

from loopstation.ui import theme  # noqa: E402

REQUIRED = [
    "bg", "panel", "raised", "overlay", "field", "line_subtle", "line", "line_strong", "line_control",
    "text", "text_2", "text_muted", "text_disabled", "text_on_accent",
    "accent", "accent_hover", "accent_pressed", "accent_text", "accent_soft", "accent2", "focus",
    "success", "success_text", "warn", "warn_text", "danger", "danger_text", "info", "info_text",
    "lane_clip", "lane_music", "lane_ambient", "playhead", "seam_marker",
]


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    chans = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        chans.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.fixture(autouse=True)
def _restore_palette():
    yield
    theme.set_palette("neon")


@pytest.mark.parametrize("key", list(theme.PALETTES))
def test_tokens_complete(key):
    t = theme.build_tokens(key)
    for name in REQUIRED:
        assert re.fullmatch(r"#[0-9a-f]{6}", t[name].lower()), (key, name, t.get(name))


@pytest.mark.parametrize("key", list(theme.PALETTES))
def test_qss_builds_flat_and_complete(key):
    theme.set_palette(key)
    for pt in (9, 10, 14):
        q = theme.qss(pt)
        assert "qlineargradient" not in q and "qradialgradient" not in q
        assert not re.search(r"\{[a-z_0-9]+\[", q), "unreplaced template placeholder"
        assert "None" not in q
        assert theme.T["accent"] in q  # the palette accent is what styles primary controls
        assert q.count("{") == q.count("}")


@pytest.mark.parametrize("key", list(theme.PALETTES))
def test_contrast(key):
    t = theme.build_tokens(key)
    assert contrast(t["text_on_accent"], t["accent"]) >= 4.5
    for surface in ("bg", "panel", "raised"):
        for fg in ("text", "text_2", "text_muted", "accent_text", "success_text", "warn_text", "danger_text",
                   "info_text"):
            assert contrast(t[fg], t[surface]) >= 4.5, (key, fg, surface)
    assert contrast(t["line_control"], t["panel"]) >= 2.5  # unchecked checkbox border stays visible


def test_palette_switch_changes_accent_only_tints():
    theme.set_palette("neon")
    a = dict(theme.T)
    theme.set_palette("ocean")
    b = dict(theme.T)
    assert a["accent"] != b["accent"]
    assert a["text"] == b["text"] and a["line"] == b["line"] and a["danger"] == b["danger"]


# ---- lint: no raw colours in UI code outside theme.py ----
HEX = re.compile(r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b")
# file -> reason (keep this list short and justified)
HEX_ALLOW: dict[str, str] = {}
MAX_INLINE_STYLESHEETS = 3  # dynamic-colour exceptions only; everything else goes through QSS properties


def _ui_files():
    return sorted(p for p in (ROOT / "loopstation" / "ui").glob("*.py") if p.name != "theme.py")


def test_no_raw_hex_outside_theme():
    offenders = []
    for p in _ui_files():
        if p.name in HEX_ALLOW:
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("  # ")[0]
            if HEX.search(code):
                offenders.append(f"{p.name}:{n}: {line.strip()[:100]}")
    assert not offenders, "raw hex colours outside theme.py:\n" + "\n".join(offenders)


def test_no_gradients_or_color_literals_in_ui_code():
    bad = []
    for p in _ui_files():
        text = p.read_text(encoding="utf-8")
        if "qlineargradient" in text or "qradialgradient" in text:
            bad.append(p.name)
    assert not bad, f"gradient QSS outside theme.py: {bad}"


def test_inline_stylesheets_are_rare():
    count = 0
    for p in _ui_files():
        count += len(re.findall(r"\.setStyleSheet\(", p.read_text(encoding="utf-8")))
    assert count <= MAX_INLINE_STYLESHEETS, f"{count} inline setStyleSheet calls (max {MAX_INLINE_STYLESHEETS})"
