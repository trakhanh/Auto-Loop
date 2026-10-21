"""Xuất biểu tượng của app (bộ icon duotone trong loopstation/ui/icons.py) ra PNG cho README.

python tests/make_readme_icons.py   → docs/icons/*.png
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "icons"
OUT.mkdir(parents=True, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from loopstation.ui import icons  # noqa: E402

ICONS = {"film": "#a78bfa", "repeat": "#f472b6", "music": "#c4b5fd", "waves": "#22d3ee", "sliders": "#fbbf24",
         "zap": "#34d399", "queue": "#60a5fa", "folder": "#fbbf24", "file_plus": "#93c5fd", "eye": "#f9a8d4",
         "play": "#a78bfa", "sort": "#fb923c"}
for name, color in ICONS.items():
    icons.icon(name, 96, color).pixmap(96, 96).save(str(OUT / f"{name}.png"))
print("Đã lưu", len(ICONS), "biểu tượng vào", OUT)
