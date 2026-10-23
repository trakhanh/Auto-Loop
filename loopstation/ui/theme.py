"""Giao diện tối "Calm Editor": token màu / chữ / khoảng cách + QSS trung tâm áp cho toàn ứng dụng.

Nguyên tắc (docs/ui/DESIGN.md): bề mặt phẳng theo bậc, MỘT màu nhấn phẳng (đổi theo bộ màu ở Cài đặt),
mỗi màn hình một nút chính. Code giao diện không ghi mã màu thô: dùng `T[...]`, `qcolor(...)` hoặc
thuộc tính động (`variant`, `tone`, `role`) rồi để QSS ở đây tô màu.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle

from ..core import ffmpeg_tools as ft

APP_NAME = "KT Loop Station"
AUTHOR = "By Khánh Trà"
APP_VERSION = "1.6.0"
# nơi lưu cài đặt (registry); KTLS_SETTINGS_ORG dùng cho test để không đụng cài đặt thật
SETTINGS_ORG = os.environ.get("KTLS_SETTINGS_ORG", "KTLoopStation")

# ---------- Bộ màu chủ đạo: chỉ quyết định màu nhấn (nền / chữ / viền dùng chung) ----------
# (tên hiển thị, accent = nền nút chính [chữ trắng ≥ 4.5:1], accent2 = màu thương hiệu, accent_text = chữ sáng trên nền tối,
#  accent_soft = chữ nhạt)
PALETTES = {
    "neon": ("Tím neon", "#8452f5", "#ec4899", "#a78bfa", "#ddd6fe"),
    "ocean": ("Đại dương", "#077f9c", "#6366f1", "#67e8f9", "#cffafe"),
    "sunset": ("Hoàng hôn", "#ca4c0a", "#e11d48", "#fdba74", "#ffedd5"),
    "classic": ("Tím xanh (bản cũ)", "#7654ff", "#3b82f6", "#a78bfa", "#c4b5fd"),
}
PALETTE = "neon"

# Trung tính dùng chung mọi bộ màu, chỉ pha tối đa 3 % màu nhấn vào các bề mặt
_NEUTRAL = {"bg": "#0e1015", "panel": "#14171e", "raised": "#1a1e27", "overlay": "#222733", "field": "#0b0d12"}
_TINT = 0.03

# Token cố định (không đổi theo bộ màu)
_FIXED = {
    # viền
    "line_subtle": "#1d212b", "line": "#2a3040", "line_strong": "#3a4255", "line_control": "#5a6378",
    # chữ
    "text": "#e8eaf0", "text_2": "#aab1c3", "text_muted": "#8a93a8", "text_disabled": "#4b5265",
    "text_on_accent": "#ffffff",
    # ngữ nghĩa: nền đặc / chữ trên nền tối
    "success": "#34b27b", "success_text": "#6ee7b7",
    "warn": "#e0a030", "warn_text": "#f5c76a",
    "danger": "#e5534b", "danger_text": "#f59a95",
    "info": "#4c9be8", "info_text": "#9cc8f5",
    # đa phương tiện (timeline, waveform)
    "lane_clip": "#4c9be8", "lane_music": "#2fb5a4", "lane_ambient": "#8b7cf0",
    "playhead": "#f4f5f8", "seam_marker": "#e0a030", "black": "#000000", "white": "#ffffff",
}

T: dict[str, str] = {}  # token đang dùng (đổi theo bộ màu)

# Khoảng cách (px) theo lưới 4: 2xs 2 · xs 4 · sm/md 8 · lg 12 · xl 16 · xxl 24 · 3xl 32
SP = {"2xs": 2, "xs": 4, "sm": 8, "md": 8, "lg": 12, "xl": 16, "xxl": 24, "3xl": 32}
PAGE_MARGINS = (SP["xl"], SP["xl"], SP["xl"], SP["xl"])  # lề trong của mọi trang (trái, trên, phải, dưới)
FORM_GAP = SP["md"]  # khoảng cách giữa các dòng trong thẻ cài đặt
SECTION_GAP = SP["lg"]  # khoảng cách giữa các thẻ / khối
# Bo góc: sm chip / checkbox · md nút, ô nhập · lg thẻ, bảng, menu · xl hộp thoại, lớp phủ · pill
R = {"sm": 4, "md": 6, "lg": 8, "xl": 12, "pill": 999}
# Chiều cao điều khiển (px)
H = {"sm": 24, "md": 32, "lg": 40}
# Thang cỡ chữ (pt, ở cỡ chữ mặc định 10 — tự nhân theo Cài đặt → Cỡ chữ): chỉ dùng các bậc này
FS = {"caption": 8.5, "small": 9, "body": 10, "label": 10, "subtitle": 11, "title": 13, "display": 17}
# Thời lượng chuyển động (ms)
DUR = {"fast": 120, "base": 180, "slow": 240}

# Màu dữ liệu của timeline: mỗi clip một màu để nhận ra clip lặp lại (không đổi theo bộ màu)
CLIP_COLORS = ["#7c5cff", "#10b981", "#f59e0b", "#ec4899", "#3b82f6", "#06b6d4", "#84cc16", "#f97316",
               "#8b5cf6", "#14b8a6"]
BOOKEND_COLOR = "#64748b"
MUSIC_COLORS = ["#3b5bdb", "#2b6cb0", "#4c51bf", "#2c7a7b"]
SOURCE_COLOR = "#334155"
FLOW_COLORS = ("#6d28d9", "#db2777", "#0e7490")  # khối minh hoạ thứ tự phát trong trang Hướng dẫn

FONT_PT = 10  # cỡ chữ đang dùng (Cài đặt → Cỡ chữ ứng dụng)


def mix(a: str, b: str, t: float) -> str:
    """Trộn hai màu hex: t = 0 → a, t = 1 → b."""
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t), round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def rgba(color: str, alpha: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha:g})"


def build_tokens(key: str) -> dict[str, str]:
    """Dựng đủ bộ token cho một bộ màu (hàm thuần, dùng cho test)."""
    if key not in PALETTES:
        key = "neon"
    _name, accent, accent2, accent_text, accent_soft = PALETTES[key]
    t = dict(_FIXED)
    for k, base in _NEUTRAL.items():
        t[k] = mix(base, accent, _TINT)
    t.update(accent=accent, accent2=accent2, accent_text=accent_text, accent_soft=accent_soft,
             accent_hover=mix(accent, "#ffffff", 0.12), accent_pressed=mix(accent, "#000000", 0.18),
             focus=accent_text)
    return t


def set_palette(key: str) -> None:
    global PALETTE
    if key not in PALETTES:
        key = "neon"
    PALETTE = key
    T.clear()
    T.update(build_tokens(key))


set_palette(PALETTE)


def qcolor(key: str, alpha: int = 255) -> QColor:
    """Màu theo bộ màu đang chọn (dùng cho phần tự vẽ: đọc lúc vẽ nên đổi bộ màu là đổi theo ngay)."""
    c = QColor(T[key])
    c.setAlpha(alpha)
    return c


def scale() -> float:
    """Tỉ lệ cỡ chữ so với mặc định 10pt (dùng cho các phần tự vẽ / HTML)."""
    return FONT_PT / 10


def px(n: float) -> int:
    """Kích thước theo cỡ chữ đang chọn."""
    return round(n * scale())


def pt(role: str) -> float:
    """Cỡ chữ (pt) của một bậc trong thang, đã nhân theo Cài đặt → Cỡ chữ."""
    return FS[role] * scale()


def page_layout(layout) -> None:
    """Lề + khoảng cách chuẩn cho bố cục ngoài cùng của một trang."""
    layout.setContentsMargins(*PAGE_MARGINS)
    layout.setSpacing(SECTION_GAP)


def tag(widget, **props) -> None:
    """Đặt thuộc tính động (variant / size / tone / role / state…) rồi áp lại kiểu một lần."""
    for k, v in props.items():
        widget.setProperty(k, v)
    repolish(widget)


def repolish(widget) -> None:
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)
    widget.update()


def css_color(key: str) -> str:
    """Mã màu cho chuỗi HTML / CSS nhúng (QLabel rich text, QTextBrowser)."""
    return T[key]


def span(tone: str, text: str) -> str:
    """Đoạn chữ HTML tô màu theo tông ngữ nghĩa: ok | warn | error | info | muted | accent."""
    key = {"ok": "success_text", "warn": "warn_text", "error": "danger_text", "info": "info_text",
           "muted": "text_muted", "accent": "accent_text"}.get(tone, tone)
    return f"<span style='color:{T[key]}'>{text}</span>"


def tone_color(tone: str) -> str:
    """Màu chữ của một tông ngữ nghĩa (ok | warn | error | info | muted | accent | text)."""
    key = {"ok": "success_text", "warn": "warn_text", "error": "danger_text", "info": "info_text",
           "muted": "text_muted", "accent": "accent_text"}.get(tone, tone)
    return T[key]


# ---------- icon cho QSS (ghi ra file vì QSS chỉ nhận đường dẫn) ----------
_CHECK_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
              '<path d="M3.5 8.5l3 3 6-7" fill="none" stroke="white" stroke-width="2.2" '
              'stroke-linecap="round" stroke-linejoin="round"/></svg>')
_ARROW_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12">'
              '<path d="M2.5 4.5l3.5 3.5 3.5-3.5" fill="none" stroke="{c}" stroke-width="1.6" '
              'stroke-linecap="round" stroke-linejoin="round"/></svg>')
_UP_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
           '<path d="M2 6.5l3-3 3 3" fill="none" stroke="{c}" stroke-width="1.5" '
           'stroke-linecap="round" stroke-linejoin="round"/></svg>')
_DOWN_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
             '<path d="M2 3.5l3 3 3-3" fill="none" stroke="{c}" stroke-width="1.5" '
             'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _asset(name: str, content: str) -> str:
    d = ft.data_dir() / "ui"
    d.mkdir(exist_ok=True)
    p = d / name
    if not p.is_file() or p.read_text(encoding="utf-8") != content:
        p.write_text(content, encoding="utf-8")
    return str(p).replace("\\", "/")


# ---------- QSS: mỗi nhóm thành phần một hàm ----------
def _q_base(t: dict, f: dict, a: dict) -> str:
    return f"""
/* danh sách xổ xuống luôn hiện NGAY DƯỚI ô chọn (kiểu Fusion mặc định hiện đè lên ô) */
QComboBox {{ combobox-popup: 0; }}
QWidget {{ color: {t['text']}; selection-background-color: {rgba(t['accent'], 0.45)}; selection-color: {t['text']}; }}
QMainWindow, QDialog, QMessageBox {{ background: {t['bg']}; }}
QToolTip {{ background: {t['overlay']}; color: {t['text']}; border: 1px solid {t['line']};
           padding: 6px 10px; border-radius: {R['md']}px; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}
QSplitter::handle:vertical {{ height: 8px; }}
QSplitter#workSplit::handle {{ background: {t['line_subtle']}; }}
QSplitter#workSplit::handle:hover {{ background: {t['accent']}; }}
QStatusBar {{ background: {t['panel']}; color: {t['text_muted']}; border-top: 1px solid {t['line']}; }}
QMessageBox {{ background: {t['overlay']}; }}
QMenu {{ background: {t['overlay']}; border: 1px solid {t['line']}; padding: 4px; border-radius: {R['lg']}px; }}
QMenu::item {{ padding: 6px 14px; border-radius: {R['sm']}px; }}
QMenu::item:selected {{ background: {rgba(t['accent'], 0.22)}; color: {t['text']}; }}
QMenu::item:disabled {{ color: {t['text_disabled']}; }}
QMenu::separator {{ height: 1px; background: {t['line_subtle']}; margin: 4px 6px; }}
"""


def _q_shell(t: dict, f: dict, a: dict) -> str:
    return f"""
/* ---------- khung chính ---------- */
QWidget#shell {{ background: {t['bg']}; border-top: 1px solid {t['line']}; }}
QWidget#sidebar {{ background: {t['panel']}; border-right: 1px solid {t['line']}; }}
QStackedWidget#pageStack {{ background: {t['bg']}; }}
QWidget#sidebar QLabel, QWidget#sidebar QWidget {{ background: transparent; }}
QWidget#sidebar QWidget#sidebarCard {{ background: {t['field']}; }}
QWidget#sidebarCard {{ background: {t['field']}; border: 1px solid {t['line']}; border-radius: {R['lg']}px; }}
QWidget#header {{ background: {t['panel']}; border-bottom: 1px solid {t['line']}; }}
QWidget#header QLabel {{ background: transparent; }}
/* chữ số liệu ở thanh trên cùng: không khung, không nền (tổng thời lượng là một chỉ số, không phải nút) */
QWidget#header QLabel#chip, QWidget#header QLabel#chipOff {{ background: transparent; border: none; padding: 0 4px;
                                                       color: {t['text_muted']}; font-weight: 400; }}
QWidget#header QLabel#chipAccent {{ background: transparent; border: none; padding: 0 4px; color: {t['text']};
                                    font-family: Consolas, 'Cascadia Mono', monospace; font-weight: 700; }}
QWidget#header QLabel#chipError {{ background: {rgba(t['danger'], 0.14)}; }}
QWidget#header QLabel#chipWarn {{ background: {rgba(t['warn'], 0.16)}; }}
QWidget#header QLabel#chipOk {{ background: {rgba(t['success'], 0.16)}; }}
QWidget#subHeader {{ background: {t['bg']}; border-bottom: 1px solid {t['line']}; }}
QWidget#timelineDock {{ background: {t['panel']}; border-top: 1px solid {t['line']}; }}
QPushButton#dockBar {{ background: transparent; border: none; color: {t['text_muted']}; padding: 0 6px; font-size: {f['small']};
                      font-weight: 600; text-align: left; }}
QPushButton#dockBar:hover {{ color: {t['text']}; background: {rgba('#ffffff', 0.05)}; }}

/* ---------- thẻ ---------- */
QWidget#quickBar, QFrame#batchCard, QWidget#metricCard {{ background: {t['panel']}; border: 1px solid {t['line_subtle']};
                     border-radius: {R['lg']}px; }}
QGroupBox {{ background: {t['panel']}; border: 1px solid {t['line_subtle']}; border-radius: {R['lg']}px;
            margin-top: 6px; padding: 30px 16px 16px 16px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: padding; subcontrol-position: top left; left: 14px; top: 8px;
                   padding: 0 2px; color: {t['text']}; font-size: {f['subtitle']}; font-weight: 600; background: transparent; }}
QGroupBox * {{ font-weight: 400; }}
QLabel#metricTitle {{ color: {t['text_muted']}; font-size: {f['caption']}; font-weight: 600; background: transparent; }}
QLabel#metricValue {{ color: {t['text']}; font-size: {f['label']}; font-weight: 700; background: transparent; }}
QLabel#batchTree {{ background: {t['field']}; border: 1px solid {t['line']}; border-radius: {R['lg']}px; padding: 8px 12px; }}

/* ---------- chữ ---------- */
QLabel#appName {{ font-size: {f['title']}; font-weight: 700; color: {t['text']}; }}
QLabel#appAuthor {{ color: {t['text_muted']}; font-size: {f['caption']}; }}
QLabel#sectionLabel {{ color: {t['text_muted']}; font-size: {f['small']}; font-weight: 600;
                      padding: 8px 8px 2px 8px; background: transparent; }}
QLabel#h2 {{ font-size: {f['label']}; font-weight: 600; color: {t['text']}; background: transparent; }}
QLabel#muted, QLabel[role="muted"] {{ color: {t['text_muted']}; background: transparent; }}
QLabel[role="mono"] {{ font-family: Consolas, 'Cascadia Mono', monospace; font-weight: 600; background: transparent; }}
QLabel[role="strong"] {{ font-weight: 600; background: transparent; }}
QLabel[role="match"] {{ color: {t['accent_text']}; font-weight: 600; background: transparent; }}
QLabel[role="match"][tone="danger"] {{ color: {t['danger_text']}; }}
QLabel#info {{ background: {rgba(t['info'], 0.10)}; border: 1px solid {rgba(t['info'], 0.32)};
               border-radius: {R['md']}px; padding: 10px 14px; color: {t['text']}; }}
QLabel#info[tone="accent"] {{ background: {rgba(t['accent'], 0.14)}; border-color: {rgba(t['accent'], 0.45)}; }}
QFrame#suggestBar {{ background: {rgba(t['accent'], 0.14)}; border: 1px solid {rgba(t['accent'], 0.45)};
                    border-radius: {R['md']}px; }}
QLabel#toastDot {{ background: transparent; font-size: {f['subtitle']}; color: {t['accent_text']}; }}
QLabel#toastDot[tone="ok"] {{ color: {t['success_text']}; }}
QLabel#toastDot[tone="warn"] {{ color: {t['warn_text']}; }}
QLabel#toastDot[tone="error"] {{ color: {t['danger_text']}; }}

/* ---------- chip / huy hiệu ---------- */
QLabel#chip {{ background: {t['raised']}; border: 1px solid {t['line']}; border-radius: {R['pill']}px;
               padding: 3px 10px; color: {t['text_2']}; font-weight: 600; }}
QLabel#chipAccent {{ background: {rgba(t['accent'], 0.18)}; border: 1px solid {rgba(t['accent'], 0.40)};
                     border-radius: {R['pill']}px; padding: 3px 10px; color: {t['accent_text']}; font-weight: 600; }}
QLabel#chipError {{ background: {rgba(t['danger'], 0.14)}; border: 1px solid {rgba(t['danger'], 0.40)};
                    border-radius: {R['pill']}px; padding: 3px 10px; color: {t['danger_text']}; font-weight: 600; }}
QLabel#chipOk {{ background: {rgba(t['success'], 0.14)}; border: 1px solid {rgba(t['success'], 0.40)};
                 border-radius: {R['pill']}px; padding: 3px 10px; color: {t['success_text']}; font-weight: 600; }}
QLabel#chipOff {{ background: {t['raised']}; border: 1px solid {t['line_subtle']}; border-radius: {R['pill']}px;
                  padding: 3px 10px; color: {t['text_muted']}; }}
QLabel#chipWarn {{ background: {rgba(t['warn'], 0.14)}; border: 1px solid {rgba(t['warn'], 0.40)};
                   border-radius: {R['pill']}px; padding: 3px 10px; color: {t['warn_text']}; font-weight: 600; }}
"""


def _q_tabs_buttons(t: dict, f: dict, a: dict) -> str:
    return f"""
/* ---------- tab con: gạch chân ---------- */
QTabWidget::pane {{ background: transparent; border: none; border-top: 1px solid {t['line_subtle']}; margin-top: 0; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; border: none; border-bottom: 2px solid transparent; color: {t['text_muted']};
               padding: 8px 14px; margin-right: 2px; font-weight: 600; }}
QTabBar::tab:hover {{ color: {t['text']}; }}
QTabBar::tab:selected {{ color: {t['text']}; border-bottom: 2px solid {t['accent']}; }}

/* ---------- nút bấm: secondary (mặc định) · primary · tonal · ghost · danger ---------- */
QPushButton {{ background: {t['raised']}; border: 1px solid {t['line']}; border-radius: {R['md']}px;
              padding: 6px 14px; color: {t['text']}; font-weight: 600; }}
QPushButton:hover {{ border-color: {t['line_strong']}; background: {t['overlay']}; }}
QPushButton:pressed {{ background: {t['field']}; }}
QPushButton:disabled {{ color: {t['text_disabled']}; border-color: {t['line_subtle']}; background: {t['panel']}; }}
QPushButton:checked {{ background: {rgba(t['accent'], 0.20)}; border-color: {rgba(t['accent'], 0.55)}; }}

QPushButton#accentBtn, QPushButton[variant="tonal"] {{ background: {rgba(t['accent'], 0.16)}; border: 1px solid transparent;
                        color: {t['accent_text']}; font-weight: 600; }}
QPushButton#accentBtn:hover, QPushButton[variant="tonal"]:hover {{ background: {rgba(t['accent'], 0.26)}; color: {t['text']}; }}
QPushButton#accentBtn:pressed, QPushButton[variant="tonal"]:pressed {{ background: {rgba(t['accent'], 0.34)}; }}
QPushButton#accentBtn:disabled, QPushButton[variant="tonal"]:disabled {{ color: {t['text_disabled']};
                        border-color: {t['line_subtle']}; background: {t['panel']}; }}

QPushButton#nextStepBtn, QPushButton#primary, QPushButton[variant="primary"] {{ background: {t['accent']}; border: none;
                          color: {t['text_on_accent']}; font-weight: 600; padding: 6px 16px; }}
QPushButton#nextStepBtn:hover, QPushButton#primary:hover, QPushButton[variant="primary"]:hover {{ background: {t['accent_hover']}; }}
QPushButton#nextStepBtn:pressed, QPushButton#primary:pressed, QPushButton[variant="primary"]:pressed {{
                          background: {t['accent_pressed']}; }}
QPushButton#nextStepBtn:disabled, QPushButton#primary:disabled, QPushButton[variant="primary"]:disabled {{
                          background: {t['raised']}; color: {t['text_disabled']}; }}
QPushButton#primary {{ font-size: {f['subtitle']}; padding: 9px 20px; }}

QPushButton#danger, QPushButton[variant="danger"] {{ background: transparent; border: 1px solid transparent;
                          color: {t['danger_text']}; }}
QPushButton#danger:hover:enabled, QPushButton[variant="danger"]:hover:enabled {{ background: {rgba(t['danger'], 0.14)};
                          border-color: {rgba(t['danger'], 0.40)}; }}
QPushButton#danger:pressed:enabled, QPushButton[variant="danger"]:pressed:enabled {{ background: {rgba(t['danger'], 0.22)}; }}
QPushButton#danger:disabled, QPushButton[variant="danger"]:disabled {{ background: transparent; border-color: transparent; }}

QPushButton#ghost, QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent;
                          color: {t['text_2']}; padding: 5px 8px; }}
QPushButton#ghost:hover, QPushButton[variant="ghost"]:hover {{ background: {rgba('#ffffff', 0.06)}; color: {t['text']}; }}
QPushButton#ghost:pressed, QPushButton[variant="ghost"]:pressed {{ background: {rgba('#ffffff', 0.10)}; }}
QPushButton#ghost:checked, QPushButton[variant="ghost"]:checked {{ background: {rgba(t['accent'], 0.16)}; color: {t['accent_text']};
                          border-color: transparent; }}
QPushButton#ghost[icononly="true"] {{ padding: 0; }}
QPushButton#ghost:disabled, QPushButton[variant="ghost"]:disabled {{ background: transparent; border-color: transparent;
                          color: {t['text_disabled']}; }}

QPushButton#pill, QPushButton[size="sm"] {{ background: {t['field']}; border: 1px solid {t['line']}; border-radius: {R['md']}px;
                   padding: 3px 8px; color: {t['text_2']}; font-size: {f['small']}; font-weight: 600; }}
QPushButton#pill:hover, QPushButton[size="sm"]:hover {{ border-color: {t['line_strong']}; color: {t['text']};
                   background: {t['raised']}; }}
QPushButton#pill:checked, QPushButton[size="sm"]:checked {{ background: {rgba(t['accent'], 0.22)};
                   border-color: {rgba(t['accent'], 0.55)}; color: {t['text']}; }}
QPushButton#pill:disabled, QPushButton[size="sm"]:disabled {{ color: {t['text_disabled']}; background: {t['panel']};
                   border-color: {t['line_subtle']}; }}

/* nhóm chọn một trong nhiều (kiểu cũ: ba nút dính nhau) */
QPushButton#segL, QPushButton#segM, QPushButton#segR {{ background: {t['field']}; border: 1px solid {t['line']};
    padding: 6px 14px; color: {t['text_2']}; border-radius: 0; margin: 0; font-weight: 600; }}
QPushButton#segL {{ border-top-left-radius: {R['md']}px; border-bottom-left-radius: {R['md']}px; }}
QPushButton#segR {{ border-top-right-radius: {R['md']}px; border-bottom-right-radius: {R['md']}px; }}
QPushButton#segL:hover, QPushButton#segM:hover, QPushButton#segR:hover {{ color: {t['text']}; background: {t['raised']}; }}
QPushButton#segL:checked, QPushButton#segM:checked, QPushButton#segR:checked {{
    background: {t['raised']}; border-color: {t['line_strong']}; color: {t['text']}; font-weight: 600; }}
/* bộ chọn có khối trượt (motion.SegmentBox) */
QWidget#segBox {{ background: {t['field']}; border: 1px solid {t['line']}; border-radius: {R['lg']}px; }}
QWidget#segPill {{ background: {t['raised']}; border: 1px solid {t['line_strong']}; border-radius: {R['md']}px; }}
QPushButton#segBtn {{ background: transparent; border: 1px solid transparent; border-radius: {R['md']}px; padding: 5px 13px;
                     color: {t['text_2']}; font-weight: 600; }}
QPushButton#segBtn:hover {{ color: {t['text']}; background: transparent; }}
QPushButton#segBtn:checked {{ color: {t['text']}; font-weight: 600; background: transparent; border-color: transparent; }}
QPushButton#segBtn:disabled {{ color: {t['text_disabled']}; }}

/* ---------- thanh bên ---------- */
QPushButton#nav {{ background: transparent; border: 1px solid transparent; border-radius: {R['md']}px; text-align: left;
                  padding: 8px 12px; color: {t['text_2']}; font-weight: 600; }}
QPushButton#nav:hover:enabled {{ background: {rgba('#ffffff', 0.05)}; color: {t['text']}; }}
QPushButton#nav:checked {{ background: transparent; border-color: transparent; color: {t['text']}; font-weight: 600; }}
QPushButton#nav:checked:hover {{ background: transparent; }}
QPushButton#nav:disabled {{ color: {t['text_disabled']}; background: transparent; border-color: transparent; }}
/* nền mục đang chọn: một khối riêng trượt mượt giữa các mục (motion.NavPill) */
QWidget#navPill {{ background: {rgba(t['accent'], 0.18)}; border: none; border-left: 3px solid {t['accent']};
                   border-radius: {R['md']}px; }}

/* ---------- màn hình chào, Bắt đầu, hướng dẫn từng bước ---------- */
QScrollArea#welcomeScroll, QWidget#welcomeInner {{ background: transparent; }}
QFrame#welcomeCard {{ background: {t['overlay']}; border: 1px solid {t['line']}; border-radius: {R['xl']}px; }}
QFrame#welcomeStep {{ background: {t['panel']}; border: 1px solid {t['line_subtle']}; border-radius: {R['lg']}px; }}
QLabel#welcomeNum {{ background: {rgba(t['accent'], 0.20)}; color: {t['accent_text']}; border-radius: 13px; font-weight: 700; }}
QLabel#welcomeStepTitle {{ color: {t['text']}; font-size: {f['subtitle']}; font-weight: 600; background: transparent; }}
QLabel#welcomeStepText {{ color: {t['text_2']}; background: transparent; }}
#homeHero {{ font-size: {f['display']}; font-weight: 700; color: {t['text']}; background: transparent; }}
QPushButton#homeCard {{ background: {t['panel']}; border: 1px solid {t['line_subtle']}; border-radius: {R['lg']}px;
                        text-align: left; padding: 0; }}
QPushButton#homeCard:hover {{ background: {t['raised']}; border-color: {t['line_strong']}; }}
QPushButton#homeCard:pressed {{ background: {t['field']}; }}
QLabel#homeBadge {{ background: {t['raised']}; border-radius: {R['lg']}px; }}
QLabel#homeBadge[tone="accent"] {{ background: {rgba(t['accent'], 0.16)}; }}
QLabel#homeBadge[tone="info"] {{ background: {rgba(t['info'], 0.14)}; }}
QLabel#homeBadge[tone="success"] {{ background: {rgba(t['success'], 0.14)}; }}
QLabel#homeBadge[tone="warn"] {{ background: {rgba(t['warn'], 0.14)}; }}
QLabel#homeTitle {{ font-size: {f['subtitle']}; font-weight: 600; color: {t['text']}; background: transparent; }}
QLabel#homeDesc {{ color: {t['text_2']}; background: transparent; }}
QLabel#homeExample {{ color: {t['text_muted']}; font-size: {f['small']}; background: transparent; }}
QWidget#stepGuide {{ background: {t['bg']}; border-bottom: 1px solid {t['line']}; }}
QPushButton#stepPill {{ border-radius: {R['pill']}px; padding: 2px 12px; font-weight: 600; border: 1px solid {t['line']};
                        background: transparent; color: {t['text_muted']}; font-size: {f['small']}; }}
QPushButton#stepPill[state="current"] {{ background: {rgba(t['accent'], 0.20)}; border-color: {rgba(t['accent'], 0.55)};
                        color: {t['text']}; }}
QPushButton#stepPill[state="done"] {{ color: {t['success_text']}; border-color: {rgba(t['success'], 0.45)}; }}
QPushButton#stepPill:hover {{ border-color: {t['line_strong']}; }}
QLabel#stepArrow {{ color: {t['text_muted']}; font-size: {f['title']}; background: transparent; }}
QLabel#stepHint {{ color: {t['text_2']}; background: transparent; }}
QLabel#sizeEst {{ font-size: {f['title']}; font-weight: 700; color: {t['text']}; background: transparent;
                 font-family: Consolas, 'Cascadia Mono', monospace; }}
QWidget#exportFooter {{ background: {t['panel']}; border-top: 1px solid {t['line']}; }}
QWidget#exportFooter QLabel {{ background: transparent; }}
QLabel#info[plain="true"] {{ background: transparent; border: none; padding: 0; }}
QLabel[role="fieldlabel"] {{ color: {t['text_2']}; background: transparent; }}
QPushButton[align="left"] {{ text-align: left; }}
QLabel#sizeEst[busy="true"] {{ color: {t['text_muted']}; }}
QWidget#toast {{ background: {t['overlay']}; border: 1px solid {t['line']}; border-radius: {R['xl']}px; }}
QWidget#toast QLabel {{ background: transparent; color: {t['text']}; font-weight: 600; }}
QListWidget#helpToc {{ background: {t['panel']}; border: 1px solid {t['line_subtle']}; border-radius: {R['lg']}px;
    padding: 6px; outline: none; }}
QListWidget#helpToc::item {{ padding: 6px 8px; border-radius: {R['sm']}px; color: {t['text_2']}; }}
QListWidget#helpToc::item:hover {{ background: {rgba('#ffffff', 0.05)}; color: {t['text']}; }}
QListWidget#helpToc::item:selected {{ background: {rgba(t['accent'], 0.20)}; color: {t['text']}; }}
"""


def _q_inputs(t: dict, f: dict, a: dict) -> str:
    arrow, up, down, check = a["arrow"], a["up"], a["down"], a["check"]
    return f"""
/* ---------- ô nhập & chọn ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {t['field']}; border: 1px solid {t['line']};
    border-radius: {R['md']}px; padding: 5px 10px; min-height: 20px; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {t['line_strong']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {rgba(t['accent_text'], 0.80)}; }}
QLineEdit[bad="true"], QLineEdit[state="warn"] {{ border-color: {t['warn']}; }}
QLineEdit[state="error"] {{ border-color: {t['danger']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    color: {t['text_disabled']}; background: {t['panel']}; border-color: {t['line_subtle']}; }}
QLineEdit#title {{ font-size: {f['title']}; font-weight: 700; padding: 4px 10px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{arrow}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {t['overlay']}; border: 1px solid {t['line']};
    selection-background-color: {rgba(t['accent'], 0.28)}; selection-color: {t['text']}; padding: 4px;
    border-radius: {R['lg']}px; outline: none; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 10px; border-radius: {R['sm']}px; }}
QComboBox QAbstractItemView::item:selected {{ background: {rgba(t['accent'], 0.28)}; color: {t['text']}; }}

QSpinBox, QDoubleSpinBox {{ padding-right: 20px; }}
QSpinBox#timeBox {{ padding: 4px 2px; }}  /* ô giờ / phút / giây: không mũi tên, số căn giữa */
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
    width: 18px; border: none; border-top-right-radius: {R['md']}px; background: transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
    width: 18px; border: none; border-bottom-right-radius: {R['md']}px; background: transparent; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {t['raised']}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 9px; height: 9px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 9px; height: 9px; }}

/* ---------- thanh trượt ---------- */
QSlider::groove:horizontal {{ height: 4px; background: {t['line']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {t['text']}; border: 2px solid {t['accent']}; width: 14px; height: 14px;
                            margin: -6px 0; border-radius: 8px; }}
QSlider::handle:horizontal:hover {{ background: {t['accent_soft']}; border-color: {t['accent_text']}; }}
QSlider::groove:horizontal:disabled {{ background: {t['line_subtle']}; }}
QSlider::sub-page:horizontal:disabled {{ background: {t['text_disabled']}; }}
QSlider::handle:horizontal:disabled {{ background: {t['text_disabled']}; border-color: {t['line']}; }}

/* ---------- ô tick: ô trống luôn nhìn thấy ---------- */
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QTreeView::indicator {{ width: 16px; height: 16px; border-radius: {R['sm']}px;
    border: 1px solid {t['line_control']}; background: {t['field']}; }}
QCheckBox::indicator:hover, QTreeView::indicator:hover {{ border-color: {t['accent_text']}; }}
QCheckBox::indicator:checked, QTreeView::indicator:checked {{ background: {t['accent']};
    border-color: {t['accent']}; image: url("{check}"); }}
QCheckBox:disabled {{ color: {t['text_disabled']}; }}
QCheckBox::indicator:disabled {{ background: {t['panel']}; border-color: {t['line']}; }}
QCheckBox::indicator:checked:disabled, QTreeView::indicator:checked:disabled {{ background: {rgba(t['accent'], 0.35)};
    border-color: {rgba(t['accent'], 0.35)}; }}
QTreeView:disabled {{ color: {t['text_disabled']}; }}
"""


def _q_lists(t: dict, f: dict, a: dict) -> str:
    return f"""
/* ---------- bảng danh sách ---------- */
QTreeWidget, QTreeView {{ background: {t['panel']}; alternate-background-color: {mix(t['panel'], t['text'], 0.022)};
    border: 1px solid {t['line_subtle']}; border-radius: {R['lg']}px; padding: 2px; }}
QTreeView::item {{ height: 32px; border: none; border-bottom: 1px solid {t['line_subtle']}; padding: 0 4px; }}
QTreeWidget#clips::item {{ height: 56px; }}
QTreeView::item:hover {{ background: {rgba('#ffffff', 0.04)}; }}
QTreeView::item:selected {{ background: {rgba(t['accent'], 0.22)}; color: {t['text']}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {t['panel']}; color: {t['text_muted']}; border: none;
    border-bottom: 1px solid {t['line']}; padding: 7px 6px; font-weight: 600; font-size: {f['small']}; }}
QHeaderView::section:hover {{ color: {t['text']}; }}

QTextBrowser {{ background: {t['panel']}; border: none; border-radius: {R['lg']}px; padding: 12px 18px; }}
QPlainTextEdit {{ background: {t['field']}; border: 1px solid {t['line']}; border-radius: {R['lg']}px;
    padding: 8px; font-family: Consolas, 'Cascadia Mono', monospace; font-size: {f['small']}; color: {t['text_2']}; }}

QProgressBar {{ background: {t['field']}; border: 1px solid {t['line']}; border-radius: {R['lg']}px;
    min-height: 20px; text-align: center; color: {t['text']}; font-weight: 600; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: {R['md']}px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {t['line_strong']}; border-radius: {R['sm']}px; min-height: 32px; min-width: 32px; }}
QScrollBar::handle:hover {{ background: {rgba(t['text_muted'], 0.60)}; }}
QScrollBar::handle:pressed {{ background: {t['accent']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page
    {{ width: 0; height: 0; background: none; }}
"""


def _q_player(t: dict, f: dict, a: dict) -> str:
    return f"""
/* ---------- khung xem trước ---------- */
QFrame#playerPanel {{ background: {t['field']}; border-left: 1px solid {t['line']}; }}
QLabel#playerInfo {{ color: {t['text_muted']}; background: {t['raised']}; border-radius: {R['md']}px; padding: 1px 7px;
                    font-size: {f['caption']}; }}
QLabel#playerTitle {{ color: {t['text_muted']}; font-weight: 600; font-size: {f['small']}; }}
QLabel#playerTime {{ color: {t['text']}; font-family: Consolas, 'Cascadia Mono', monospace; font-weight: 700; }}
QLabel#playerTimeTotal {{ color: {t['text_muted']}; font-family: Consolas, 'Cascadia Mono', monospace; }}
QPushButton#playerBtn {{ background: transparent; border: 1px solid transparent; border-radius: {R['md']}px; padding: 6px 8px;
                        color: {t['text']}; font-weight: 600; font-size: {f['caption']}; }}
QPushButton#playerBtn:hover {{ background: {rgba('#ffffff', 0.06)}; }}
QPushButton#playerBtn:pressed {{ background: {rgba('#ffffff', 0.10)}; }}
QPushButton#playerBtn:disabled {{ color: {t['text_disabled']}; }}
QPushButton#playerPlay {{ background: {t['accent']}; border: none; border-radius: 21px; min-width: 42px; max-width: 42px;
                         min-height: 42px; max-height: 42px; padding: 0; }}
QPushButton#playerPlay:hover {{ background: {t['accent_hover']}; }}
QPushButton#playerPlay:pressed {{ background: {t['accent_pressed']}; }}
QPushButton#playerPlay:disabled {{ background: {t['raised']}; }}
QComboBox#playerCombo {{ padding: 2px 8px; font-size: {f['small']}; }}
/* hộp thoại cắt đoạn */
QFrame#playerFrame {{ background: {t['black']}; border: 1px solid {t['line']}; border-radius: {R['lg']}px; }}
QFrame#sideCard {{ background: {t['panel']}; border: 1px solid {t['line']}; border-radius: {R['xl']}px; }}
QLabel[role="thumb"] {{ background: {t['field']}; border: 1px solid {t['line']}; border-radius: {R['md']}px;
                        color: {t['text_muted']}; }}
QLabel#previewBox {{ color: {t['text_muted']}; background: {t['field']}; border: 1px solid {t['line']}; border-radius: {R['lg']}px; }}
QFrame[role="hairline"] {{ color: {t['line_subtle']}; background: {t['line_subtle']}; max-width: 1px; }}
"""


_GROUPS = (_q_base, _q_shell, _q_tabs_buttons, _q_inputs, _q_lists, _q_player)


def qss(font_pt: int = 10) -> str:
    """QSS toàn app, dựng từ token của bộ màu đang chọn. Cỡ chữ lấy từ thang `FS` nhân theo `font_pt`."""
    k = font_pt / 10
    f = {name: f"{size * k:.1f}pt" for name, size in FS.items()}
    a = {"check": _asset("check.svg", _CHECK_SVG),
         "arrow": _asset("arrow.svg", _ARROW_SVG.format(c=T["text_muted"])),
         "up": _asset("up.svg", _UP_SVG.format(c=T["text_muted"])),
         "down": _asset("down.svg", _DOWN_SVG.format(c=T["text_muted"]))}
    return f"QWidget {{ font-size: {font_pt}pt; }}\n" + "".join(g(T, f, a) for g in _GROUPS)


class ThemeStyle(QProxyStyle):
    """Vòng focus bàn phím: chỉ hiện khi người dùng bấm Tab (không hiện khi bấm chuột)."""

    def drawPrimitive(self, element, option, painter: QPainter, widget=None) -> None:
        if element == QStyle.PrimitiveElement.PE_FrameFocusRect:
            if not (option.state & QStyle.StateFlag.State_KeyboardFocusChange):
                return
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(T["focus"]), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(option.rect).adjusted(-1, -1, 1, 1), R["md"], R["md"])
            painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)


def apply(app: QApplication, font_pt: int = 10, palette: str | None = None) -> None:
    global FONT_PT
    if palette is not None:
        set_palette(palette)
    FONT_PT = font_pt
    if not isinstance(app.style(), ThemeStyle):
        app.setStyle(ThemeStyle("Fusion"))
    app.setFont(QFont("Segoe UI", font_pt))
    pal = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, T["bg"]), (QPalette.ColorRole.Base, T["panel"]),
        (QPalette.ColorRole.AlternateBase, T["panel"]), (QPalette.ColorRole.Text, T["text"]),
        (QPalette.ColorRole.WindowText, T["text"]), (QPalette.ColorRole.Button, T["raised"]),
        (QPalette.ColorRole.ButtonText, T["text"]), (QPalette.ColorRole.Highlight, T["accent"]),
        (QPalette.ColorRole.HighlightedText, T["text_on_accent"]), (QPalette.ColorRole.ToolTipBase, T["overlay"]),
        (QPalette.ColorRole.ToolTipText, T["text"]), (QPalette.ColorRole.PlaceholderText, T["text_muted"]),
    ):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(qss(font_pt))
