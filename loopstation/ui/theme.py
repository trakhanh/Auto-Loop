"""Giao diện tối hiện đại: bảng màu + QSS áp cho toàn ứng dụng."""
from __future__ import annotations

import os
import re

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from ..core import ffmpeg_tools as ft

APP_NAME = "KT Loop Station"
AUTHOR = "By Khánh Trà"
APP_VERSION = "1.6.0"
# nơi lưu cài đặt (registry); KTLS_SETTINGS_ORG dùng cho test để không đụng cài đặt thật
SETTINGS_ORG = os.environ.get("KTLS_SETTINGS_ORG", "KTLoopStation")

C = {
    "bg": "#0b0d13",
    "surface": "#121621",
    "surface2": "#1a2030",
    "surface3": "#232b3e",
    "field": "#0d1018",
    "border": "#252c3f",
    "border_light": "#343e58",
    "text": "#eef1f8",
    "muted": "#8c96b0",
    "accent": "#8b5cf6",  # màu chủ đạo — đổi theo PALETTES (Cài đặt → Màu chủ đạo)
    "accent2": "#ec4899",  # màu thứ hai của dải chuyển màu
    "mid": "#a78bfa",  # chữ / biểu tượng sáng theo màu chủ đạo
    "soft": "#ddd6fe",  # chữ nhạt theo màu chủ đạo
    "ok": "#10b981",
    "warn": "#f59e0b",
    "danger": "#ef4444",
}

# Bộ màu chủ đạo: (tên, màu chính, màu thứ hai, màu sáng, màu nhạt). Đổi ngay ở Cài đặt → Giao diện hiển thị.
PALETTES = {
    "neon": ("Neon tím hồng", "#8b5cf6", "#ec4899", "#a78bfa", "#ddd6fe"),
    "ocean": ("Đại dương", "#06b6d4", "#6366f1", "#67e8f9", "#cffafe"),
    "sunset": ("Hoàng hôn", "#f97316", "#e11d48", "#fdba74", "#ffedd5"),
    "classic": ("Tím xanh (bản cũ)", "#7c5cff", "#3b82f6", "#a78bfa", "#c4b5fd"),
}
PALETTE = "neon"
# màu của bản cũ ghi thẳng trong QSS → thay bằng màu của bộ đang chọn (mọi bộ màu dùng chung một bản QSS)
_OLD = {"accent": "#7c5cff", "accent2": "#3b82f6", "mid": "#a78bfa", "soft": "#c4b5fd"}


# nền / thẻ / viền gốc (xám xanh rất tối) — mỗi bộ màu pha thêm chút màu chủ đạo cho có "hồn"
_BASE = {"bg": ("#0a0b11", 0.035), "surface": ("#11141e", 0.05), "surface2": ("#181d2b", 0.06),
         "surface3": ("#212839", 0.07), "field": ("#0c0e16", 0.03), "border": ("#232a3c", 0.12),
         "border_light": ("#323b54", 0.14)}


def set_palette(key: str) -> None:
    global PALETTE
    if key not in PALETTES:
        key = "neon"
    PALETTE = key
    _name, C["accent"], C["accent2"], C["mid"], C["soft"] = PALETTES[key]
    for k, (base, t) in _BASE.items():
        C[k] = mix(base, C["accent"], t)


def mix(a: str, b: str, t: float) -> str:
    """Trộn hai màu hex: t = 0 → a, t = 1 → b."""
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t), round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def rgba(color: str, alpha: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha:g})"


set_palette(PALETTE)


def qcolor(key: str, alpha: int = 255) -> QColor:
    """Màu theo bộ màu đang chọn (dùng cho phần tự vẽ: đọc lúc vẽ nên đổi bộ màu là đổi theo ngay)."""
    c = QColor(C[key])
    c.setAlpha(alpha)
    return c

# ---------- Bảng quy chuẩn kích thước: mọi trang dùng chung để nhìn gọn, đều tay ----------
# Khoảng cách (px) theo lưới 4: xs 4 · sm 6 · md 8 · lg 12 · xl 16 · xxl 24
SP = {"xs": 4, "sm": 6, "md": 8, "lg": 12, "xl": 16, "xxl": 24}
PAGE_MARGINS = (SP["xl"], SP["lg"], SP["xl"], SP["lg"])  # lề trong của mọi trang (trái, trên, phải, dưới)
FORM_GAP = SP["md"]  # khoảng cách giữa các dòng trong thẻ cài đặt
SECTION_GAP = SP["md"]  # khoảng cách giữa các thẻ / khối
# Thang cỡ chữ (pt, ở cỡ chữ mặc định 10 — tự nhân theo Cài đặt → Cỡ chữ): chỉ dùng các bậc này
FS = {"caption": 8.5, "small": 9, "body": 10, "label": 10.5, "lead": 11.5, "title": 12.5, "brand": 13.5,
      "hero": 17}


def page_layout(layout) -> None:
    """Lề + khoảng cách chuẩn cho bố cục ngoài cùng của một trang."""
    layout.setContentsMargins(*PAGE_MARGINS)
    layout.setSpacing(SECTION_GAP)


_CHECK_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
              '<path d="M3.5 8.5l3 3 6-7" fill="none" stroke="white" stroke-width="2.2" '
              'stroke-linecap="round" stroke-linejoin="round"/></svg>')
_ARROW_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12">'
              '<path d="M2.5 4.5l3.5 3.5 3.5-3.5" fill="none" stroke="#8c96b0" stroke-width="1.6" '
              'stroke-linecap="round" stroke-linejoin="round"/></svg>')
_UP_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
           '<path d="M2 6.5l3-3 3 3" fill="none" stroke="#8c96b0" stroke-width="1.5" '
           'stroke-linecap="round" stroke-linejoin="round"/></svg>')
_DOWN_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
             '<path d="M2 3.5l3 3 3-3" fill="none" stroke="#8c96b0" stroke-width="1.5" '
             'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _asset(name: str, content: str) -> str:
    d = ft.data_dir() / "ui"
    d.mkdir(exist_ok=True)
    p = d / name
    if not p.is_file() or p.read_text(encoding="utf-8") != content:
        p.write_text(content, encoding="utf-8")
    return str(p).replace("\\", "/")


FONT_PT = 10  # cỡ chữ đang dùng (Cài đặt → Cỡ chữ ứng dụng)


def scale() -> float:
    """Tỉ lệ cỡ chữ so với mặc định 10pt (dùng cho các phần tự vẽ / HTML)."""
    return FONT_PT / 10


def qss(font_pt: int = 10) -> str:
    """QSS toàn app. Mọi cỡ chữ ghi trong QSS được nhân theo `font_pt` (mặc định 10) để đổi cỡ chữ có tác dụng."""
    k = font_pt / 10
    base = _qss_base().replace("QWidget {{ color", "QWidget {{ color", 1)
    base = re.sub(r"font-size:\s*([\d.]+)pt", lambda m: f"font-size: {float(m.group(1)) * k:.1f}pt", base)
    return f"QWidget {{ font-size: {font_pt}pt; }}\n" + base


def _qss_base() -> str:
    check = _asset("check.svg", _CHECK_SVG)
    arrow = _asset("arrow.svg", _ARROW_SVG)
    up = _asset("up.svg", _UP_SVG)
    down = _asset("down.svg", _DOWN_SVG)
    grad = f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {C['accent']}, stop:1 {C['accent2']})"
    grad_hover = (f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {mix(C['accent'], '#ffffff', 0.16)}, "
                  f"stop:1 {mix(C['accent2'], '#ffffff', 0.16)})")
    grad_diag = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {C['accent']}, stop:1 {C['accent2']})"
    grad_soft = (f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {rgba(C['accent'], 0.30)}, "
                 f"stop:1 {rgba(C['accent2'], 0.16)})")
    # nền thẻ: hơi trong (thấy quầng sáng phía sau) + dải màu nhẹ từ trên xuống
    card_bg = (f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {rgba(mix(C['surface'], C['accent'], 0.13), 0.95)}, "
               f"stop:1 {rgba(C['surface'], 0.90)})")
    return f"""
* {{ outline: none; }}
/* danh sách xổ xuống luôn hiện NGAY DƯỚI ô chọn (kiểu Fusion mặc định hiện đè lên ô) */
QComboBox {{ combobox-popup: 0; }}
QComboBox QAbstractItemView {{ background: {C['surface2']}; border: 1px solid {C['border_light']}; padding: 4px;
                              outline: none; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 10px; border-radius: 6px; }}
QComboBox QAbstractItemView::item:selected {{ background: {grad}; color: white; }}
QWidget {{ color: {C['text']}; selection-background-color: {C['accent']}; }}
QMainWindow, QDialog, QMessageBox {{ background: {C['bg']}; }}
QToolTip {{ background: {C['surface2']}; color: {C['text']}; border: 1px solid {rgba(C['accent'], 0.55)};
           padding: 7px 10px; border-radius: 8px; }}

/* ---------- khung chính ---------- */
QWidget#shell {{ background: {C['bg']}; border-top: 1px solid {C['border']}; }}
QWidget#sidebar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {mix(C['surface'], C['accent'], 0.16)},
    stop:0.42 {C['surface']}, stop:1 {mix(C['surface'], C['accent2'], 0.10)}); border-right: 1px solid {C['border']}; }}
/* vùng trang: quầng sáng màu chủ đạo ở góc trên trái, lan dần vào nền */
QStackedWidget#pageStack {{ background: qradialgradient(cx:0.0, cy:0.0, radius:1.15, fx:0.0, fy:0.0,
    stop:0 {rgba(C['accent'], 0.30)}, stop:0.5 {rgba(C['accent2'], 0.09)}, stop:1 rgba(0,0,0,0)); }}
QListWidget#helpToc {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 10px; padding: 6px;
    outline: none; }}
QListWidget#helpToc::item {{ padding: 6px 8px; border-radius: 7px; color: {C['text']}; }}
QListWidget#helpToc::item:hover {{ background: {C['surface2']}; }}
QListWidget#helpToc::item:selected {{ background: {grad}; color: white; }}
QWidget#sidebar QLabel, QWidget#sidebar QWidget {{ background: transparent; }}
QWidget#sidebar QWidget#sidebarCard {{ background: {C['field']}; }}
QWidget#sidebarCard {{ background: {C['field']}; border: 1px solid {C['border']}; border-radius: 10px; }}
QWidget#header {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {mix(C['surface'], C['accent'], 0.12)},
    stop:0.55 {C['surface']}, stop:1 {mix(C['surface'], C['accent2'], 0.12)}); }}
QWidget#header QLabel {{ background: transparent; }}
QWidget#header QLabel#chip {{ background: {C['surface2']}; }}
QWidget#header QLabel#chipAccent {{ background: {grad}; }}
QWidget#header QLabel#chipError {{ background: rgba(239,68,68,0.16); }}
QWidget#header QLabel#chipWarn {{ background: rgba(245,158,11,0.16); }}
QWidget#header QLabel#chipOk {{ background: rgba(16,185,129,0.15); }}
QWidget#subHeader {{ background: {C['bg']}; border-bottom: 1px solid {C['border']}; }}
QWidget#quickBar {{ background: {card_bg}; border: 1px solid {C['border']}; border-top-color: {rgba(C['accent'], 0.40)};
                     border-radius: 10px; }}
QWidget#metricCard {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 10px; }}
QLabel#metricTitle {{ color: {C['muted']}; font-size: {FS['caption']}pt; font-weight: 600; background: transparent; }}
QLabel#metricValue {{ color: white; font-size: {FS['label']}pt; font-weight: 700; background: transparent; }}

QLabel#appName {{ font-size: {FS['brand']}pt; font-weight: 800; color: white; }}
QLabel#appAuthor {{ color: {C['muted']}; font-size: {FS['caption']}pt; }}
QLabel#sectionLabel {{ color: #64708d; font-size: {FS['caption']}pt; font-weight: 800; letter-spacing: 1px;
                      padding: 4px 8px 2px 8px; background: transparent; }}
QLabel#h2 {{ font-size: {FS['label']}pt; font-weight: 700; color: white; background: transparent; }}
QLabel#muted {{ color: {C['muted']}; background: transparent; }}
QLabel#info {{ background: rgba(59,130,246,0.10); border: 1px solid rgba(59,130,246,0.32);
               border-radius: 10px; padding: 9px 12px; color: {C['text']}; }}
QLabel#chip {{ background: {C['surface2']}; border: 1px solid {C['border']}; border-radius: 13px;
               padding: 4px 12px; color: {C['text']}; font-weight: 600; }}
QLabel#chipAccent {{ background: {grad}; border: none;
                     border-radius: 13px; padding: 5px 14px; color: white; font-weight: 700; }}
QLabel#chipError {{ background: rgba(239,68,68,0.16); border: 1px solid {C['danger']};
                    border-radius: 13px; padding: 4px 12px; color: #fca5a5; font-weight: 600; }}
QLabel#chipOk {{ background: rgba(16,185,129,0.15); border: 1px solid rgba(16,185,129,0.55);
                 border-radius: 11px; padding: 3px 10px; color: #6ee7b7; font-weight: 600; }}
QLabel#chipOff {{ background: rgba(148,163,184,0.08); border: 1px solid #2b3244;
                  border-radius: 11px; padding: 3px 10px; color: #68728a; }}
QLabel#chipWarn {{ background: rgba(245,158,11,0.16); border: 1px solid {C['warn']};
                   border-radius: 13px; padding: 4px 12px; color: #fcd34d; font-weight: 600; }}

/* ---------- thẻ (GroupBox) hiện đại ---------- */
QGroupBox {{ background: {card_bg}; border: 1px solid {C['border']}; border-top-color: {rgba(C['accent'], 0.42)};
            border-radius: 12px;
            margin-top: 6px; padding: 30px 12px 12px 12px; font-weight: 700; }}
QGroupBox::title {{ subcontrol-origin: padding; subcontrol-position: top left; left: 13px; top: 9px;
                   padding: 0 2px; color: {C['soft']}; font-size: {FS['body']}pt; font-weight: 700; background: transparent; }}
QGroupBox * {{ font-weight: 400; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}
QSplitter::handle:vertical {{ height: 8px; }}

/* ---------- tab con (QTabWidget) ---------- */
QTabWidget::pane {{ background: transparent; border: none; margin-top: 6px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: {C['surface']}; border: 1px solid {C['border']}; color: {C['muted']};
               padding: 7px 14px; margin-right: 6px; border-radius: 9px; font-weight: 600; }}
QTabBar::tab:hover {{ color: {C['text']}; background: {C['surface2']}; border-color: {C['border_light']}; }}
QTabBar::tab:selected {{ background: {grad_soft}; border-color: {C['accent']};
                        color: white; font-weight: 700; }}

/* ---------- nút bấm ---------- */
QPushButton {{ background: {C['surface2']}; border: 1px solid {C['border']}; border-radius: 8px;
              padding: 6px 12px; color: {C['text']}; font-weight: 600; }}
QPushButton:hover {{ border-color: {rgba(C['accent'], 0.85)}; background: {mix(C['surface3'], C['accent'], 0.10)}; }}
QPushButton:pressed {{ background: #2c354d; }}
QPushButton:disabled {{ color: #475066; border-color: #1a1f2c; background: #11151f; }}
QPushButton#accentBtn {{ background: {grad_soft}; border: 1px solid {C['accent']};
                        color: {C['soft']}; font-weight: 700; }}
QPushButton#accentBtn:hover {{ background: {rgba(C['accent'], 0.32)}; color: white; }}
QPushButton#accentBtn:disabled {{ color: #475066; border-color: #1e2433; background: #121621; }}
QPushButton#nextStepBtn {{ background: {grad}; border: none; color: white;
                          font-weight: 700; border-radius: 8px; padding: 6px 16px; }}
QPushButton#nextStepBtn:hover {{ background: {grad_hover}; }}
QPushButton#primary {{ background: {grad}; border: none; color: white; font-size: {FS['lead']}pt;
                      font-weight: 700; border-radius: 10px; padding: 10px 20px; }}
QPushButton#primary:hover {{ background: {grad_hover}; }}
QPushButton#primary:disabled {{ background: #1e2433; color: #566079; }}
QPushButton#danger:enabled {{ border-color: rgba(239,68,68,0.65); color: #fca5a5; background: rgba(239,68,68,0.10); }}
QPushButton#danger:hover:enabled {{ background: rgba(239,68,68,0.22); border-color: {C['danger']}; color: white; }}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {C['muted']}; padding: 5px 7px; }}
QPushButton#ghost:hover {{ background: {C['surface2']}; border-color: {C['border']}; color: {C['text']}; }}
QPushButton#pill {{ background: {C['field']}; border: 1px solid {C['border']}; border-radius: 7px;
                   padding: 4px 8px; color: {C['muted']}; font-size: {FS['small']}pt; font-weight: 600; }}
QPushButton#pill:hover {{ border-color: {C['accent']}; color: white; background: {C['surface2']}; }}
QPushButton#pill:checked {{ background: {grad_soft}; border-color: {C['accent']}; color: white; }}

QPushButton#segL, QPushButton#segM, QPushButton#segR {{ background: {C['field']}; border: 1px solid {C['border']};
    padding: 6px 14px; color: {C['muted']}; border-radius: 0; margin: 0; font-weight: 600; }}
QPushButton#segL {{ border-top-left-radius: 9px; border-bottom-left-radius: 9px; }}
QPushButton#segR {{ border-top-right-radius: 9px; border-bottom-right-radius: 9px; }}
QPushButton#segL:hover, QPushButton#segM:hover, QPushButton#segR:hover {{ color: {C['text']}; background: {C['surface2']}; }}
QPushButton#segL:checked, QPushButton#segM:checked, QPushButton#segR:checked {{
    background: {grad_soft}; border-color: {C['accent']}; color: white; font-weight: 700; }}

/* màn hình chào lần đầu (welcome.WelcomeOverlay) */
QScrollArea#welcomeScroll, QWidget#welcomeInner {{ background: transparent; }}
QFrame#welcomeCard {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {mix(C['surface'], C['accent'], 0.14)},
    stop:0.5 {C['surface']}, stop:1 {mix(C['surface'], C['accent2'], 0.10)}); border: 1px solid {rgba(C['accent'], 0.50)};
    border-radius: 18px; }}
QFrame#welcomeStep {{ background: {rgba(C['bg'], 0.75)}; border: 1px solid {C['border']}; border-radius: 12px; }}
QLabel#welcomeNum {{ background: {grad}; color: white; border-radius: 13px; font-weight: 800; }}
QLabel#welcomeStepTitle {{ color: white; font-size: {FS['lead']}pt; font-weight: 700; background: transparent; }}
QLabel#welcomeStepText {{ color: {C['text']}; background: transparent; }}
/* bộ chọn có khối sáng trượt (motion.SegmentBox): kiểu sản phẩm, kiểu xuất hàng loạt */
QWidget#segBox {{ background: {C['field']}; border: 1px solid {C['border']}; border-radius: 10px; }}
QWidget#segPill {{ background: {grad_soft}; border: 1px solid {C['accent']}; border-radius: 8px; }}
QPushButton#segBtn {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 5px 13px;
                     color: {C['muted']}; font-weight: 600; }}
QPushButton#segBtn:hover {{ color: {C['text']}; background: rgba(255,255,255,0.04); }}
QPushButton#segBtn:checked {{ color: white; font-weight: 700; background: transparent; }}
QPushButton#segBtn:disabled {{ color: #475066; }}

QPushButton#nav {{ background: transparent; border: 1px solid transparent; border-radius: 10px; text-align: left;
                  padding: 10px 12px; font-size: {FS['label']}pt; color: {C['muted']}; font-weight: 600; }}
QPushButton#nav:hover:enabled {{ background: {C['surface2']}; color: {C['text']}; }}
QPushButton#nav:checked {{ background: transparent; border-color: transparent; color: white; font-weight: 700; }}
QPushButton#nav:checked:hover {{ background: transparent; }}
/* nền mục đang chọn ở thanh bên: một khối riêng trượt mượt giữa các mục (motion.NavPill) */
QWidget#navPill {{ background: {grad_soft}; border: 1px solid {rgba(C['accent'], 0.50)};
                   border-left: 3px solid {C['accent']}; border-radius: 10px; }}
/* màn hình Bắt đầu */
#homeHero {{ font-size: {FS['hero']}pt; font-weight: 800; color: white; background: transparent; }}
QPushButton#homeCard {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 14px;
                        text-align: left; padding: 0; }}
QPushButton#homeCard:hover {{ background: {C['surface2']}; border-color: {C['accent']}; }}
QPushButton#homeCard:pressed {{ background: {rgba(C['accent'], 0.16)}; }}
QLabel#homeBadge {{ background: {C['surface3']}; border-radius: 10px; }}
QLabel#homeTitle {{ font-size: {FS['title']}pt; font-weight: 700; color: white; background: transparent; }}
QLabel#homeDesc {{ color: {C['text']}; background: transparent; }}
QLabel#homeExample {{ color: {C['muted']}; font-size: {FS['small']}pt; background: transparent; }}
/* thanh hướng dẫn từng bước */
QWidget#stepGuide {{ background: {mix(C['surface'], C['bg'], 0.5)}; border-bottom: 1px solid {C['border']}; }}
QPushButton#stepPill {{ border-radius: 12px; padding: 4px 12px; font-weight: 700; border: 1px solid {C['border']};
                        background: transparent; color: {C['muted']}; }}
QPushButton#stepPill[state="current"] {{ background: {grad}; border-color: transparent; color: white; }}
QPushButton#stepPill[state="done"] {{ color: #6ee7b7; border-color: rgba(16,185,129,0.45); }}
QPushButton#stepPill:hover {{ border-color: {C['accent']}; }}
QLabel#stepArrow {{ color: {C['muted']}; font-size: {FS['brand']}pt; background: transparent; }}
QLabel#stepHint {{ color: {C['text']}; background: transparent; }}
/* dự đoán dung lượng (trang Xuất) */
QLabel#sizeEst {{ font-size: {FS['lead']}pt; font-weight: 700; color: {C['soft']}; background: transparent; }}
QLabel#sizeEst[busy="true"] {{ color: #7c86a2; }}
/* thông báo nổi góc dưới (motion.Toast) */
QWidget#toast {{ background: {C['surface2']}; border: 1px solid {rgba(C['accent'], 0.50)}; border-radius: 12px; }}
QWidget#toast QLabel {{ background: transparent; color: {C['text']}; font-weight: 600; }}
QPushButton#nav:disabled {{ color: #3b4254; background: transparent; border-color: transparent; }}

/* ---------- ô nhập & chọn ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {C['field']}; border: 1px solid {C['border']};
    border-radius: 8px; padding: 5px 9px; selection-background-color: {C['accent']}; min-height: 20px; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {C['border_light']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {C['accent']}; }}
QLineEdit[bad="true"] {{ border-color: #f59e0b; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    color: #525a70; background: #10131c; border-color: #1c2130; }}
QLineEdit#title {{ font-size: {FS['title']}pt; font-weight: 700; background: {C['field']};
                  border: 1px solid {C['border']}; border-radius: 9px; padding: 4px 10px; color: white; }}
QLineEdit#title:hover {{ border-color: {C['border_light']}; }}
QLineEdit#title:focus {{ border-color: {C['accent']}; background: #0b0e16; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{arrow}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {C['surface2']}; border: 1px solid {C['border_light']};
    selection-background-color: {C['accent']}; padding: 4px; border-radius: 8px; }}

QSpinBox, QDoubleSpinBox {{ padding-right: 20px; }}
QFrame#playerPanel {{ background: #0b0d13; border-left: 1px solid {C['border']}; }}
QLabel#playerInfo {{ color: {C['muted']}; background: {C['surface2']}; border-radius: 6px; padding: 1px 7px;
                    font-size: {FS['caption']}pt; }}
QLabel#playerTitle {{ color: {C['muted']}; font-weight: 700; font-size: {FS['small']}pt; letter-spacing: 1px; }}
QLabel#playerTime {{ color: {C['text']}; font-family: Consolas, 'Cascadia Mono', monospace; font-weight: 700; }}
QLabel#playerTimeTotal {{ color: {C['muted']}; font-family: Consolas, 'Cascadia Mono', monospace; }}
QPushButton#playerBtn {{ background: transparent; border: 1px solid transparent; border-radius: 9px; padding: 6px 8px;
                        color: {C['text']}; font-weight: 700; font-size: {FS['caption']}pt; }}
QPushButton#playerBtn:hover {{ background: {C['surface2']}; border-color: {C['border_light']}; }}
QPushButton#playerBtn:disabled {{ color: #475166; }}
QPushButton#playerPlay {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {C['accent']}, stop:1 {C['accent2']});
                         border: none; border-radius: 21px; min-width: 42px; max-width: 42px;
                         min-height: 42px; max-height: 42px; padding: 0; }}
QPushButton#playerPlay:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {mix(C['accent'], '#ffffff', 0.18)}, stop:1 {mix(C['accent2'], '#ffffff', 0.18)}); }}
QPushButton#playerPlay:pressed {{ background: {mix(C['accent'], '#000000', 0.2)}; }}
QPushButton#playerPlay:disabled {{ background: {C['surface3']}; }}
QComboBox#playerCombo {{ padding: 2px 8px; font-size: {FS['small']}pt; }}
QWidget#timelineDock {{ background: {C['bg']}; border-top: 1px solid {C['border']}; }}
QSplitter#workSplit::handle {{ background: {C['border']}; }}
QSplitter#workSplit::handle:hover {{ background: {C['accent']}; }}
QFrame#batchCard {{ background: {card_bg}; border: 1px solid {C['border']}; border-top-color: {rgba(C['accent'], 0.40)};
                     border-radius: 10px; }}
QLabel#batchTree {{ background: {C['field']}; border: 1px solid {C['border']}; border-radius: 8px; padding: 8px 12px; }}
QSpinBox#timeBox {{ padding: 4px 2px; }}  /* ô giờ / phút / giây: không mũi tên, số căn giữa */
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
    width: 18px; border-left: 1px solid {C['border']}; border-bottom: 1px solid {C['border']};
    border-top-right-radius: 7px; background: {C['surface2']}; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
    width: 18px; border-left: 1px solid {C['border']};
    border-bottom-right-radius: 7px; background: {C['surface2']}; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {C['surface3']}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 9px; height: 9px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 9px; height: 9px; }}

/* ---------- thanh trượt (Slider) ---------- */
QSlider::groove:horizontal {{ height: 6px; background: {C['field']}; border: 1px solid {C['border']};
                            border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {grad}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: white; border: 2px solid {C['accent']}; width: 14px; height: 14px;
                            margin: -5px 0; border-radius: 8px; }}
QSlider::handle:horizontal:hover {{ background: {C['soft']}; }}
QSlider::sub-page:horizontal:disabled {{ background: #2c3347; }}
QSlider::handle:horizontal:disabled {{ background: #525a70; border-color: #363d52; }}

/* ---------- ô tick ---------- */
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QTreeView::indicator {{ width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid #3d465e; background: {C['field']}; }}
QCheckBox::indicator:hover, QTreeView::indicator:hover {{ border-color: {C['accent']}; }}
QCheckBox::indicator:checked, QTreeView::indicator:checked {{ background: {grad_diag};
    border-color: {C['accent']}; image: url("{check}"); }}
QCheckBox:disabled {{ color: #525a70; }}
QCheckBox::indicator:disabled {{ background: #141822; border-color: #232838; }}
QCheckBox::indicator:checked:disabled, QTreeView::indicator:checked:disabled {{ background: #3a3557;
    border-color: #3a3557; }}
QTreeView:disabled {{ color: #525a70; }}

/* ---------- bảng danh sách ---------- */
QTreeWidget, QTreeView {{ background: {C['surface']}; alternate-background-color: #161b28;
    border: 1px solid {C['border']}; border-radius: 10px; padding: 2px; }}
QTreeView::item {{ height: 32px; border: none; padding: 0 4px; }}
QTreeWidget#clips::item {{ height: 60px; }}
QTreeView::item:hover {{ background: rgba(255,255,255,0.04); }}
QTreeView::item:selected {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {rgba(C['accent'], 0.38)},
    stop:1 {rgba(C['accent2'], 0.16)}); color: white; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {C['surface2']}; color: {C['muted']}; border: none;
    border-bottom: 1px solid {C['border']}; border-right: 1px solid rgba(255,255,255,0.03);
    padding: 7px 8px; font-weight: 700; font-size: {FS['small']}pt; }}

QTextBrowser {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 12px;
    padding: 12px 18px; }}
QPlainTextEdit {{ background: #080a0f; border: 1px solid {C['border']}; border-radius: 10px;
    padding: 8px; font-family: Consolas, 'Cascadia Mono', monospace; font-size: {FS['small']}pt; color: #cbd5e1; }}

QProgressBar {{ background: {C['field']}; border: 1px solid {C['border']}; border-radius: 9px;
    min-height: 20px; text-align: center; color: white; font-weight: 700; }}
QProgressBar::chunk {{ background: {grad}; border-radius: 8px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: #2c3347; border-radius: 4px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {rgba(C['accent'], 0.60)}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page
    {{ width: 0; height: 0; background: none; }}

QStatusBar {{ background: {C['surface']}; color: {C['muted']}; border-top: 1px solid {C['border']}; }}
QMessageBox {{ background: {C['surface']}; }}
QMenu {{ background: {C['surface2']}; border: 1px solid {C['border_light']}; padding: 4px; border-radius: 8px; }}
QMenu::item {{ padding: 6px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {grad}; color: white; }}
"""


def apply(app: QApplication, font_pt: int = 10, palette: str | None = None) -> None:
    if palette is not None:
        set_palette(palette)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", font_pt))
    pal = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, C["bg"]), (QPalette.ColorRole.Base, C["surface"]),
        (QPalette.ColorRole.AlternateBase, "#161b28"), (QPalette.ColorRole.Text, C["text"]),
        (QPalette.ColorRole.WindowText, C["text"]), (QPalette.ColorRole.Button, C["surface2"]),
        (QPalette.ColorRole.ButtonText, C["text"]), (QPalette.ColorRole.Highlight, C["accent"]),
        (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.ToolTipBase, C["surface2"]),
        (QPalette.ColorRole.ToolTipText, C["text"]), (QPalette.ColorRole.PlaceholderText, "#646c80"),
    ):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    global FONT_PT
    FONT_PT = font_pt
    app.setStyleSheet(qss(font_pt))

