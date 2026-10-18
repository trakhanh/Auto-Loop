from loopstation.core import interleave as il
from loopstation.core.project import ClipItem


def names(clips):
    return [c.path.split("/")[-1] for c in clips]


def test_detect_and_natural_order():
    clips = [ClipItem("v/10_shot.mp4"), ClipItem("v/loop_chr2_prob4.mp4"), ClipItem("v/2_2Camera.mp4"),
             ClipItem("v/5_shot_5.mp4")]
    assert il.detect_base(clips) == 1
    out = il.build(clips, il.InterleaveOptions(base_index=1))
    assert names(out) == ["loop_chr2_prob4.mp4", "2_2Camera.mp4", "loop_chr2_prob4.mp4", "5_shot_5.mp4",
                          "loop_chr2_prob4.mp4", "10_shot.mp4", "loop_chr2_prob4.mp4"]
    assert [c.count for c in out] == [70, 1, 70, 1, 70, 1, 70]


def test_no_base_word():
    assert il.detect_base([ClipItem("a/2_cam.mp4"), ClipItem("a/3_cam.mp4")]) is None
    assert not il.looks_like_base("a/bloopers.mp4")
    assert il.looks_like_base("a/Nền mưa.mp4")


def test_rebuild_is_idempotent_and_keeps_settings():
    clips = [ClipItem("v/loop.mp4", trim_start=1.0, loop_xfade=1.0), ClipItem("v/3_b.mp4", next_xfade=0.5),
             ClipItem("v/2_a.mp4"), ClipItem("v/9_off.mp4", enabled=False)]
    opt = il.InterleaveOptions(base_index=0, base_plays=("duration", 1, 1, 600.0), start_with_base=False)
    out = il.build(clips, opt)
    assert names(out) == ["2_a.mp4", "loop.mp4", "3_b.mp4", "loop.mp4", "9_off.mp4"]
    base = out[1]
    assert base.plays_mode == "duration" and base.play_seconds == 600.0 and base.trim_start == 1.0
    assert out[2].next_xfade == 0.5 and not out[-1].enabled
    again = il.build(out, il.InterleaveOptions(base_index=1, base_plays=("duration", 1, 1, 600.0),
                                               start_with_base=False))
    assert names(again) == names(out)


def test_no_end_and_table_order():
    clips = [ClipItem("v/loop.mp4"), ClipItem("v/3.mp4"), ClipItem("v/2.mp4")]
    out = il.build(clips, il.InterleaveOptions(base_index=0, order="table", end_with_base=False, insert_plays=2))
    assert names(out) == ["loop.mp4", "3.mp4", "loop.mp4", "2.mp4"]
    assert out[1].count == 2


def test_shuffle_is_deterministic():
    clips = [ClipItem("v/loop.mp4")] + [ClipItem(f"v/{i}.mp4") for i in range(2, 9)]
    a = il.build(clips, il.InterleaveOptions(base_index=0, order="shuffle", seed=7))
    b = il.build(clips, il.InterleaveOptions(base_index=0, order="shuffle", seed=7))
    assert names(a) == names(b)
    assert sorted(names(a)[1::2]) == sorted(f"{i}.mp4" for i in range(2, 9))


def test_repeat_pattern_and_custom_order():
    clips = [ClipItem("v/loop.mp4"), ClipItem("v/1_a.mp4"), ClipItem("v/2_b.mp4"), ClipItem("v/3_c.mp4")]
    specs = [il.InsertSpec("v/2_b.mp4", appear=1, plays=2), il.InsertSpec("v/1_a.mp4"),
             il.InsertSpec("v/3_c.mp4", enabled=False)]
    out = il.build(clips, il.InterleaveOptions(base_index=0, inserts=specs, repeat=4))
    on = [c for c in out if c.enabled]
    assert names(on) == ["loop.mp4", "2_b.mp4", "loop.mp4", "1_a.mp4"] * 4 + ["loop.mp4"]
    assert on[1].count == 2 and on[3].count == 1
    assert names(out)[-1] == "3_c.mp4" and not out[-1].enabled  # cảnh bỏ chọn vẫn giữ trong bảng (tắt)


def test_appear_twice_and_reshuffle_no_back_to_back():
    clips = [ClipItem("v/loop.mp4"), ClipItem("v/1.mp4"), ClipItem("v/2.mp4"), ClipItem("v/3.mp4")]
    specs = [il.InsertSpec("v/1.mp4", appear=2), il.InsertSpec("v/2.mp4")]
    out = il.build(clips, il.InterleaveOptions(base_index=0, inserts=specs, start_with_base=False,
                                               end_with_base=False))
    assert names([c for c in out if c.enabled]) == ["1.mp4", "loop.mp4", "1.mp4", "loop.mp4", "2.mp4"]
    for seed in range(30):
        specs = [il.InsertSpec(f"v/{i}.mp4") for i in (1, 2, 3)]
        out = il.build(clips, il.InterleaveOptions(base_index=0, inserts=specs, repeat=5, reshuffle=True, seed=seed))
        shots = [n for n in names(out) if n != "loop.mp4"]
        assert len(shots) == 15 and all(a != b for a, b in zip(shots, shots[1:]))
