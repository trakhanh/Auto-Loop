<img src="loopstation/ui/assets/logo-512.png" width="96" align="left" style="margin-right:12px">
# KT Loop Station

*By Khánh Trà*

<br clear="left">

Ứng dụng Windows ghép và loop các clip ngắn (ví dụ clip tạo bằng Google Flow) cùng playlist nhạc thành **video YouTube dài hàng giờ**: clip nền lặp 70 lần xen kẽ các cảnh, nhạc tự lặp theo độ dài video, thêm tiếng mưa / sóng / lửa… Xuất nhanh bằng card đồ hoạ NVIDIA / Intel / AMD, giao diện tiếng Việt.

<p align="center">
  <a href="https://github.com/trakhanh/Auto-Loop/releases/latest/download/KTLoopStation-Setup.exe">
    <img src="docs/download-button.svg" alt="Tải về KT Loop Station cho Windows" width="480">
  </a>
  <br>
  <sub>Bấm nút để tải bộ cài · <a href="https://github.com/trakhanh/Auto-Loop/releases">Xem các phiên bản cũ</a></sub>
</p>

## Cài đặt trong 3 bước

1. **Bấm nút "Tải về cho Windows"** ở trên. Trình duyệt tải về file `KTLoopStation-Setup.exe`.
2. **Mở file vừa tải** (bấm vào file ở góc trình duyệt, hoặc mở thư mục *Downloads*).
   Nếu Windows hiện khung xanh *"Windows protected your PC"*: bấm **More info** (Thông tin thêm) → **Run anyway** (Vẫn chạy).
3. Bấm **Next → Install → Finish**. Mở app bằng biểu tượng **KT Loop Station** trên màn hình hoặc trong menu Start.

> Không cần mật khẩu quản trị, không cần cài thêm gì. Đã có sẵn dự án mẫu để thử ngay ở màn hình **Bắt đầu**.

### Thông tin thêm

- Windows 10 / 11 64-bit. **Không cần quyền quản trị** (cài vào tài khoản đang dùng).
- **Đã kèm sẵn FFmpeg** và một bộ **dự án mẫu** để thử ngay. Không cần cài thêm gì.
- Card đồ hoạ NVIDIA / Intel / AMD giúp xuất nhanh hơn nhiều; không có card thì app tự dùng CPU.
- Windows có thể hiện cảnh báo *"Windows protected your PC"* vì bộ cài chưa ký số: bấm **More info → Run anyway**.
- Gỡ cài đặt: *Settings → Apps → KT Loop Station → Uninstall*. Dự án tự lưu, hàng đợi và bộ nhớ đệm nằm ở `%LOCALAPPDATA%\KTLoopStation`.

## Ảnh màn hình

| Màn hình Bắt đầu | Trang Video |
|---|---|
| ![Bắt đầu](docs/screenshots/01-bat-dau.png) | ![Video](docs/screenshots/02-video.png) |
| **Trang Nhạc + Bảng trộn âm** | **Trang Xuất** |
| ![Nhạc](docs/screenshots/03-nhac-bang-tron-am.png) | ![Xuất](docs/screenshots/04-xuat.png) |

![Xuất hàng loạt](docs/screenshots/05-hang-loat.png)

## Làm được gì

**Ba kiểu sản phẩm** (chọn ở thanh trên cùng):

| Kiểu | Kết quả |
|---|---|
| **Video có nhạc** | `.mp4`: clip loop + playlist nhạc tự lặp theo độ dài video |
| **Chỉ video** | `.mp4`: chỉ loop clip, giữ tiếng gốc và / hoặc thêm tiếng nền (mưa, sóng…) |
| **Chỉ nhạc** | `.mp3 / .m4a / .flac / .wav`: playlist lặp đủ thời lượng, xuất được nhiều bản khác thứ tự; hoặc chỉ tiếng nền (ASMR, white noise) |

**Video**
- Số lần phát mỗi clip: `70` lần, `50-80` ngẫu nhiên, hoặc theo thời lượng `10p` / `1:30:00`.
- **Xen kẽ clip nền** tự động theo tên file: `loop…` là nền; `2_…`, `3_…` là các cảnh. Có mẫu dựng sẵn, lặp cả mẫu N lượt.
- Cắt lấy đoạn giữa clip, crossfade giữa các lần loop / giữa các cảnh, Intro / Outro cố định.
- **Màu & Logo**: bộ màu có sẵn (ấm, lạnh, điện ảnh, đen trắng…) và đóng logo PNG.
- Clip khác tỉ lệ: viền đen / nền mờ / cắt cho đầy khung.

**Nhạc & âm thanh**
- Playlist theo thứ tự hoặc ngẫu nhiên không lặp bài liền nhau; ghim bài luôn có trong file.
- Chuẩn hoá độ to về -14 LUFS (chuẩn YouTube), crossfade giữa bài, to dần / nhỏ dần.
- **Thư viện tiếng nền có sẵn** do app tự tạo: mưa rào, mưa hiên nhà, sóng biển, gió, lửa củi, white / pink / brown noise. Chỗ lặp được hoà mượt.
- **Bảng trộn âm** dùng chung cả 3 kiểu: âm lượng nhạc, tiếng gốc clip và từng lớp tiếng nền, cộng âm lượng riêng từng bài. Có nút **Nghe thử 20 giây**; đang nghe mà kéo thanh là nghe đổi ngay.

**Xuất**
- Mã hoá bằng NVENC / Quick Sync / AMF hoặc CPU. Khối giống nhau chỉ mã hoá một lần rồi ghép, nên video 10 tiếng vẫn nhanh.
- Dự đoán dung lượng trước khi xuất; giới hạn theo bitrate hoặc theo dung lượng tối đa (GB).
- File kèm: tracklist (dán làm YouTube Chapters), mốc thời gian cho editor (`.txt / .csv / .srt` và marker DaVinci `.edl`), bản sao dự án.
- **Hàng đợi** chạy nhiều dự án liền nhau (giữ máy không ngủ, có thể tự tắt máy khi xong).
- **Xuất hàng loạt theo thư mục**: mỗi thư mục con thành một video. Có chỉnh thứ tự cảnh và âm lượng riêng từng video, nghe thử từng dòng.

Hướng dẫn chi tiết từng chức năng có ngay trong app: **Hướng dẫn** ở thanh bên hoặc phím **F1**.

## Dùng nhanh

1. **Video**: kéo thả clip hoặc cả thư mục vào bảng, đặt số lần phát (có clip `loop…` thì bấm **Xen kẽ clip nền**).
2. **Nhạc**: kéo thả bài nhạc; nhạc tự lặp theo độ dài video. Thêm tiếng nền, chỉnh **Bảng trộn âm** rồi bấm **Nghe thử 20 giây**.
3. **Xuất**: chọn thư mục lưu → **Bắt đầu xuất**, hoặc **Thêm vào hàng đợi** để xuất nhiều video liền nhau.

Muốn thử ngay: màn hình **Bắt đầu** → *Mẫu: Loop 70 lần* hoặc *Mẫu: 3 tiếng*.

---

## Dành cho người phát triển

### Chạy từ mã nguồn

Cần **Python 3.12+** và **FFmpeg 7+** (đặt `ffmpeg.exe`, `ffprobe.exe` trong `PATH` hoặc trong thư mục `bin\` cạnh `app.py`).

Bấm đúp `run.bat` (lần đầu tự tạo `.venv` và cài PySide6), hoặc:

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

### Kiểm thử

```bash
python -m pytest -q tests
```

Các script kiểm thử khác (đều dùng thư mục dữ liệu riêng, không đụng dữ liệu thật):

| Lệnh | Việc |
|---|---|
| `python tests/render_check.py <thư_mục>` | Xuất thật 14 kịch bản rồi kiểm tra bằng ffprobe |
| `python tests/ui_smoke.py <thư_mục>` | Chạy khắp giao diện (không hiện cửa sổ), bắt lỗi ngầm |
| `python tests/batch_volume_check.py <thư_mục>` | Kiểm tra âm lượng / nghe thử trong Xuất hàng loạt |
| `python tests/make_test_pack.py` | Tạo lại bộ mẫu `Mau-Test` (cần `numpy`) |
| `python tests/make_samples.py` | Tạo lại clip / nhạc giả trong `samples/` |
| `python tests/make_screenshots.py` | Chụp lại ảnh cho README |

### Cấu trúc

```
app.py                  khởi động (màn hình chờ, chỉ mở 1 cửa sổ, ghi lỗi bất ngờ)
loopstation/core/       xử lý: lập kế hoạch phát, dựng khối video / âm thanh, xuất, hàng đợi, hàng loạt…
loopstation/ui/         giao diện PySide6 (các trang, Bảng trộn âm, hộp thoại)
tests/                  kiểm thử + script kiểm tra / tạo mẫu
Mau-Test/, samples/     media mẫu do script tự tạo (đi kèm bộ cài)
SPEC.md                 đặc tả chi tiết
```

## Giấy phép

Mã nguồn © Khánh Trà. Bộ cài kèm **FFmpeg** (bản dựng của gyan.dev, giấy phép GPL v3, xem `bin\FFmpeg-LICENSE.txt` sau khi cài).
