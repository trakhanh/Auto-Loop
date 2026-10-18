# Bộ mẫu để test KT Loop Station

Mọi file trong thư mục này đều được máy tự tạo (video chuyển màu, nhạc lofi tổng hợp), dùng thoải mái để thử.

| Thư mục | Nội dung |
|---|---|
| `Video/` | 6 clip 8 giây, 1080p 24 fps. Clip **01** và **04** có tiếng gốc (để thử "Trộn tiếng gốc"). Clip **06** là video **dọc 9:16** (để thử "Nền mờ" / "Cắt cho đầy khung"). |
| `Nhac/` | **10 bài lofi**, tổng khoảng **30 phút**, các bài to nhỏ khác nhau để thử "Chuẩn hoá âm lượng". |
| `Tieng-nen/` | `Mưa rơi.mp3`, `Lửa trại.mp3`: 30 giây, dùng làm lớp tiếng nền. |
| `Intro-Outro/` | `Intro.mp4` (có tiếng "ting"), `Outro.mp4`. |
| `Anh/` | 2 ảnh tĩnh: 4:3 và 16:9, để thử ảnh làm clip. |
| `Xuat/` | Nơi các dự án mẫu xuất video ra. |

## Hai dự án mở sẵn

Bấm **Mở…** ở thanh bên trái rồi chọn một trong hai file:

1. **`Du-an-mau - Loop 70 lan.lsproj`**: đúng ví dụ của bạn.
   - V1 ×70 → V2 → V3 → V4 ×70 → V5 → V6 ×70, có crossfade.
   - Có intro/outro, 10 bài nhạc ngẫu nhiên không lặp liền nhau, tiếng mưa 35%.
   - Video dài khoảng 25 phút (crossfade làm mỗi chỗ nối ngắn đi một chút).
2. **`Du-an-mau - 3 tieng.lsproj`**: video **3 tiếng**.
   - Lặp cả chuỗi, xáo lại mỗi vòng, có một ảnh tĩnh, tiếng lửa trại.
   - Khi chọn kiểu 🎵 Chỉ nhạc, độ dài file nhạc đã đặt sẵn 1 tiếng.

## Gợi ý kiểm tra (khoảng 15 phút)

1. Mở dự án 1 → xem **thanh timeline** trên cùng và các chỉ số ở thanh trên. Bôi đen dòng V1 → **▶ Xem thử chỗ nối**.
2. Trang **Xuất** → **Bắt đầu xuất video** → mở file trong `Xuat/`. Kiểm tra:
   - crossfade giữa các lần loop và giữa các clip,
   - intro/outro,
   - nhạc lặp đều, có tiếng mưa,
   - đoạn cuối nhỏ dần,
   - file `_tracklist.txt` đi kèm.
3. Chọn kiểu **🎵 Chỉ nhạc** ở thanh trên → trang **Xuất** → *Thời lượng* 1h → **Bắt đầu xuất file nhạc**. Kết quả là file MP3 1 tiếng ghép từ 10 bài (30 phút) lặp lại.
   Thử thêm kiểu **🎬 Chỉ video**: playlist bị làm mờ, video xuất ra không có nhạc.
4. Mở dự án 2 → **＋ Thêm vào hàng đợi**. Đổi độ phân giải sang **Dọc 9:16**, thêm lần nữa. Sau đó **▶ Chạy hàng đợi**.
5. Kéo nhỏ cửa sổ: thanh bên thu thành biểu tượng, phần cài đặt tự xếp xuống dưới.
6. Thử với clip thật tải từ Google Flow và nhạc thật của công ty.

Làm lại bộ mẫu (cần numpy):

```bash
.venv\Scripts\python.exe tests\make_test_pack.py
```
