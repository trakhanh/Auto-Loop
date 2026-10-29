import os

from loopstation.core import batch, table_preset as tp
from loopstation.core.project import ClipItem, Project, is_sample_file
from loopstation.ui.interleave_dialog import arrange_from_preset


def _table(prefix: str) -> list[ClipItem]:
    """Bảng giống ảnh chụp của người dùng: STT_loopB ×1 → STT_loopA ×57 → STT_loopB ×1 → STT_loopA ×1."""
    return [ClipItem(f"D:/v/{prefix}_loopB.mp4", count=1),
            ClipItem(f"D:/v/{prefix}_loopA.mp4", count=57, loop_xfade=0.0, next_xfade=1.0, trim_start=2.0),
            ClipItem(f"D:/v/{prefix}_loopB.mp4", count=1),
            ClipItem(f"D:/v/{prefix}_loopA.mp4", count=1)]


def test_role_ignores_number_prefix():
    assert tp.role_of("D:/a/5_loopB.mp4") == "loopb"
    assert tp.role_of("12 - LoopA.MOV") == "loopa"
    assert tp.role_of("Content.mp4") == "content"
    assert tp.role_label("5_loopB.mp4") == "STT_loopB"


def test_save_and_apply_to_other_video():
    rows = tp.from_clips(_table("5"))
    assert tp.summary(rows) == "STT_loopB ×1 → STT_loopA ×57 → STT_loopB ×1 → STT_loopA ×1"
    clips, missing = tp.build(rows, ["E:/x/6_loopA.mp4", "E:/x/6_loopB.mp4", "E:/x/ghi-chu.txt"])
    assert not missing
    assert [(c.path.rsplit("/", 1)[-1], c.count) for c in clips] == [
        ("6_loopB.mp4", 1), ("6_loopA.mp4", 57), ("6_loopB.mp4", 1), ("6_loopA.mp4", 1)]
    assert clips[1].next_xfade == 1.0 and clips[1].trim_start == 2.0  # giữ thông số của dòng


def test_missing_role_drops_rows():
    rows = tp.from_clips(_table("5"))
    clips, missing = tp.build(rows, ["E:/x/7_loopA.mp4"])
    assert missing == ["loopb"] and [c.count for c in clips] == [57, 1]


def test_batch_uses_table_preset():
    preset = {"name": "A57", "kind": "table", "rows": tp.from_clips(_table("5"))}
    arrange = arrange_from_preset(preset)
    job = batch.FolderJob(folder="E:/x/Video 06", name="Video 06", clips=["E:/x/6_loopA.mp4", "E:/x/6_loopB.mp4"])
    proj = batch.build_project(Project(), job, arrange=arrange, loop_xfade=1.0, next_xfade=0.5)
    assert [c.count for c in proj.video.clips] == [1, 57, 1, 1]
    assert proj.video.clips[1].next_xfade == 1.0  # mẫu bảng giữ nối của mẫu, không bị crossfade chung đè
    assert proj.video.order == "list"


def test_is_sample_file():
    assert is_sample_file(r"C:\Program Files\KT Loop Station\Mau-Test\Intro-Outro\Intro.mp4")
    assert not is_sample_file(r"D:\Kenh\Intro.mp4")


def test_many_situations_in_one_folder_stack_into_one_video():
    rows = tp.from_clips(_table("5"))
    paths = [f"D:/f/{n}_loop{r}.mp4" for n in range(1, 11) for r in "AB"]
    clips, missing = tp.build(rows, paths)
    assert not missing and len(clips) == 40
    names = [c.path.rsplit("/", 1)[-1] for c in clips]
    assert names[:4] == ["1_loopB.mp4", "1_loopA.mp4", "1_loopB.mp4", "1_loopA.mp4"]
    assert names[4] == "2_loopB.mp4" and names[-1] == "10_loopA.mp4"  # 2 trước 10, không theo kiểu chữ
    assert [c.count for c in clips[:4]] * 10 == [c.count for c in clips]
    _items, missing, used = tp.plan(rows, [p for p in paths if p != "D:/f/7_loopB.mp4"])
    assert missing == ["7_loopb"] and used == list(range(1, 11))


def test_library_examples_for_every_preset():
    from loopstation.ui.interleave_dialog import BUILTIN, SEQUENCE_PRESETS
    from loopstation.ui.preset_library import example
    for p in [*BUILTIN, *SEQUENCE_PRESETS, {"name": "t", "kind": "table", "rows": tp.from_clips(_table("5"))}]:
        blocks, total, files = example(dict(p))
        assert blocks and total > 0 and files, p["name"]
    blocks, total, _ = example(dict(BUILTIN[0]))
    assert [b[0] for b in blocks[:3]] == ["Nền", "Cảnh 2", "Nền"] and blocks[0][1] == "×70"
    blocks, total, _ = example({"kind": "table", "rows": tp.from_clips(_table("5"))})
    assert [b[1] for b in blocks] == ["×1", "×57", "×1", "×1"] and total == 600


def test_builtin_table_preset_ships_with_app():
    """Mẫu "Loop A ×57 kẹp Loop B" nằm trong app: máy mới (chưa lưu gì) vẫn có, áp được cho 1_… đến 10_…."""
    from PySide6.QtCore import QSettings
    from loopstation.ui.interleave_dialog import TABLE_BUILTIN, all_presets, all_table_presets, save_table_presets
    st = QSettings("KTLoopStation-Test", "builtin-table")
    st.clear()
    p = next(x for x in all_presets(st) if x["name"] == "Loop A ×57 kẹp Loop B")
    assert p["kind"] == "table" and not p.get("user")
    assert tp.summary(p["rows"]) == "STT_loopB ×1 → STT_loopA ×57 → STT_loopB ×1 → STT_loopA ×1"
    clips, missing = tp.build(p["rows"], [f"D:/f/{n}_loop{r}.mp4" for n in range(1, 11) for r in "AB"])
    assert not missing and len(clips) == 40 and clips[1].path.endswith("1_loopA.mp4") and clips[1].count == 57
    save_table_presets(st, [{"name": "Loop A ×57 kẹp Loop B", "rows": p["rows"][:2]}])  # bản của bạn trùng tên: thay mẫu có sẵn
    mine = [x for x in all_table_presets(st) if x["name"] == "Loop A ×57 kẹp Loop B"]
    assert len(mine) == 1 and mine[0].get("user") and len(mine[0]["rows"]) == 2
    assert len(TABLE_BUILTIN[0]["rows"]) == 4  # mẫu gốc không đổi
    st.clear()


def test_episode_names_tap_stt_role():
    """Tên Tập_STT_Vai: "33_4_LOOP A.mp4" = tập 33, tình huống 4, vai loopA (hoa / thường, dấu cách không quan trọng)."""
    assert (tp.episode_of("33_4_LOOP A.mp4"), tp.stt_of("33_4_LOOP A.mp4"), tp.role_of("33_4_LOOP A.mp4")) == (33, 4, "loopa")
    assert tp.role_of("33_10_Loop_B.mov") == tp.role_of("5_loopB.mp4") == tp.role_of("loop-b.mp4") == "loopb"
    assert (tp.episode_of("5_loopB.mp4"), tp.stt_of("5_loopB.mp4")) == (None, 5)  # kiểu cũ giữ nguyên
    assert tp.role_label("33_4_LOOP A.mp4") == "STT_LOOP A"
    old = [dict(r, role="loop_a" if r["role"] == "loopa" else r["role"]) for r in tp.from_clips(_table("5"))]
    assert len(tp.build(old, ["D:/x/33_1_LOOP A.mp4", "D:/x/33_1_LOOP B.mp4"])[0]) == 4  # mẫu cũ ghi "loop_a" vẫn khớp


def test_each_episode_is_its_own_video():
    from loopstation.ui.interleave_dialog import TABLE_BUILTIN
    rows = TABLE_BUILTIN[0]["rows"]
    paths = [f"D:/m/{e}_{n}_LOOP {r}.mp4" for e in (34, 33) for n in range(1, 11) for r in "AB"]
    assert tp.episodes(paths) == [33, 34]
    for ep in (33, 34):
        clips, missing = tp.build(rows, paths, ep)
        names = [c.path.rsplit("/", 1)[-1] for c in clips]
        assert not missing and len(clips) == 40
        assert names[:5] == [f"{ep}_1_LOOP B.mp4", f"{ep}_1_LOOP A.mp4", f"{ep}_1_LOOP B.mp4", f"{ep}_1_LOOP A.mp4",
                             f"{ep}_2_LOOP B.mp4"]
        assert names[-1] == f"{ep}_10_LOOP A.mp4" and all(n.startswith(f"{ep}_") for n in names)
        assert clips[1].count == 57
    assert tp.build(rows, paths)[0][0].path.endswith("33_1_LOOP B.mp4")  # không chọn tập: tập nhỏ nhất
    gap = [p for p in paths if not p.endswith("33_7_LOOP B.mp4")]
    clips, missing = tp.build(rows, gap, 33)
    assert len(clips) == 38 and missing == ["33_7_loopb"]
    assert tp.missing_names(rows, missing, gap) == ["33_7_LOOP B"]
    assert len(tp.build(rows, gap, 34)[0]) == 40  # tập khác không bị ảnh hưởng


def test_batch_splits_episodes(tmp_path):
    from loopstation.ui.interleave_dialog import TABLE_BUILTIN
    season = tmp_path / "Mua 3"
    season.mkdir()
    for e in (33, 34):
        for n in range(1, 11):
            for r in "AB":
                (season / f"{e}_{n}_LOOP {r}.mp4").write_bytes(b"")
    jobs = batch.scan(str(season))  # chọn thẳng thư mục chứa file: chính nó là một việc
    assert [j.name for j in jobs] == ["Mua 3"] and len(jobs[0].clips) == 40
    split = batch.split_episodes(jobs)
    assert [j.name for j in split] == ["Tập 33", "Tập 34"] and len({j.folder for j in split}) == 2
    arrange = arrange_from_preset(dict(TABLE_BUILTIN[0]))
    for j, ep in zip(split, (33, 34)):
        proj = batch.build_project(Project(), j, arrange=arrange)
        assert len(proj.video.clips) == 40 and proj.export.filename == f"Tập {ep}"
        assert all(os.path.basename(c.path).startswith(f"{ep}_") for c in proj.video.clips)
    plain = batch.FolderJob(folder="x", name="Video 6", clips=["E:/x/6_loopA.mp4", "E:/x/6_loopB.mp4"])
    assert batch.split_episodes([plain]) == [plain]  # tên kiểu cũ: không tách
