# Trộn bản mới giữ nguyên clip · ghim clip · đặt tên mục hàng đợi

## Vì sao

Góp ý của anh Khánh: bảng có 50 clip phát ngẫu nhiên + 1 clip cố định. Thêm một bản vào hàng đợi xong, muốn trộn
tiếp ra bản khác thì bấm "Làm video tiếp theo" là **mất hết clip** (hàm `next_video` cố ý xoá bảng — làm cho kiểu
"mỗi tập một bộ clip khác"), phải thêm lại từ đầu. Thêm vào hàng đợi cũng **không đặt tên được**, nên không biết mục
nào là mục nào để mở lại chỉnh.

Thành công = trộn 5–10 bản khác nhau từ cùng một bảng clip chỉ bằng vài cú bấm, mỗi bản có tên rõ ràng trong hàng
đợi, đổi tên / mở lại chỉnh được; clip cố định luôn nằm đúng chỗ anh đặt.

## Mục tiêu

1. **Ghim clip khi trộn ngẫu nhiên** (anh chọn "ghim ở vị trí bất kỳ"): chuột phải một dòng → *Ghim chỗ này khi trộn
   ngẫu nhiên*. Khi Thứ tự clip = Ngẫu nhiên, clip ghim luôn đứng đúng vị trí của nó trong bảng (dòng thứ mấy trong
   các dòng đang bật); các clip khác xáo quanh nó. Muốn đổi vị trí: kéo dòng lên / xuống. Mọi lượt lặp (kể cả "mỗi
   lượt xáo mới") đều giữ clip ghim ở chỗ đó. Dòng ghim có chữ "Ghim · vị trí N" ở dòng phụ, dải "Thứ tự sẽ xuất"
   cũng thể hiện đúng.
2. **Hộp thoại "Đã thêm vào hàng đợi"** (anh chọn "Trộn bản mới + nhiều bản"):
   - Nút chính **Trộn bản mới (giữ nguyên clip)**: giữ bảng clip + mọi cài đặt; đổi số mầm video (và số mầm nhạc nếu
     nhạc đang xáo) sang số mới; tên file tự tăng ("Bản trộn 1" → "Bản trộn 2"). App báo rõ đã đổi gì (số mầm cũ →
     mới, tên mới) — không đổi ngầm.
   - **Thêm N bản trộn khác nhau vào hàng đợi** (ô số, mặc định 5): thêm luôn N mục, mỗi mục một số mầm, tên tự tăng
     tiếp; app thử số mầm để các bản không trùng thứ tự lượt đầu.
   - **Video mới, bảng trống** (nút phụ): giữ hành vi cũ cho tập khác clip.
   - Chạy hàng đợi ngay / Ở lại trang Xuất: như cũ.
3. **Đặt tên khi thêm** (anh chọn "hỏi tên mỗi lần thêm"): bấm Thêm vào hàng đợi → hộp nhỏ "Tên mục" điền sẵn tên tự
   tăng, Enter là xong, Esc là thôi. Tên = tên file xuất (cột Tên trong hàng đợi). Đang "Cập nhật mục" thì không hỏi.
4. **Đổi tên trong hàng đợi**: chuột phải → *Đổi tên…* (hoặc F2) với mục chưa chạy / chưa xong; đổi tên file đích
   (cả thư mục riêng nếu bật "mỗi video một thư mục"). Mở lại chỉnh thông số: giữ "Sửa mục này…" / nhấp đúp như cũ.

5. **Mỗi bản một clip mở đầu riêng** (anh bổ sung, duyệt ngày 27/11): chuột phải → *Đánh dấu / bỏ đánh dấu clip
   mở đầu*; `ClipItem.opener` = thứ tự đánh dấu (A = 1, B = 2…). Thêm nhiều bản: số bản gợi ý = số clip mở đầu chưa
   dùng, bản k mở đầu clip kế tiếp (quay vòng), các clip mở đầu khác vẫn phát ở phần sau. Trộn bản mới cũng chuyển
   sang clip mở đầu kế tiếp. Cách làm: đổi chỗ clip mở đầu với dòng bật đầu tiên rồi ghim (clip ghim khác giữ chỗ;
   dòng đầu đang ghim clip khác thì bị thay, có báo). Tóm tắt mục hàng đợi ghi "mở đầu <tên clip>".

## Không làm

- Không thêm chế độ ẩn tính năng; không phát hành.
- Không đổi Xen kẽ clip nền, Xuất hàng loạt từ thư mục, Thả cả mùa (giữ cách đặt tên theo thư mục / tập).
- Không ghim theo số vị trí gõ tay (vị trí = chỗ dòng trong bảng; kéo dòng để đổi).

## Cách làm đã cân nhắc

| Cách | Được | Mất |
|---|---|---|
| **Ghim theo chỗ dòng trong bảng (chọn)** | Nhìn bảng là biết clip đứng đâu; kéo dòng để đổi; không thêm cột | Clip đang tắt không tính vào vị trí |
| Ô "vị trí" gõ số cho từng clip | Đặt chính xác dù bảng lộn xộn | Thêm cột / hộp thoại, dễ lệch khi thêm bớt clip |
| Chỉ ghim đầu / cuối | Đơn giản nhất | Anh cần vị trí bất kỳ |

Hộp thoại: anh chọn "Trộn bản mới + nhiều bản" (thay vì chỉ một nút, hay hỏi giữ/xoá bảng). Đặt tên: anh chọn hỏi
tên mỗi lần thêm (thay vì ô tên trên dải Sẵn sàng).

## Chi tiết kỹ thuật

- `ClipItem.pinned: bool = False`, lưu vào file dự án chỉ khi True (dự án cũ mở bình thường).
- `planner.resolve_round`: với `order == "shuffle"`, các chỗ (vị trí trong danh sách dòng bật) của clip ghim giữ
  nguyên, các clip còn lại xáo rồi lấp vào chỗ trống. Thứ tự "list" không đổi gì.
- Hàm thuần, có test: `next_name(name, taken)` — tăng số cuối ("Tập 9" → "Tập 10", "Bản trộn" → "Bản trộn 2"), bỏ
  qua tên đã có trong hàng đợi / trên đĩa; `remix(project, seed)` — bản sao chỉ đổi số mầm + tên.
- `render_queue.signature`: thêm thứ tự + số mầm khi video trộn ngẫu nhiên, để bản trộn khác số mầm không bị báo
  "Có thể bị trùng".
- Đổi tên mục: hàm thuần `renamed_output(output, new_stem, own_folder)`.
- Màu chỉ dùng token trong `theme.py`; không thêm `setStyleSheet`.

## Để người làm tự quyết

Vị trí chính xác của ô số N, chữ trên nút, cách tính tên gợi ý khi ô Tên file trống (đề xuất: "Bản trộn 1").
