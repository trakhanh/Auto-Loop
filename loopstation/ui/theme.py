"""Giao diện tối hiện đại: bảng màu + QSS áp cho toàn ứng dụng."""
from __future__ import annotations

import os
import re

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from ..core import ffmpeg_tools as ft

APP_NAME = "KT Loop Station"
AUTHOR = "By Khánh Trà"
APP_VERSION = "1.4.8"
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
    "accent": "#7c5cff",
    "accent2": "#3b82f6",
    "ok": "#10b981",
    "warn": "#f59e0b",
    "danger": "#ef4444",
}

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
    grad_hover = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8f73ff, stop:1 #5694ff)"
    return f"""
* {{ outline: none; }}
/* danh sách xổ xuống luôn hiện NGAY DƯỚI ô chọn (kiểu Fusion mặc định hiện đè lên ô) */
QComboBox {{ combobox-popup: 0; }}
QComboBox QAbstractItemView {{ background: {C['surface2']}; border: 1px solid {C['border_light']}; padding: 4px;
                              outline: none; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 10px; border-radius: 6px; }}
QComboBox QAbstractItemView::item:selected {{ background: {C['accent']}; color: white; }}
QWidget {{ color: {C['text']}; selection-background-color: {C['accent']}; }}
QMainWindow, QDialog, QMessageBox {{ background: {C['bg']}; }}
QToolTip {{ background: {C['surface2']}; color: {C['text']}; border: 1px solid {C['border_light']};
           padding: 7px 10px; border-radius: 8px; }}

/* ---------- khung chính ---------- */
QWidget#shell {{ background: {C['bg']}; border-top: 1px solid #26304a; }}
QWidget#sidebar {{ background: {C['surface']}; border-right: 1px solid {C['border']}; }}
QListWidget#helpToc {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 10px; padding: 6px;
    outline: none; }}
QListWidget#helpToc::item {{ padding: 6px 8px; border-radius: 7px; color: {C['text']}; }}
QListWidget#helpToc::item:hover {{ background: {C['surface2']}; }}
QListWidget#helpToc::item:selected {{ background: {C['accent']}; color: white; }}
QWidget#sidebar QLabel, QWidget#sidebar QWidget {{ background: transparent; }}
QWidget#sidebar QWidget#sidebarCard {{ background: {C['field']}; }}
QWidget#sidebarCard {{ background: {C['field']}; border: 1px solid {C['border']}; border-radius: 10px; }}
QWidget#header {{ background: {C['surface']}; border-bottom: 1px solid {C['border']}; }}
QWidget#header QLabel {{ background: transparent; }}
QWidget#header QLabel#chip {{ background: {C['surface2']}; }}
QWidget#header QLabel#chipAccent {{ background: {grad}; }}
QWidget#header QLabel#chipError {{ background: rgba(239,68,68,0.16); }}
QWidget#header QLabel#chipWarn {{ background: rgba(245,158,11,0.16); }}
QWidget#header QLabel#chipOk {{ background: rgba(16,185,129,0.15); }}
QWidget#subHeader {{ background: {C['bg']}; border-bottom: 1px solid {C['border']}; }}
QWidget#quickBar {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 10px; }}
QWidget#metricCard {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 10px; }}
QLabel#metricTitle {{ color: {C['muted']}; font-size: 8.5pt; font-weight: 600; background: transparent; }}
QLabel#metricValue {{ color: white; font-size: 10.5pt; font-weight: 700; background: transparent; }}

QLabel#appName {{ font-size: 13.5pt; font-weight: 800; color: white; }}
QLabel#appAuthor {{ color: {C['muted']}; font-size: 8.5pt; }}
QLabel#sectionLabel {{ color: #64708d; font-size: 8pt; font-weight: 800; letter-spacing: 1px;
                      padding: 4px 8px 2px 8px; background: transparent; }}
QLabel#h2 {{ font-size: 10.5pt; font-weight: 700; color: white; background: transparent; }}
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
QGroupBox {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 12px;
            margin-top: 6px; padding: 30px 12px 12px 12px; font-weight: 700; }}
QGroupBox::title {{ subcontrol-origin: padding; subcontrol-position: top left; left: 13px; top: 9px;
                   padding: 0 2px; color: #f1f5f9; font-size: 10pt; font-weight: 700; background: transparent; }}
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
QTabBar::tab:selected {{ background: rgba(124,92,255,0.22); border-color: {C['accent']};
                        color: white; font-weight: 700; }}

/* ---------- nút bấm ---------- */
QPushButton {{ background: {C['surface2']}; border: 1px solid {C['border']}; border-radius: 8px;
              padding: 6px 12px; color: {C['text']}; font-weight: 600; }}
QPushButton:hover {{ border-color: {C['accent']}; background: {C['surface3']}; }}
QPushButton:pressed {{ background: #2c354d; }}
QPushButton:disabled {{ color: #475066; border-color: #1a1f2c; background: #11151f; }}
QPushButton#accentBtn {{ background: rgba(124,92,255,0.18); border: 1px solid {C['accent']};
                        color: #e2dcff; font-weight: 700; }}
QPushButton#accentBtn:hover {{ background: rgba(124,92,255,0.32); color: white; }}
QPushButton#accentBtn:disabled {{ color: #475066; border-color: #1e2433; background: #121621; }}
QPushButton#nextStepBtn {{ background: {grad}; border: none; color: white;
                          font-weight: 700; border-radius: 8px; padding: 6px 16px; }}
QPushButton#nextStepBtn:hover {{ background: {grad_hover}; }}
QPushButton#primary {{ background: {grad}; border: none; color: white; font-size: 11.5pt;
                      font-weight: 700; border-radius: 10px; padding: 10px 20px; }}
QPushButton#primary:hover {{ background: {grad_hover}; }}
QPushButton#primary:disabled {{ background: #1e2433; color: #566079; }}
QPushButton#danger:enabled {{ border-color: rgba(239,68,68,0.65); color: #fca5a5; background: rgba(239,68,68,0.10); }}
QPushButton#danger:hover:enabled {{ background: rgba(239,68,68,0.22); border-color: {C['danger']}; color: white; }}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {C['muted']}; padding: 5px 7px; }}
QPushButton#ghost:hover {{ background: {C['surface2']}; border-color: {C['border']}; color: {C['text']}; }}
QPushButton#pill {{ background: {C['field']}; border: 1px solid {C['border']}; border-radius: 7px;
                   padding: 4px 8px; color: {C['muted']}; font-size: 9pt; font-weight: 600; }}
QPushButton#pill:hover {{ border-color: {C['accent']}; color: white; background: {C['surface2']}; }}
QPushButton#pill:checked {{ background: rgba(124,92,255,0.22); border-color: {C['accent']}; color: white; }}

QPushButton#segL, QPushButton#segM, QPushButton#segR {{ background: {C['field']}; border: 1px solid {C['border']};
    padding: 6px 14px; color: {C['muted']}; border-radius: 0; margin: 0; font-weight: 600; }}
QPushButton#segL {{ border-top-left-radius: 9px; border-bottom-left-radius: 9px; }}
QPushButton#segR {{ border-top-right-radius: 9px; border-bottom-right-radius: 9px; }}
QPushButton#segL:hover, QPushButton#segM:hover, QPushButton#segR:hover {{ color: {C['text']}; background: {C['surface2']}; }}
QPushButton#segL:checked, QPushButton#segM:checked, QPushButton#segR:checked {{
    background: rgba(124,92,255,0.26); border-color: {C['accent']}; color: white; font-weight: 700; }}

QPushButton#nav {{ background: transparent; border: 1px solid transparent; border-radius: 10px; text-align: left;
                  padding: 10px 12px; font-size: 10.5pt; color: {C['muted']}; font-weight: 600; }}
QPushButton#nav:hover:enabled {{ background: {C['surface2']}; color: {C['text']}; }}
QPushButton#nav:checked {{ background: transparent; border-color: transparent; color: white; font-weight: 700; }}
QPushButton#nav:checked:hover {{ background: transparent; }}
/* nền mục đang chọn ở thanh bên: một khối riêng trượt mượt giữa các mục (motion.NavPill) */
QWidget#navPill {{ background: rgba(124,92,255,0.20); border: 1px solid rgba(124,92,255,0.45);
                   border-left: 3px solid {C['accent']}; border-radius: 10px; }}
/* màn hình Bắt đầu */
QLabel#homeHero {{ font-size: 17pt; font-weight: 800; color: white; background: transparent; }}
QPushButton#homeCard {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 14px;
                        text-align: left; padding: 0; }}
QPushButton#homeCard:hover {{ background: {C['surface2']}; border-color: {C['accent']}; }}
QPushButton#homeCard:pressed {{ background: rgba(124,92,255,0.16); }}
QLabel#homeBadge {{ background: {C['surface3']}; border-radius: 10px; }}
QLabel#homeTitle {{ font-size: 12pt; font-weight: 700; color: white; background: transparent; }}
QLabel#homeDesc {{ color: {C['text']}; background: transparent; }}
QLabel#homeExample {{ color: {C['muted']}; font-size: 9pt; background: transparent; }}
/* thanh hướng dẫn từng bước */
QWidget#stepGuide {{ background: {C['surface']}; border-bottom: 1px solid {C['border']}; }}
QPushButton#stepPill {{ border-radius: 12px; padding: 4px 12px; font-weight: 700; border: 1px solid {C['border']};
                        background: transparent; color: {C['muted']}; }}
QPushButton#stepPill[state="current"] {{ background: {C['accent']}; border-color: {C['accent']}; color: white; }}
QPushButton#stepPill[state="done"] {{ color: #6ee7b7; border-color: rgba(16,185,129,0.45); }}
QPushButton#stepPill:hover {{ border-color: {C['accent']}; }}
QLabel#stepArrow {{ color: {C['muted']}; font-size: 13pt; background: transparent; }}
QLabel#stepHint {{ color: {C['text']}; background: transparent; }}
/* dự đoán dung lượng (trang Xuất) */
QLabel#sizeEst {{ font-size: 11.5pt; font-weight: 700; color: #c4b5fd; background: transparent; }}
QLabel#sizeEst[busy="true"] {{ color: #7c86a2; }}
/* thông báo nổi góc dưới (motion.Toast) */
QWidget#toast {{ background: #1c2132; border: 1px solid #343c58; border-radius: 12px; }}
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
QLineEdit#title {{ font-size: 12.5pt; font-weight: 700; background: {C['field']};
                  border: 1px solid {C['border']}; border-radius: 9px; padding: 4px 10px; color: white; }}
QLineEdit#title:hover {{ border-color: {C['border_light']}; }}
QLineEdit#title:focus {{ border-color: {C['accent']}; background: #0b0e16; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{arrow}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {C['surface2']}; border: 1px solid {C['border_light']};
    selection-background-color: {C['accent']}; padding: 4px; border-radius: 8px; }}

QSpinBox, QDoubleSpinBox {{ padding-right: 20px; }}
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
QSlider::handle:horizontal:hover {{ background: #ede9fe; }}
QSlider::sub-page:horizontal:disabled {{ background: #2c3347; }}
QSlider::handle:horizontal:disabled {{ background: #525a70; border-color: #363d52; }}

/* ---------- ô tick ---------- */
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QTreeView::indicator {{ width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid #3d465e; background: {C['field']}; }}
QCheckBox::indicator:hover, QTreeView::indicator:hover {{ border-color: {C['accent']}; }}
QCheckBox::indicator:checked, QTreeView::indicator:checked {{ background: {C['accent']};
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
QTreeView::item:selected {{ background: rgba(124,92,255,0.28); color: white; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {C['surface2']}; color: {C['muted']}; border: none;
    border-bottom: 1px solid {C['border']}; border-right: 1px solid rgba(255,255,255,0.03);
    padding: 7px 8px; font-weight: 700; font-size: 9pt; }}

QTextBrowser {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 12px;
    padding: 12px 18px; }}
QPlainTextEdit {{ background: #080a0f; border: 1px solid {C['border']}; border-radius: 10px;
    padding: 8px; font-family: Consolas, 'Cascadia Mono', monospace; font-size: 9pt; color: #cbd5e1; }}

QProgressBar {{ background: {C['field']}; border: 1px solid {C['border']}; border-radius: 9px;
    min-height: 20px; text-align: center; color: white; font-weight: 700; }}
QProgressBar::chunk {{ background: {grad}; border-radius: 8px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: #2c3347; border-radius: 4px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: #3d4763; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page
    {{ width: 0; height: 0; background: none; }}

QStatusBar {{ background: {C['surface']}; color: {C['muted']}; border-top: 1px solid {C['border']}; }}
QMessageBox {{ background: {C['surface']}; }}
QMenu {{ background: {C['surface2']}; border: 1px solid {C['border_light']}; padding: 4px; border-radius: 8px; }}
QMenu::item {{ padding: 6px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {C['accent']}; color: white; }}
"""


def apply(app: QApplication, font_pt: int = 10) -> None:
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

