"""Trang Hướng dẫn sử dụng (thanh bên → Hướng dẫn, hoặc phím F1).

Trực quan: mục lục chủ đề bên trái (có ô tìm, gõ không dấu cũng được), mỗi chủ đề một trang ngắn với
ảnh chụp app đánh số ①②③ (tests/make_help_images.py tạo), sơ đồ các bước, ví dụ, mẹo, và nút
"Mở …" đưa thẳng tới đúng chỗ trong app.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSplitter, QTextBrowser, QVBoxLayout,
    QWidget,
)

from ..core import ffmpeg_tools as ft
from . import branding, icons, theme
from .widgets import FlowLayout, sample_label
from .theme import APP_NAME, APP_VERSION, AUTHOR

T = theme.T  # token màu (đọc lúc dựng trang; trang hướng dẫn dựng một lần khi mở app)

HELP_DIR = Path(__file__).resolve().parent / "assets"
ACCENT, BADGE, CARD, CARD2 = T["accent_text"], T["warn"], T["panel"], T["raised"]

CSS_TEMPLATE = f"""
body {{ color: {T['text']}; font-family: 'Segoe UI'; font-size: @BODY@pt; }}
h1 {{ font-size: @H1@pt; color: {T['text']}; margin: 0 0 2px 0; }}
h2 {{ font-size: @H2@pt; color: {T['text']}; margin: 20px 0 6px 0; }}
h3 {{ font-size: @H3@pt; color: {T['accent_soft']}; margin: 14px 0 4px 0; }}
p, li {{ line-height: 150%; }}
/* đoạn chứa ảnh: giãn dòng thường — 150 % nhân cả chiều cao ảnh, để lại khoảng trống to bằng nửa ảnh bên dưới */
p.shot {{ line-height: 100%; margin-top: 8px; margin-bottom: 8px; }}
a {{ color: {T['info_text']}; text-decoration: none; }}
code {{ background: {T['overlay']}; color: {T['warn_text']}; font-family: Consolas; }}
td {{ vertical-align: top; }}
.k {{ color: {T['warn_text']}; font-family: Consolas; white-space: nowrap; }}
.muted {{ color: {T['text_muted']}; }}
.cap {{ color: {T['text_muted']}; font-size: @SMALL@pt; }}
.big {{ font-size: @H3@pt; font-weight: 700; color: {T['text']}; }}
"""


def css() -> str:
    """CSS trang hướng dẫn theo cỡ chữ đang chọn."""
    from . import theme
    k = theme.scale()
    out = CSS_TEMPLATE
    for tok, pt in (("@BODY@", 10.5), ("@H1@", 17), ("@H2@", 13.5), ("@H3@", 11.5), ("@SMALL@", 9.5)):
        out = out.replace(tok, f"{pt * k:.1f}")
    return out


CSS = css()


# ---------------- các khối trình bày ----------------
def hero(title: str, when: str, actions: tuple = ()) -> str:
    """Tiêu đề chủ đề + "dùng khi nào" + nút đi tới đúng chỗ trong app.

    Không vẽ bằng HTML nữa: trả về dấu ẩn, topic() tách ra → khung đọc hiện thanh tiêu đề thật (help_hub.TopicHeader)."""
    import json
    data = json.dumps({"title": title, "when": when, "actions": [list(x) for x in actions]}, ensure_ascii=False)
    return f"<!--HERO {data} -->"


def steps(items: list[tuple[str, str]]) -> str:
    """Sơ đồ các bước: [①  tên + mô tả] → [②  …] → [③  …]."""
    cells = []
    for k, (name, desc) in enumerate(items, 1):
        if k > 1:
            cells.append(f'<td valign="middle" align="center" width="22"><span style="color:{ACCENT}; '
                         f'font-size:16pt;">›</span></td>')
        cells.append(f'<td bgcolor="{CARD2}" width="{100 // len(items)}%"><span style="color:{BADGE}; '
                     f'font-weight:700; font-size:14pt;">{k}</span>&nbsp; <span class="big">{name}</span><br>'
                     f'<span class="muted">{desc}</span></td>')
    return f'<table width="100%" cellpadding="10" cellspacing="0"><tr>{"".join(cells)}</tr></table>'


def legend(items: list[tuple[str, str]]) -> str:
    """Chú thích các số trên ảnh: [số cam] tên — mô tả."""
    rows = "".join(
        f'<tr><td width="30" align="center" bgcolor="{BADGE}"><b><span style="color:{T["bg"]};">{k}</span></b></td>'
        f'<td>&nbsp;<b>{name}</b> — {desc}</td></tr>' for k, (name, desc) in enumerate(items, 1))
    return f'<table cellpadding="5" cellspacing="4">{rows}</table>'


def img(name: str, caption: str = "") -> str:
    """Ảnh chụp app (đổi cỡ theo khung đọc khi hiển thị)."""
    caption = (caption + " " if caption else "") + "(Bấm vào ảnh để phóng to.)"
    cap = f"<br><span class='cap'>{caption}</span>"
    return f'<p align="center" class="shot">@IMG:{name}@{cap}</p>'


def box(kind: str, text: str) -> str:
    """Khung Mẹo / Lưu ý / Ví dụ."""
    tone, title = {"tip": ("info", "Mẹo"), "warn": ("warn", "Lưu ý"), "ex": ("accent", "Ví dụ")}[kind]
    color = theme.mix(T["panel"], T[tone], 0.55)
    bg = theme.mix(T["panel"], T[tone], 0.14)
    return (f'<table width="100%" cellpadding="10" cellspacing="0" bgcolor="{bg}"><tr>'
            f'<td width="6" bgcolor="{color}"></td><td><b>{title}:</b> {text}</td></tr></table>')


def cards(items: list[tuple[str, str, str]]) -> str:
    """Các thẻ so sánh nằm ngang: (tiêu đề, mô tả, ví dụ)."""
    cells = "".join(f'<td bgcolor="{CARD2}" width="{100 // len(items)}%"><span class="big">{t}</span><br>{d}'
                    f'<br><span class="cap">{e}</span></td>' for t, d, e in items)
    return f'<table width="100%" cellpadding="12" cellspacing="6"><tr>{cells}</tr></table>'


def examples(rows: list[tuple[str, str]], head: tuple[str, str] = ("Gõ", "Nghĩa là")) -> str:
    body = "".join(f'<tr><td bgcolor="{CARD2}"><code>{a}</code></td><td>{b}</td></tr>' for a, b in rows)
    return (f'<table cellpadding="6" cellspacing="2"><tr><td class="muted"><b>{head[0]}</b></td>'
            f'<td class="muted"><b>{head[1]}</b></td></tr>{body}</table>')


def flow_blocks(items: list[tuple[str, str]]) -> str:
    """Dải màu minh hoạ thứ tự phát (ví dụ NỀN ×70 → Cảnh 2 → NỀN ×70 …)."""
    cells = "".join(f'<td bgcolor="{c}" align="center"><b><span style="color:{T["text"]};">{t}</span></b></td>'
                    for t, c in items)
    return f'<table width="100%" cellpadding="8" cellspacing="3"><tr>{cells}</tr></table>'


NEN, CANH, CANH2 = theme.FLOW_COLORS
GREY, GREY2 = T["line_strong"], T["raised"]

# ---------------- nội dung từng chủ đề ----------------
TOPICS: list[tuple[str, str, str, str, str]] = []  # (id, nhóm, icon, tiêu đề, html)


def _tokens(html: str) -> str:
    """Thay @c:tên@ trong HTML tĩnh bằng màu theo token."""
    cols = {"ok_bg": theme.mix(T["panel"], T["success"], 0.30), "raised": T["raised"], "field": T["field"]}
    return re.sub(r"@c:(\w+)@", lambda m: cols[m.group(1)], html)


META: dict[str, dict] = {}  # tid → {"title", "when", "actions"} lấy từ hero()


def topic(tid: str, group: str, icon: str, title: str, html: str) -> None:
    import json
    m = re.search(r"<!--HERO (.*?) -->", html, re.S)
    if m:
        META[tid] = json.loads(m.group(1))
        html = html[:m.start()] + html[m.end():]
    TOPICS.append((tid, group, icon, title, _tokens(html)))


topic("batdau", "Bắt đầu", "home", "Bắt đầu trong 3 bước", hero(
    "Bắt đầu trong 3 bước", "Lần đầu dùng app? Đọc trang này là đủ để làm được video đầu tiên.",
    (("Mở màn hình Bắt đầu", "app:home"), ("Mở dự án mẫu", "app:sample"))) + """
<h2>Mọi video đều đi qua 3 bước</h2>""" + steps([
    ("Video", "Thêm clip, đặt mỗi clip phát bao nhiêu lần (ví dụ 70 lần)."),
    ("Nhạc", "Thêm bài nhạc — nhạc tự lặp cho đủ độ dài video. Thêm tiếng mưa nếu muốn."),
    ("Xuất", "Chọn thư mục lưu → bấm Bắt đầu xuất. Xong là có file .mp4.")]) + """
<h2>Cách nhanh nhất cho nhân viên (file đặt tên 33_4_LOOP A…)</h2>""" + steps([
    ("Thả file hoặc cả thư mục vào trang Video", "app tự nhận tập + tình huống và <b>tự áp mẫu dùng lần trước</b> "
                                                "(không đúng ý: Đổi mẫu… hoặc Ctrl+Z)."),
    ("Xem dải xanh “Sẵn sàng”", "tập, số dòng, độ dài, intro / outro, nhạc, tiếng gốc, tên file — nhìn một chỗ là đủ."),
    ("Bấm Thêm vào hàng đợi ngay trên dải đó", "bảng tự trống chờ tập sau. Thả <b>cả mùa</b> (33_…, 34_…) thì app hỏi "
                                               "một câu: <b>Đưa cả N tập vào hàng đợi</b>.")]) + """
<p>Thanh bên trái có đúng 3 bước này. Ngay dưới thanh trên cùng luôn có <b>thanh hướng dẫn</b> cho biết đang ở
bước mấy và <b>việc cần làm tiếp</b> (bấm vào số bước để chuyển nhanh).</p>
<h2>Màn hình chào</h2>""" + img("welcome", "Hiện một lần khi mới cài app. Xem lại ở Cài đặt → Giao diện hiển thị.") + legend([
    ("Cách làm 3 bước", "Video → Nhạc → Xuất — giống thanh hướng dẫn trên mỗi trang."),
    ("Mở dự án mẫu", "có sẵn clip và nhạc để bấm thử."),
    ("Bắt đầu", "đóng màn hình chào (hoặc bấm Esc / Enter).")]) + """
<h2>Màn hình Bắt đầu</h2>""" + img("home", "Dự án mới tự mở màn hình này. Bấm một thẻ là app chuyển đúng kiểu, đúng bước.") + legend([
    ("Video có nhạc", "clip loop + playlist nhạc → video YouTube dài (dùng nhiều nhất)."),
    ("Chỉ video", "chỉ loop clip, giữ tiếng gốc hoặc thêm tiếng mưa / sóng."),
    ("Chỉ nhạc", "playlist thành một file nhạc dài (MP3…), xuất được nhiều bản khác thứ tự."),
    ("Tiếng nền (ASMR)", "chỉ tiếng mưa, lửa, sóng… phối nhiều lớp, file dài hàng giờ."),
    ("Xuất hàng loạt", "làm nhiều video cùng kiểu một lần: mỗi thư mục con thành một video."),
    ("Mở dự án đã lưu", "tiếp tục một dự án .lsproj làm trước đó.")]) + box(
    "tip", "Trước khi xuất, bấm Phát ở <b>Trình phát</b> bên phải để xem thử cả video ngay trong app; kéo vạch "
           "trên dòng thời gian ở đáy để tua (xem chủ đề <a href='topic:xemtruoc'>Trình phát</a>).") + box(
    "tip", "Muốn thử ngay mà chưa có clip? Bấm <b>Thử: Loop 70 lần</b> hoặc <b>Thử: 3 tiếng</b> ở màn hình Bắt "
           "đầu — có sẵn clip, nhạc, tiếng nền để bấm Xuất thử.") + """
<h2>App tự lưu</h2>
<p>Đóng app lúc nào cũng được: dự án đang làm và hàng đợi được tự lưu, mở lại là còn nguyên (màn hình Bắt đầu có nút
<b>Tiếp tục dự án đang làm</b>). Muốn giữ một bản riêng thì bấm <b>Lưu</b> (Ctrl+S) thành file <code>.lsproj</code>.</p>""")

topic("kieu", "Bắt đầu", "video_music", "Chọn kiểu sản phẩm", hero(
    "Chọn kiểu sản phẩm", "3 nút ở thanh trên cùng, cạnh tên dự án. Đổi lúc nào cũng được — các trang tự đổi theo.") + cards([
    ("Video có nhạc", "Clip loop + playlist nhạc tự lặp theo độ dài video → <code>.mp4</code>",
     "Ví dụ: clip nền ×70 xen các cảnh, nhạc lofi đủ 1 giờ"),
    ("Chỉ video", "Chỉ loop clip, không dùng playlist → <code>.mp4</code>. Vẫn giữ tiếng gốc / thêm tiếng nền.",
     "Ví dụ: cảnh mưa 3 giờ có tiếng mưa"),
    ("Chỉ nhạc", "Playlist lặp đủ thời lượng → <code>.mp3 .m4a .flac .wav</code>. Không cần clip.",
     "Ví dụ: 10 bài → file 1 giờ, xuất 4 bản")]) + """
<h2>Bước nào dùng cho kiểu nào?</h2>
<table cellpadding="7" cellspacing="2">
<tr><td></td><td class="muted"><b>1. Video</b></td><td class="muted"><b>2. Nhạc &amp; Nền</b></td><td class="muted"><b>3. Xuất</b></td></tr>
<tr><td><b>Video có nhạc</b></td><td bgcolor="@c:ok_bg@">✓ clip</td><td bgcolor="@c:ok_bg@">✓ playlist + tiếng nền</td><td bgcolor="@c:ok_bg@">✓ .mp4</td></tr>
<tr><td><b>Chỉ video</b></td><td bgcolor="@c:ok_bg@">✓ clip</td><td bgcolor=GREY2>chỉ tiếng nền (tuỳ chọn)</td><td bgcolor="@c:ok_bg@">✓ .mp4</td></tr>
<tr><td><b>Chỉ nhạc</b></td><td bgcolor=GREY2>bỏ qua</td><td bgcolor="@c:ok_bg@">✓ playlist / tiếng nền + độ dài</td><td bgcolor="@c:ok_bg@">✓ file nhạc</td></tr>
</table>""" + box("tip", "Muốn video dài <b>đúng bằng</b> một lượt playlist (ví dụ playlist 30 phút → video 30 phút): kiểu "
                         "Video có nhạc → trang Video → thẻ <b>Độ dài</b> → <i>Theo độ dài nhạc</i>."))

topic("tungu", "Bắt đầu", "help", "Từ ngữ trong app", hero(
    "Từ ngữ trong app", "Mỗi việc chỉ có một tên, dùng giống nhau ở mọi trang (Video, Nhạc, Xuất, Xuất hàng loạt) — "
    "đọc một lần là hiểu cả app.") + examples([
    ('Kiểu xuất', 'Video có nhạc · Chỉ video · Chỉ nhạc — 3 nút ở thanh trên cùng (Xuất hàng loạt có đúng 3 nút này).'),
    ('Clip nền', 'clip được lặp nhiều lần và nằm xen giữa các cảnh (tên có chữ loop, nen, bg).'),
    ('Clip loop', 'mỗi clip Loop1, Loop2… khi <b>Xếp lần lượt</b>: phát hết loop này rồi tới loop kia.'),
    ('Cảnh chèn', 'clip chèn giữa các đoạn clip nền khi <b>Xen kẽ clip nền</b> (đặt tên 2_…, 3_…).'),
    ('Clip nội dung', 'clip không có chữ loop trong tên (ví dụ Content.mp4) — đặt ở đầu / cuối khi Xếp lần lượt.'),
    ('Cách xếp clip', '<b>Xen kẽ clip nền</b> (nền → cảnh → nền…) · <b>Xếp lần lượt</b> (Loop1 ×60 → Loop2 ×60…) · Không xếp.'),
    ('Số lần phát', 'clip (hoặc bài nhạc) phát mấy lần liền: 70 = 70 lần, 10p = cho đủ 10 phút, 50-80 = ngẫu nhiên.'),
    ('Lượt', 'một lần phát hết cả chuỗi clip (hoặc cả playlist). “Lặp lại cả chuỗi 3 lượt” = phát chuỗi 3 lần.'),
    ('Hoà hình', 'hai cảnh mờ chồng vào nhau ở chỗ nối (crossfade). Để 0 giây (hiện <b>Cắt</b>) = nối thẳng.'),
    ('Nối loop', 'hoà hình giữa các lần lặp của <b>cùng một clip</b> — che chỗ nối bị giật.'),
    ('Sang clip', 'hoà hình khi chuyển sang <b>clip kế tiếp</b>.'),
    ('Đoạn lấy', 'chỉ dùng phần giữa của clip (bỏ vài giây đầu / cuối); <b>Lấy toàn bộ</b> = dùng nguyên clip.'),
    ('Chế độ độ dài · Dài bao lâu', 'video dài theo số lần phát (Thủ công), đúng số giờ đặt ở ô <b>Dài bao lâu</b> (Thời lượng mục tiêu), hoặc bằng một lượt playlist (Theo độ dài nhạc).'),
    ('Trình phát', 'khung xem bên phải: phát thử đúng như bản xuất. <b>Space</b> = Phát / Dừng ở mọi chỗ (trừ lúc gõ chữ).'),
    ('Bảng trộn âm', 'chỉnh to / nhỏ <b>Nhạc</b>, <b>Tiếng gốc clip</b>, từng lớp <b>Tiếng nền</b> — dùng chung mọi kiểu.'),
    ('Tiếng gốc clip', 'tiếng có sẵn trong file video.'),
    ('Tiếng nền', 'mưa, sóng, lửa… phát lặp xuyên suốt dưới nhạc / video.'),
    ('Hàng đợi', 'danh sách việc chờ xuất; bấm <b>Chạy hàng đợi</b> để xuất lần lượt (ví dụ qua đêm).'),
    ('Xuất hàng loạt', 'mỗi <b>thư mục con</b> trong <b>thư mục cha</b> thành một video / file nhạc, cài đặt theo dự án đang mở.'),
    ('Bật / Tắt', 'ô tick đầu dòng: dòng tắt thì không dùng (Ctrl+Space cho các dòng đang chọn).'),
    ('Dự án (.lsproj)', 'file lưu mọi cài đặt để mở lại. Nút <b>Thử: …</b> mở dự án dùng thử có sẵn clip và nhạc.')], ("Từ", "Nghĩa là")))

topic("video", "Làm video", "film", "Trang Video: clip & số lần loop", hero(
    "Trang Video", "Thêm clip / ảnh, đặt số lần phát, xếp thứ tự. Đây là nơi quyết định video dài bao lâu.",
    (("Mở trang Video", "app:video"),)) + img("video", "Trang Video với dự án mẫu “Loop 70 lần”.") + legend([
    ("Thêm clip", "<b>Thêm file</b> / <b>Thư mục</b>, hoặc <b>kéo thả</b> video, ảnh, cả thư mục vào bảng (bật <i>Quét thư mục con</i> để lấy cả thư mục bên trong). "
                  "<b>A–Z</b> xếp theo tên (clip2 trước clip10), <b>Xáo</b> đổi thứ tự ngẫu nhiên, <b>Chọn ▾</b> bật / tắt / đảo ngược tất cả. Ô tìm tên file (Ctrl+F) — gõ không dấu cũng được."),
    ("Bảng clip", "mỗi dòng một clip, kéo lên / xuống để đổi thứ tự. <b>Bấm đúp ô</b> để sửa: Số lần phát, Đoạn lấy, Nối loop, Sang clip."),
    ("Xen kẽ clip nền", "tự xếp kiểu <i>nền ×70 → cảnh 2 → nền ×70 → cảnh 3 …</i> theo tên file. Nhiều clip loop "
                        "(Loop1, Loop2…): nút <b>Xếp lần lượt…</b> bên cạnh (xem chủ đề Xen kẽ)."),
    ("Đặt nhanh", "bôi đen nhiều dòng rồi đặt số lần phát một lượt (×1, ×10, ×70, 10p, 1h) → <b>Áp dụng</b>; <b>Bật tự giãn</b> / <b>Bỏ giãn</b>. "
                  "Hàng <i>Cắt đoạn &amp; hoà hình ▾</i>: <b>Áp dụng cắt</b> / <b>Lấy toàn bộ</b>, <b>Áp dụng nối</b> / <b>Bỏ nối</b>, <b>Nhân bản</b>, <b>Xem thử nối</b>."),
    ("3 thẻ cài đặt", "<b>Độ dài</b> (tổng thời lượng, thứ tự, Intro/Outro) · <b>Khung &amp; Tiếng</b> (clip khác tỉ lệ, ảnh tĩnh, mờ dần cuối, tiếng gốc) · <b>Màu &amp; Logo</b>."),
    ("Dòng thời gian", "nhìn tổng thể: làn CLIP và làn NHẠC. Lăn chuột để phóng to, kéo để di chuyển, nhấp đúp để xem toàn bộ."),
    ("Thanh hướng dẫn", "đang ở bước mấy + việc nên làm tiếp."),
    ("Tiếp theo", "sang bước Nhạc (hoặc Xuất nếu không dùng nhạc).")]) + """
<h2>Ô “Số lần phát” — gõ gì?</h2>""" + examples([
    ("70", "phát 70 lần liền (loop 70 lần)"), ("1", "phát 1 lần, không loop"), ("0", "bỏ qua clip này"),
    ("50-80", "ngẫu nhiên từ 50 đến 80 lần"), ("10p  hoặc  10:00", "loop cho đủ <b>10 phút</b> — app tự tính số lần"),
    ("90s · 1h · 1:30:00", "loop cho đủ 90 giây / 1 giờ / 1 giờ 30 phút"),
    ("1h30 · 3 tiếng · 2 giờ 15 phút", "cũng được — gõ tự nhiên như nói")]) + box(
    "ex", "<b>A 10 phút → B → A 10 phút</b>: đặt A = <code>10p</code>, B = <code>1</code>; chuột phải A → <i>Nhân bản dòng</i> "
          "(Ctrl+D) rồi kéo bản sao xuống dưới B. Mỗi bản sao có số lần phát, đoạn cắt, crossfade riêng.") + """
<h2>Những thao tác hay dùng</h2>
<ul>
<li><b>Ô tick</b> đầu dòng: bật / tắt clip (phím <span class="k">Ctrl+Space</span> cho các dòng đang chọn).</li>
<li><b>Bấm đúp tên file</b> để xem clip. <b>Chuột phải</b> một dòng: Mở / Xem thử file, Hiện trong Explorer, Chọn đoạn lấy…,
Nhân bản dòng, Xen kẽ clip nền…, Bật / Tắt, Đưa lên / xuống, Xoá.</li>
<li><b>Xem thử nối</b> (hàng <i>Cắt đoạn &amp; hoà hình ▾</i>): xuất nhanh clip đang chọn phát 2 lần rồi sang clip kế, để xem crossfade có mượt không.</li>
<li>Clip khác độ phân giải / fps: không sao, app tự chuẩn hoá (thông tin hiện màu cam).</li>
<li>Làm sai? <span class="k">Ctrl+Z</span> để quay lại.</li>
</ul>
<h2>Thẻ Khung &amp; Tiếng</h2>""" + examples([
    ("Clip khác tỉ lệ", "<b>Viền đen</b> (giữ nguyên tỉ lệ) · <b>Nền mờ</b> (đẹp cho clip dọc) · <b>Cắt</b> cho đầy khung · <b>Kéo giãn</b>"),
    ("Ảnh tĩnh", "mỗi ảnh hiện bao nhiêu giây một lần phát (mặc định 8 giây)"),
    ("Mờ dần cuối video", "hình và tiếng nhỏ dần ở cuối (mặc định 3 giây)"),
    ("Tiếng gốc clip", "<b>Giữ, trộn với nhạc</b> (mặc định) · <b>Chỉ tiếng gốc, không dùng nhạc</b> · <b>Tắt</b>")], ("Mục", "Chọn được")) + box(
    "tip", "Độ to của nhạc / tiếng gốc chỉnh ở <a href='topic:tron'>Bảng trộn âm</a> (nút <i>Chỉnh âm lượng ở Bảng trộn âm…</i>)."))

topic("xenke", "Làm video", "repeat", "Xen kẽ clip nền", hero(
    "Xen kẽ clip nền", "Có 1 clip nền (loop) và vài cảnh khác? App tự xếp nền nằm giữa mọi cảnh, theo tên file.",
    (("Mở Xen kẽ clip nền", "app:interleave"),)) + """
<h2>Kết quả trông như thế này</h2>""" + flow_blocks([
    ("NỀN ×70", NEN), ("Cảnh 2", CANH), ("NỀN ×70", NEN), ("Cảnh 3", CANH2), ("NỀN ×70", NEN), ("Cảnh 4", CANH), ("NỀN ×70", NEN)]) + """
<h2>Đặt tên file để app tự nhận</h2>""" + examples([
    ("loop_mua.mp4", "clip <b>nền</b> (tên có chữ <code>loop</code>, hoặc <code>nen</code>, <code>bg</code>, <code>base</code>)"),
    ("2_canh-pho.mp4", "cảnh thứ 2"), ("3_canh-cafe.mp4", "cảnh thứ 3"), ("10_canh-cuoi.mp4", "cảnh thứ 10 (xếp đúng sau 9, không bị lên trước 2)")],
    ("Tên file", "App hiểu là")) + box(
    "tip", "Kéo cả thư mục có file <code>loop…</code> vào bảng là app tự hiện gợi ý <b>Xen kẽ ngay</b>.") + """
<h2>Hộp thoại Xen kẽ</h2>""" + img("interleave") + legend([
    ("Mẫu có sẵn", "Nền ×70 xen từng cảnh · Nền 10 phút xen từng cảnh · lặp cả mẫu 4 lượt · cảnh ngẫu nhiên 6 lượt. <i>Lưu mẫu…</i> để dùng lại cách xếp của mình."),
    ("Clip nền", "app tự chọn theo tên; đổi được nếu nhận sai."),
    ("Số lần phát clip nền", "<code>70</code> = 70 lần, <code>10p</code> = 10 phút."),
    ("Lặp lại cả chuỗi", "ví dụ 2 cảnh, lặp 4 lượt → nền, cảnh A, nền, cảnh B, nền, cảnh A… Tick <i>Mỗi lượt xáo lại</i> để mỗi lượt khác thứ tự."),
    ("Cảnh chèn", "kéo thả để đổi cảnh nào trước, bỏ tick để không dùng. <b>Xuất hiện</b> = chèn mấy lần mỗi lượt, <b>Phát</b> = mỗi lần phát mấy lần liền."),
    ("Xem trước", "đúng bảng sẽ tạo + tổng thời lượng. Ô <i>Mở đầu bằng nền</i> / <i>Kết thúc bằng nền</i> chọn video bắt đầu / kết thúc bằng clip nền hay bằng cảnh."),
    ("Áp dụng vào bảng", "thay bảng clip bằng bảng mới (Ctrl+Z để quay lại).")]) + """
<h2>Nhiều clip loop: xếp lần lượt từng loop</h2>
<p>Thư mục có <b>Content.mp4</b> và <b>Loop1.mp4 … Loop6.mp4</b>, muốn phát Content rồi lần lượt từng loop, mỗi cái
lặp 60 lần? Bấm <b>Xếp lần lượt…</b> (cạnh nút Xen kẽ clip nền) — kéo cả thư mục vào bảng là app tự gợi ý.</p>""" + flow_blocks([
    ("Content", CANH2), ("Loop1 ×60", NEN), ("Loop2 ×60", CANH), ("Loop3 ×60", NEN), ("…", GREY), ("Loop6 ×60", CANH)]) + examples([
    ("Số lần phát mỗi loop", "<code>60</code> = 60 lần · <code>10p</code> = loop cho đủ 10 phút · <code>50-80</code> = ngẫu nhiên"),
    ("Clip nội dung", "file tên <b>không</b> có chữ loop (Content, Intro…): đặt ở đầu, ở cuối, hoặc cả đầu và cuối"),
    ("Lặp lại cả chuỗi", "phát hết Loop1 → Loop6 rồi lặp lại cả chuỗi N lượt"),
    ("Thứ tự loop", "theo tên: Loop2 trước Loop10 (đánh số 1, 2, 3… là được)")], ("Ô", "Nghĩa là")) + box(
    "tip", "Xuất hàng loạt cũng có mẫu này: ô <b>Cách xếp clip</b> → <i>Xếp lần lượt: từng loop ×60, clip nội dung ở đầu / ở cuối</i>. "
           "Mọi clip loop đều nhận crossfade <b>Nối loop</b> của hộp thoại.") + box(
    "tip", "Content và các loop khác fps (ví dụ 30 và 24)? App xuất theo fps của clip phát lâu nhất (các loop) "
           "để phần lớn video không bị giật.") + """
<h2>Thư viện mẫu: xem mọi mẫu, tự tạo mẫu mới</h2>
<p>Bấm <b>Thư viện mẫu…</b> (trên bảng clip, cạnh Xếp lần lượt). Mỗi mẫu có <b>dải màu ví dụ kết quả</b> — app áp thật
mẫu lên bộ tên file ví dụ, mỗi clip 10 giây — kèm tổng thời lượng. Bấm <b>Dùng mẫu này</b> để áp vào bảng.</p>""" + examples([
    ("Loop A ×57 kẹp Loop B (bảng clip)", "(LOOP AB nếu có) → STT_loopB → STT_loopA ×57 → STT_loopB → STT_loopA; 1_… đến "
                                          "10_… nối thành 1 video"),
    ("Nền ×70 xen từng cảnh", "Nền ×70 → Cảnh 2 → Nền ×70 → Cảnh 3 → … → Nền ×70"),
    ("Nền 10 phút xen từng cảnh", "như trên, mỗi lần nền loop đủ 10 phút"),
    ("Nền ×70 xen cảnh — lặp cả mẫu 4 lượt", "chuỗi nền / cảnh trên lặp 4 lượt"),
    ("Nền 5 phút, cảnh ngẫu nhiên — lặp 6 lượt", "6 lượt, mỗi lượt cảnh xáo thứ tự khác"),
    ("Từng loop ×60, clip nội dung ở đầu", "Content → Loop1 ×60 → Loop2 ×60 → …"),
    ("Từng loop ×60, clip nội dung ở cuối", "Loop1 ×60 → Loop2 ×60 → … → Content")], ("7 mẫu có sẵn", "Kết quả")) + box(
    "tip", "Mẫu có sẵn nằm trong app nên <b>máy nào cài cũng có</b>. Mẫu bạn tự lưu chỉ nằm trên máy đã lưu. Muốn đổi "
            "mẫu có sẵn: bấm <b>Sửa</b> → app tạo <i>bản của bạn</i>, mẫu gốc vẫn còn.") + """
<h2>Mẫu bảng clip của bạn: dùng lại cho video khác</h2>
<p>Bảng tự xếp (ví dụ <b>5_loopB ×1 → 5_loopA ×57 → 5_loopB ×1 → 5_loopA ×1</b>) dùng lại cho video 6, 7…: trong
Thư viện mẫu bấm <b>Lưu bảng hiện tại thành mẫu…</b>, hoặc <b>Tạo mẫu mới…</b> để tự gõ từng dòng (vai + số lần phát +
nối loop). Mẫu nhớ file theo <b>tên bỏ số thứ tự ở đầu</b>, nên áp được cho bộ file khác cùng cách đặt tên.</p>""" + flow_blocks([
    ("STT_loopB ×1", CANH), ("STT_loopA ×57", NEN), ("STT_loopB ×1", CANH), ("STT_loopA ×1", NEN)]) + examples([
    ("5_loopB.mp4, 6_loopB.mp4, 12 - loopB.mov", "cùng vai <b>STT_loopB</b>"),
    ("5_loopA.mp4, 6_loopA.mp4", "cùng vai <b>STT_loopA</b>"),
    ("33_4_LOOP A.mp4, 33_10_Loop_A.mov", "<b>tập 33</b>, tình huống 4 / 10, vai <b>STT_loopA</b>"),
    ("Content.mp4 (không có số đầu)", "vai <b>Content</b> — cũng dùng được")], ("Tên file", "App hiểu là")) + box(
    "tip", "Vai không phân biệt cách viết: <b>LOOP A</b> = <b>Loop_A</b> = <b>loopA</b> (bỏ qua hoa / thường, dấu cách, "
           "_ và -).") + """
<h3>Tạo mẫu (làm một lần)</h3>""" + steps([
    ("Cách 1 — từ bảng đang có", "xếp bảng của 1 video đúng ý (số lần phát, nối loop, cắt đoạn) → <b>Thư viện mẫu…</b> → "
                                 "<b>Lưu bảng hiện tại thành mẫu…</b>."),
    ("Cách 2 — tự gõ", "<b>Thư viện mẫu…</b> → <b>Tạo mẫu mới…</b>: mỗi dòng gõ vai (loopA), số lần phát (57 · 10p · 50-80), "
                       "nối loop; ▲ ▼ đổi thứ tự. Dải màu bên dưới cho thấy kết quả ngay."),
    ("Đặt tên và Lưu mẫu", "ví dụ <i>Loop A ×57 kẹp Loop B</i>. Mẫu của bạn sửa / xoá được ngay trong Thư viện.")]) + """
<h3>Dùng mẫu (mỗi video mới)</h3>""" + steps([
    ("Thư viện mẫu… → Dùng mẫu này", "mở hộp thoại áp mẫu; bảng giữa hộp thoại là đúng bảng sẽ tạo."),
    ("Chọn file", "thêm file video mới vào bảng trước, hoặc bấm <b>Lấy file từ thư mục khác…</b> trong hộp thoại."),
    ("Xem cột Sẽ dùng file rồi Áp dụng vào bảng", "dòng tím = bắt đầu tình huống mới; chữ cam ở dưới báo file còn thiếu. "
                                                   "Không ưng thì Ctrl+Z.")]) + legend([
    ("Mẫu lưu gì", "thứ tự dòng, số lần phát (×57, 10 phút, ngẫu nhiên), nối loop, sang clip, cắt đoạn, bật / tắt từng dòng."),
    ("Áp dụng", "lấy file trong bảng hiện tại, hoặc <i>Lấy file từ thư mục khác…</i> (thư mục video 6). Cột <b>Sẽ dùng file</b> "
                "cho thấy file nào khớp; vai thiếu file thì dòng đó bị bỏ. Ctrl+Z để quay lại."),
    ("Nhiều tình huống một thư mục", "thư mục có <b>1_loopA, 1_loopB … 10_loopA, 10_loopB</b>: mẫu lặp cho từng số 1 → 10 "
                                     "(2 trước 10) rồi nối tiếp thành <b>một video</b>. File không có số ở đầu "
                                     "(Content.mp4…) dùng chung cho mọi tình huống."),
    ("Dòng “Chỉ khi có file”", "cho vai chỉ vài tình huống có, ví dụ <b>33_2_LOOP AB</b>: tình huống có file thì "
                                "dùng (mẫu có sẵn đặt <b>LOOP AB</b> ở đầu tình huống), không có thì bỏ, không báo thiếu. "
                                "Tick ở cột <b>Chỉ khi có file</b> trong trình tạo mẫu."),
    ("File chưa có trong mẫu", "file đánh số mà mẫu chưa có vai đó (ví dụ 34_5_LOOP C) không được dùng — app báo tên "
                               "file để bạn thêm dòng cho vai đó (Thư viện mẫu → Sửa)."),
    ("Tên Tập_STT_Vai", "tên có hai số ở đầu (<b>33_4_LOOP A</b>): số đầu là <b>tập</b>, số sau là <b>tình huống</b>. "
                        "Mỗi tập là <b>một video riêng</b>. Thư mục có nhiều tập thì hộp thoại có ô <b>Tập</b> để chọn."),
    ("Xuất hàng loạt", "ô <b>Cách xếp clip</b> → <i>Mẫu bảng clip: tên mẫu</i>: mỗi thư mục con (5_…, 6_…) dựng bảng theo mẫu, "
                       "giữ đúng nối loop của mẫu. Thư mục có nhiều tập (33_…, 34_…) tự tách thành <b>Tập 33</b>, "
                       "<b>Tập 34</b> — mỗi tập một video. Chọn thẳng thư mục chứa file (không có thư mục con) cũng được.")]))

topic("dodai", "Làm video", "clock", "Độ dài video", hero(
    "Độ dài video", "Trang Video → thẻ Độ dài. Mặc định video dài đúng theo bảng clip.",
    (("Mở trang Video", "app:video"),)) + cards([
    ("Thủ công", "Phát đúng một lượt theo bảng: dài bao nhiêu là do số lần phát.", "Dễ hiểu nhất, dùng cho đa số video"),
    ("Thời lượng mục tiêu", "Gõ số vào 3 ô <b>giờ · phút · giây</b> (ví dụ <code>10</code> ở ô giờ) hoặc bấm 30p / 1h / 10h → app tự lặp cho đủ.",
     "Lặp cả chuỗi, hoặc chỉ giãn các clip tick “Tự giãn”"),
    ("Theo độ dài nhạc", "Video dài đúng bằng một lượt playlist.", "Không dùng được ở kiểu Chỉ video")]) + """
<h2>Nhập thời lượng thế nào?</h2>""" + flow_blocks([("10", GREY), ("giờ", GREY2), ("30", GREY),
                                                     ("phút", GREY2), ("0", GREY), ("giây", GREY2)]) + examples([
    ("10 ở ô giờ", "10 giờ"), ("Tab", "sang ô phút / giây"), ("↑ ↓", "tăng / giảm 1 trong ô đang chọn"),
    ("90 ở ô phút", "tự đổi thành 1 giờ 30 phút")], ("Làm", "Kết quả")) + box(
    "tip", "Bấm vào ô là số được bôi đen sẵn — gõ là thay luôn. Bấm <b>Enter</b> hoặc bấm ra ngoài để áp dụng "
           "(đang gõ dở app không tính lại). Hoặc bấm nhanh các nút <b>30p · 1h · 2h · 3h · 10h</b>.") + """
<ul>
<li><b>Lặp lại cả chuỗi</b>: V1→V6 rồi lại V1→V6… Ô <i>Mỗi lượt lặp lại xáo thứ tự mới</i> bật sẵn — bỏ tick nếu muốn lượt nào cũng y hệt.</li>
<li><b>Tăng số lần phát của clip tick “Tự giãn”</b>: phát một chuỗi, chỉ các clip được tick dài ra cho đủ giờ.</li>
<li><b>Cắt chính xác đúng thời lượng đích (kèm mờ dần)</b> — bật sẵn: cắt phần dư cho tròn (ví dụ đúng 3:00:00).</li>
<li><b>Thứ tự clip</b>: theo bảng hoặc ngẫu nhiên. Chọn <b>Ngẫu nhiên</b> thì ngay trên bảng clip hiện dải tím <b>Thứ tự sẽ xuất</b>
(1. … → 2. … → …) — xuất ra đúng thứ tự đó. Nhiều clip (40–50): bấm <b>Xem đủ thứ tự…</b> mở cửa sổ riêng, mỗi clip một dòng
có ảnh xem trước, số lần, phát lúc mấy phút. <b>Trộn lại</b>: ra thứ tự khác · <b>Dùng thứ tự này</b>: chép thứ tự vào bảng để sửa tay
tiếp (Ctrl+Z quay lại). <b>Số mầm</b> giữ kết quả ngẫu nhiên giống hệt bản xem trước.</li>
<li><b>Xem chi tiết từng lượt phát</b>: liệt kê từng lượt phát clip nào, bao nhiêu lần.</li>
</ul>""" + box("tip", "Thanh trên cùng luôn hiện <b>Tổng</b> thời lượng. Chip vàng là có lưu ý — rê chuột lên để đọc.") + box(
    "warn", "Video / file nhạc dài tối đa <b>48 giờ</b>, mỗi clip phát tối đa <b>99.999 lần</b>. Gõ quá mức thì app tự đưa về mức tối đa."))

topic("catdoan", "Làm video", "scissors", "Cắt đoạn, crossfade, Intro / Outro", hero(
    "Cắt đoạn, crossfade, Intro / Outro", "Làm chỗ nối mượt, bỏ phần thừa đầu / cuối clip, thêm đoạn mở đầu / kết thúc cố định.",
    (("Mở trang Video", "app:video"),)) + """
<h2>Đoạn lấy — chỉ dùng phần giữa clip</h2>""" + flow_blocks([("bỏ 2s đầu", GREY), ("dùng 2s → 8s", T["accent"]), ("bỏ 2s cuối", GREY)]) + """
<p>Bấm đúp ô <b>Đoạn lấy</b>: hộp thoại có trình phát tự lặp đúng đoạn đã chọn. Kéo 2 tay nắm, hoặc phát tới chỗ muốn cắt
rồi bấm <i>Đặt điểm đầu tại đây</i> / <i>Đặt điểm cuối tại đây</i> (phím <span class="k">I</span> / <span class="k">O</span>,
<span class="k">Space</span> phát / dừng). Đoạn cắt áp cho <b>mọi lần</b> loop. Bấm <b>Lưu đoạn cắt</b> để áp dụng.</p>
<ul>
<li>Nút nhanh: <b>Lấy toàn bộ</b> · <b>Bỏ 0.5s / 1s / 2s mỗi đầu</b> · <b>Giữ đoạn giữa</b> (lấy đúng chính giữa clip, dài bằng số giây bên cạnh).</li>
<li><b>Lặp đoạn đã chọn</b>: trình phát lặp lại đoạn để nghe / nhìn chỗ nối. <b>Mở cửa sổ xem lớn</b> để xem toàn màn hình.</li>
<li>Đang chọn nhiều dòng: tick <b>Áp dụng cho cả N clip đang chọn</b>. Hoặc bôi đen các dòng → <i>Cắt đoạn &amp; hoà hình ▾</i> → Áp dụng cắt.</li>
</ul>
<h2>Crossfade (hoà hình)</h2>""" + examples([
    ("Nối loop", "hoà hình giữa các lần loop của <b>chính clip đó</b> (che chỗ nối bị giật)"),
    ("Sang clip", "hoà hình khi chuyển sang clip kế tiếp"), ("Cắt", "nối thẳng, không hoà (để 0 giây)")], ("Cột", "Tác dụng")) + """
<h2>Intro / Outro</h2>
<p>Thẻ Độ dài → <b>Intro / Outro cố định</b>: luôn ở đầu / cuối video, không bị xáo, có crossfade riêng. Ô
<i>Giữ nguyên tiếng gốc của Intro / Outro</i> bật sẵn (giữ nhạc hiệu của intro) — bỏ tick nếu muốn intro im lặng.</p>""")

topic("mau", "Làm video", "eye", "Màu & Logo", hero(
    "Màu & Logo", "Trang Video → thẻ Màu & Logo. Có khung xem trước một khung hình đã áp, cập nhật ngay khi chỉnh.",
    (("Mở trang Video", "app:video"),)) + cards([
    ("Ấm nắng chiều", "vàng cam ấm áp", ""), ("Lạnh xanh đêm", "xanh, dịu", ""), ("Vintage phim cũ", "ngả màu, hoài cổ", ""),
    ("Đen trắng", "", ""), ("Rực rỡ", "màu tươi hơn", ""), ("Teal &amp; Orange", "kiểu điện ảnh", "")]) + """
<ul>
<li><b>Cường độ</b> 0–100%: 50% = nửa hình gốc, nửa bộ lọc.</li>
<li><b>Logo / khung PNG</b>: chọn ảnh <code>.png</code> nền trong suốt; đặt ở 4 góc, chính giữa, hoặc <b>phủ cả khung hình</b>
(khung viền, banner); chỉnh kích thước và độ rõ.</li>
<li>Mặc định <b>không</b> áp lên Intro / Outro (thường đã có thương hiệu riêng) — tick ô cuối nếu muốn áp cả.</li>
<li>Không làm chậm việc xuất: mỗi clip vẫn chỉ mã hoá một lần.</li>
</ul>""")

topic("nhac", "Âm thanh", "music", "Trang Nhạc: playlist", hero(
    "Trang Nhạc", "Thêm bài nhạc — nhạc tự lặp cho đủ độ dài video, bài cuối nhỏ dần đúng lúc video kết thúc.",
    (("Mở trang Nhạc", "app:music"),)) + img("music") + legend([
    ("Playlist", "kéo thả bài hoặc cả thư mục nhạc. Bỏ tick bài không dùng. <b>Số lần/lượt</b> = bài đó phát mấy lần mỗi lượt playlist. Bấm đúp tên bài để nghe."),
    ("Âm lượng %", "to / nhỏ <b>riêng từng bài</b>: bấm đúp để sửa, hoặc bôi đen nhiều bài → chuột phải → <i>Đặt âm lượng bài đang chọn…</i>. "
                   "Cột <b>Độ to gốc</b> cho biết bài nào vốn to / nhỏ hơn."),
    ("Lịch phát dự kiến", "bài nào phát lúc mấy giờ — chính là YouTube Chapters."),
    ("Bảng trộn âm", "độ to của nhạc, tiếng gốc clip, từng lớp tiếng nền + <b>Nghe thử 20 giây</b> (xem chủ đề Bảng trộn âm).")]) + """
<h2>Cột phải còn có</h2>
<ul>
<li><b>Thứ tự phát</b>: theo bảng · ngẫu nhiên · <b>ngẫu nhiên không lặp bài liền nhau</b>.</li>
<li><b>Ghim bài</b> (chuột phải → Ghim): bài ghim luôn có trong file, kể cả khi file ngắn hơn cả playlist.</li>
<li><b>Nâng cao ▾</b>: crossfade giữa bài (mặc định 3 giây), <b>khoảng lặng giữa bài</b>, to dần đầu (2 giây) / nhỏ dần cuối (5 giây),
<b>chuẩn hoá độ to</b> mặc định -14 LUFS (chuẩn YouTube; đổi được từ -30 đến -5) để các bài to đều nhau.</li>
</ul>""" + box("tip", "Playlist dài hơn video thì chỉ phát những bài kịp phát. Video dài hơn playlist thì playlist tự lặp lại.") + box(
    "warn", "Ở kiểu <b>Chỉ video</b> (hoặc chọn <i>Chỉ tiếng gốc clip</i>), playlist bị làm mờ vì không dùng — tiếng nền vẫn dùng được."))

topic("tron", "Âm thanh", "sliders", "Bảng trộn âm & nghe thử", hero(
    "Bảng trộn âm & nghe thử", "Một chỗ chỉnh to / nhỏ cho mọi nguồn âm, dùng chung cả 3 kiểu. Nghe thử 20 giây trước khi xuất.",
    (("Mở Bảng trộn âm", "app:mixer"),)) + """<table width="100%" cellspacing="0" cellpadding="0"><tr>
<td width="46%" align="center">""" + img("mixer") + """</td><td>""" + legend([
    ("Tiếng gốc clip: 3 nút", "<b>Giữ tiếng gốc + nhạc</b> · <b>Chỉ tiếng gốc</b> · <b>Tắt tiếng gốc</b> — chọn ngay ở đây (trang "
                              "Video đổi theo). Dòng bên dưới ghi clip nào có tiếng."),
    ("Tự cân độ to tiếng gốc", "bật sẵn: app đo độ to từng clip rồi đưa về cùng mức với nhạc, nên clip to / nhỏ khác nhau "
                               "không còn chênh và <b>100% + 100% nghe ngang nhau</b>."),
    ("Chọn nhanh", "<b>Nhạc là chính</b> (100 / 35) · <b>Cân bằng</b> (100 / 100) · <b>Tiếng gốc là chính</b> (30 / 100). Dòng "
                   "xanh dưới thanh ghi tiếng gốc to / nhỏ hơn nhạc bao nhiêu."),
    ("Nhạc", "âm lượng cả playlist."), ("Tiếng gốc clip", "tiếng có sẵn trong clip (kể cả Intro / Outro nếu giữ tiếng)."),
    ("Từng lớp tiếng nền", "mưa, sóng, lửa… mỗi lớp một thanh."),
    ("Nghe từ", "<b>Đầu</b> · <b>Giữa</b> · <b>Chỗ đổi bài</b> (nghe crossfade giữa 2 bài đầu) · <b>Cuối</b> (nghe đoạn nhỏ dần), "
                "hoặc gõ mốc vào 3 ô <b>giờ · phút · giây</b>. File ngắn dưới 25 giây thì Giữa / Cuối bị mờ."),
    ("Nghe thử 20 giây", "trộn đúng như khi xuất rồi phát ngay trong app. <b>Đang nghe mà kéo thanh là nghe đổi ngay.</b>")]) + """</td></tr></table>
<h2>Kéo thanh bao nhiêu?</h2>""" + examples([
    ("100%", "giữ nguyên (mặc định). Bấm đúp tên thanh để về 100%"), ("50%", "nhỏ đi rõ rệt (khoảng một nửa độ to nghe được)"),
    ("150 – 200%", "to hơn — nhưng đẩy quá to sẽ bị bộ chống vỡ tiếng nén lại"), ("0%", "tắt hẳn nguồn đó")], ("Mức", "Nghe thế nào")) + box(
    "ex", "Muốn <b>tiếng mưa trong clip nổi hơn nhạc</b>: bấm <b>Tiếng gốc là chính</b>. Muốn nhạc rõ, tiếng clip làm nền: "
          "<b>Nhạc là chính</b>. Loop giữ tiếng: mỗi lần loop tiếng gốc lặp lại khớp hình; clip có tiếng đều (tiếng tút, nhạc "
          "trong clip) nên đặt <b>Nối loop 0.5 s</b> cho mượt.") + box(
    "tip", "Lần đầu bấm Nghe thử hơi lâu (app đo độ to các bài). Đổi playlist hoặc âm lượng từng bài khi đang nghe thì bấm Dừng rồi nghe lại."))

topic("nen", "Âm thanh", "waves", "Tiếng nền: mưa, sóng, lửa…", hero(
    "Tiếng nền", "Phát lặp xuyên suốt dưới nhạc / video. Dùng được ở cả 3 kiểu — kể cả Chỉ video.",
    (("Mở Thư viện tiếng nền có sẵn", "app:ambient_lib"),)) + """<table width="100%" cellspacing="0" cellpadding="0"><tr>
<td width="46%" align="center">""" + img("ambient") + """</td><td>""" + legend([
    ("Bảng lớp tiếng nền", "mỗi dòng một lớp, cột Âm lượng % (hoặc kéo thanh ở Bảng trộn âm). Bỏ tick để tắt lớp."),
    ("Thư viện có sẵn…", "app tự tạo, không cần file, không cần mạng, dùng thoải mái cho YouTube: mưa rào, mưa hiên nhà, sóng biển, gió, lửa củi, white / pink / brown noise. Có nút Nghe thử.")]) + """</td></tr></table>
<ul>
<li><b>Thêm file…</b>: dùng file của bạn (mp3, wav, hoặc cả video — app lấy phần tiếng).</li>
<li>Chỗ lặp được <b>hoà mượt</b> (đuôi file hoà dần vào đầu) nên không nghe khựng.</li>
<li>Phối nhiều lớp: ví dụ <b>mưa 70% + lửa 40%</b>.</li>
</ul>""")

topic("chinhac", "Âm thanh", "queue", "Chỉ nhạc, nhiều bản, ASMR", hero(
    "Chỉ nhạc", "Ghép playlist thành một file nhạc dài, hoặc nhiều file cùng bài nhưng khác thứ tự. Không cần clip.",
    (("Chuyển sang Chỉ nhạc", "app:mode_music"),)) + """<table width="100%" cellspacing="0" cellpadding="0"><tr>
<td width="46%" align="center">""" + img("music_only") + """</td><td>""" + legend([
    ("Tính theo", "<b>thời lượng</b> (30p, 1h, 3h, 10h…) hoặc <b>số lượt playlist</b>."),
    ("Dài bao lâu", "ví dụ 10 bài dài 30 phút → chọn 1h là ra file 1 giờ."),
    ("Số bản xuất", "ví dụ 4 → 4 file, mỗi file một thứ tự phát khác nhau, mở đầu bằng bài khác nhau (nút nhanh 1 · 2 · 4 · 6). "
                    "Nhiều bản thì nút xuất đổi thành <b>Xuất N bản nhạc</b> và các bản tự vào hàng đợi.")]) + """</td></tr></table>""" + steps([
    ("Chỉ nhạc", "Bấm Chỉ nhạc ở thanh trên cùng."), ("Thêm bài", "Kéo thả nhạc, chỉnh độ dài, số bản."),
    ("Xuất", "Chọn định dạng (MP3 320, MP3 192 nhẹ, M4A, FLAC, WAV) → Xuất.")]) + """
<ul>
<li>Mỗi file kèm <code>_tracklist.txt</code> (mốc từng bài). Nhiều bản: <code>…_ban-1.mp3 … _ban-4.mp3</code> chung một thư mục.</li>
<li>Ô <b>Xem bản</b> cạnh Lịch phát để xem trước thứ tự của từng bản.</li>
<li><b>Bài ghim</b> luôn có trong mọi bản; chọn đặt ở <i>Mở đầu file</i> hoặc <i>Vị trí ngẫu nhiên</i> (thẻ Thứ tự phát).</li>
</ul>""" + box("ex", "<b>File ngủ ngon 8 tiếng</b> (ASMR): Chỉ nhạc, <b>không thêm bài nào</b>, thêm tiếng nền mưa 70% + lửa 40% từ "
                     "Thư viện có sẵn, độ dài 8h → Xuất. Thẻ <b>Tiếng nền (ASMR)</b> ở màn hình Bắt đầu mở sẵn đúng chỗ."))

topic("xemtruoc", "Xuất file", "play", "Trình phát: xem trước video", hero(
    "Trình phát (xem trước)", "Luôn hiện bên phải bước Video / Nhạc / Xuất, như CapCut / Premiere: phát thử video thành "
    "phẩm — hình, nhạc, tiếng gốc, tiếng nền, crossfade, màu & logo y như bản xuất — không phải xuất file.",
    (("Đến Trình phát", "app:preview"),)) + steps([
    ("Bấm Phát", "Nút tròn dưới khung hình, bấm vào hình, hoặc phím Space ở bất kỳ đâu (trừ lúc đang gõ chữ)."),
    ("Tua", "Kéo vạch trắng trên dòng thời gian ở đáy màn hình — hình chạy theo ngay khi kéo."),
    ("Chỉnh và xem lại", "Sửa clip, nhạc, màu… là trình phát tự cập nhật, giữ nguyên chỗ đang xem.")]) + img("preview") + legend([
    ("Khung hình", "đúng như bản xuất. <b>Bấm vào hình</b> để phát / dừng, nhấp đúp để xem <b>toàn màn hình</b> "
                   "(Esc để thoát). Chỉ nhạc: chỉ có tiếng."),
    ("Phát / Dừng", "hoặc phím <span class='k'>Space</span> — dùng được ở mọi chỗ trong cửa sổ, trừ lúc đang gõ chữ vào "
                    "ô (tên, tìm kiếm, số lần phát…). Dừng rồi phát tiếp là chạy ngay."),
    ("Lùi / tới 10 giây", "nút vòng tròn số 10 (phím <span class='k'>←</span> <span class='k'>→</span>: 5 giây, "
                          "<span class='k'>Home</span>: về đầu). Bên trái là mã thời gian giờ:phút:giây:khung."),
    ("Thanh tua", "rê chuột để xem giờ tại chỗ đó, bấm hoặc kéo để tua. Vạch mờ trên thanh là chỗ đổi bài nhạc."),
    ("Vạch phát", "trên dòng thời gian ở đáy: <b>kéo tay nắm trên thước giờ</b> để tua (đang dừng thì hình chạy theo); "
                  "bấm vào làn CLIP / NHẠC để nhảy tới đó."),
    ("Chất lượng xem", "<b>Tự động</b> (theo cỡ khung xem) · 360p mượt (máy yếu) · 540p · 720p. Không ảnh hưởng bản xuất."),
    ("Toàn màn hình", "xem cả màn hình, thanh điều khiển tự ẩn khi không rê chuột. Nút loa bên cạnh: tắt tiếng trình "
                      "phát (không đổi âm lượng của dự án).")]) + """
<ul>
<li>Kéo <b>vạch chia</b> giữa trang đang làm và trình phát để khung xem to / nhỏ (app nhớ cho lần sau).</li>
<li>Kéo thanh âm lượng ở <a href='topic:tron'>Bảng trộn âm</a> khi đang phát là nghe đổi ngay, không phải dựng lại.</li>
<li>Sang Cài đặt / Hướng dẫn thì trình phát tự dừng. Xuất hàng loạt: chuột phải một dòng → <b>Xem trước video này</b>.</li>
</ul>""" + box(
    "tip", "Lần đầu bấm Phát với một dự án mới có thể chờ vài giây (app đo độ to các bài nhạc). Những lần sau, và "
           "khi tua, chỉ khoảng nửa giây.") + box(
    "tip", "Xem trước nhanh vì không phải nén thành file: app giải mã clip và vẽ thẳng lên màn hình. Clip nền lặp nhiều "
           "lần được nhớ sẵn nên tua qua lại rất nhẹ."))

topic("xuat", "Xuất file", "export", "Trang Xuất & dung lượng", hero(
    "Trang Xuất", "Chọn chất lượng, xem trước dung lượng file, chọn nơi lưu rồi xuất (hoặc thêm vào hàng đợi).",
    (("Mở trang Xuất", "app:export"),)) + img("export") + legend([
    ("Định dạng &amp; chất lượng", "độ phân giải (theo clip đầu tiên, 720p, 1080p, 2K, 4K, dọc 9:16 cho Shorts / TikTok, vuông 1:1), chất lượng hình, <b>Bitrate hình</b> (tự đặt số Mbps, mức YouTube, hoặc số GB tối đa — dòng gợi ý bên dưới ghi sẵn số Mbps hợp với độ phân giải). "
                                    "<i>Tuỳ chọn nâng cao ▾</i>: chuẩn nén H.264 / H.265, khung hình / giây, bộ mã hoá, âm thanh AAC 192 (nhanh) / 320."),
    ("Dự đoán dung lượng", "tự cập nhật khi đổi cấu hình — app mã hoá thử vài giây để tính, sai số thường dưới 10%."),
    ("Nơi lưu &amp; file kèm", "thư mục lưu, tên file (để trống = tên dự án + ngày giờ), mỗi video một thư mục riêng, file mốc thời gian, tracklist, bản sao dự án."),
    ("Bắt đầu xuất", "xuất ngay dự án đang mở. Đang xuất có nút <b>Huỷ xuất</b>; xong thì <b>Hiện file vừa xuất</b>. File cùng tên đã có thì app hỏi ghi đè."),
    ("Thêm vào hàng đợi", "xếp dự án này vào hàng đợi để xuất nhiều video liền nhau (xem chủ đề Hàng đợi)."),
    ("Hàng đợi", "danh sách việc chờ xuất; chuột phải mục lỗi → Chạy lại.")]) + """
<h2>Độ phân giải &amp; khung hình/giây: nên để bằng clip gốc</h2>""" + box(
    "tip", "Đổi độ phân giải / fps là <b>làm lại từng khung hình</b>, không chỉ đổi thông tin file. Ngay dưới ô "
           "<b>Độ phân giải</b> app ghi so với clip gốc (clip phát nhiều nhất); lệch thì bấm <b>Theo clip gốc</b>.") + legend([
    ("Lớn hơn clip gốc", "ví dụ clip 1080p xuất 2K: hình to ra nhưng <b>không nét thêm</b>, file nặng gấp ~1,8 lần. "
                         "(Mẹo YouTube: bản 2K được YouTube nén tốt hơn — chỉ chọn khi cố ý, nhớ hạ Bitrate hình.)"),
    ("Nhỏ hơn clip gốc", "ví dụ 4K xuất 1080p: file nhẹ hơn, vẫn nét."),
    ("fps cao hơn clip gốc", "24 → 60 fps chỉ lặp lại khung cũ, <b>không mượt hơn</b>, file nặng hơn. Để <b>Theo clip chính</b>."),
    ("fps thấp hơn clip gốc", "bỏ bớt khung: chuyển động kém mượt hơn chút."),
    ("Chất lượng thật", "do <b>Chất lượng hình ảnh</b> và <b>Bitrate hình</b> quyết định — mỗi đoạn luôn được nén lại một lần.")]) + """
<h2>Video loop nặng? Làm nhẹ theo thứ tự hiệu quả</h2>""" + steps([
    ("Hạ độ phân giải", "2K → 1080p nhẹ hơn khoảng 2 lần, YouTube vẫn nét."),
    ("Dùng H.265", "nhẹ hơn khoảng 20–40% (Tuỳ chọn nâng cao)."),
    ("Tiết kiệm dung lượng", "mức chất lượng nhẹ nhất, vẫn đẹp khi xem YouTube."),
    ("Hạ bitrate", "ô <b>Bitrate hình</b> → <b>Tự đặt bitrate</b> rồi gõ số Mbps (ví dụ 2K: 16 → 10 Mbps). Mỗi 1 Mbps ≈ 450 MB mỗi giờ video.")]) + box(
    "tip", "File MP4 không có cách ghi “lặp lại đoạn này 70 lần”: mỗi lần lặp vẫn chiếm dung lượng, nên dung lượng ≈ bitrate × "
           "độ dài. Xem con số <b>Dự đoán dung lượng</b> đổi ngay khi chỉnh.") + box(
    "warn", "Đừng mở file đang xuất bằng trình xem khác, đừng xoá clip / nhạc gốc khi đang xuất."))

topic("hangdoi", "Xuất file", "queue", "Hàng đợi (xuất qua đêm)", hero(
    "Hàng đợi", "Xếp nhiều dự án rồi để máy xuất lần lượt, ví dụ chạy qua đêm.", (("Mở trang Xuất", "app:export"),)) + steps([
    ("Làm xong 1 video", "trang Video xếp bảng (Thư viện mẫu… → Dùng mẫu này). Tên file tự gợi ý <b>Tập 33</b> khi file "
                         "đặt kiểu 33_…; muốn tên khác thì gõ ở trang Xuất."),
    ("Thêm vào hàng đợi", "app báo đã thêm gì, lưu ở đâu, rồi hỏi bước tiếp: <b>Làm video tiếp theo</b> (bảng trống, giữ "
                          "intro / outro, nhạc, cài đặt xuất) · <b>Chạy hàng đợi</b> · <b>Ở lại</b>."),
    ("Lặp lại cho video sau", "thêm file → áp mẫu → Thêm vào hàng đợi. Mỗi mục giữ đúng nội dung lúc thêm, sửa bảng sau đó "
                              "không ảnh hưởng."),
    ("Chạy hàng đợi", "xuất lần lượt từ trên xuống. Muốn thì vào Cài đặt tick Tắt máy khi xong.")]) + legend([
    ("Biết trong hàng đợi có gì", "mỗi dòng ghi <b>Tên file</b> và <b>Nội dung</b> (tập, tình huống, số dòng, độ dài). Bấm "
                                  "vào một mục: hiện vài dòng đầu của bảng, khung hình, intro / outro, nhạc, nơi lưu."),
    ("Sửa mục đã thêm", "chọn mục → <b>Sửa mục này</b> (hoặc nháy đúp): mục mở lại ở trang Video, nút Thêm đổi thành "
                        "<b>Cập nhật “Tập 33”</b> — bấm là lưu vào đúng mục đó, không tạo mục mới."),
    ("Lỡ thêm trùng", "thêm một video giống hệt mục đang chờ (cùng clip, số lần phát, intro / outro) thì app hỏi lại."),
    ("Thư mục lưu", "ô <b>Mỗi video một thư mục riêng</b> (trang Xuất, bật sẵn): <i>Thư mục lưu › Tập 33 › Tập 33.mp4</i> "
                    "kèm file mốc thời gian. Tắt: mọi file nằm chung một thư mục. Nút <b>Mở thư mục</b> ở chi tiết mục."),
    ("Đang Xuất ngay mà thêm mục", "được — xuất xong app hỏi <i>Chạy hàng đợi luôn?</i>.")]) + """
<ul>
<li>Máy <b>không tự ngủ</b> khi đang xuất (màn hình vẫn tắt bình thường).</li>
<li>Tên file trùng tự thêm <code>_2</code>, <code>_3</code>. Đóng app giữa chừng: mục đang dở quay về <b>Chờ</b> — mở lại app và bấm
<b>Chạy hàng đợi</b> để chạy tiếp.</li>
<li>Chuột phải mục <b>Lỗi / Đã huỷ</b> → <i>Chạy lại</i>. Nút ↑ ↓ để đổi thứ tự, <i>Xoá mục chọn</i>, <i>Dọn mục đã xong</i> để gọn danh sách.</li>
<li>Nút <b>Xuất hàng loạt…</b> cạnh hàng đợi: thêm cả loạt video một lúc (xem chủ đề <a href='topic:hangloat'>Xuất hàng loạt</a>).</li>
</ul>""")

topic("hangloat", "Xuất file", "folder", "Xuất hàng loạt theo thư mục", hero(
    "Xuất hàng loạt", "Làm nhiều video / file nhạc một lần: mỗi thư mục con là một file. Dùng được cho cả 3 kiểu, "
    "mọi cài đặt khác lấy theo dự án đang mở.",
    (("Mở Xuất hàng loạt", "app:batch"),)) + """
<h2>Chọn kiểu ở đầu hộp thoại (Xuất ra)</h2>""" + examples([
    ("Video có nhạc", "mỗi thư mục con → 1 video .mp4: clip trong thư mục + nhạc trong thư mục (không có thì dùng playlist của dự án)"),
    ("Chỉ video", "mỗi thư mục con → 1 video .mp4 không nhạc, giữ tiếng gốc clip (file nhạc trong thư mục bị bỏ qua)"),
    ("Chỉ nhạc", "mỗi thư mục con → 1 file nhạc: các bài trong thư mục là playlist, lặp cho đủ độ dài")],
    ("Kiểu", "Mỗi thư mục con thành")) + box(
    "tip", "Kiểu của dự án đang mở được chọn sẵn. Bấm kiểu khác là hộp thoại đổi ngay — thư mục cha, độ dài và âm lượng "
           "đã chọn được giữ nguyên. Khung phía trên luôn ghi rõ mỗi thư mục con cần có gì kèm sơ đồ mẫu.") + """
<h2>1. Chuẩn bị thư mục</h2>
<table cellpadding="10" cellspacing="0" bgcolor="@c:field@"><tr><td><pre style="font-family:Consolas;">
Video-can-lam\\                ← thư mục cha (chọn thư mục này)
├─ Video 01 - Mưa đêm\\         → video "Video 01 - Mưa đêm.mp4"
│    loop_mua.mp4    2_pho.mp4    3_cafe.mp4
├─ Video 02 - Rừng xanh\\
│    loop_rung.mp4   2_suoi.mp4
│    Nhac\\  bai1.mp3  bai2.mp3   ← nhạc riêng (nếu có)
└─ _chung\\                     ← bắt đầu bằng _ = bỏ qua
</pre></td></tr></table>
<p>Kiểu <b>Chỉ nhạc</b>: mỗi thư mục con chỉ cần các bài nhạc.</p>
<table cellpadding="10" cellspacing="0" bgcolor="@c:field@"><tr><td><pre style="font-family:Consolas;">
Nhac-can-lam\\                 ← thư mục cha
├─ Piano đêm\\                  → "Piano đêm.mp3"
│    bai1.mp3   bai2.mp3
└─ Lofi học bài\\               → "Lofi học bài.mp3"
     01.mp3   02.mp3   03.mp3
</pre></td></tr></table>
<h2>2. Mở dự án làm “khuôn”, rồi mở Xuất hàng loạt</h2>
<p>Khuôn = dự án đang mở: cấu hình xuất, thư mục lưu, Intro / Outro, tiếng nền, playlist chung… áp cho cả loạt.</p>""" + img("batch") + legend([
    ("Kiểu xuất", "Video có nhạc / Chỉ video / Chỉ nhạc — giống 3 nút ở thanh trên cùng; bấm là đổi cho cả loạt."),
    ("Thư mục cha", "chọn thư mục chứa các thư mục con (nút <i>Thư mục thử</i> để dùng thử)."),
    ("Chế độ độ dài / Tính theo", "giống hệt trang Video (<i>Thủ công · Thời lượng mục tiêu · Theo độ dài nhạc</i>) và "
                                  "Chỉ nhạc (<i>Theo thời lượng · Theo số lượt playlist</i>), rồi ô <b>Dài bao lâu</b>. Ví dụ "
                                  "Thời lượng mục tiêu 3 giờ → video nào cũng dài 3:00:00. Dòng chữ cạnh ô nói rõ kết quả."),
    ("Cách xếp clip", "giống 2 nút ở trang Video: <b>Xen kẽ clip nền</b> (một clip nền xen giữa các cảnh) hoặc "
                      "<b>Xếp lần lượt</b> (Loop1 → Loop2 … mỗi cái lặp N lần). Kiểu Chỉ nhạc không có ô này."),
    ("Âm lượng", "Nhạc / Tiếng gốc clip / từng lớp tiếng nền cho cả loạt (mặc định theo Bảng trộn âm của dự án)."),
    ("Danh sách", "mỗi dòng một video. Bỏ tick dòng nào thì video đó không được thêm. Chuột phải → "
                  "<b>Chỉnh âm lượng video này…</b> để một video to / nhỏ khác."),
    ("Chỉnh…", "đổi thứ tự clip riêng cho video đó (dòng hiện <i>Đã chỉnh tay</i>)."),
    ("Xem", "phát video đó trong trình phát bên phải (bấm vào dòng cũng được)."),
    ("Trình phát", "giống trình phát ở màn hình chính: hình + tiếng đúng như bản xuất, Space = Phát / Dừng, kéo thanh "
                   "Âm lượng là nghe đổi ngay."),
    ("Thêm vào hàng đợi", "đưa cả loạt vào hàng đợi (tick <i>Chạy hàng đợi ngay</i> để chạy luôn).")]) + box(
    "warn", "Chọn <b>thư mục lưu</b> ở trang Xuất trước khi mở Xuất hàng loạt — cả loạt xuất vào đó.") + """
<ul>
<li><b>Cách xếp clip</b> có thêm lựa chọn <i>Không xếp — phát theo thứ tự tên file</i>. <b>Không hoà hình</b> đặt cả hai ô nối về Cắt.</li>
<li><b>Nhạc</b>: nhạc trong từng thư mục (thiếu thì dùng playlist dự án) · luôn dùng playlist dự án · chỉ nhạc trong thư mục.</li>
<li>Chuột phải một dòng: <i>Chỉnh âm lượng video này…</i>, <i>Bỏ chỉnh tay</i>, <i>Bỏ âm lượng riêng</i>. Bỏ tick dòng nào thì video đó không được thêm.</li>
<li>Nút <b>Theo dự án</b> ở hàng Âm lượng: đặt lại âm lượng như Bảng trộn âm của dự án đang mở.</li>
</ul>""" + box(
    "tip", "Thư mục lưu nằm trong thư mục cha thì app tự lưu vào <code>_Xuat</code> để lần quét sau không lẫn với clip."))

topic("filekem", "Xuất file", "file_plus", "File kèm: tracklist, mốc cho editor", hero(
    "File kèm theo video", "Bật ở trang Xuất → Nơi lưu & File xuất kèm. Mặc định mỗi video một thư mục riêng chứa tất cả.") + examples([
    ("Tên-video.mp4", "video"),
    ("_tracklist.txt", "mốc thời gian từng bài nhạc — <b>dán vào mô tả YouTube</b> là có Chapters"),
    ("_moc-thoi-gian.txt / .csv", "từng đoạn <b>LOOP</b> (nền lặp) và <b>THƯỜNG</b> (cảnh chèn — chỗ nên thêm sound effect), chính xác từng khung hình; .csv mở bằng Excel"),
    ("_moc-thoi-gian.srt", "kéo vào Premiere / CapCut / DaVinci thành track chữ hiện tên từng đoạn trên timeline"),
    ("_markers-davinci.edl", "DaVinci Resolve: Timeline → Import → Timeline Markers from EDL (timeline bắt đầu 01:00:00:00). THƯỜNG đỏ, LOOP xanh dương, INTRO / OUTRO xanh lá"),
    ("_project.lsproj", "mở lại để xuất lại y hệt (chỉ kèm theo video, file nhạc không có)")], ("File", "Dùng để")))

topic("caidat", "Khác", "settings", "Cài đặt & card đồ hoạ", hero(
    "Cài đặt & card đồ hoạ", "Kiểm tra máy có dùng được card đồ hoạ để xuất nhanh không, và các tuỳ chọn hệ thống.",
    (("Mở Cài đặt", "app:settings"),)) + img("settings") + legend([
    ("Thông số máy", "hệ điều hành, CPU, RAM, card đồ hoạ (driver, VRAM, nhiệt độ), CUDA, ổ đĩa."),
    ("FFmpeg &amp; tăng tốc", "✓ xanh = dùng được: NVIDIA <b>NVENC</b>, Intel <b>Quick Sync</b>, AMD <b>AMF</b>, giải mã <b>CUDA</b>. Chỉ cần <b>một</b> dòng xanh là xuất nhanh.")]) + """
<ul>
<li><b>Kiểm tra lại phần cứng</b>: đọc lại thông số sau khi cắm / cập nhật driver card đồ hoạ.</li>
<li><b>Đo tốc độ mã hoá</b> (khoảng 30 giây): mã hoá thử bằng từng bộ mã hoá (×10 = nhanh gấp 10 lần thời gian thực).</li>
<li>Thư mục xuất mặc định, <b>mở thư mục</b> / <b>âm báo</b> khi xuất xong, cỡ chữ.</li>
<li><b>Màu chủ đạo</b> (Giao diện hiển thị): <i>Tím neon</i> (mặc định), <i>Đại dương</i>, <i>Hoàng hôn</i>,
<i>Tím xanh</i> (như bản cũ) — đổi là thấy ngay. Vài biểu tượng nhỏ đổi màu hẳn sau khi mở lại app.
<b>Xem lại màn hình chào</b> cũng ở đây.</li>
<li><b>Tắt máy khi chạy xong hàng đợi</b> (có 2 phút để huỷ) — chỉ có tác dụng tới khi tắt app, lần mở sau phải tick lại.</li>
<li><b>Đường dẫn FFmpeg</b>: để <i>Tự động</i> (dùng bản kèm theo app); chỉ đổi khi được hướng dẫn.</li>
<li><b>Xoá bộ nhớ đệm</b>, <b>Mở thư mục dữ liệu</b> (dự án tự lưu, hàng đợi, nhật ký, file lỗi).</li>
</ul>""" + box("tip", "Tốc độ xuất chủ yếu đến từ bộ mã hoá trên card (NVENC / Quick Sync / AMF) — app luôn tự dùng. "
                     "“Giải mã bằng GPU (CUDA)” thường <b>không</b> nhanh hơn với clip ngắn, chỉ nên bật khi CPU yếu.") + box(
    "tip", "Bộ nhớ đệm giúp lần xuất sau nhanh hơn; app tự dọn khi quá 30 GB. Xoá tay ở đây nếu ổ C sắp đầy."))

topic("dulieu", "Khác", "folder", "Cài app, cập nhật & dữ liệu", hero(
    "Cài app, cập nhật & dữ liệu", "Cài lên máy mới, lên bản mới, và biết app lưu dữ liệu ở đâu.") + steps([
    ("Tải bộ cài", "File <code>KTLoopStation-Setup.exe</code> (~190 MB) từ trang tải của app."),
    ("Mở file", "Hiện khung xanh <i>Windows protected your PC</i>: bấm <b>More info</b> → <b>Run anyway</b>."),
    ("Next → Install → Finish", "Mở app bằng biểu tượng <b>KT Loop Station</b> trên màn hình nền hoặc menu Start.")]) + """
<ul>
<li>Cần <b>Windows 10 / 11 64-bit</b>. Không cần quyền quản trị, không cần cài thêm gì (đã kèm FFmpeg).</li>
<li><b>Lên bản mới ngay trong app</b>: có bản mới thì thanh bên hiện nút <b>Có bản mới</b> → <b>Tải &amp; cài đặt</b> (app tự đóng, cài đè rồi tự mở lại). Kiểm tra tay: <b>Cài đặt → Giới thiệu → Kiểm tra cập nhật</b>. Dự án, hàng đợi, cài đặt được giữ nguyên.</li>
<li><b>Gỡ app</b>: Windows Settings → Apps → KT Loop Station → Uninstall. Dữ liệu và video đã xuất <b>không</b> bị xoá.</li>
</ul>
<h2>App lưu gì, ở đâu?</h2>""" + examples([
    ("autosave.lsproj", "dự án đang làm (tự lưu liên tục)"), ("queue.json", "hàng đợi xuất"),
    ("logs\\", "nhật ký từng lần xuất (nút <i>Thư mục nhật ký</i> ở đầu trang này)"),
    ("loi-ung-dung.log", "lỗi bất ngờ của app — gửi file này khi cần hỗ trợ"),
    ("cache\\", "bộ nhớ đệm giúp xuất lần sau nhanh hơn; tự dọn khi quá 30 GB")], ("File / thư mục", "Là gì")) + box(
    "tip", "Tất cả nằm trong <code>%LOCALAPPDATA%\\KTLoopStation</code> — mở nhanh bằng Cài đặt → <b>Mở thư mục dữ liệu</b>.") + box(
    "warn", "Đừng xoá <code>autosave.lsproj</code> / <code>queue.json</code> khi app đang mở. Muốn giữ dự án lâu dài thì bấm <b>Lưu</b> "
            "(Ctrl+S) thành file <code>.lsproj</code> ở thư mục của bạn."))

topic("hoi", "Khác", "help", "Câu hỏi thường gặp", hero(
    "Câu hỏi thường gặp", "Bấm Ctrl+F (hoặc ô tìm bên trái) để tìm nhanh theo từ khoá — gõ không dấu cũng được.") + "".join(
    f'<h3>{q}</h3><p>{a}</p>' for q, a in [
        ("Nhạc có tự lặp theo video không?", "Có (kiểu Video có nhạc). Nhạc nối tiếp và lặp tới hết video, bài cuối nhỏ dần đúng lúc video kết thúc."),
        ("Chỉ muốn loop video, hoặc chỉ loop nhạc?", "Chọn <b>Chỉ video</b> hoặc <b>Chỉ nhạc</b> ở thanh trên cùng (xem chủ đề Chọn kiểu sản phẩm)."),
        ("Vì sao xuất nhanh vậy?", "Mỗi clip chỉ mã hoá <b>một lần</b>, các lần loop chỉ là sao chép. Video 1 giờ thường khoảng nửa phút, 10 giờ khoảng 10 phút (tuỳ máy). Lần sau còn nhanh hơn nhờ bộ nhớ đệm."),
        ("Video loop nặng quá?", "Xem chủ đề <a href='topic:xuat'>Trang Xuất &amp; dung lượng</a>: hạ độ phân giải, H.265, Tiết kiệm dung lượng, hạ Bitrate hình."),
        ("Video có màn hình “KT Loop Station” ở đầu?", "Đó là <b>Intro / Outro mẫu</b> của bộ tập dùng (thường do làm tiếp từ "
                                                       "dự án mẫu). Ô Intro / Outro ghi <b>· MẪU</b> và app hỏi trước khi xuất — "
                                                       "bấm thùng rác cạnh ô để bỏ, hoặc Chọn… để thay bằng intro của kênh."),
        ("Ghép xong màu bị lệch, xỉn, tối hơn?", "Thường do clip <b>HDR</b> (điện thoại quay HDR — iPhone bật mặc định — hoặc HDR10). "
                                               "Từ bản 1.8.1 app tự nhận clip HDR (cột thông tin ghi <b>HDR</b>) và chuyển sang màu thường khi xem "
                                               "trước và khi xuất. Clip thường (kể cả clip AI không ghi hệ màu) không bị đổi màu khi ghép. "
                                               "Hai clip vốn khác tông thì dùng thẻ <b>Màu &amp; Logo</b> cho đều."),
        ("Ổ đĩa có đủ chỗ không?", "Trang Xuất hiện dung lượng dự đoán và báo đỏ nếu không đủ; trước khi ghép app kiểm tra lại. Video 10 tiếng 1080p thường cần 10–40 GB."),
        ("Mở app hiện “đang mở rồi”?", "App chỉ cho mở một cửa sổ để hàng đợi không bị ghi đè — xem trên thanh tác vụ. Không thấy cửa sổ nào: "
                                       "mở <b>Task Manager</b> (Ctrl+Shift+Esc), tắt <b>KT Loop Station</b> rồi mở lại."),
        ("App đứng ở màn hình khởi động, không mở lên?", "Thường do dự án tự lưu có thời lượng quá lớn (ví dụ lỡ gõ 1.000.000 phút ở bản 1.4.8). "
                                                       "Từ bản 1.4.10 app tự đưa về tối đa 48 giờ và báo khi mở. Cài bản mới nhất rồi mở lại."),
        ("Video dài tối đa bao nhiêu?", "48 giờ cho mỗi video / file nhạc, mỗi clip phát tối đa 99.999 lần. YouTube nhận video tối đa 12 giờ."),
        ("Cài đặt báo CUDA ✗?", "CUDA chỉ dùng để <b>giải mã</b> trên card NVIDIA, không bắt buộc. Chỉ cần một dòng <b>NVENC / Quick Sync / AMF</b> "
                                "xanh là xuất nhanh; không có dòng nào xanh thì app dùng CPU (chậm hơn nhưng vẫn xuất được)."),
        ("Báo lỗi khi xuất?", "Xem <b>Nhật ký</b> ở trang Xuất (đầy đủ trong <i>Thư mục nhật ký</i> ở đầu trang này). Card đồ hoạ lỗi thì app tự "
                              "chuyển sang CPU; vẫn lỗi thì trang Xuất → Tuỳ chọn nâng cao ▾ → Bộ mã hoá: CPU rồi xuất lại. Lỗi bất ngờ của app "
                              "được ghi vào <code>loi-ung-dung.log</code> (Cài đặt → <i>Mở thư mục dữ liệu</i>) — gửi file này cho người hỗ trợ."),
        ("Cập nhật bản mới thế nào?", "App tự kiểm tra khi mở; có bản mới thì thanh bên hiện nút <b>Có bản mới</b> → <b>Tải &amp; cài đặt</b>: app tải bộ cài, kiểm tra mã SHA-256, tự đóng để cài đè rồi tự mở lại. Kiểm tra tay ở <b>Cài đặt → Giới thiệu → Kiểm tra cập nhật</b>. Dự án, hàng đợi, cài đặt được giữ nguyên."),
        ("File đích đang mở trong VLC?", "App không xoá video vừa xuất: lưu thành tên <code>…_moi.mp4</code> và ghi rõ trong nhật ký."),
    ]))

topic("phim", "Khác", "zap", "Phím tắt", hero("Phím tắt", "Thao tác nhanh bằng bàn phím.") + examples([
    ("F1", "Mở trang Hướng dẫn"), ("Ctrl+N / Ctrl+O", "Dự án mới / Mở dự án"), ("Ctrl+S / Ctrl+Shift+S", "Lưu / Lưu thành…"),
    ("Ctrl+F", "Tìm tên file trong bảng (trang Video / Nhạc) · tìm trong trang Hướng dẫn"),
    ("Esc", "Xoá ô tìm · đóng màn hình chào (Enter cũng được)"),
    ("Ctrl+Z", "Hoàn tác (trang Video)"), ("Ctrl+D", "Nhân bản dòng đang chọn (bảng clip và playlist nhạc)"),
    ("Ctrl+C / Ctrl+V", "Chép các dòng đang chọn / dán ngay bên dưới dòng đang chọn (bảng clip và playlist nhạc)"),
    ("Space", "Phát / dừng trình phát (mọi chỗ, trừ khi đang gõ chữ) · trong hộp thoại Đoạn lấy: phát / dừng đoạn cắt"),
    ("Ctrl+Space", "Bật / tắt các dòng đang chọn (bảng clip, playlist)"), ("Delete", "Xoá các dòng đang chọn"),
    ("Ctrl+A", "Chọn tất cả dòng"), ("I / O", "Đặt điểm đầu / cuối (hộp thoại Đoạn lấy)"), ("Bấm đúp", "Tên file: xem / nghe · Ô số: sửa"),
    ("← → · Home", "Trình phát (bấm vào khung hình trước): tua 5 giây · về đầu"),
    ("Tab · ↑ ↓", "Sang ô giờ / phút / giây kế tiếp · tăng / giảm 1"),
    ("Lăn chuột", "Chỉ cuộn trang; muốn đổi ô số bằng lăn chuột thì bấm vào ô trước")], ("Phím", "Tác dụng")))

GROUPS = ["Bắt đầu", "Làm video", "Âm thanh", "Xuất file", "Khác"]
HUB = "__hub"  # mục "Tổng quan" đầu mục lục


def _plain(html: str) -> str:
    return re.sub(r"<[^>]+>|&\w+;", " ", html)


# nội dung cũ (một trang dài) — giữ lại cho chỗ khác còn tham chiếu
GUIDE = "".join(h for _i, _g, _c, _t, h in TOPICS)


class _CachedBrowser(QTextBrowser):
    """QTextBrowser giữ ảnh đã nạp: dựng lại trang (đổi cỡ khung / cỡ chữ) không phải giải mã lại file PNG."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._res: dict[str, object] = {}

    def loadResource(self, rtype, url):  # noqa: N802
        if int(getattr(rtype, "value", rtype)) != 2:  # chỉ ảnh
            return super().loadResource(rtype, url)
        key = url.toString()
        if key not in self._res:
            m = re.match(r"helpimg/([\w-]+)@(\d+)x([\d.]+)\.png$", key)
            if m:  # ảnh minh hoạ thu sẵn đúng cỡ hiển thị (xem HelpPage._img_tag)
                src = QImage(str(HELP_DIR / "help" / f"{m.group(1)}.png"))
                wpx, dpr = int(m.group(2)), float(m.group(3))
                if not src.isNull():
                    hpx = max(1, round(src.height() * wpx / src.width()))
                    if wpx != src.width() or dpr != 1.0:
                        src = src.scaled(round(wpx * dpr), round(hpx * dpr), Qt.AspectRatioMode.IgnoreAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
                    src.setDevicePixelRatio(dpr)
                self._res[key] = src
            else:
                self._res[key] = super().loadResource(rtype, url)
        return self._res[key]


class HelpPage(QWidget):
    _stale = False
    openProjectRequested = Signal(str)
    actionRequested = Signal(str)  # "video" | "music" | "export" | "mixer" | "batch" | … → cửa sổ chính chuyển tới

    def __init__(self, parent=None):
        super().__init__(parent)
        sample_dir = Path(ft.app_dir()) / "Mau-Test"
        self._samples = sorted(sample_dir.glob("*.lsproj")) if sample_dir.is_dir() else []
        tools = []
        for proj in self._samples:
            b = QPushButton(sample_label(proj.stem))
            b.setObjectName("pill")
            b.setIcon(icons.icon("folder", 13))
            b.setToolTip(f"Mở dự án mẫu {proj.name} để thử")
            b.clicked.connect(lambda _=False, p=str(proj): self.openProjectRequested.emit(p))
            tools.append(b)
        self._sample_guide = sample_dir / "HUONG-DAN-TEST.md"
        if sample_dir.is_dir():
            g = QPushButton("Hướng dẫn test bộ mẫu")
            g.setObjectName("pill")
            g.setIcon(icons.icon("help", 13))
            g.setToolTip("Đọc hướng dẫn thử bộ mẫu ngay trong app")
            g.clicked.connect(self._show_sample_guide)
            tools.append(g)
        logs = QPushButton("Thư mục nhật ký")
        logs.setIcon(icons.icon("terminal", 13))
        logs.setObjectName("pill")
        logs.setToolTip("Nhật ký mỗi lần xuất, bộ nhớ đệm, tự lưu")
        logs.clicked.connect(self._open_data)
        tools.append(logs)

        # ----- mục lục chủ đề -----
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm trong hướng dẫn… (gõ không dấu cũng được)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        from PySide6.QtGui import QKeySequence, QShortcut
        find = QShortcut(QKeySequence.StandardKey.Find, self)
        find.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        find.activated.connect(lambda: (self.search.setFocus(), self.search.selectAll()))
        self.toc = QListWidget()
        self.toc.setObjectName("helpToc")
        self.toc.setIconSize(QSize(16, 16))
        self.toc.setSpacing(1)
        self.toc.setWordWrap(True)
        self.toc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._items: dict[str, QListWidgetItem] = {}
        self._group_items: dict[str, QListWidgetItem] = {}
        hub_item = QListWidgetItem(icons.icon("home", 16, "accent_text"), "Tổng quan")
        hub_item.setData(Qt.ItemDataRole.UserRole, HUB)
        hf = hub_item.font()
        hf.setBold(True)
        hub_item.setFont(hf)
        self.toc.addItem(hub_item)
        self._items[HUB] = hub_item
        for g in GROUPS:
            gi = QListWidgetItem(g.upper())
            gi.setFlags(Qt.ItemFlag.NoItemFlags)
            gi.setForeground(Qt.GlobalColor.gray)
            f = gi.font()
            f.setBold(True)
            f.setPointSizeF(f.pointSizeF() * 0.85)
            gi.setFont(f)
            self.toc.addItem(gi)
            self._group_items[g] = gi
            for tid, grp, ic, title, _h in TOPICS:
                if grp != g:
                    continue
                it = QListWidgetItem(icons.icon(ic, 16), title)
                it.setData(Qt.ItemDataRole.UserRole, tid)
                self.toc.addItem(it)
                self._items[tid] = it
        self.toc.currentItemChanged.connect(self._on_toc)
        self.no_hit = QLabel("Không thấy chủ đề nào khớp.")
        self.no_hit.setObjectName("muted")
        self.no_hit.hide()
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        lv.addWidget(self.search)
        lv.addWidget(self.toc, 1)
        lv.addWidget(self.no_hit)
        left.setMinimumWidth(240)
        left.setMaximumWidth(330)

        self.view = _CachedBrowser()
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._on_link)
        self.view.setSearchPaths([str(HELP_DIR)])
        self.view.document().setDefaultStyleSheet(css())
        self.back_btn = QPushButton("← Quay lại Hướng dẫn sử dụng")
        self.back_btn.setObjectName("ghost")
        self.back_btn.clicked.connect(self._show_guide)
        self.back_btn.hide()
        from PySide6.QtWidgets import QStackedWidget
        from .help_hub import HubPage, TopicHeader, TopicNav
        self.head = TopicHeader()
        self.head.homeRequested.connect(self.show_hub)
        self.head.linkRequested.connect(lambda h: self._on_link(QUrl(h)))
        self.nav = TopicNav()
        self.nav.topicRequested.connect(self.show_topic)
        reader = QFrame()
        reader.setObjectName("helpReader")
        rv = QVBoxLayout(reader)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        rv.addWidget(self.back_btn, 0, Qt.AlignmentFlag.AlignLeft)
        rv.addWidget(self.head)
        rv.addWidget(self.view, 1)
        nav_box = QWidget()
        nl = QVBoxLayout(nav_box)
        nl.setContentsMargins(theme.SP["lg"], theme.SP["sm"], theme.SP["lg"], theme.SP["md"])
        nl.addWidget(self.nav)
        rv.addWidget(nav_box)
        self.hub = HubPage(TOPICS, META, GROUPS, HELP_DIR, APP_VERSION, self._samples, tools)
        self.hub.topicRequested.connect(self.show_topic)
        self.hub.linkRequested.connect(lambda h: self._on_link(QUrl(h)))
        self.pages = QStackedWidget()
        self.pages.addWidget(self.hub)
        self.pages.addWidget(reader)
        right = self.pages

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([270, 1000])

        lay = QVBoxLayout(self)
        theme.page_layout(lay)
        lay.setSpacing(theme.SP['lg'])
        lay.addWidget(split, 1)

        self._img_sizes: dict[str, QSize] = {}
        self._current = HUB
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(lambda: self._render(keep_pos=True))
        self._last_w = 0
        self._stale = False
        self.toc.setCurrentItem(self._items[self._current])

    # ---------- hiển thị ----------
    def show_topic(self, tid: str) -> None:
        if tid in self._items:
            self.toc.setCurrentItem(self._items[tid])

    def show_hub(self) -> None:
        self.show_topic(HUB)

    def _on_toc(self, cur, _prev) -> None:
        tid = cur.data(Qt.ItemDataRole.UserRole) if cur is not None else None
        if tid:
            self._current = tid
            self.back_btn.hide()
            if tid == HUB:
                self.pages.setCurrentIndex(0)
                self.hub.verticalScrollBar().setValue(0)
                return
            self.pages.setCurrentIndex(1)
            self._render()

    def _img_tag(self, m: re.Match) -> str:
        """Ảnh minh hoạ thu sẵn về ĐÚNG cỡ hiển thị (tính cả màn hình phóng to 125 / 150 %) rồi đưa thẳng vào tài
        liệu, ghi rõ rộng × cao. Trước đây để khung đọc tự co ảnh theo width: khi lăn chuột, Qt vẽ lại từng mảnh
        và hay vẽ thiếu — ảnh chỉ còn một mẩu, phần còn lại trống."""
        name = m.group(1)
        if name not in self._img_sizes:
            self._img_sizes[name] = QImageReader(str(HELP_DIR / "help" / f"{name}.png")).size()
        size = self._img_sizes[name]
        avail = max(320, self.view.viewport().width() - 48)
        if not size.isValid():
            return f'<a href="zoom:{name}"><img src="help/{name}.png" width="{avail}"></a>'
        wpx = min(size.width(), avail)
        hpx = max(1, round(size.height() * wpx / size.width()))
        dpr = max(1.0, self.view.devicePixelRatioF())
        url = f"helpimg/{name}@{wpx}x{dpr:g}.png"  # _CachedBrowser.loadResource tạo ảnh đúng cỡ này
        return f'<a href="zoom:{name}"><img src="{url}" width="{wpx}" height="{hpx}"></a>'

    def _render(self, keep_pos: bool = False) -> None:
        if self.back_btn.isVisible() or self._current == HUB:
            return
        tid, group, ic, title, html = next(t for t in TOPICS if t[0] == self._current)
        meta = META.get(tid, {})
        self.head.set_topic(group, ic, meta.get("title", title), meta.get("when", ""), meta.get("actions", ()))
        self.head.show()
        self.nav.show()
        k = [t[0] for t in TOPICS].index(tid)
        self.nav.set_neighbours((TOPICS[k - 1][0], TOPICS[k - 1][3]) if k > 0 else None,
                                (TOPICS[k + 1][0], TOPICS[k + 1][3]) if k < len(TOPICS) - 1 else None)
        html = re.sub(r"@IMG:([\w-]+)@", self._img_tag, html)
        pos = self.view.verticalScrollBar().value()
        self.view.document().setDefaultStyleSheet(css())
        self.view.setHtml(html)
        self.view.verticalScrollBar().setValue(pos if keep_pos else 0)
        self._last_w = self.view.viewport().width()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if abs(self.view.viewport().width() - self._last_w) > 24:
            if self.isVisible():
                self._resize_timer.start()  # ảnh co giãn theo khung đọc
            else:
                self._stale = True  # trang đang ẩn: dựng lại khi hiện, không tốn công lúc kéo cửa sổ

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        if self._stale:
            self._stale = False
            self._resize_timer.start()

    def _on_link(self, url: QUrl) -> None:
        s = url.toString()
        if s.startswith("topic:"):
            self.show_topic(s[6:])
        elif s.startswith("zoom:"):
            self._zoom(s[5:])
        elif s.startswith("app:"):
            act = s[4:]
            if act == "sample" and self._samples:
                first = next((p for p in self._samples if "loop" in p.stem.lower()), self._samples[0])
                self.openProjectRequested.emit(str(first))
            else:
                self.actionRequested.emit(act)
        elif s.startswith("#"):
            self.view.scrollToAnchor(s[1:])
        else:
            from . import widgets as w
            w.open_with_default_app(s)

    def _zoom(self, name: str) -> None:
        """Xem ảnh minh hoạ cỡ thật (cuộn được) trong một cửa sổ nhỏ."""
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QDialog, QScrollArea
        dlg = QDialog(self)
        dlg.setWindowTitle("Ảnh minh hoạ — bấm Esc để đóng")
        pix = QPixmap(str(HELP_DIR / "help" / f"{name}.png"))
        lab = QLabel()
        lab.setPixmap(pix)
        area = QScrollArea()
        area.setWidget(lab)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(area)
        scr = self.screen().availableGeometry() if self.screen() else None
        dlg.resize(min(pix.width() + 24, scr.width() - 80 if scr else 1400),
                   min(pix.height() + 24, scr.height() - 80 if scr else 900))
        dlg.exec()

    def _filter(self, text: str) -> None:
        from .widgets import fold
        words = fold(text).split()
        shown_groups: set[str] = set()
        first = None
        for tid, grp, _ic, title, html in TOPICS:
            meta = META.get(tid, {})
            hay = fold(title + " " + meta.get("when", "") + " " + _plain(html))
            ok = all(wd in hay for wd in words)
            self._items[tid].setHidden(not ok)
            if ok:
                shown_groups.add(grp)
                first = first or tid
        for g, gi in self._group_items.items():
            gi.setHidden(g not in shown_groups)
        self.no_hit.setVisible(first is None)
        cur = self.toc.currentItem()
        on_hub = cur is not None and cur.data(Qt.ItemDataRole.UserRole) == HUB
        self._items[HUB].setHidden(bool(words))
        if first and (cur is None or cur.isHidden() or (on_hub and words)):
            self.show_topic(first)

    def _show_sample_guide(self) -> None:
        """Hiện file hướng dẫn test (Markdown) ngay trong khung đọc, không phải mở bằng chương trình khác."""
        try:
            text = self._sample_guide.read_text(encoding="utf-8")
        except OSError:
            text = "Không tìm thấy file hướng dẫn test trong thư mục Mau-Test."
        self.view.document().setDefaultStyleSheet(css())
        self.view.setMarkdown(text)
        self.pages.setCurrentIndex(1)
        self.head.hide()
        self.nav.hide()
        self.back_btn.show()
        self.view.verticalScrollBar().setValue(0)

    def _show_guide(self) -> None:
        self.back_btn.hide()
        if self._current == HUB:
            self.pages.setCurrentIndex(0)
        self._render()

    def refresh_font(self) -> None:
        """Đổi cỡ chữ: dựng lại trang đang xem theo cỡ mới (giữ đúng vị trí đang đọc)."""
        if self.back_btn.isVisible():
            pos = self.view.verticalScrollBar().value()
            self._show_sample_guide()
            self.view.verticalScrollBar().setValue(pos)
        else:
            self._render(keep_pos=True)

    def _open_data(self) -> None:
        d = ft.data_dir() / "logs"
        d.mkdir(exist_ok=True)
        os.startfile(str(d))  # type: ignore[attr-defined]

    def adapt(self, width: int, height: int = 0) -> None:
        pass
