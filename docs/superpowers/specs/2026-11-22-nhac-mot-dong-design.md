# Nhạc chạy từ clip nào — gom về một dòng

Ngày 2026-11-22 · anh Khánh chọn hướng "Một dòng chọn".

## Vì sao
Góp ý của anh Khánh: "phần ghép nhạc chạy từ clip nào… có cách nào làm dễ hơn không… chỉnh trong kia thì nhiều tính
năng quá". Bản 1.9.6 có tới 7 cách chỉnh cùng một việc: ô Nhạc từng clip (Tiếp tục / Không nhạc / Bắt đầu bằng bài),
Nhạc vào lúc, Chọn clip…, kéo mép đoạn nhạc, chuột phải khối clip, Alt + quét. Rối, khó nhớ.

## Mục tiêu
- Một chỗ duy nhất, đọc là hiểu: **♪ Nhạc chạy từ clip [5 · Loop1 ▾] tới [hết ▾] · bài đầu [Bài 1 ▾]**.
- Trên dòng thời gian chỉ một tay nắm **♪** để kéo đổi clip bắt đầu (bắt vào ranh giới clip).
- Giữ **Đoạn nghe** (bỏ đầu / bỏ cuối từng bài, trang Nhạc) — việc khác: chỉnh bài, không chỉnh chỗ.

## Không làm
- Nhạc ngắt quãng (clip 2–3 rồi 7–8) — anh chấp nhận bỏ để đổi lấy đơn giản.
- Không thêm chế độ ẩn / hiện tính năng.

## Cách đã cân nhắc
1. **Một dòng chọn (chọn)** — gọn nhất, đủ cho việc hay làm (nhạc vào từ clip X, bài đầu là bài Y).
2. Chỉ cột ♪ trong bảng — vẫn làm được ngắt quãng nhưng phải tick từng dòng.
3. Cả hai — vẫn hai chỗ chỉnh, chưa đủ gọn.

## Thiết kế
- **"Clip N" = lần phát thứ N trên dòng thời gian** (đếm theo khối trên làn CLIP, kể cả khi bảng lặp cả chuỗi), không
  phải dòng N của bảng. Bảng 10 clip phát một lần thì hai cách đếm trùng nhau; bảng 5 clip lặp nhiều vòng thì nhạc vào
  một lần ở lần phát thứ N rồi chạy luôn (không lặp lại mỗi vòng). *(Em tự quyết — anh xem lại.)*
- Ô chọn liệt kê các lần phát kèm mốc giờ: "5 · Loop1 · 0:40". Bảng lặp dài: liệt kê 60 lần phát đầu; xa hơn thì
  kéo tay nắm ♪ trên dòng thời gian.
- "tới [hết ▾]": hết video, hoặc hết clip M (nhạc nhỏ dần rồi tắt ở cuối clip M).
- "bài đầu [Bài 1 ▾]": bài phát đầu tiên khi nhạc vào; mặc định "theo playlist".
- Lưu trong dự án: `MusicSettings.start_clip` / `end_clip` (lần phát, 0 = đầu / hết) + `first_track` (đường dẫn bài).
  Bên trong quy về mốc giờ (đã có sẵn `start_at` + lịch nhạc theo đoạn `plan_music_windows`).
- Vị trí: dòng nằm ngay trên dòng thời gian (dải đáy, thấy ở mọi trang), không chiếm chỗ bảng clip.
- **Bỏ khỏi giao diện:** cột Nhạc trong bảng clip, ô "Nhạc vào lúc", nút "Chọn clip…" và hộp chọn, kéo mép đoạn nhạc,
  các mục nhạc trong menu chuột phải khối clip, Alt + quét.
- **Dự án cũ (1.9.6–2.0.1) đã đặt nhạc theo từng clip:** khi mở, quy về một dòng (từ lần phát đầu tiên có nhạc tới lần
  phát cuối có nhạc, bài đầu = bài đã chọn nếu có). Nếu trước đó nhạc ngắt quãng thì báo một dòng "đã gộp nhạc ngắt
  quãng thành một đoạn" để anh biết, không đổi ngầm.

## Kiểm tra
Test mới cho: lịch nhạc từ lần phát N (cả bảng lặp cả chuỗi), "tới clip M", bài đầu, tay nắm ♪ kéo đổi clip, dự án
cũ quy đổi + thông báo. Chạy toàn bộ pytest + `tests/*_check.py` trên `python` và `.venv`; chụp ảnh trước / sau.
Không phát hành khi anh chưa bảo.
