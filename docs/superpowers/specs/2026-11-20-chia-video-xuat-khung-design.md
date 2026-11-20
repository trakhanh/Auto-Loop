# Trang "Cắt video": Chia đoạn + Xuất ảnh

Ngày 2026-11-20 · anh Khánh chốt: cắt video dài thành đoạn ngắn để **up hàng loạt lên nền tảng**; không nối với bảng
clip hay trang Tải video — chỉ ra file trong thư mục; **một trang, hai thẻ** (Cách 1). Các điểm ghi
*(quyết định của người làm thiết kế)* là đề xuất của Claude đã báo anh Khánh, anh có thể sửa.

## Vì sao
Nhân viên cần cắt video dài (thường vừa tải về) thành nhiều đoạn ngắn rồi up hàng loạt lên TikTok / Shorts / Reels…,
và lấy ảnh từ video. Hiện phải dùng tool ngoài (ảnh tham khảo anh gửi). Gộp vào KT Loop Station bằng FFmpeg đã đi kèm
trong `bin\` — không cài thêm gì.

## Mục tiêu
- **Chia đoạn** — 5 cách cắt: chia N phần · mỗi đoạn dài cố định · độ dài ngẫu nhiên A–B · danh sách mốc thời gian ·
  danh sách khoảng A–B.
- **Xuất ảnh** — 4 cách: theo tổng số ảnh · mỗi N giây · mỗi N khung hình · theo đổi cảnh (% độ nhạy).
- Một hoặc nhiều video một lần; thư mục kết quả; thư mục riêng mỗi video.
- Chia đoạn: chế độ xuất Nhanh / Chính xác; đổi tỉ lệ khung (9:16, 16:9, 1:1, 4:5) bằng nền mờ / viền đen / cắt.
- Tiến độ, nút Dừng, nhật ký ngắn.

## Không làm (anti-goal)
- Không đưa file ra vào bảng clip / playlist / dự án; không đổi gì trong dự án đang mở.
- Không chạy ngầm: chỉ chạy khi bấm **Bắt đầu**.
- Không tách "chế độ đơn giản / nâng cao"; không có ô "Tệp đơn / Hàng loạt" — 1 video hay nhiều video là cùng một
  danh sách, app tự hiểu *(quyết định của người làm thiết kế)*.
- Không ghi đè file gốc; không xoá file nào của người dùng (chỉ dọn file do chính lượt chạy bị Dừng tạo ra, mục 5).
- Không thêm chữ dài lên giao diện: giải thích để trong tooltip.
- Không làm: ghép đoạn, thêm chữ / logo, phụ đề, đổi tốc độ, tự đăng lên nền tảng.

## Các cách đã cân nhắc
1. **Mỗi đoạn / mỗi lượt xuất ảnh là một lần chạy FFmpeg (chọn).** Tiến độ chính xác, Dừng ngay, đoạn lỗi chỉ báo
   đoạn đó; dùng được cho cả 5 cách cắt và đổi tỉ lệ.
2. FFmpeg `-f segment` chia một lèo — nhanh hơn chút, nhưng chỉ hợp cắt đều / theo mốc, không làm được khoảng A–B rời
   nhau hay ngẫu nhiên có kiểm soát, không đổi được tỉ lệ khi `-c copy`. Bỏ.
3. Hai trang riêng trên thanh bên — dễ thấy hơn nhưng thanh bên dài thêm 2 dòng, laptop nhỏ chật. Anh Khánh chọn một
   trang hai thẻ.

## Thiết kế

### 1. Vị trí trong app
- **Trang mới trong `MainWindow.stack`**, chỉ số `CUT_PAGE = 7` (sau `DOWNLOAD_PAGE = 6`), bọc trong `QScrollArea`
  như trang Tải video. Không phải hộp thoại: cắt lâu, người dùng đi làm việc khác trong lúc chạy.
- Thanh bên: nút **"Cắt video"** (biểu tượng `scissors` — thêm vào `icons.py` nếu chưa có) ngay dưới "Tải video",
  `checkable`, thuộc `self.nav` (id 7). Nhãn "MỚI" trong nút tới lần mở đầu (`new/cut_seen`), cùng cách nút Tải video.
  Khi đang chạy: chữ kèm tiến độ, vd "Cắt video (3/10)".
- Trang **Bắt đầu**: thêm 2 thẻ vào `CARDS` (không vào `MAIN_KEYS`):
  - `("cut", "scissors", <tone>, "Chia video thành đoạn", "Cắt video dài thành nhiều đoạn ngắn để up hàng loạt — chia đều, theo độ dài, ngẫu nhiên, theo mốc.", "Đổi sang 9:16 nền mờ cho TikTok / Shorts")`
  - `("frames", "image", <tone>, "Xuất ảnh từ video", "Lấy ảnh từ video: theo số ảnh, mỗi N giây, mỗi N khung, theo đổi cảnh.", "Nhiều video một lần → mỗi video một thư mục ảnh")`
  - `_home_choice("cut")` → `go_to(CUT_PAGE)` + chọn thẻ Chia đoạn; `"frames"` → thẻ Xuất ảnh.
- Ở trang này: ẩn dòng thời gian, trình phát bên phải, thanh các bước và phần đầu dự án — xử lý y như `DOWNLOAD_PAGE`
  trong `go_to` (dùng chung một tập "trang công cụ toàn màn hình").
- `_help_action`: thêm khoá `"cut": CUT_PAGE` (trang Hướng dẫn chưa cần sửa — phiên khác đang sửa `help_page.py`).
- Đóng app khi đang chạy → hỏi "Đang cắt video. Dừng và thoát?" như Tải video. Hẹn tắt máy sau hàng đợi xuất → chờ
  trang Cắt video xong như chờ tải video *(quyết định của người làm thiết kế)*.

### 2. Bố cục trang
Dùng lại mẫu trang Tải video: trái = danh sách video, phải = thẻ cài đặt hẹp (`QScrollArea` cố định ~345 px; cửa sổ
hẹp thì xếp dọc qua `adapt`), thanh dưới cố định.

```
┌ Cắt video ───────────────────────────────────────────────────────────────────┐
│ [ Chia đoạn | Xuất ảnh ]   (Segmented to, đầu trang)                         │
│ ┌ Danh sách video ──────────────────────────┐ ┌ Cài đặt chia đoạn ─────────┐ │
│ │ [+ Thêm video] [+ Thư mục]                │ │ Cách cắt                   │ │
│ │ ▣ video-a.mp4   12:30  1080×1920  ✓ 25 đoạn│ │ ( ) Chia N phần   [ 2 ]    │ │
│ │ ▣ video-b.mp4    3:05  1920×1080  ▓▓▓░ 40% │ │ (•) Mỗi đoạn  [00:00:30]   │ │
│ │ ▣ video-c.mp4    —     lỗi: không đọc được │ │ ( ) Ngẫu nhiên [10s]~[45s] │ │
│ │ (kéo thả file / thư mục vào đây)           │ │ ( ) Theo mốc   [ ...... ]  │ │
│ │                                            │ │ ( ) Theo khoảng [ ...... ] │ │
│ ├ Nhật ký ──────────────────────────────────┤ │ Dự kiến: 25 đoạn × ~30 s   │ │
│ │ 10:21 video-a → 25 đoạn (1 phút 12 giây)   │ │ Chế độ xuất [Chính xác|Nhanh]│
│ │ 10:22 video-b: đoạn 7 lỗi — …             │ │ Tỉ lệ [Giữ|9:16|16:9|1:1|4:5]│
│ └────────────────────────────────────────────┘ │ Khi đổi [Nền mờ|Viền đen|Cắt]│
│                                                │ Lưu vào [D:\…\Chia video][Đổi]│
│                                                │ ☑ Thư mục riêng mỗi video   │ │
│                                                └────────────────────────────┘ │
│ ════════════ (thanh tổng mảnh `thinBar`, chỉ hiện khi chạy) ══════════════ │
│ 3 video · 51 đoạn dự kiến        [⋯] [Mở thư mục] [ ▶ Bắt đầu chia ]        │
└──────────────────────────────────────────────────────────────────────────────┘
```

- **Thẻ trên cùng** `Segmented` (lấy từ `download_page.py` — chuyển sang `widgets.py` nếu cần dùng chung, nhưng
  **không sửa `download_page.py`**: import `Segmented`, `Spinner` từ đó). Đổi thẻ chỉ đổi thẻ cài đặt bên phải và
  chữ nút Bắt đầu; danh sách video, thư mục, nhật ký dùng chung. Nhớ thẻ đang mở (`cut/tab`).
- **Danh sách video** (`QTreeWidget`, cột: Tên · Thời lượng · Khung hình · Trạng thái). Thêm bằng nút, kéo thả file
  hoặc thư mục (thư mục: lấy các file video ở cấp đầu, đuôi giống bộ lọc video sẵn có của app). Mỗi file được đọc
  thời lượng / kích thước bằng `probe` ở nền. Ô tick đầu dòng để bỏ qua một video mà không xoá khỏi danh sách.
  Chuột phải: Bỏ khỏi danh sách · Mở thư mục kết quả · Mở file gốc. Menu ⋯: Xoá danh sách (không xoá file).
  Danh sách nhớ giữa các lần mở app *(quyết định của người làm thiết kế: lưu `cut/files` trong QSettings, file mất
  thì bỏ qua)*. Trạng thái: Chờ · % (ProgressDelegate kiểu Tải video) · ✓ 25 đoạn / ✓ 100 ảnh · lỗi (đỏ, lý do ngắn).
  Trạng thái riêng cho từng thẻ (giữ trong bộ nhớ): đổi thẻ thì cột Trạng thái hiện trạng thái của thẻ đó; nhật ký
  dùng chung. Xem mục 5 về khi nào trạng thái về "Chờ".
- **Nhật ký**: `QPlainTextEdit` chỉ đọc, thấp (~6 dòng), dưới danh sách; mỗi dòng có giờ. Ghi: bắt đầu / xong từng
  video (số đoạn, thời gian chạy), lỗi (câu dễ hiểu + 1 dòng cuối của FFmpeg), dừng. Tối đa 500 dòng.
- **Dự kiến** (dưới cách cắt): tính ngay khi đổi cài đặt — với video đang chọn (hoặc video đầu): số đoạn và độ dài.
  Cách cắt gõ sai → chữ đỏ ngắn ("Mốc 00:75:00 sai") và khoá nút Bắt đầu.
- **Thanh dưới**: tóm tắt ("3 video · 51 đoạn dự kiến"), ⋯, Mở thư mục, nút chính **Bắt đầu chia** / **Bắt đầu xuất
  ảnh**; khi chạy đổi thành **Dừng** (`variant="stop"`) + thanh tổng `thinBar` có hiệu ứng mượt như Tải video.
- Màu / chữ dùng token `theme.py` và các QSS sẵn có (`segTrack`, `fieldLabel`, `pathBox`, `sectionToggle`,
  `thinBar`); không mã hex ngoài `theme.py`; không thêm `setStyleSheet`.

### 3. Thẻ "Chia đoạn" — cài đặt (nhớ hết trong `cut/split/*`)
Cách cắt là nhóm nút radio (chỉ một cách được chọn — ảnh tham khảo dùng ô tick nhưng thực chất chỉ chọn một).

| Cách | Ô nhập | Mặc định | Quy tắc |
|---|---|---|---|
| Chia thành N phần | số 2–999 | 2 | N đoạn bằng nhau; N lớn tới mức mỗi phần < 1 s → hạ N xuống ⌊thời lượng⌋ và dòng Dự kiến báo vàng *(quyết định của người làm thiết kế)* |
| Mỗi đoạn dài | hh:mm:ss | 00:00:30 | đoạn cuối dư giữ lại; bỏ nếu < 1 s |
| Ngẫu nhiên | A ~ B (hh:mm:ss) | 00:00:10 ~ 00:00:45 | mỗi đoạn dài ngẫu nhiên trong [A, B]; đoạn cuối < A thì **nhập vào đoạn trước** nếu tổng ≤ B, không thì giữ riêng (≥ 1 s); A > B → báo lỗi |
| Theo mốc | "00:01:15, 00:05:30, 12:00" | trống | cắt tại các mốc → (số mốc + 1) đoạn; mốc trùng / ngoài video bỏ qua (ghi nhật ký); tự sắp xếp |
| Theo khoảng | "00:01:10-00:01:45, 00:05:00-00:05:30" | trống | mỗi khoảng một đoạn, theo thứ tự gõ; khoảng chồng nhau vẫn cắt; khoảng vượt cuối video thì cắt tới hết |

- Định dạng thời gian nhận: `hh:mm:ss`, `mm:ss`, `ss`, có phần lẻ `.5`; phân cách bằng dấu phẩy, chấm phẩy hoặc xuống
  dòng; gạch nối `-` / `–` / `—` cho khoảng.
- **Ngẫu nhiên**: mỗi lần bấm Bắt đầu ra cách chia khác (mỗi video một bộ số riêng). *(quyết định của người làm thiết
  kế: không cần "hạt giống" cố định.)*
- **Chế độ xuất** (`Segmented`):
  - **Chính xác** (mặc định): mã hoá lại H.264 bằng `encoders.pick("h264", "auto", available)` +
    `encoders.encoder_args(enc, "high", gop)`, tiếng AAC 192k; cắt đúng giây (`-ss` trước `-i` + `-t`, FFmpeg giải
    mã chính xác). Card đồ hoạ nếu có, không có thì libx264.
  - **Nhanh**: `-c copy` — gần như tức thì, giữ nguyên chất lượng, có thể lệch tới khung khoá gần nhất (tooltip nói rõ).
    Chọn Nhanh → khoá Tỉ lệ khung về "Giữ nguyên" (mờ đi, tooltip "Đổi tỉ lệ cần chế độ Chính xác").
- **Tỉ lệ khung** (`Segmented`): Giữ nguyên (mặc định) · 9:16 · 16:9 · 1:1 · 4:5.
  **Khi đổi** (`Segmented`, chỉ bật khi tỉ lệ ≠ Giữ nguyên): Nền mờ (mặc định) · Viền đen · Cắt.
  - Kích thước ra: giữ cạnh dài của nguồn làm cạnh dài ra, làm tròn số chẵn; vd nguồn 1920×1080 → 9:16 = 1080×1920;
    1:1 = 1080×1080 (cạnh ngắn nguồn) *(quyết định của người làm thiết kế: không phóng to quá cạnh ngắn của nguồn
    với 1:1 / 4:5)*. Cụ thể: ra (W, H) sao cho W/H = tỉ lệ, max(W, H) = max(nguồn) với 9:16 / 16:9, = min(nguồn) với
    1:1 / 4:5.
  - Nền mờ: `split` → nền = scale phủ kín + crop + `gblur=sigma=30` (hạ độ phân giải trước khi làm mờ cho nhanh) ;
    hình chính = scale vừa khung; `overlay` giữa.
  - Viền đen: scale vừa khung + `pad` màu đen giữa.
  - Cắt: scale phủ kín + `crop` giữa.
  - Video xoay (điện thoại) dùng kích thước sau xoay mà `probe` đã tính.
- **Lưu vào**: thư mục nhớ trong `cut/folder`; mặc định `QStandardPaths.MoviesLocation / "KT Loop Station" /
  "Chia video"`. ☑ **Thư mục riêng mỗi video** (mặc định bật) → `<thư mục>/<tên gốc>/`.
- **Tên file**: `<tên gốc>_01.mp4`, `_02` … (số chữ số = đủ cho tổng số đoạn, tối thiểu 2). Đuôi `.mp4` khi Chính xác;
  khi Nhanh giữ đuôi gốc (`.mp4`, `.mov`, `.mkv` …) để `-c copy` không lỗi codec. Thư mục ra đã có file trùng tên →
  **không ghi đè**: thêm hậu tố ` (2)` vào tên thư mục riêng (khi bật thư mục riêng) hoặc vào tên file *(quyết định
  của người làm thiết kế)*.
- Tiếng: giữ tiếng gốc; video không có tiếng vẫn chạy.

### 4. Thẻ "Xuất ảnh" — cài đặt (nhớ trong `cut/frames/*`)
| Cách | Ô nhập | Mặc định | FFmpeg |
|---|---|---|---|
| Theo tổng số ảnh | số 1–9999 | 100 | lấy đều giữa từng khoảng: ảnh thứ k (k = 0…N−1) ở (k + 0,5) × D / N → `-ss D/(2N)` trước `-i` + `fps=N/D` + `-frames:v N` (D = thời lượng) |
| Mỗi N giây | số thực 0,1–3600 | 5,00 | `fps=1/N` |
| Mỗi N khung hình | số 1–100000 | 150 | `select='not(mod(n,N))'` + `-vsync vfr` |
| Theo chuyển động / đổi cảnh | mức thay đổi 1–100 % | 10 | `select='eq(n,0)+gt(scene,T)'` + `-vsync vfr`, **T = % / 100** (10 % → 0,10): khung khác khung trước ít nhất bấy nhiêu thì lấy ảnh — **số nhỏ = nhiều ảnh** (đã báo anh Khánh như vậy); luôn lấy ảnh đầu tiên |

- Định dạng ảnh (`Segmented`): **JPG** (mặc định, `-q:v 2`) · PNG.
- Kích thước ảnh = kích thước video (đã xoay đúng chiều). Không đổi tỉ lệ ở thẻ này.
- Tên ảnh: `<tên gốc>_0001.jpg` … (4 chữ số, đủ hơn thì 5). Thư mục giống thẻ Chia đoạn nhưng nhớ riêng
  (`cut/frames_folder`, mặc định `…/KT Loop Station/Xuất ảnh`), ☑ Thư mục riêng mỗi video (mặc định bật).
- Tiến độ: từ `out_time` của `-progress` so với thời lượng video.
- Trùng tên: như mục 3.

### 5. Chạy và dừng
- Lõi trong `loopstation/core/cutter.py` (không có Qt): parse thời gian, tính danh sách đoạn cho 5 cách, tính kích
  thước + chuỗi filter cho tỉ lệ, dựng tham số FFmpeg cho đoạn / ảnh, đặt tên file, ánh xạ độ nhạy. Hàm thuần → test
  không cần FFmpeg. Một hàm `split_video(runner, src, info, settings, folder, on_progress)` và
  `extract_frames(...)` chạy thật bằng `ffmpeg_tools.Runner`.
- Trang `loopstation/ui/cut_page.py`: luồng nền chạy lần lượt từng video (một video một lúc; trong video, các đoạn
  lần lượt). Tín hiệu Qt qua `_Bridge` như Tải video. Encoder: `MainWindow` gọi `cut_page.set_encoders(available)`
  khi dò xong (giống `download_page.set_encoders`).
- **Trong lúc chạy**: khoá đổi thẻ, khoá thẻ cài đặt và thêm / bớt video (thanh bên, trang khác vẫn dùng được).
- **Bắt đầu chạy những gì** *(quyết định của người làm thiết kế)*: các video đang tick mà trạng thái ở thẻ này chưa
  phải ✓. Nếu mọi video tick đều ✓ thì nút ghi **Chạy lại** và chạy lại tất cả (ra thư mục / tên mới theo quy tắc không
  ghi đè). Đổi bất kỳ cài đặt nào của thẻ → mọi dòng ✓ / lỗi / đã dừng của thẻ đó về "Chờ".
- **Dừng**: `runner.cancel()` → FFmpeg bị dừng ngay; file đang ghi dở bị xoá; video đang chạy về "Đã dừng
  (7/25 đoạn)". Video đã dừng khi chạy lại sẽ **xoá trước các file mà chính lượt dừng đó đã tạo** (app nhớ danh sách
  trong bộ nhớ, theo dòng — chỉ file do app vừa tạo, không đụng file khác) rồi chạy lại từ đầu vào đúng thư mục / tên
  cũ — không sót đoạn thừa dù cài đặt đã đổi *(quyết định của người làm thiết kế: không nối tiếp từng đoạn)*.
- Một đoạn lỗi → ghi nhật ký, đoạn sau chạy tiếp; video có đoạn lỗi kết thúc với trạng thái vàng "✓ 24/25 đoạn ·
  1 lỗi". File nguồn không đọc được → dòng đỏ, sang video sau.
- Hết chỗ trống ổ đĩa (`disk_free` < 500 MB) trước khi bắt đầu video → dừng lượt, báo.
- Xong lượt: thông báo nổi (`notice` như Tải video) "Xong: 3 video → 51 đoạn" và ☑ **Mở thư mục khi xong** (mặc định
  tắt, nhớ `cut/open_after`).
- Song song với Xuất file / Tải video được (không chặn); không chạy hai lượt cắt cùng lúc.

### 6. Test
- `tests/test_cutter.py`: parse thời gian (đúng / sai), 5 cách chia (biên: đoạn cuối < 1 s, ngẫu nhiên nhập đoạn
  cuối, mốc ngoài video, khoảng vượt cuối, N > thời lượng), kích thước ra cho các tỉ lệ (nguồn ngang / dọc / lẻ),
  chuỗi filter 3 kiểu, đặt tên + số chữ số + không ghi đè, ánh xạ độ nhạy, tham số FFmpeg 4 cách xuất ảnh.
- Test chạy thật bằng FFmpeg đi kèm trên video mẫu tạo bằng `testsrc` (vài giây): chia 3 phần ra đúng 3 file đúng độ
  dài (±0,1 s Chính xác); 9:16 nền mờ ra đúng kích thước; xuất 5 ảnh ra 5 file; Dừng giữa chừng không để file dở.
- `tests/test_cut_page.py` (offscreen, cô lập `KTLS_DATA_DIR` / `KTLS_SETTINGS_ORG`): thêm file, đổi thẻ, Dự kiến
  cập nhật, gõ sai khoá nút, chạy hết một lượt nhỏ ra file, Dừng; nút thanh bên + thẻ Bắt đầu mở đúng thẻ.
- `tests/test_theme_tokens.py` vẫn qua (không hex, không thêm `setStyleSheet`).

## Để người làm tự quyết
- Bố cục chi tiết, khoảng cách, chữ tooltip; biểu tượng (`scissors`, `image`) nếu chưa có thì vẽ thêm trong
  `icons.py` theo kiểu sẵn có.
- Tông màu 2 thẻ trang Bắt đầu.
- Giới hạn số video trong danh sách (không cần).
