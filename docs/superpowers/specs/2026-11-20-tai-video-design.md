# Trang "Tải video" (yt-dlp)

Ngày 2026-11-20 · anh Khánh chốt: chỉ lưu vào thư mục (tham khảo / đăng lại); tải cả link lẻ lẫn danh sách phát /
kênh; có đăng nhập từ trình duyệt; người dùng tự chọn chất lượng; cài công cụ tải khi dùng lần đầu (Cách 1).
Các điểm ghi *(quyết định của người làm thiết kế)* là đề xuất của Claude, anh Khánh có thể sửa.

## Vì sao
Nhân viên cần lấy video từ Bilibili, YouTube, TikTok, X, Facebook, Instagram… về máy để **tham khảo hoặc đăng lại**.
Hiện phải dùng web tải lậu / phần mềm ngoài. Gộp vào KT Loop Station bằng [yt-dlp](https://github.com/yt-dlp/yt-dlp)
(công cụ tải mã nguồn mở, hỗ trợ hàng nghìn trang).

File tải về **chỉ lưu vào thư mục**. Không tự đưa vào bảng clip, playlist hay dự án.

## Mục tiêu
- Dán một hoặc nhiều link (mỗi dòng một link), xem trước tên / ảnh nhỏ / thời lượng, chọn rồi mới tải.
- Link danh sách phát / kênh mở thành một nhóm video có ô tick; mặc định chỉ tick **50 video đầu** (kênh: mới nhất).
- Tải lần lượt, tiến độ riêng từng video; video lỗi chỉ báo đỏ dòng đó (lý do dễ hiểu), video khác tải tiếp.
- Người dùng tự chọn chất lượng (mặc định 1080p mở được mọi phần mềm dựng; có Cao nhất 2K/4K và 720p), luôn ra **MP4**.
- Đăng nhập từ trình duyệt cho trang bắt đăng nhập (Facebook, Instagram, đôi khi X): lựa chọn nhỏ, **mặc định tắt**.
- Công cụ tải (yt-dlp + Deno) luôn mới mà không phải phát hành lại app.

## Không làm (anti-goal)
- Không tự thêm file tải về vào bảng clip / playlist / dự án; không tự đổi gì trong dự án đang mở.
- Không tải ngầm: chỉ tải khi người dùng bấm **Tải đã chọn**.
- Không làm "chế độ đơn giản / nâng cao" hay tách hai chế độ "tải lẻ / tải kênh" — một ô dán link cho mọi trường hợp.
- Không làm bộ cài nặng thêm (giữ ~195 MB).
- Không thêm chữ dài lên giao diện (phản hồi "rối, nhiều chữ" của 2026-11-18): giải thích đưa vào chú thích (tooltip)
  và trang Hướng dẫn.
- Không làm: chỉ tải tiếng (MP3), phụ đề, chọn định dạng thủ công, hẹn giờ tải, tải song song nhiều video.

## Lưu ý pháp lý (ghi để anh nắm, không chặn trong app)
Chỉ nên tải nội dung công ty có quyền dùng (video của mình, nội dung cho phép dùng lại, đã mua bản quyền). Tải video
người khác để đăng lại có thể vi phạm điều khoản nền tảng và bị gậy bản quyền YouTube. Trang Hướng dẫn có một dòng
nhắc; app không chặn.

## Các cách đã cân nhắc
1. **Tải công cụ về khi dùng lần đầu (chọn).** yt-dlp.exe + Deno lấy từ trang phát hành chính thức (GitHub), kiểm tra
   SHA-256, cất trong thư mục dữ liệu app; tự cập nhật. Bộ cài không đổi; yt-dlp luôn mới. Cần mạng lúc cài lần đầu
   (máy đi tải video thì đằng nào cũng có mạng).
2. Gói sẵn yt-dlp + Deno trong bộ cài — cài xong dùng ngay, nhưng mọi nhân viên phải tải thêm ~45–60 MB và bản gói kèm
   vẫn cũ đi sau vài tuần, nên vẫn cần cơ chế cập nhật của cách 1.
3. Nhúng thư viện Python `yt_dlp` vào app bằng PyInstaller — nhẹ nhất (~3 MB) nhưng chỉ cập nhật được theo bản app
   (các trang đổi cách chặn liên tục → hay lỗi giữa hai lần phát hành), vẫn cần Deno, và file spec đang loại bớt
   module chuẩn (`unittest`, …) dễ gây lỗi khó lần.

## Thiết kế

### 1. Vị trí trong app
- **Một trang mới trong `MainWindow.stack`** (chỉ số `DOWNLOAD_PAGE = 6`, sau trang Bắt đầu = 5), không phải hộp
  thoại: tải lâu nên người dùng phải chuyển sang trang khác làm việc tiếp trong lúc tải.
- Thanh bên, mục **Công cụ**: thêm nút **"Tải video"** (biểu tượng `download`), đặt đầu nhóm (trên "Xuất hàng loạt…").
  Nút này `checkable`, thuộc `self.nav` (id 6) để thanh trượt chọn trang chạy tới. Khi đang tải: chữ trên nút kèm số,
  vd "Tải video (2/10)" — cùng cách `_update_nav_badges` ghi "Xuất file (3 chờ)".
- Trang **Bắt đầu**: thêm thẻ công cụ `("download", "download", <tone>, "Tải video", …)` vào `CARDS` (không vào
  `MAIN_KEYS`); `_home_choice("download")` → `go_to(DOWNLOAD_PAGE)`. Nhãn "MỚI" như thẻ Lọc tạp âm, tắt sau lần mở đầu
  (`new/download_seen`).
- Ở trang này: ẩn dòng thời gian (timeline), ẩn trình phát bên phải và thanh các bước (StepGuide) — xử lý như trang
  Cài đặt / Hướng dẫn.

### 2. Bố cục trang

```
┌ Tải video ────────────────────────────────────────────────────────────┐
│ [ Dán một hoặc nhiều link (mỗi dòng một link)…                ] [Đọc link] │
│                                                                       │
│ ☑ [ảnh] Tên video A               TikTok    0:45   Chờ                │
│ ☑ [ảnh] Tên video B               YouTube  12:10   ▓▓▓▓░░ 60% · 3 MB/s │
│ ☐ [ảnh] Tên video C               X         1:02   ✓ Đã có            │
│ ▾ Kênh XYZ — 248 video   (☑ 50 mới nhất · Hiện thêm 50)               │
│     ☑ [ảnh] …                                                         │
│ ✕ [ảnh] Tên video D               Facebook  —      Cần đăng nhập ⓘ    │
│                                                                       │
│ Lưu vào: D:\Tai-video [Đổi]  Chất lượng: 1080p ▾  Đăng nhập: Không ▾  [Tải đã chọn] [Mở thư mục] │
│ Công cụ tải: yt-dlp 2026.11.xx                                        │
└───────────────────────────────────────────────────────────────────────┘
```

- **Ô dán link** nhiều dòng; link trùng / dòng không phải link bị bỏ qua (báo gọn một dòng). Ctrl+V khi đang ở trang
  mà ô không có tiêu điểm cũng dán vào ô. **Đọc link** chạy nền, mỗi link thành một dòng (hoặc một nhóm) trong danh
  sách; lỗi đọc link → dòng đỏ với lý do.
- **Danh sách**: ô tick, ảnh nhỏ, tên, nền tảng, thời lượng, trạng thái (Chờ / % + tốc độ / Đang ghép / ✓ Xong /
  ✓ Đã có / lỗi). Chuột phải: Bỏ khỏi danh sách · Thử lại · Mở thư mục chứa file · Chép link. Nút **Xoá danh sách**
  (chỉ xoá dòng, không xoá file) đặt trong menu ⋯ để đỡ một nút.
- **Nhóm danh sách phát / kênh**: tiêu đề nhóm có ô tick tổng, số video, mặc định tick 50 video đầu; **Hiện thêm 50**
  tải thêm mục (không đọc hết cả kênh vài nghìn video một lúc).
- **Lưu vào**: thư mục chọn một lần, nhớ trong `QSettings` (`download/folder`); mặc định `Videos\KT Loop Station`
  của người dùng (`QStandardPaths.MoviesLocation`). Thư mục không ghi được → báo và bắt chọn lại.
- **Chất lượng ▾**: 1080p (mặc định lần đầu) · Cao nhất (2K/4K) · 720p — nhớ lựa chọn trong `download/quality`; áp
  cho các video tải sau khi đổi (video đang tải giữ nguyên). Chi tiết ở mục 4.
- **Đăng nhập ▾**: Không (mặc định) · Firefox · Edge · Chrome · File đăng nhập (cookies.txt)… — nhớ trong
  `download/login`. Chú thích nói Firefox chắc chắn nhất; Chrome / Edge trên Windows hay chặn, khi đó dùng file
  đăng nhập (trang Hướng dẫn có các bước xuất file).
- **Tải đã chọn** → tải lần lượt các dòng đang tick và chưa xong. Trong lúc tải nút đổi thành **Dừng** (dừng video
  đang tải, giữ hàng chờ). **Mở thư mục** mở thư mục lưu.
- Dòng **Công cụ tải** nhỏ, mờ ở chân trang: phiên bản; khi vừa tự cập nhật: "Đã cập nhật công cụ tải lên bản …".
- Màu, chữ dùng token `theme.py`; không mã hex trực tiếp; không thêm `setStyleSheet` (giới hạn 3 lần trong
  `loopstation/ui` ngoài theme.py).

### 3. Cài công cụ lần đầu và tự cập nhật (`loopstation/core/dl_tools.py`)
- Công cụ cất ở `ffmpeg_tools.data_dir() / "tools"` (`yt-dlp.exe`, `deno.exe`) — test dùng `KTLS_DATA_DIR` nên
  không đụng dữ liệu thật.
- Chưa có công cụ → trang hiện thẻ trống: "Cần cài công cụ tải (~65 MB, một lần)" + nút **Cài công cụ tải**, thanh
  tiến độ, Huỷ. Ô dán link vẫn dán được; Đọc link / Tải bị khoá tới khi cài xong.
- Nguồn:
  - yt-dlp: GitHub API kho **nightly** `repos/yt-dlp/yt-dlp-nightly-builds/releases/latest`, tài sản `yt-dlp.exe`; SHA-256 lấy từ trường `digest`
    của tài sản, dự phòng file `SHA2-256SUMS` trong cùng bản phát hành.
  - Deno: `repos/denoland/deno/releases/latest`, tài sản `deno-x86_64-pc-windows-msvc.zip` (+ `.sha256sum`); giải
    nén lấy `deno.exe`.
  - Chỉ chấp nhận link GitHub (cùng danh sách `_ALLOWED` của `updater.py`); sai SHA / sai cỡ → xoá file tải dở, báo
    lỗi. Ghi file tạm `.part` rồi đổi tên.
- **Vì sao nightly** *(quyết định của người làm thiết kế)*: yt-dlp khuyên người dùng thường dùng bản nightly vì bản
  sửa lỗi trang chặn ra trong vài ngày, còn bản stable có khi cách nhau vài tuần — kiểm tra hằng ngày chỉ có ích
  với nightly.
- **Tự cập nhật**: khi mở trang Tải video, tối đa một lần mỗi ngày (`download/tools_checked`), kiểm tra bản mới ở nền.
  yt-dlp: mỗi ngày; Deno: mỗi 7 ngày. Có bản mới **và không có video nào đang tải** → tải về, thay file, ghi dòng
  "Đã cập nhật công cụ tải lên bản …" ở chân trang. Đang tải → để lần sau. Lỗi mạng khi kiểm tra → im lặng.
  Việc này chỉ thay công cụ, không đổi lựa chọn hay file của người dùng.
- Một video lỗi kiểu "trang chặn / không đọc được" mà công cụ chưa kiểm tra hôm nay → kiểm tra bản mới ngay, có bản
  mới thì cập nhật rồi gợi ý "Thử lại".
- Khi `updater.enabled()` là False (test / offscreen / `KTLS_NO_UPDATE`) thì không gọi mạng.
- Cài đặt → Giới thiệu (hoặc nhóm gần đó): một dòng phiên bản công cụ tải + nút **Kiểm tra bản mới** + **Gỡ công cụ
  tải** (xoá thư mục tools).

### 4. Chạy yt-dlp (`loopstation/core/downloader.py`)
yt-dlp chạy như tiến trình riêng (giống FFmpeg), gắn vào job "tắt app là tắt theo" (`ffmpeg_tools._attach`), không
hiện cửa sổ đen (`CREATE_NO_WINDOW`).

**Đọc link** — `yt-dlp -J --flat-playlist --playlist-end N <link>` (N = 50, "Hiện thêm" tăng `--playlist-start/end`).
Kết quả JSON → `Item(url, id, title, platform, duration, thumbnail)` hoặc `Group(title, count, items)`. Link kênh
YouTube dạng `/@ten` (trả về các thẻ Videos / Shorts / Live) → đọc thẻ **Videos**; người làm tự xử lý tương tự cho
nền tảng khác nếu gặp. Ảnh nhỏ tải nền, nhỏ, lưu `cache_dir("dlthumbs")` (thêm vào `CACHE_PARTS`).

**Tải** — các tham số chính:
- `--ffmpeg-location <bin của app>` (dùng `ffmpeg_tools.ffmpeg()`), `--js-runtimes deno:<tools\deno.exe>`.
- Chất lượng theo ô **Chất lượng ▾** (anh Khánh: "cho người dùng tự chọn"); luôn ghép ra MP4
  (`--merge-output-format mp4`), không encode lại:
  - **1080p — mở được mọi phần mềm** (mặc định lần đầu): tối đa 1080p, ưu tiên H.264 + AAC
    (`-S "res:1080,vcodec:h264,acodec:aac"`).
  - **Cao nhất (2K/4K)**: độ phân giải cao nhất, cùng độ phân giải thì ưu tiên H.264 (`-S "res,vcodec:h264,acodec:aac"`).
    YouTube trên 1080p chỉ có VP9/AV1 → chú thích của lựa chọn nói Premiere cũ / CapCut có thể không mở được.
  - **720p — file nhẹ**: `-S "res:720,vcodec:h264,acodec:aac"`.
  - Chung: `-f "bv*+ba/b"`. Khi xong, cột trạng thái ghi codec nếu không phải H.264 (vd "✓ Xong · AV1").
- Tên file: `%(extractor_key)s - %(title).150B [%(id)s].%(ext)s`, `--windows-filenames`, `--no-mtime`.
- Không tải trùng: file có cùng `[id]` đã nằm trong thư mục lưu → dòng "✓ Đã có", bỏ tick, không chạy yt-dlp.
- Tiến độ: `--newline --progress-template` có tiền tố riêng (vd `KTLS|%(progress.downloaded_bytes)s|…`) để tách dòng
  tiến độ khỏi log; các bước ghép (`[Merger]`) hiện "Đang ghép…".
- Đăng nhập: `--cookies-from-browser firefox|edge|chrome` hoặc `--cookies <file>` theo lựa chọn.
- `--no-playlist` khi tải từng video đã tách từ nhóm.
- **Dừng** *(quyết định của người làm thiết kế)*: dừng cả lượt tải (nút trở lại "Tải đã chọn"), kết thúc tiến trình,
  xoá file `.part` / mảnh dở của video đang tải; video đó về "Chờ", vẫn tick — bấm Tải đã chọn là tải lại từ đầu
  video đó. Muốn bỏ một video thì bỏ tick / Bỏ khỏi danh sách.

**Lỗi → câu dễ hiểu** (bảng so khớp chuỗi stderr, có test): cần đăng nhập / "confirm you're not a bot" → "Cần đăng
nhập — chọn Đăng nhập ▾"; riêng tư / đã xoá / unavailable → "Video riêng tư hoặc đã bị xoá"; chặn theo quốc gia →
"Bị chặn ở Việt Nam"; 403 / không đọc được → "Trang chặn tải — đang thử cập nhật công cụ"; link không hỗ trợ → "Link
này chưa hỗ trợ"; không đọc được cookie trình duyệt → "Không lấy được đăng nhập từ <trình duyệt> — thử Firefox hoặc
file đăng nhập"; hết chỗ ổ đĩa → "Ổ đĩa hết chỗ". Còn lại: "Lỗi tải" + chú thích (ⓘ) chứa vài dòng cuối stderr.

### 5. Hàng chờ và tắt app giữa chừng
- Danh sách (link, id, tên, nền tảng, trạng thái, tick, nhóm) lưu `data_dir()/downloads.json` mỗi khi đổi.
- Tắt app khi đang tải → hỏi xác nhận như khi đang xuất video. Mở lại app mà còn video chưa xong trong lúc đang tải
  → hỏi "Còn N video đang tải dở — tải tiếp?" (giống hàng đợi xuất `queue/was_running`). Không tự tải tiếp khi chưa hỏi.
- Mở app bình thường: danh sách cũ hiện lại (dòng đã xong vẫn giữ để bấm Mở thư mục), tới khi người dùng xoá.

### 5b. Giữ máy thức và "Tắt máy khi xong" *(quyết định của người làm thiết kế)*
- Đang tải → giữ máy không ngủ (`power.keep_awake`, như khi xuất video); hết tải thì nhả (không nhả khi hàng đợi
  xuất vẫn đang chạy và ngược lại).
- Tuỳ chọn "Tắt máy khi chạy xong hàng đợi" vẫn chỉ gắn với hàng đợi xuất. Nhưng hàng đợi xuất xong mà còn đang tải
  video thì **đếm ngược tắt máy chờ tới khi tải xong** (không cắt ngang, không mất file). Tải video một mình không
  bao giờ tự tắt máy.

### 6. Hướng dẫn
Trang Hướng dẫn thêm mục "Tải video": dán link, chọn, tải; đăng nhập (xuất file cookies.txt từ trình duyệt bằng
tiện ích, các bước ngắn); một dòng nhắc bản quyền; công cụ tự cập nhật.

## Để người làm tự quyết
Câu chữ cụ thể; biểu tượng / tông màu thẻ; cách vẽ dòng danh sách (QTreeWidget hay QListView + delegate) miễn
mượt với vài trăm dòng; giá trị cụ thể của `--progress-template`; cách nhận diện link kênh của từng nền tảng ngoài
YouTube; vị trí nút Kiểm tra bản mới / Gỡ trong Cài đặt.

## Rủi ro đã biết
- Các trang đổi cách chặn liên tục → có lúc tải lỗi tới khi yt-dlp ra bản sửa (thường vài ngày). Tự cập nhật hằng
  ngày giảm thời gian lỗi, không xoá được hẳn.
- Chrome / Edge trên Windows mã hoá đăng nhập kiểu mới → `--cookies-from-browser chrome` hay thất bại; Firefox và
  file cookies.txt là đường chắc chắn.
- Deno ~45 MB nén / ~110 MB sau giải nén trong `%LOCALAPPDATA%` — chỉ máy nào cài công cụ tải mới tốn.
- Phần mềm diệt virus đôi khi nghi `yt-dlp.exe` (đóng gói PyInstaller); nếu bị chặn, báo "Công cụ tải bị phần mềm
  diệt virus chặn" thay vì lỗi khó hiểu.

## Kiểm tra
- Test pytest không gọi mạng (giả lập HTTP / tiến trình): đọc JSON `-J` (video lẻ, danh sách phát, kênh có thẻ),
  dựng tham số tải (chất lượng, cookies, tên file, ffmpeg, deno), tách dòng tiến độ, bảng lỗi → câu tiếng Việt,
  không tải trùng theo `[id]`, cài công cụ (đúng SHA → đặt file; sai SHA / link lạ → từ chối, không để lại file),
  không cập nhật khi đang tải, lưu / khôi phục `downloads.json`.
- Test giao diện offscreen: trang có trong `stack`, nút thanh bên + thẻ trang Bắt đầu đi tới trang, khoá Đọc link /
  Tải khi chưa có công cụ, `layout_audit` / `ui_smoke` vẫn qua, lint token màu + giới hạn setStyleSheet.
- Kiểm tra tay có mạng (không chạy trong pytest): script `tests/download_check.py` tải một video ngắn công khai mỗi
  nền tảng vào thư mục tạm.
- Mọi test chạy cô lập: `KTLS_DATA_DIR` thư mục tạm, `KTLS_SETTINGS_ORG=KTLoopStation-Test`, `KTLS_NO_UPDATE=1`,
  `QT_QPA_PLATFORM=offscreen`.
