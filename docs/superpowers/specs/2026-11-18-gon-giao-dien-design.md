# Gọn giao diện (phản hồi người dùng: rối, nhiều chữ, nhiều chức năng)

Ngày 2026-11-18 · anh Khánh duyệt hướng "cứ làm theo đề xuất".

## Vì sao
Người dùng (nhân viên làm video theo tập) thấy app rối, nhiều chữ, nhiều chức năng. Soát ảnh các trang Video / Nhạc /
Xuất: không thiếu chỗ cho tính năng, mà **một thông tin bị nói 2–3 lần** và **nút đứng rời rạc**.

## Mục tiêu
- Mỗi trang đọc lướt được: một dòng trạng thái, ít câu dài.
- Ít nút đứng rời: gom nút cùng nhóm vào một nút có menu.
- Không mất tính năng nào; phím tắt, chuột phải, menu ⋯ giữ nguyên.

## Không làm (anti-goal)
- Không làm "chế độ đơn giản / nâng cao" hay ẩn tính năng theo chế độ.
- Không làm giao diện nhạt đi: giữ màu, hiệu ứng mượt.
- Không đổi hành vi xuất video.

## Cách đã cân nhắc
1. **Gom và bớt chữ lặp (chọn)** — giữ bố cục, gom nút, chuyển mẹo vào chú thích. Rủi ro thấp, test cũ vẫn bám được.
2. Làm lại bố cục từng trang — gọn hơn nữa nhưng rủi ro lớn, đụng mọi test bố cục; để sau nếu vẫn còn rối.
3. Chế độ ẩn bớt tính năng — trái ý anh Khánh (không làm chế độ ẩn tính năng).

## Thiết kế (5 việc)
1. **Một dòng trạng thái mỗi trang**: bỏ dòng "Mẹo: …" ở chân trang Video / Nhạc — nội dung chuyển vào chú thích
   (tooltip) của bảng. Dải "Sẵn sàng" giữ (có nút hành động), dòng trạng thái đầu trang giữ.
2. **"Xếp clip ▾"**: 3 nút Xen kẽ nền… / Xếp lần lượt… / Thư viện mẫu… thành một nút có menu 3 mục (giữ biểu tượng,
   chú thích). Các thuộc tính cũ (`interleave_btn`…) vẫn trỏ được tới hành động để không vỡ code khác.
3. **Đặt nhanh**: 5 nút ×1 / ×10 / ×70 / 10p / 1h gộp vào ô nhập (ô có danh sách gợi ý thả xuống), còn ô + Áp dụng.
4. **File xuất kèm** (trang Xuất): 4 ô tick câu dài thu thành một dòng tóm tắt ("Kèm: thư mục riêng · mốc thời gian ·
   tracklist · bản sao dự án") + nút mở ra 4 ô tick như cũ (nhớ trạng thái mở / gấp, mở / gấp mượt).
5. **Rút thông báo dài**: khung thông báo trang Nhạc và phần tóm tắt trùng ở trang Xuất rút còn một dòng; chi tiết
   chuyển vào chú thích.

## Để người làm tự quyết
Câu chữ cụ thể, vị trí chính xác của nút "Xếp clip ▾", cách vẽ danh sách gợi ý của ô Đặt nhanh — giữ token màu của
`theme.py`, không thêm setStyleSheet.

## Kiểm tra
Test mới cho từng việc (pytest), chạy lại toàn bộ pytest + `tests/*_check.py` (layout_audit, ui_smoke,
clickable_check…) trên `python` và `.venv`. Chụp ảnh trước / sau cho anh Khánh xem.
