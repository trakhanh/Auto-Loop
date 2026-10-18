"""Trang Hướng dẫn sử dụng (thanh bên → Hướng dẫn, hoặc phím F1)."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from ..core import ffmpeg_tools as ft
from . import branding, icons
from .theme import APP_NAME, APP_VERSION, AUTHOR, C

CSS_TEMPLATE = f"""
body {{ color: {C['text']}; font-family: 'Segoe UI'; font-size: @BODY@pt; }}
h1 {{ font-size: @H1@pt; color: white; margin: 8px 0 4px 0; }}
h2 {{ font-size: @H2@pt; color: white; margin: 22px 0 6px 0; }}
h3 {{ font-size: @H3@pt; color: #c4b5fd; margin: 14px 0 4px 0; }}
p, li {{ line-height: 150%; }}
a {{ color: #93c5fd; text-decoration: none; }}
code {{ background: #1f2330; color: #fcd34d; font-family: Consolas; }}
.tip {{ background: #13233f; border: 1px solid #2c4a7a; padding: 8px; }}
.warn {{ background: #3a2a0f; border: 1px solid #7a5a1c; padding: 8px; }}
td {{ padding: 4px 10px 4px 0; vertical-align: top; }}
.k {{ color: #fcd34d; font-family: Consolas; white-space: nowrap; }}
.muted {{ color: {C['muted']}; }}
"""


def css() -> str:
    """CSS trang hướng dẫn theo cỡ chữ đang chọn."""
    from . import theme
    k = theme.scale()
    out = CSS_TEMPLATE
    for tok, pt in (("@BODY@", 10.5), ("@H1@", 17), ("@H2@", 13.5), ("@H3@", 11)):
        out = out.replace(tok, f"{pt * k:.1f}")
    return out


CSS = css()

GUIDE = """
<a name="top"></a>
<h1>Hướng dẫn sử dụng</h1>
<p class="muted">Bấm vào mục để nhảy tới:
<a href="#kieu">1. Chọn kiểu sản phẩm</a> ·
<a href="#luong">2. Làm theo từng bước</a> ·
<a href="#lienket">3. Các trang liên kết thế nào</a> ·
<a href="#video">Trang Video</a> ·
<a href="#nhac">Trang Nhạc</a> ·
<a href="#xuat">Trang Xuất</a> ·
<a href="#caidat">Cài đặt</a> ·
<a href="#hoi">Câu hỏi thường gặp</a> ·
<a href="#phim">Phím tắt</a></p>

<a name="kieu"></a>
<h2>1. Bước đầu tiên: chọn kiểu sản phẩm</h2>
<p>Cách dễ nhất: mở <b>Bắt đầu</b> (trên cùng thanh bên trái — dự án mới cũng tự mở trang này) và bấm một thẻ:
<b>Video loop có nhạc</b>, <b>Chỉ video</b>, <b>Chỉ nhạc</b>, <b>Âm thanh nền (ASMR)</b>, <b>Hàng loạt từ thư mục</b>
hoặc <b>Mở dự án</b>. App tự chuyển đúng kiểu và mở đúng bước. Ngay dưới thanh trên cùng luôn có
<b>thanh hướng dẫn</b>: đang ở bước mấy (bấm vào số bước để chuyển) và <b>việc cần làm tiếp theo</b>.</p>
<p>Đổi kiểu bất cứ lúc nào bằng 3 nút trên thanh trên cùng (cạnh tên dự án); các trang tự đổi theo
(phần không dùng bị làm mờ, nút Xuất đổi đúng loại file).</p>
<table>
<tr><td><b>Video có nhạc</b><br><span class="muted">(mặc định)</span></td>
<td>Clip loop + playlist nhạc <b>tự lặp theo độ dài video</b> → ra file <code>.mp4</code>.
Dùng cho video YouTube chill/lofi dài.</td></tr>
<tr><td><b>Chỉ video</b></td>
<td>Chỉ loop clip, <b>không dùng playlist nhạc</b> → file <code>.mp4</code>. Vẫn giữ được tiếng gốc của clip
và lớp tiếng nền (mưa, lửa…) nếu muốn.</td></tr>
<tr><td><b>Chỉ nhạc</b></td>
<td>Chỉ loop playlist nhạc cho đủ thời lượng (ví dụ 10 bài 30 phút → 1 giờ) → file
<code>.mp3 / .m4a / .flac / .wav</code>. <b>Không cần clip</b>, trang Video bị bỏ qua.</td></tr>
</table>

<a name="luong"></a>
<h2>2. Làm theo từng bước</h2>

<h3>Luồng A: Video có nhạc</h3>
<ol>
<li>Thanh trên: chọn <b>Video có nhạc</b>.</li>
<li><b>Trang Video</b>: kéo thả clip vào bảng. Bấm đúp ô <b>Số lần phát</b> để nhập số lần loop
(ví dụ <code>70</code>). Muốn bỏ phần đầu/cuối của clip → bấm đúp ô <b>Đoạn lấy</b>.
Thêm crossfade nếu muốn chỗ nối mượt.</li>
<li><b>Trang Video → thẻ Độ dài</b>: để <i>Thủ công</i> (video dài đúng theo bảng),
hoặc chọn <i>Thời lượng mục tiêu</i> (ví dụ 3 giờ) để app tự lặp cho đủ.</li>
<li><b>Trang Nhạc</b>: kéo thả 1 bài hoặc cả thư mục nhạc. <b>Không cần chỉnh độ dài</b>: nhạc tự lặp đúng bằng video.
Dòng xanh trên cùng cho biết nhạc sẽ lặp mấy lượt.</li>
<li><b>Trang Xuất</b>: chọn thư mục lưu → <b>▶ Bắt đầu xuất video</b>.</li>
</ol>
<p class="tip">Video có ít bài nhạc thì nhạc lặp lại nhiều lần; playlist dài hơn video thì chỉ phát những bài kịp
phát, bài cuối nhỏ dần đúng lúc video kết thúc.</p>

<h3>Luồng B: Chỉ video</h3>
<ol>
<li>Thanh trên: chọn <b>Chỉ video</b>.</li>
<li><b>Trang Video</b>: làm như luồng A (clip, số lần phát, độ dài).</li>
<li>Tiếng gốc của clip được <b>giữ sẵn</b> (đổi ở trang Video → thẻ <b>Khung &amp; Tiếng</b> → <i>Tiếng gốc clip</i>); có thể thêm trang Nhạc → <b>Lớp tiếng nền</b>.
Để trống cả hai thì video <b>không có tiếng</b>.</li>
<li><b>Trang Xuất</b> → <b>▶ Bắt đầu xuất video</b>.</li>
</ol>

<h3>Luồng C: Chỉ nhạc</h3>
<ol>
<li>Thanh trên: chọn <b>Chỉ nhạc</b>. Trang Video không cần làm gì.</li>
<li><b>Trang Nhạc</b>: kéo thả bài nhạc, chọn thứ tự, crossfade, chuẩn hoá âm lượng, tiếng nền (tuỳ ý).</li>
<li><b>Trang Nhạc → thẻ Độ dài file nhạc</b> (trên cùng bên phải): chọn <i>Theo thời lượng</i> (ví dụ <b>1h</b>: 10 bài 30 phút sẽ tự lặp thành 1 tiếng) hoặc
<i>Theo số lượt playlist</i> (ví dụ 3 lượt). Định dạng file (MP3 320, M4A, FLAC, WAV…) chọn ở trang <b>Xuất</b>.</li>
<li>Bấm <b>▶ Bắt đầu xuất file nhạc</b>. File ra kèm <code>_tracklist.txt</code>.</li>
</ol>

<h3>Luồng D: video chạy theo độ dài nhạc</h3>
<p>Khi bạn có sẵn 1 playlist (ví dụ dài 30 phút) và muốn video dài <b>đúng bằng</b> playlist đó:
kiểu <b>Video có nhạc</b> → trang Video → thẻ Độ dài → <i>Chế độ độ dài: Theo độ dài nhạc</i>.
App sẽ loop clip cho vừa đúng một lượt playlist.</p>

<h3>Luồng E: xuất nhiều file qua đêm (hàng đợi)</h3>
<ol>
<li>Làm xong dự án/cài đặt thứ nhất → trang Xuất → <b>＋ Thêm vào hàng đợi</b>.</li>
<li>Đổi sang dự án khác (hoặc đổi kiểu, độ phân giải…) → <b>＋ Thêm vào hàng đợi</b> tiếp.
Mỗi mục được chụp lại cài đặt lúc thêm vào.</li>
<li>Bấm <b>▶ Chạy hàng đợi</b>. Nếu muốn, vào <b>Cài đặt</b> tick <i>Tắt máy khi chạy xong hàng đợi</i>.</li>
</ol>

<a name="lienket"></a>
<h2>3. Các trang liên kết với nhau thế nào</h2>
<p>Video, Nhạc, Xuất là <b>3 phần của cùng một dự án</b>; bấm <b>Lưu</b> là lưu cả ba vào 1 file <code>.lsproj</code>.</p>
<table>
<tr><td><b>Ai quyết định độ dài?</b></td><td><b>Video</b> (mặc định) — nhạc chạy theo.<br>
<b>Nhạc</b> nếu chọn <i>Theo độ dài nhạc</i> — video chạy theo.<br>
Kiểu Chỉ nhạc: thẻ <b>Độ dài file nhạc</b> ở trang Nhạc — playlist lặp cho đủ thời lượng bạn đặt.</td></tr>
<tr><td><b>Âm lượng nhạc / tiếng gốc / tiếng nền</b></td><td><b>Bảng trộn âm</b> ở trang 2 (dùng chung cả 3 kiểu),
có nút <b>Nghe thử 20 giây</b>. Âm lượng riêng từng bài: cột <i>Âm lượng %</i> trong playlist.</td></tr>
<tr><td><b>Nhìn tổng thể</b></td><td>Thanh <b>dòng thời gian</b>: làn <b>CLIP</b> là các clip theo thứ tự phát
(cùng một file luôn cùng màu). Làn dưới đổi tên theo âm thanh thật có trong video: <b>NHẠC</b> (playlist),
<b>TIẾNG GỐC</b> (chỉ tiếng có sẵn trong clip) hoặc <b>NHẠC + GỐC</b> (trộn cả hai). Rê chuột vào tên làn để xem giải thích.
Clip quá ngắn (ví dụ cảnh 10 giây giữa 2 đoạn loop 10 phút) hiện thành <b>vạch có nhãn số</b>.
<b>Lăn chuột</b> trên thanh để phóng to, <b>kéo</b> để di chuyển, <b>nhấp đúp</b> để xem lại toàn bộ.</td></tr>
</table>
<p class="tip">Thanh trên cùng luôn hiện <b>độ dài một chuỗi</b>, <b>số vòng</b> và <b>tổng thời lượng</b>
(kiểu Chỉ nhạc: độ dài 1 lượt playlist và số lượt bài). Chip màu vàng là có lưu ý, rê chuột lên để xem.
App tự lưu mọi thứ khi đóng.</p>

<a name="video"></a>
<h2>Trang Video</h2>
<h3>Bảng clip</h3>
<ul>
<li>Kéo thả <b>video</b> (mp4, mov, mkv…) hoặc <b>ảnh</b> (jpg, png…) vào bảng; kéo dòng lên/xuống để đổi thứ tự.</li>
<li><b>Tìm tên file</b> (ô tìm kiếm cạnh thanh công cụ, phím <span class="k">Ctrl+F</span>) — có ở bảng clip và
playlist nhạc: gõ một phần tên, không cần dấu (<code>mua</code> ra "Mưa…"), nhiều từ thì phải có đủ. Khi đang tìm,
Xoá / Bật / Tắt / Chọn tất cả chỉ áp cho các dòng đang hiện. <span class="k">Esc</span> để xoá ô tìm.</li>
<li><b>Ô tick</b> đầu dòng: bật/tắt clip. Phím <span class="k">Space</span> bật/tắt các dòng đang chọn.</li>
<li><b>Số lần phát</b> (bấm đúp để sửa): <code>70</code> = phát 70 lần · <code>1</code> = không loop ·
<code>0</code> = bỏ qua · <code>50-80</code> = ngẫu nhiên từ 50 đến 80 lần ·
<b>theo thời lượng</b>: <code>10p</code> hoặc <code>10:00</code> = loop cho đủ 10 phút (cũng nhận <code>90s</code>,
<code>1h</code>, <code>1:30:00</code>) — app tự tính số lần, có tính cả đoạn cắt và crossfade.</li>
<li><b>Nhân bản dòng</b> (<span class="k">Ctrl+D</span>, chuột phải, hoặc nút ở hàng <i>Cắt đoạn &amp; chuyển cảnh ▾</i>): dùng lại cùng một clip ở chỗ khác.
Ví dụ <b>A 10 phút → B → A 10 phút</b>: đặt A = <code>10p</code>, B = <code>1</code>, bấm Nhân bản A rồi kéo bản sao xuống
dưới B. Mỗi bản sao có số lần phát, đoạn cắt và crossfade riêng.</li>
<li><b>Xen kẽ clip nền</b> (nút ở góc trên bảng, hoặc chuột phải): tự dựng bảng kiểu
<b>nền ×70 → cảnh 2 → nền ×70 → cảnh 3 → … → nền ×70</b> theo tên file. Clip nền được nhận theo tên có chữ
<code>loop</code> (hoặc <code>nen</code>, <code>bg</code>, <code>base</code>), ví dụ <code>loop_chr2.mp4</code>;
các clip còn lại là cảnh chèn, xếp theo <b>số đầu tên file</b> (<code>2_…</code>, <code>3_…</code>, … <code>10_…</code>).
Trong hộp thoại:
<ul>
<li><b>Mẫu có sẵn</b>: Nền ×70 xen từng cảnh · Nền 10 phút xen từng cảnh · Nền ×70 lặp cả mẫu 4 lượt ·
Nền 5 phút, cảnh ngẫu nhiên lặp 6 lượt. Bấm <b>Lưu mẫu…</b> để lưu cách xếp của mình (nhớ cả thứ tự và số lần
từng cảnh theo tên file) rồi dùng lại cho dự án khác.</li>
<li><b>Nền phát mỗi lần</b>: <code>70</code> hoặc <code>10p</code>. <b>Lặp lại cả mẫu</b>: ví dụ 1 loop + 2 cảnh,
lặp 4 lượt → <i>nền → cảnh 1 → nền → cảnh 2 → nền → cảnh 1 → …</i> (4 lượt) <i>→ nền</i>; tick
<i>Mỗi lượt xáo lại thứ tự</i> để mỗi lượt khác nhau.</li>
<li><b>Danh sách cảnh chèn</b>: kéo thả (hoặc nút ↑ ↓) để đổi cảnh nào trước; bỏ tick để không dùng;
cột <b>Xuất hiện</b> = cảnh đó chèn mấy lần trong mỗi lượt mẫu; cột <b>Phát</b> = mỗi lần chèn phát mấy lần liền.</li>
<li>Khung bên phải <b>xem trước</b> đúng bảng sẽ tạo và tổng thời lượng; bấm <i>Áp dụng vào bảng</i>.</li>
</ul>
Khi kéo cả thư mục có file <code>loop…</code> vào, app tự hiện gợi ý <i>Xen kẽ ngay</i>. Làm lại được nhiều lần
(các dòng trùng được gộp rồi dựng lại); <span class="k">Ctrl+Z</span> để quay lại.</li>
<li><b>Đoạn lấy</b> (bấm đúp ô, hoặc chuột phải → <i>Chọn đoạn lấy</i>): bỏ phần đầu / phần cuối, chỉ dùng đoạn giữa
của clip. Ví dụ clip 10 giây, bỏ 2s đầu + 2s cuối → mỗi lần phát dài 6 giây, kể cả khi loop 70 lần.
Hộp thoại có <b>trình phát video</b> tự lặp đúng đoạn đã chọn; kéo 2 tay nắm (video nhảy theo), hoặc phát tới chỗ
muốn cắt rồi bấm <i>Đặt điểm đầu / cuối tại đây</i> (phím <span class="k">I</span> / <span class="k">O</span>).
Cắt nhiều clip cùng lúc: bôi đen các dòng → bấm <i>Cắt đoạn &amp; chuyển cảnh ▾</i> → hàng <b>Cắt đoạn</b>.</li>
<li><b>Nối vòng lặp</b>: hoà hình (crossfade) giữa các lần loop của chính clip đó. <b>Cắt</b> = nối thẳng.</li>
<li><b>Sang clip sau</b>: hoà hình khi chuyển sang clip kế tiếp.</li>
<li><b>Tự giãn</b>: chỉ hiện khi chọn <i>Thời lượng mục tiêu</i> + <i>Tăng số lần phát của clip tick 'Tự giãn'</i>.
Clip được tick sẽ tự phát thêm cho đủ giờ; clip không tick giữ nguyên số lần.</li>
<li>Bấm đúp <b>tên file</b> để xem clip.</li>
</ul>
<p class="tip">Đặt cho nhiều clip cùng lúc: bôi đen các dòng (<span class="k">Ctrl</span>/<span class="k">Shift</span>
+ bấm, hoặc <span class="k">Ctrl+A</span>) → thẻ <b>Đặt nhanh</b>.<br>
<b>▶ Xem thử chỗ nối</b>: xuất nhanh clip đang chọn phát 2 lần rồi sang clip kế, để xem crossfade.</p>

<h3>Độ dài video</h3>
<ul>
<li><b>Thủ công</b>: phát đúng một lượt theo bảng.</li>
<li><b>Thời lượng mục tiêu</b> (ví dụ 3 giờ), 2 cách lấp đầy:
  <ul>
  <li><b>Lặp lại cả chuỗi</b>: V1→V6 rồi lại V1→V6… (tick <i>Mỗi vòng xáo lại</i> để mỗi vòng một thứ tự).</li>
  <li><b>Tăng số lần phát của clip tick 'Tự giãn'</b>: phát một chuỗi, các clip được tick dài ra cho đủ giờ.</li>
  </ul></li>
<li><b>Theo độ dài nhạc</b>: video dài đúng một lượt playlist (không dùng được ở kiểu Chỉ video).</li>
<li><b>Kết thúc đúng thời lượng</b>: cắt phần dư cho tròn (ví dụ đúng 3:00:00) và mờ dần ở cuối.</li>
</ul>

<h3>Thứ tự, Intro/Outro, Hình ảnh, Âm thanh</h3>
<ul>
<li><b>Thứ tự</b>: theo bảng hoặc ngẫu nhiên. <b>Số mầm</b> giữ cho kết quả ngẫu nhiên giống hệt bản xem trước;
<b>Đổi mầm</b> để ra thứ tự khác.</li>
<li><b>Intro/Outro</b>: luôn ở đầu/cuối, không bị xáo, có crossfade; tick <i>Giữ tiếng gốc</i> nếu intro có nhạc hiệu.</li>
<li><b>Clip khác tỉ lệ</b> (ví dụ clip dọc trong video ngang): Viền đen / <b>Nền mờ</b> (đẹp nhất) / Cắt cho đầy khung / Kéo giãn.</li>
<li><b>Mỗi ảnh tĩnh hiện</b>: thời lượng một lần phát ảnh. <b>Mờ dần ở cuối</b>: hình tối dần khi kết thúc.</li>
<li><b>Tiếng gốc clip</b>: mặc định <b>giữ</b> và trộn với nhạc nền (clip không có tiếng thì im lặng); có thể chọn
<i>Chỉ tiếng gốc</i> (bỏ nhạc) hoặc <i>Tắt tiếng gốc</i>. Độ to của tiếng gốc / nhạc / tiếng nền chỉnh ở
<b>Bảng trộn âm</b> (trang 2).</li>
</ul>
<h3>Màu &amp; Logo (thẻ thứ 3 cột phải)</h3>
<ul>
<li><b>Chỉnh màu</b>: 6 bộ lọc dựng sẵn — Ấm nắng chiều, Lạnh xanh đêm, Vintage phim cũ, Đen trắng, Rực rỡ,
Điện ảnh Teal &amp; Orange — kèm <b>Cường độ 0–100%</b> (50% = nửa hình gốc, nửa bộ lọc).</li>
<li><b>Logo / Khung PNG</b>: chọn ảnh <code>.png</code> nền trong suốt; đặt ở 4 góc, chính giữa, hoặc
<b>Phủ cả khung hình</b> (khung viền, banner trang trí); chỉnh <b>kích thước</b> và <b>độ rõ</b>.</li>
<li>Khung <b>Xem trước</b> hiện đúng một khung hình của clip đầu tiên đã áp màu &amp; logo, cập nhật ngay khi chỉnh.</li>
<li>Mặc định <b>không</b> áp lên Intro / Outro (thường đã có thương hiệu riêng) — tick ô cuối nếu muốn áp cả.</li>
<li>Không làm chậm việc xuất: mỗi clip vẫn chỉ mã hoá một lần.</li>
</ul>

<a name="nhac"></a>
<h2>Trang Nhạc</h2>
<ul>
<li><b>Playlist</b>: kéo thả bài hoặc thư mục nhạc. Bỏ tick bài không dùng. <b>Số lần/lượt</b> = bài đó phát mấy lần
trong mỗi lượt playlist. Bấm đúp tên bài để nghe thử.</li>
<li><b>Thứ tự</b>: theo bảng, ngẫu nhiên, hoặc <b>ngẫu nhiên không lặp bài liền nhau</b>.</li>
<li><b>Crossfade giữa bài</b> (hoặc khoảng lặng), <b>to dần ở đầu</b>, <b>nhỏ dần ở cuối</b>.
Với 1 bài lặp lại, crossfade chính là chỗ nối giữa các lần lặp (đặt 0 nếu bài đã làm sẵn để loop khít).</li>
<li><b>Chuẩn hoá âm lượng</b>: các bài to nhỏ khác nhau được đưa về cùng mức (-14 LUFS = chuẩn YouTube).</li>
<li><b>Bảng trộn âm</b> (đầu cột phải, có ở cả 3 kiểu): thanh <b>Nhạc</b>, <b>Tiếng gốc clip</b> và <b>từng lớp tiếng nền</b>,
0–200% (100% = giữ nguyên; bấm đúp tên để về 100%). Muốn mưa nổi hơn nhạc: kéo <b>Nhạc xuống 50–70%</b> sẽ tự nhiên hơn
đẩy mưa lên quá 150% (cuối cùng app có bộ chống vỡ tiếng nên đẩy quá to sẽ bị nén lại).
<b>Nghe thử 20 giây</b>: chọn mốc <i>Nghe từ</i> (Đầu / Giữa / Chỗ đổi bài / Cuối hoặc tự gõ, ví dụ 1:30:00) → app trộn
đúng như khi xuất rồi phát ngay trong app; <b>đang nghe mà kéo thanh âm lượng là nghe thay đổi ngay</b> (không ngắt tiếng). Đổi playlist / âm lượng từng bài thì bấm Dừng rồi nghe lại.</li>
<li><b>Âm lượng riêng từng bài</b>: bấm đúp cột <i>Âm lượng %</i> trong playlist (hoặc chuột phải → Đặt âm lượng cho
nhiều bài cùng lúc). Áp sau khi chuẩn hoá: 50% ≈ nhỏ đi 6 dB, 150% ≈ to thêm 3,5 dB, 0% = tắt tiếng bài đó.</li>
<li><b>Lớp tiếng nền</b> (mưa, lửa, sóng… — file nhạc hoặc video): tự lặp suốt video/file nhạc, âm lượng riêng từng lớp,
dùng được ở cả 3 kiểu. Không có file? Bấm <b>Thư viện có sẵn…</b>: mưa rào, mưa nhẹ hiên nhà, sóng biển, gió, lửa củi, white / pink / brown noise — app tự tạo (không cần mạng, dùng thoải mái cho YouTube), có nút <i>Nghe thử</i>. Chỗ lặp được <b>hoà mượt</b> (đuôi file hoà dần vào đầu file) nên không nghe khựng.</li>
<li><b>Âm thanh nền / ASMR / white noise</b>: ở kiểu <b>Chỉ nhạc</b>, <b>không cần bài nhạc nào</b> — chỉ thêm các lớp
tiếng nền (ví dụ mưa 70% + sấm 30% + lửa 50%), đặt độ dài ở thẻ <i>Độ dài file nhạc</i> (ví dụ 8 giờ) rồi xuất
MP3 / M4A / FLAC / WAV. Thẻ <b>Âm thanh nền (ASMR)</b> ở trang Bắt đầu mở sẵn đúng chỗ.</li>
<li><b>Lịch phát nhạc</b> bên dưới cho biết bài nào phát lúc nào.</li>
</ul>
<p class="warn"><b>Lưu ý:</b> Ở kiểu <b>Chỉ video</b>, playlist bị làm mờ vì không được dùng (tiếng nền vẫn dùng được).</p>

<a name="xuat"></a>
<h2>Trang Xuất</h2>
<h3>Kiểu Video có nhạc / Chỉ video → thẻ Định dạng</h3>
<table>
<tr><td><b>Codec</b></td><td><b>H.264</b> chạy được mọi nơi; <b>H.265</b> file nhẹ hơn khoảng 40%.</td></tr>
<tr><td><b>Độ phân giải</b></td><td>Theo clip đầu, 720p, 1080p, 2K, 4K, <b>dọc 9:16</b> (Shorts/TikTok), vuông 1:1.</td></tr>
<tr><td><b>Khung hình/giây</b></td><td>Theo clip đầu (khuyên dùng), hoặc 24/25/30/50/60.</td></tr>
<tr><td><b>Bộ mã hoá</b></td><td><b>Tự động</b> dùng card đồ hoạ (NVIDIA/Intel/AMD); card lỗi thì tự chuyển sang CPU.</td></tr>
<tr><td><b>Chất lượng âm thanh</b></td><td>Riêng cho phần tiếng (nhạc + tiếng gốc + tiếng nền), không liên quan tới
chất lượng hình ảnh. AAC 192 kbps (nhanh, khuyên dùng — đủ cho YouTube) hoặc 320 kbps (chậm hơn khoảng 10 lần,
chỉ thêm khoảng 60 MB mỗi giờ).</td></tr>
<tr><td><b>Chất lượng hình ảnh</b></td><td><b>Tiết kiệm dung lượng</b> (nhẹ nhất, vẫn đẹp khi xem YouTube) · Cân bằng ·
Cao (mặc định) · Rất cao.</td></tr>
<tr><td><b>Giới hạn dung lượng</b></td><td>Không giới hạn · <b>Theo khuyến nghị YouTube</b> (1080p ≈ 8 Mbps, 2K ≈ 16,
4K ≈ 44) · <b>Tự đặt Mbps</b> · <b>Theo dung lượng tối đa</b> (gõ số GB, app tự tính bitrate theo độ dài video).</td></tr>
<tr><td><b>Dự đoán dung lượng</b></td><td>Tự cập nhật mỗi khi đổi bất kỳ cấu hình nào (ở cả thanh trên cùng).
App mã hoá thử vài giây của clip loop với đúng cấu hình đang chọn rồi tính theo độ dài video — sai số thường
dưới 10%.</td></tr>
</table>
<h3>Vì sao video loop lại nặng? Làm sao cho nhẹ?</h3>
<p>File MP4 không có cách ghi "lặp lại đoạn này 70 lần": mỗi lần lặp vẫn chiếm dung lượng như nhau, nên dung lượng
≈ bitrate × độ dài. Clip AI (Google Flow…) nhiều chi tiết nên bitrate cao. Cách giảm, theo mức hiệu quả:
<b>① hạ độ phân giải</b> (2K → 1080p nhẹ hơn khoảng 2 lần, YouTube vẫn nét) ·
<b>② H.265/HEVC</b> (nhẹ hơn khoảng 20–40%) · <b>③ chất lượng Tiết kiệm dung lượng</b> ·
<b>④ Giới hạn dung lượng</b> theo YouTube hoặc theo số GB muốn có.
Xem con số <b>Dự đoán dung lượng</b> thay đổi ngay khi chỉnh.</p>
<h3>Kiểu Chỉ nhạc → thẻ Độ dài file nhạc (trang Nhạc) + định dạng (trang Xuất)</h3>
<p><b>Độ dài theo</b> thời lượng (30p / 1h / 3h hoặc tự gõ) hoặc theo số lượt playlist; <b>Định dạng</b>
MP3 320/192, M4A, FLAC (không mất chất lượng), WAV.</p>
<h3>Xuất hàng loạt theo thư mục</h3>
<p>Làm nhiều video <b>cùng một kiểu</b>, chỉ khác bộ clip: để mỗi video vào một <b>thư mục con</b> (clip nền tên có
chữ <code>loop</code>, cảnh chèn đánh số <code>2_</code>, <code>3_</code>…, nhạc riêng nếu có để trong thư mục con đó),
mở một dự án làm <b>khuôn</b> (cấu hình xuất, intro/outro, tiếng nền, playlist chung…), rồi bấm <b>Xuất hàng loạt…</b>
ở thanh bên (hoặc <i>Hàng loạt từ thư mục…</i> ở khung hàng đợi). Chọn thư mục cha, chọn mẫu xếp clip, chọn <b>Tiếng gốc clip</b> cho cả loạt (giữ và trộn với nhạc / chỉ tiếng gốc / tắt — mặc định theo dự án khuôn) — bảng hiện
từng video sẽ tạo (clip nền, số clip, nhạc riêng/chung, thời lượng) — bấm <b>Thêm vào hàng đợi</b>. Mỗi video lấy tên
thư mục. Muốn <b>đổi thứ tự cảnh riêng một video</b> (ví dụ cảnh 3 lên trước cảnh 2): bấm <b>Chỉnh…</b> ở dòng đó
(hoặc nhấp đúp) → kéo thả / ↑ ↓, đổi số lần phát → Áp dụng; dòng đó hiện <i>Đã chỉnh tay</i>, các video khác vẫn theo
mẫu chung; chuột phải → <i>Bỏ chỉnh tay</i> để quay lại mẫu. Kiểu <b>Chỉ nhạc</b>: mỗi thư mục con là một playlist → một file nhạc. Thư mục bắt đầu bằng <code>_</code>
được bỏ qua. Thử ngay với thư mục mẫu <code>Mau-Test › Hang-loat</code> (nút <i>Thư mục mẫu</i>, có HUONG-DAN.txt).</p>
<p><b>Âm lượng cả loạt</b>: hàng <b>Âm lượng</b> trong hộp thoại (Nhạc / Tiếng gốc / từng lớp tiếng nền, mặc định
theo Bảng trộn âm của dự án đang mở). Bấm <b>Nghe</b> ở một dòng để nghe 20 giây của đúng video đó (mốc chọn ở ô
<i>Nghe từ</i>: đầu / giữa / chỗ đổi bài) — đang nghe mà kéo thanh là nghe đổi ngay. Muốn <b>một video to / nhỏ khác</b>
(ví dụ video 2 mưa to hơn): chuột phải dòng đó → <i>Chỉnh âm lượng video này…</i> (có nghe thử) → dòng hiện
<i>Đã chỉnh âm lượng riêng</i>; chuột phải → <i>Bỏ âm lượng riêng</i> để quay về mức chung.</p>
<h3>Xuất nhiều bản nhạc khác thứ tự + bài ghim</h3>
<ul>
<li>Trang Nhạc → thẻ <b>Độ dài file nhạc</b> → <b>Số bản xuất</b> (ví dụ 4): app tạo 4 file, cùng các bài nhưng
<b>mỗi file một thứ tự phát khác nhau</b> và cố gắng mở đầu bằng bài khác nhau — tiện đăng nhiều video nhạc
từ cùng một playlist. File tên <code>…_ban-1.mp3</code> … <code>…_ban-4.mp3</code>, mỗi bản có tracklist riêng,
nằm chung một thư mục. Bấm <b>Xuất 4 bản nhạc</b>: các bản được xếp vào hàng đợi và xuất lần lượt.</li>
<li>Cạnh <b>Lịch phát dự kiến</b> có ô <b>Xem bản</b> để xem trước thứ tự bài của từng bản.</li>
<li><b>Bài ghim</b>: chuột phải một bài → <i>Ghim</i> (có biểu tượng ghim màu vàng). Bài ghim <b>luôn có trong file</b> ở
mọi bản, kể cả khi file ngắn hơn cả playlist (ví dụ 63 bài nhưng chỉ xuất 1 giờ). Thẻ <b>Thứ tự phát</b> →
<i>Bài ghim đặt ở</i>: <b>Mở đầu file</b> hoặc <b>Vị trí ngẫu nhiên</b> (vẫn chắc chắn có trong file).</li>
</ul>
<h3>Nơi lưu, hàng đợi, file kèm</h3>
<ul>
<li>Chọn thư mục; tên file để trống = tự đặt theo tên dự án + ngày giờ.</li>
<li><b>＋ Thêm vào hàng đợi</b> / <b>▶ Chạy hàng đợi</b>: xem luồng E ở trên. Tên trùng tự thêm <code>_2</code>, <code>_3</code>.</li>
<li><b>Mỗi video một thư mục riêng</b> (bật sẵn): <code>Thư mục lưu › Tên-video › Tên-video.mp4</code>, mọi file kèm nằm
chung trong đó.</li>
<li><b>File mốc thời gian cho editor</b> (bật sẵn) — liệt kê từng đoạn <b>LOOP</b> (nền lặp) và <b>THƯỜNG</b>
(cảnh chèn phát 1 lần, chỗ nên thêm sound effect), chính xác tới từng khung hình:
<code>_moc-thoi-gian.txt</code> (đọc ngay) · <code>.csv</code> (Excel) ·
<code>.srt</code> (kéo vào Premiere / CapCut / DaVinci thành một track chữ hiện tên từng đoạn trên timeline) ·
<code>_markers-davinci.edl</code> (DaVinci Resolve: chuột phải timeline → <i>Timelines → Import → Timeline Markers
from EDL</i>; đoạn THƯỜNG màu đỏ, LOOP màu xanh).</li>
<li>Kèm theo mỗi file: <b>_tracklist.txt</b> (mốc thời gian từng bài, dán vào mô tả YouTube để có chapter) và
<b>_project.lsproj</b> (mở lại để xuất lại y hệt).</li>
</ul>

<a name="caidat"></a>
<h2>Cài đặt và thông số máy</h2>
<ul>
<li><b>Máy tính của bạn</b>: hệ điều hành, CPU, RAM, card đồ hoạ (driver, VRAM, nhiệt độ), phiên bản <b>CUDA</b>, ổ đĩa.</li>
<li><b>FFmpeg và tăng tốc phần cứng</b>: xác nhận có FFmpeg và các bộ mã hoá bằng card: NVIDIA <b>NVENC</b>,
Intel <b>Quick Sync</b>, AMD <b>AMF</b>, giải mã <b>CUDA</b> (✓ xanh = dùng được).</li>
<li><b>Đo tốc độ</b>, thư mục xuất mặc định, mở thư mục/âm báo khi xong, <b>tắt máy khi xong hàng đợi</b>,
chọn bản FFmpeg khác, xoá bộ nhớ đệm, cỡ chữ.</li>
</ul>
<p class="tip">Tốc độ xuất chủ yếu đến từ bộ mã hoá trên card (NVENC/Quick Sync/AMF), app luôn tự dùng.
"Giải mã bằng GPU (CUDA)" thường <b>không</b> nhanh hơn với clip ngắn, chỉ nên bật khi CPU yếu.</p>

<a name="hoi"></a>
<h2>Câu hỏi thường gặp</h2>
<h3>Nhạc có tự lặp theo video không?</h3>
<p>Có (kiểu Video có nhạc). Nhạc phát nối tiếp và lặp cho tới hết video, bài cuối nhỏ dần đúng lúc video kết thúc.</p>
<h3>Chỉ muốn loop 1 trong 2 (chỉ video hoặc chỉ nhạc)?</h3>
<p>Chọn kiểu <b>Chỉ video</b> hoặc <b>Chỉ nhạc</b> ở thanh trên cùng — xem luồng B và C.</p>
<h3>Vì sao xuất nhanh vậy?</h3>
<p>Mỗi clip chỉ mã hoá <b>một lần</b>, các lần loop chỉ là sao chép dữ liệu. Video 1 giờ thường khoảng nửa phút,
10 giờ khoảng 10 phút (tuỳ máy). Lần xuất sau cùng clip còn nhanh hơn nhờ bộ nhớ đệm.</p>
<h3>Clip có độ phân giải / fps khác nhau?</h3>
<p>Không sao, app tự chuẩn hoá về cùng thông số. Cột Thông tin hiện màu cam ở clip khác với clip đầu.</p>
<h3>Ổ đĩa có đủ chỗ không?</h3>
<p>Trang Xuất hiện dung lượng dự đoán và báo đỏ nếu ổ không đủ chỗ; trước khi ghép app kiểm tra lại chính xác.
Video 10 tiếng 1080p thường cần khoảng 10–40 GB.</p>
<h3>Báo lỗi khi xuất?</h3>
<p>Xem <b>Nhật ký</b> ở trang Xuất; nhật ký đầy đủ nằm trong thư mục dữ liệu (nút <b>Thư mục nhật ký</b> ở đầu trang này).
Nếu card đồ hoạ lỗi, mở <b>Tuỳ chọn nâng cao ▾</b> ở trang Xuất → <b>Bộ mã hoá: CPU</b> rồi xuất lại. Lỗi bất ngờ của app được ghi vào <code>loi-ung-dung.log</code> trong thư mục dữ liệu.</p>
<p class="warn"><b>Lưu ý:</b> Đừng mở file đang được xuất bằng trình xem khác; đừng xoá clip/nhạc gốc khi đang xuất.</p>

<a name="phim"></a>
<h2>Phím tắt</h2>
<table>
<tr><td class="k">F1</td><td>Mở trang Hướng dẫn này</td></tr>
<tr><td class="k">Ctrl+N / Ctrl+O</td><td>Dự án mới / Mở dự án</td></tr>
<tr><td class="k">Ctrl+S / Ctrl+Shift+S</td><td>Lưu / Lưu thành…</td></tr>
<tr><td class="k">Space</td><td>Bật/tắt các dòng đang chọn</td></tr>
<tr><td class="k">Delete</td><td>Xoá các dòng đang chọn</td></tr>
<tr><td class="k">Ctrl+A</td><td>Chọn tất cả dòng trong bảng</td></tr>
<tr><td class="k">Bấm đúp</td><td>Tên file: xem/nghe thử · Ô số: sửa</td></tr>
<tr><td class="k">Lăn chuột</td><td>Chỉ cuộn trang; muốn đổi giá trị ô bằng lăn chuột thì bấm vào ô trước</td></tr>
</table>
<p><a href="#top">↑ Lên đầu trang</a></p>
"""


class HelpPage(QWidget):
    openProjectRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        logo = QLabel()
        logo.setPixmap(branding.pixmap(72, self.devicePixelRatioF()))
        name = QLabel(APP_NAME)
        name.setObjectName("appName")
        sub = QLabel(f"{AUTHOR} · Phiên bản {APP_VERSION}")
        sub.setObjectName("muted")
        desc = QLabel("Ghép và loop clip + nhạc thành video YouTube dài, dùng card đồ hoạ để xuất thật nhanh.")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        info = QVBoxLayout()
        info.setSpacing(2)
        info.addWidget(name)
        info.addWidget(sub)
        info.addWidget(desc)
        head = QHBoxLayout()
        head.addWidget(logo)
        head.addSpacing(10)
        head.addLayout(info, 1)

        btns = QHBoxLayout()
        sample_dir = Path(ft.app_dir()) / "Mau-Test"
        for proj in sorted(sample_dir.glob("*.lsproj")) if sample_dir.is_dir() else []:
            b = QPushButton(f"Mở {proj.stem}")
            b.setIcon(icons.icon("folder", 14))
            b.setToolTip(str(proj))
            b.clicked.connect(lambda _=False, p=str(proj): self.openProjectRequested.emit(p))
            btns.addWidget(b)
        if sample_dir.is_dir():
            g = QPushButton("Hướng dẫn test bộ mẫu")
            g.setIcon(icons.icon("help", 14))
            self._sample_guide = sample_dir / "HUONG-DAN-TEST.md"
            g.setToolTip("Đọc hướng dẫn thử bộ mẫu ngay trong app")
            g.clicked.connect(self._show_sample_guide)
            btns.addWidget(g)
        logs = QPushButton("Thư mục nhật ký")
        logs.setIcon(icons.icon("terminal", 14))
        logs.setObjectName("ghost")
        logs.setToolTip("Nhật ký mỗi lần xuất, bộ nhớ đệm, tự lưu")
        logs.clicked.connect(self._open_data)
        btns.addWidget(logs)
        btns.addStretch(1)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.setOpenLinks(True)
        self.view.document().setDefaultStyleSheet(css())
        self.view.setHtml(GUIDE)
        # nút quay lại khi đang xem tài liệu khác (ví dụ hướng dẫn test bộ mẫu)
        self.back_btn = QPushButton("← Quay lại Hướng dẫn sử dụng")
        self.back_btn.setObjectName("ghost")
        self.back_btn.clicked.connect(self._show_guide)
        self.back_btn.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.addLayout(head)
        lay.addLayout(btns)
        lay.addWidget(self.back_btn, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.view, 1)

    def _show_sample_guide(self) -> None:
        """Hiện file hướng dẫn test (Markdown) ngay trong khung đọc, không phải mở bằng chương trình khác."""
        try:
            text = self._sample_guide.read_text(encoding="utf-8")
        except OSError:
            text = "Không tìm thấy file hướng dẫn test trong thư mục Mau-Test."
        self.view.setMarkdown(text)
        self.view.document().setDefaultStyleSheet(css())
        self.view.setMarkdown(text)  # đặt lại sau khi có CSS để áp màu chữ tối
        self.back_btn.show()
        self.view.verticalScrollBar().setValue(0)

    def _show_guide(self) -> None:
        self.view.document().setDefaultStyleSheet(css())
        self.view.setHtml(GUIDE)
        self.back_btn.hide()

    def refresh_font(self) -> None:
        """Đổi cỡ chữ: dựng lại trang hướng dẫn theo cỡ mới (giữ đúng vị trí đang đọc)."""
        pos = self.view.verticalScrollBar().value()
        if self.back_btn.isVisible():
            self._show_sample_guide()
        else:
            self._show_guide()
        self.view.verticalScrollBar().setValue(pos)

    def _open_data(self) -> None:
        d = ft.data_dir() / "logs"
        d.mkdir(exist_ok=True)
        os.startfile(str(d))  # type: ignore[attr-defined]

    def adapt(self, width: int) -> None:
        pass
