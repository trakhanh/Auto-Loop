# KT Loop Station — Đặc tả yêu cầu

*By Khánh Trà*

Ứng dụng desktop Windows để ghép, loop video ngắn và loop nhạc thành video YouTube dài, dùng nội bộ công ty.

---

## 1. Quyết định đã chốt

| Hạng mục | Quyết định |
|---|---|
| Công nghệ | Python 3.12 + PySide6 (giao diện) + FFmpeg (xử lý), đóng gói kèm `ffmpeg.exe` |
| Hệ điều hành | Chỉ Windows 10/11 |
| Mục đích chính | Video YouTube dài (vài chục phút → 10 tiếng) |
| Video nguồn | MP4 tải từ Google Flow, mỗi clip 6–10s, thường cùng độ phân giải nhưng app phải chịu được clip khác nhau |
| Âm thanh gốc của clip | Người dùng chọn, **mặc định: tắt** |
| Số lần phát | Người dùng tự nhập cho từng clip: **tổng số lần phát** (0 = bỏ qua, 1 = phát một lần / không loop, 70 = phát 70 lần liền như video chill trên YouTube), có tuỳ chọn ngẫu nhiên |
| Độ dài tổng | 3 chế độ: thủ công / thời lượng mục tiêu / theo nhạc. Hai chế độ sau có 2 cách lấp đầy: **lặp cả chuỗi** hoặc **giãn số lần phát của clip được đánh dấu** |
| Chuyển cảnh | Người dùng chọn: cắt thẳng hoặc crossfade (giữa các lần loop và giữa các clip) |
| GPU | Máy nhân viên lẫn lộn NVIDIA / Intel / AMD → tự nhận diện, tự chuyển về CPU khi cần |

---

## 2. Nguyên tắc kỹ thuật cốt lõi

**Không bao giờ encode lại cùng một nội dung nhiều lần.**

```
Clip nguồn ──► Chuẩn hoá 1 lần (GPU) ──► Các "khối" video đã encode
                                          │
               Danh sách nối: [A1, U1×68, Z1, A2..., ...]
                                          │
                       Nối bằng stream copy (không encode) ──► video.mp4 (chỉ hình)
                                                                     │
Nhạc ──► Chuẩn âm lượng ──► Xếp lịch phát + crossfade ──► audio.m4a  ├──► Ghép ──► output.mp4
Âm gốc clip (nếu bật) ──► Theo đúng timeline video ──► trộn ────────┘
```

- **Chuẩn hoá:** đưa mọi clip về cùng độ phân giải, fps, pixel format, timebase, GOP đóng, keyframe ở frame đầu. Bắt buộc phải làm vì nối bằng stream copy đòi hỏi mọi khối giống nhau tuyệt đối. Mọi khối trong một lần render phải dùng cùng một encoder và cùng thông số.
- **Cache:** khối đã chuẩn hoá được lưu ở `%LOCALAPPDATA%\LoopStation\cache`, khoá theo (file + ngày sửa + kích thước + thông số xuất). Render lại cùng clip sẽ không phải encode lại.
- **Tốc độ dự kiến:** clip 8s loop 70 lần ≈ 9 phút video, nhưng chỉ encode khoảng 8–16s. Video 10 tiếng chủ yếu tốn thời gian ghi đĩa.

### 2.1 Crossfade giữa các lần loop (vẫn nhanh)

Với clip dài `L` và crossfade dài `d`, đặt `B` = đuôi `[L-d, L]` hoà vào đầu `[0, d]` (dài `d`). Cắt clip thành 3 khối, mỗi khối encode **một lần**:

| Khối | Nội dung | Độ dài |
|---|---|---|
| `A` (mở đầu) | `[0, L-d]` | L − d |
| `U` (lặp lại) | `B` + `[d, L-d]` | L − d |
| `Z` (kết thúc) | `B` + `[d, L]` | L |

Loop N lần = `A` + `U` × (N−2) + `Z`, tổng độ dài = N·L − (N−1)·d. Ràng buộc: `d ≤ L/2`, N ≥ 2.

### 2.2 Crossfade giữa hai clip khác nhau

Chỉ render riêng đoạn chuyển cảnh `d` giây (đuôi clip trước hoà vào đầu clip sau). Phần còn lại của hai clip vẫn dùng khối copy.

### 2.3 Âm thanh

Âm thanh luôn được dựng lại toàn bộ bằng CPU. Việc này rất nhẹ nên không ảnh hưởng tốc độ, và cho phép crossfade hay trộn tuỳ ý.

---

## 3. Giao diện

Cửa sổ chính có 3 tab: **Video**, **Nhạc**, **Xuất**. Thanh trên cùng gồm: Mới / Mở / Lưu project, tên project, **tổng thời lượng hiện tại** (cập nhật ngay khi chỉnh).

### 3.1 Tab Video

**Bảng clip** (kéo thả để đổi thứ tự, kéo file từ Explorer vào để thêm):

| Cột | Mô tả |
|---|---|
| ☑ | Bật/tắt clip |
| Ảnh nhỏ | Frame đầu của clip, bấm đúp để xem thử |
| Tên file, độ phân giải, fps, thời lượng | Đọc bằng ffprobe; cảnh báo vàng nếu khác thông số xuất |
| Số lần phát | `Cố định: N` hoặc `Ngẫu nhiên: từ … đến …`. 1 = không loop, 0 = bỏ qua |
| Tự giãn | ☑ = clip này được tăng/giảm số lần phát khi lấp đầy theo cách "Giãn clip đánh dấu" |
| Giữa các lần loop | Cắt / Crossfade `x` giây |
| Sang clip kế tiếp | Cắt / Crossfade `x` giây |
| Thời lượng sau loop | Tự tính |

**Thứ tự clip:** Theo danh sách / Xáo ngẫu nhiên. Mọi thứ ngẫu nhiên đều có **seed** (số mầm): cùng seed thì cùng kết quả, có nút 🎲 "Tạo lại". Kết quả ngẫu nhiên được hiển thị và khoá lại trước khi render, để thứ tự đã xem trước đúng với video xuất ra.

**Chế độ độ dài:**

Ví dụ với 6 clip dài 8 giây:

```
Bảng:  V1 ×70 | V2 ×1 | V3 ×1 | V4 ×70 | V5 ×1 | V6 ×70      → 1 "chuỗi" ≈ 28:24
Xuất:  [V1 V1 ... ×70][V2][V3][V4 ... ×70][V5][V6 ... ×70]   + nhạc chạy suốt bên dưới
```

1. **Thủ công:** phát đúng một chuỗi như trong bảng. Tổng = cộng các clip theo số lần phát đã nhập.
2. **Thời lượng mục tiêu:** nhập ví dụ `03:00:00`, rồi chọn **cách lấp đầy**:
   - **(B) Lặp cả chuỗi:** phát chuỗi V1→V6 rồi lại V1→V6… cho tới đủ thời lượng. Tuỳ chọn khi thứ tự hoặc số lần phát là ngẫu nhiên: ☑ "Xáo lại mỗi vòng" (mỗi vòng ra thứ tự / số lần khác nhau) hoặc giữ nguyên như vòng đầu.
   - **(C) Giãn clip đánh dấu:** chỉ phát một chuỗi. Clip không tick "Tự giãn" giữ nguyên số lần phát, thời gian còn thiếu chia đều cho các clip "Tự giãn" (làm tròn theo số lần nguyên). Ví dụ 3 tiếng, tick V1, V4, V6 → mỗi clip ≈ 450 lần.

   Cả hai cách đều có tuỳ chọn **"Kết thúc chính xác"**: cắt phần dư ở cuối cho đúng thời lượng và fade-out hình + tiếng. Không tick thì video dừng ở cuối lần phát gần nhất (dài hơn mục tiêu tối đa một clip).
3. **Theo nhạc:** thời lượng mục tiêu = tổng thời lượng playlist (sau crossfade), sau đó lấp đầy theo (B) hoặc (C) như chế độ 2.

Thanh trên cùng luôn hiển thị: thời lượng một chuỗi, số vòng (với cách B) và tổng thời lượng cuối cùng.

**Âm thanh gốc của clip:**

- Tắt *(mặc định)*
- Chỉ âm gốc (không dùng nhạc)
- Trộn với nhạc, chỉnh âm lượng % riêng cho âm gốc và cho nhạc

Có thể ghi đè riêng cho từng clip.

**Khung hình khác tỉ lệ:** Viền đen *(mặc định)* / Nền mờ / Cắt cho đầy khung / Kéo giãn.

**Xem thử chỗ nối:** render nhanh 6 giây quanh một chỗ nối để kiểm tra crossfade.

### 3.2 Tab Nhạc

- Thêm nhạc: chọn folder (tự quét `mp3, wav, flac, m4a, aac, ogg, opus`) hoặc kéo thả file.
- **Bảng bài:** ☑ bật/tắt, thứ tự (kéo thả), tên, thời lượng, số lần phát mỗi lượt (mặc định 1), nút nghe thử.
- **Chế độ phát:**
  - Theo thứ tự
  - Ngẫu nhiên (seed)
  - Ngẫu nhiên, không để một bài lặp lại liền nhau, kể cả ở chỗ playlist quay vòng
- **Lặp playlist:** lặp tới khi đủ độ dài video. Bài cuối bị cắt thì fade-out.
- **Crossfade giữa bài:** 0–10s. Có thể thêm khoảng lặng giữa bài thay cho crossfade.
- Fade-in đầu video, fade-out cuối video (số giây).
- **Chuẩn hoá âm lượng:** về −14 LUFS, true peak −1 dBTP (chuẩn YouTube). Phân tích 2 lượt cho từng bài, kết quả được cache.
- Xem trước **lịch phát:** danh sách bài kèm mốc thời gian bắt đầu.

### 3.3 Tab Xuất

- **Preset xuất** (mục 4), thư mục và tên file (mặc định `TênProject_YYYYMMDD_HHMM.mp4`).
- **Encoder:** Tự động *(mặc định)* / NVIDIA / Intel / AMD / CPU. Chỉ hiện các encoder đã kiểm tra là chạy được trên máy.
- **Chất lượng:** Cân bằng / Cao / Rất cao (dịch ra CQ hoặc bitrate theo từng encoder).
- **Kiểm tra trước khi render:**
  - Dung lượng ổ đĩa (ước tính file ra + cache + 10%)
  - Clip bị thiếu
  - Crossfade dài hơn giới hạn
- **Hàng đợi render:** thêm nhiều project rồi chạy lần lượt (để chạy qua đêm). Mỗi job có tiến trình %, tốc độ, ETA, nút Huỷ, nút xem log.
- **Xuất kèm:**
  - `*_tracklist.txt` dạng chapter YouTube (`00:00 Tên bài`). Tự kiểm tra luật YouTube: bắt đầu từ 00:00, ít nhất 3 mốc, mỗi mốc ≥ 10s.
  - `*_project.json`: bản sao cấu hình để render lại.
- Khi xong: thông báo Windows và nút "Mở thư mục".

---

## 4. Preset xuất

| Preset | Video | Âm thanh | Container |
|---|---|---|---|
| **H.264** *(mặc định)* | Tương thích nhất; độ phân giải và fps chọn riêng (mặc định 1080p, fps theo clip đầu) | AAC 48 kHz stereo (xem dưới) | MP4 + faststart |
| H.265/HEVC | 8-bit, nhẹ hơn ~40% | AAC 48 kHz stereo | MP4 |
| YouTube 4K (upscale) | H.265, 3840×2160 (~40 Mbps). YouTube cấp codec nén tốt hơn cho video 4K nên hình vẫn nét hơn dù nguồn 1080p | AAC 320 kbps | MP4 |
| Master dựng tiếp | ProRes 422 HQ, chỉ chạy CPU, file rất lớn | PCM 24-bit 48 kHz | MOV |
| Tuỳ chỉnh | Chọn codec, độ phân giải, fps, bitrate/CQ | Chọn codec, bitrate | — |

**Âm thanh (đo thực tế khi làm GĐ1):** bộ AAC tích hợp của ffmpeg chỉ chạy khoảng 16 lần thời gian thực, nên video 10 tiếng mất gần 40 phút chỉ để encode tiếng. Vì vậy mặc định dùng **AAC 192 kbps qua Media Foundation của Windows (`aac_mf`)**, nhanh hơn khoảng 10 lần. 192 kbps vẫn cao hơn mức YouTube phát lại (~128 kbps). Tuỳ chọn **AAC 320 kbps** vẫn có cho ai cần.

**Encoder theo GPU:**

| GPU | H.264 | H.265 | AV1 |
|---|---|---|---|
| NVIDIA (GTX 16xx / RTX) | `h264_nvenc` | `hevc_nvenc` | `av1_nvenc` (RTX 40+) |
| Intel (UHD 7xx / Arc) | `h264_qsv` | `hevc_qsv` | `av1_qsv` (Arc) |
| AMD (RX) | `h264_amf` | `hevc_amf` | `av1_amf` (RX 7000+) |
| Không GPU | `libx264` | `libx265` | `libsvtav1` |

**Nhận diện GPU:** khi mở app lần đầu, thử encode 1 giây video trống bằng từng encoder, rồi ghi lại encoder nào chạy được. Chỉ đọc danh sách encoder thì không đủ, vì driver cũ hay laptop tắt GPU vẫn liệt kê nhưng không chạy. Thứ tự ưu tiên: NVIDIA → Intel → AMD → CPU. Nếu đang render mà encoder GPU lỗi thì tự chạy lại bằng CPU và ghi chú vào log.

*Máy phát triển hiện tại có GTX 1660 Ti (NVENC: H.264, H.265, không có AV1) và Intel UHD 730 (QSV), dùng để thử cả hai đường.*

---

## 5. File project (`.lsproj`, JSON)

```json
{
  "version": 1,
  "name": "Lofi Rain 3h",
  "video": {
    "order": "list",              // list | shuffle
    "seed": 12345,
    "length_mode": "manual",      // manual | target | music
    "target_duration": "03:00:00",
    "fill": "repeat_sequence",    // repeat_sequence (B) | stretch_marked (C)
    "reshuffle_each_round": true,
    "exact_end": true,
    "fit": "letterbox",           // letterbox | blur | crop | stretch
    "source_audio": "off",        // off | only | mix
    "clips": [
      { "path": "D:/clips/rain1.mp4", "enabled": true,
        "plays": { "mode": "fixed", "count": 70 },   // random: { "mode": "random", "min": 50, "max": 80 }
        "stretch": true,
        "loop_crossfade": 0,          // 0 = cắt thẳng, hoặc số giây
        "next_crossfade": 1.5 }
    ]
  },
  "music": {
    "tracks": [ { "path": "D:/music/song1.mp3", "enabled": true, "plays": 1 } ],
    "order": "shuffle_no_repeat", "seed": 999,
    "crossfade": 3.0, "fade_in": 2.0, "fade_out": 5.0,
    "loudness": { "enabled": true, "lufs": -14, "true_peak": -1 }
  },
  "export": { "preset": "youtube_1080p_h264", "encoder": "auto", "quality": "high",
              "output_dir": "D:/out", "tracklist": true }
}
```

Đường dẫn file được lưu tương đối so với file project nếu nằm cùng ổ, để chép cả folder sang máy khác vẫn mở được.

---

## 6. Cấu trúc mã nguồn

```
LoopStation/
├─ app.py                  # điểm khởi chạy
├─ loopstation/
│  ├─ core/                # không phụ thuộc giao diện, kiểm thử được độc lập
│  │  ├─ project.py        # dataclass + đọc/ghi JSON
│  │  ├─ probe.py          # ffprobe: thời lượng, độ phân giải, fps, audio
│  │  ├─ planner.py        # tính timeline: loop, ngẫu nhiên, 3 chế độ độ dài, lịch nhạc
│  │  ├─ encoders.py       # nhận diện GPU, bảng tham số từng encoder
│  │  ├─ video_build.py    # chuẩn hoá, khối A/U/Z, chuyển cảnh, file nối
│  │  ├─ audio_build.py    # loudnorm, crossfade nhạc, trộn âm gốc
│  │  ├─ render.py         # chạy ffmpeg, đọc tiến trình, huỷ, dọn file tạm
│  │  └─ tracklist.py
│  └─ ui/                  # PySide6: main_window, video_tab, music_tab, export_tab
├─ bin/                    # ffmpeg.exe, ffprobe.exe (đóng gói kèm)
├─ tests/                  # pytest, có script tạo clip/nhạc giả bằng ffmpeg để thử
└─ SPEC.md
```

---

## 7. Trường hợp đặc biệt cần xử lý

- **Clip khác độ phân giải / fps / VFR:** chuẩn hoá về thông số xuất. Clip của Flow thường 24fps; nếu trộn 24 và 30fps thì đổi về fps của preset.
- **Clip có hoặc không có audio:** clip không có âm gốc thì chèn khoảng lặng cho đúng timeline.
- **Ràng buộc crossfade:** `d ≤ L/2`, nếu vượt thì giao diện báo đỏ. Loop = 1 thì bỏ qua "giữa các lần loop".
- **Tất cả clip bị tắt / loop = 0, hoặc playlist rỗng** khi bật nhạc: chặn render và báo rõ lý do.
- **Đường dẫn có dấu tiếng Việt, khoảng trắng:** truyền qua file danh sách UTF-8, không ghép vào chuỗi lệnh.
- **Huỷ giữa chừng:** dừng ffmpeg, xoá file dở, giữ lại cache.
- **Video rất dài:** bước faststart phải ghi lại cả file, nên ước tính thời gian và dung lượng cho bước này.

---

## 8. Lộ trình

| Giai đoạn | Nội dung |
|---|---|
| **GĐ1 — MVP** ✅ *(đã xong)* | Tab Video (loop cố định + ngẫu nhiên, cắt thẳng, 3 chế độ độ dài, 2 cách lấp đầy), tab Nhạc (crossfade, khoảng lặng, 3 kiểu thứ tự, chuẩn hoá âm lượng, lịch phát), trộn tiếng gốc, tab Xuất (YouTube 1080p H.264/HEVC, tự nhận GPU NVIDIA/Intel/AMD, tự chuyển CPU khi GPU lỗi, tiến trình + ETA, huỷ), lưu/mở dự án + tự lưu khi đóng, tracklist. Kèm các ý dễ dùng: quét thư mục (có thư mục con), sắp tên tự nhiên, đọc file nền có tiến trình, Chọn hết / Bỏ hết / Đảo chọn / Chỉ dòng đang bôi, phím Space và Delete, kéo thả đổi thứ tự, nút Trộn, bấm đúp để xem/nghe thử |
| **GĐ2** ✅ *(đã xong)* | Crossfade giữa các lần loop và giữa các clip (cột "Nối vòng lặp" / "Sang clip sau", vẫn nhanh nhờ encode riêng đoạn chuyển cảnh) · Xem thử chỗ nối · **Intro/outro** cố định kèm crossfade, giữ tiếng gốc · **Lớp tiếng nền** (mưa, lửa, sóng… tự loop, âm lượng từng lớp) · **Xuất riêng nhạc** theo thời lượng hoặc số lượt playlist (MP3 320/192, M4A, FLAC, WAV) kèm tracklist · **Hàng đợi xuất** (video + nhạc, chạy lần lượt, lưu lại khi đóng app, tự tránh trùng tên file) · **Ảnh tĩnh làm clip** (jpg/png/webp…, thời lượng mỗi lần phát chỉnh được) · Chọn **độ phân giải** (theo clip đầu / 720p / 1080p / 2K / 4K / dọc 9:16 / vuông) và **fps** (theo clip đầu / 24 / 25 / 30 / 50 / 60) · Giao diện tối hiện đại, **co giãn theo cửa sổ** (thanh bên thu gọn, cài đặt tự xếp xuống dưới, trang cuộn được), **ảnh nhỏ** của clip trong bảng, **thanh dòng thời gian** trực quan · Bộ mẫu test `Mau-Test/` + 2 dự án mẫu |
| **GĐ3** | ✅ Logo + icon (`assets/icon.ico`), trang Hướng dẫn trong app (F1) · Đóng gói (PyInstaller dạng thư mục + bộ cài Inno Setup), **chỉnh màu** theo preset (ấm, lạnh, vintage, điện ảnh…), **lớp phủ hiệu ứng** (mưa/tuyết nền đen hoà kiểu screen), **khung/watermark PNG**, cỡ chữ và giao diện tối, template dùng chung, kiểm tra cập nhật |

*Các mục in đậm ở GĐ2–GĐ3 được tham khảo từ app "GhepClipNhac" của đồng nghiệp. Lưu ý: chỉnh màu, lớp phủ và watermark buộc phải encode lại toàn bộ video, nên với video dài sẽ chậm hơn nhiều so với cách nối khối hiện tại. Cần áp chúng lên từng khối trước khi nối để vẫn giữ được tốc độ.*

**Ghi chú license:** bản FFmpeg "full build" là GPL. Dùng nội bộ trong công ty thì không vấn đề. Nếu sau này phát ra ngoài hoặc bán thì cần xem lại.

---

## 9. Quyết định mặc định (đã chốt theo bản nháp)

1. "Ngẫu nhiên" hỗ trợ cả **thứ tự clip ngẫu nhiên** và **số lần phát ngẫu nhiên** (nhập `50-80`).
2. Clip khác tỉ lệ: mặc định **viền đen**.
3. Preset mặc định: **1080p**.
4. Giao diện: **tiếng Việt**.
