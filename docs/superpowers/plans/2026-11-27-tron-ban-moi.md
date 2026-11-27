# Trộn bản mới · ghim clip · đặt tên mục hàng đợi — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trộn tiếp nhiều bản từ cùng bảng clip mà không mất clip, ghim clip ở vị trí cố định khi trộn ngẫu nhiên,
đặt / đổi tên mục hàng đợi.

**Architecture:** Logic thuần ở `core` (ghim trong `planner.resolve_round`, tên tự tăng + bản trộn + đổi tên đường dẫn
ở `core/render_queue.py`), giao diện chỉ gọi vào. Hộp thoại mới ở `ui/queue_dialogs.py`.

**Tech Stack:** Python 3, PySide6, pytest; check script offscreen.

**Spec:** `docs/superpowers/specs/2026-11-27-tron-ban-moi-design.md`

## Global Constraints

- Không mã màu hex trong `loopstation/ui` (chỉ token `theme.py`); không thêm `setStyleSheet` ngoài `theme.py`.
- Test chạy cô lập: `KTLS_DATA_DIR`, `KTLS_SETTINGS_ORG=KTLoopStation-Test`, `KTLS_NO_UPDATE=1`,
  `QT_QPA_PLATFORM=offscreen`, `PYTHONIOENCODING=utf-8`, basetemp/TMP trên ổ E.
- Chữ giao diện tiếng Việt; app gợi ý, người dùng quyết định — mọi thay đổi số mầm / tên phải báo ra.
- File dự án cũ mở được; `pinned` chỉ ghi khi True.

## Review Focus

- Ghim nhiều clip, ghim clip đang tắt, ghim khi Thứ tự = theo bảng → tắt clip không tính chỗ; list không đổi gì.
- Tên đã có số ("Tập 9") → "Tập 10"; tên trống → "Bản trộn 1"; trùng trong hàng đợi lẫn trên đĩa đều bỏ qua.
- Bản trộn khác số mầm không bị hỏi "Có thể bị trùng".
- Đổi tên mục khi bật "mỗi video một thư mục" đổi cả tên thư mục; tên rỗng / ký tự cấm bị làm sạch.
- Huỷ hộp tên (Esc) → không thêm gì, ô Tên file giữ nguyên.

---

### Task 1: Ghim clip khi trộn ngẫu nhiên

**Files:** Modify `loopstation/core/project.py` (ClipItem, to_dict/from_dict), `loopstation/core/planner.py:71`
(`resolve_round`), `loopstation/ui/video_tab.py` (menu_extras, `_make_item`, `_clip_from_item`, dòng phụ);
Test `tests/test_remix.py`.

**Produces:** `ClipItem.pinned: bool = False`.

- [ ] Test: 6 clip, clip 2 ghim, `order="shuffle"`, 30 số mầm → `round_order` lượt đầu luôn có clip 2 ở vị trí 2;
  `reshuffle_each_round=True` nhiều lượt → mọi lượt giữ; clip 0 tắt → clip 2 ở vị trí 1 trong các dòng bật; order
  "list" giống hệt không ghim; số mầm khác vẫn ra thứ tự khác cho các clip không ghim; to_dict/from_dict giữ
  `pinned`, dict của clip không ghim không có khoá `pinned`.
- [ ] Code: trong `resolve_round`, chỗ ghim = các chỉ số k trong `idx` mà `clips[idx[k]].pinned`; xáo phần còn lại
  bằng `rng.shuffle`, lấp vào chỗ trống theo thứ tự.
- [ ] UI: menu dòng "Ghim / bỏ ghim chỗ này khi trộn ngẫu nhiên"; dòng phụ thêm "Ghim · vị trí N" (màu token);
  `_clip_from_item` giữ `pinned` của dòng cũ; nhân bản dòng không mang ghim.
- [ ] Chạy test → PASS.

### Task 2: Tên tự tăng, bản trộn, chữ ký, đổi tên đường dẫn

**Files:** Modify `loopstation/core/render_queue.py`; Test `tests/test_remix.py`.

**Produces:**
- `next_name(name: str, taken: set[str]) -> str` — `taken` là tên (stem, chữ thường) đã dùng.
- `remix(project: Project, seed: int, name: str) -> Project` — bản sao sâu, `video.seed = seed`,
  `music.seed` cũng đổi (theo `seed`) khi `music.order != "list"`, `export.filename = name`.
- `renamed_output(output: str, new_stem: str, own_folder: bool) -> str`.
- `signature(...)` thêm `(v.order, v.seed)` khi `v.order == "shuffle"` hoặc có clip phát ngẫu nhiên số lần.

- [ ] Test: `next_name("Tập 9", set()) == "Tập 9"`; `next_name("Tập 9", {"tập 9"}) == "Tập 10"`;
  `next_name("", set()) == "Bản trộn 1"`; `next_name("Bản trộn", {"bản trộn"}) == "Bản trộn 2"`;
  `remix` giữ clip + ghim, đổi seed, không đụng bản gốc; `renamed_output("D:/o/A/A.mp4", "B", True) == "D:/o/B/B.mp4"`
  (so bằng Path); hai dự án trộn khác seed có signature khác, order list thì seed không ảnh hưởng.
- [ ] Code, chạy test → PASS.

### Task 3: Hỏi tên khi thêm, hộp "Đã thêm" mới, đổi tên trong hàng đợi

**Files:** Modify `loopstation/ui/queue_dialogs.py` (thêm `NameDialog`, sửa `QueueAddedDialog`),
`loopstation/ui/main_window.py` (`add_to_queue`, `_after_queue_add`, thêm `remix_next`, `add_remixes`, `_rename_queue_item`),
`loopstation/ui/export_tab.py` (menu Đổi tên…, F2, signal `queueRenameRequested(int)`), `tests/queue_flow_check.py`.

**Consumes:** Task 2.

- [ ] `NameDialog(title, name, hint, parent)`; `.name` sau khi accept; Esc = huỷ.
- [ ] `add_to_queue`: sau khi biết đường dẫn được (thư mục lưu có, timeline ok), không ở chế độ Cập nhật → hỏi tên,
  gợi ý `next_name(ô Tên file hoặc "", tên đã dùng)`; huỷ thì thôi; tên vào `proj.export.filename` + ô Tên file.
- [ ] `QueueAddedDialog`: `choice` ∈ `remix` (nút chính "Trộn bản mới (giữ nguyên clip)"), `many` (+ ô số
  `count`, mặc định 5, 1–50), `blank` ("Video mới, bảng trống"), `run`, `stay`.
- [ ] `remix_next()`: số mầm mới ngẫu nhiên khác số cũ, tên `next_name`, nạp lại dự án (giữ bảng), báo
  "Số mầm A → B · tên “…”". `add_remixes(n)`: n mục, mỗi mục `remix`, tránh trùng thứ tự lượt đầu (thử ≤ 20 số mầm
  mỗi bản), báo danh sách tên.
- [ ] Hàng đợi: "Đổi tên…" (F2) cho mục chưa chạy / chưa xong → hỏi tên → `renamed_output`, tránh trùng, lưu.
- [ ] `queue_flow_check.py`: thêm bước trả lời hộp tên, kiểm Trộn bản mới giữ bảng + đổi seed + tên tăng, Thêm 3 bản,
  Đổi tên, Video mới bảng trống.

### Task 4: Hướng dẫn + sổ tay, chạy toàn bộ test, commit

- [ ] `loopstation/ui/help_page.py` (Hàng đợi, bảng clip / ghim) + `docs/So-tay-KT-Loop-Station.html`.
- [ ] pytest + mọi `tests/*_check.py` (trừ `download_check.py`) trên `python` và `.venv/Scripts/python.exe`.
- [ ] Commit lên `ui-overhaul`.
