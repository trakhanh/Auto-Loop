"""Trộn bản mới giữ nguyên clip: ghim clip khi trộn ngẫu nhiên, tên tự tăng, bản trộn, chữ ký hàng đợi, đổi tên mục."""
from fractions import Fraction
from pathlib import Path

from loopstation.core import planner
from loopstation.core import render_queue as rq
from loopstation.core.project import ClipItem, Project, VideoSettings

FPS = Fraction(24)
F = 48


def make_vs(n, pinned=(), **kw) -> VideoSettings:
    vs = VideoSettings(clips=[ClipItem(path=f"v{i}.mp4", pinned=i in pinned) for i in range(n)], order="shuffle")
    for k, v in kw.items():
        setattr(vs, k, v)
    return vs


def first_round(vs) -> list[int]:
    plan = planner.plan_video(vs, {i: F for i in range(len(vs.clips))}, FPS, None)
    return [c for c, _n in planner.round_order(plan)]


def test_pinned_clip_keeps_its_row_position_when_shuffled():
    for seed in range(30):
        assert first_round(make_vs(6, pinned={2}, seed=seed))[2] == 2


def test_many_pins_and_others_still_shuffle():
    orders = set()
    for seed in range(30):
        o = first_round(make_vs(8, pinned={0, 5}, seed=seed))
        assert o[0] == 0 and o[5] == 5
        assert sorted(o) == list(range(8))
        orders.add(tuple(o))
    assert len(orders) > 5  # các clip không ghim vẫn xáo theo số mầm


def test_pin_counts_only_enabled_rows():
    vs = make_vs(6, pinned={2}, seed=3)
    vs.clips[0].enabled = False
    for seed in range(20):
        vs.seed = seed
        o = first_round(vs)
        assert o[1] == 2 and 0 not in o  # clip 2 là dòng bật thứ 2


def test_pin_kept_every_reshuffled_round():
    vs = make_vs(5, pinned={4}, seed=7, length_mode="target", target_duration=5 * 2 * 6.0,
                 reshuffle_each_round=True)
    plan = planner.plan_video(vs, {i: F for i in range(5)}, FPS, 5 * 2 * 6.0)
    rounds = {rr for _c, _n, rr in plan.all_plays()}
    assert len(rounds) >= 3
    for r in rounds:
        o = [c for c, _n in planner.round_order(plan, r)]
        if len(o) == 5:
            assert o[4] == 4


def test_list_order_ignores_pins():
    assert first_round(make_vs(5, pinned={1}, order="list")) == [0, 1, 2, 3, 4]


def test_pinned_round_trips_and_old_files_have_no_key():
    p = Project()
    p.video.clips = [ClipItem("a.mp4", pinned=True), ClipItem("b.mp4")]
    d = p.to_dict(None)
    assert d["video"]["clips"][0]["pinned"] is True
    assert "pinned" not in d["video"]["clips"][1]
    back = Project.from_dict(d, None)
    assert [c.pinned for c in back.video.clips] == [True, False]


def test_next_name():
    assert rq.next_name("Tập 9", set()) == "Tập 9"
    assert rq.next_name("Tập 9", {"tập 9"}) == "Tập 10"
    assert rq.next_name("Tập 9", {"tập 9", "tập 10"}) == "Tập 11"
    assert rq.next_name("", set()) == "Bản trộn 1"
    assert rq.next_name("", {"bản trộn 1", "bản trộn 2"}) == "Bản trộn 3"
    assert rq.next_name("Bản trộn", {"bản trộn"}) == "Bản trộn 2"
    assert rq.next_name("  a:b  ", set()) == "a_b"  # ký tự Windows không cho phép thành _


def test_remix_keeps_clips_changes_seed_and_name():
    p = Project(name="Mưa")
    p.video.clips = [ClipItem(f"v{i}.mp4", pinned=i == 3) for i in range(5)]
    p.video.order, p.video.seed = "shuffle", 1
    p.music.order, p.music.seed = "shuffle", 1
    p.export.filename = "Bản trộn 1"
    r = rq.remix(p, 777, "Bản trộn 2")
    assert [c.path for c in r.video.clips] == [c.path for c in p.video.clips]
    assert r.video.clips[3].pinned
    assert r.video.seed == 777 and r.music.seed != 1 and r.export.filename == "Bản trộn 2"
    assert p.video.seed == 1 and p.export.filename == "Bản trộn 1"  # bản gốc không đổi
    p.music.order = "list"
    assert rq.remix(p, 5, "x").music.seed == 1  # nhạc theo thứ tự bảng: không đụng


def test_signature_differs_by_seed_only_when_shuffled():
    p = Project()
    p.video.clips = [ClipItem("a.mp4"), ClipItem("b.mp4")]
    p.video.order = "shuffle"
    assert rq.signature(rq.remix(p, 1, "a")) != rq.signature(rq.remix(p, 2, "b"))
    p.video.order = "list"
    assert rq.signature(rq.remix(p, 1, "a")) == rq.signature(rq.remix(p, 2, "b"))


def test_renamed_output():
    assert Path(rq.renamed_output("D:/o/A/A.mp4", "B", True)) == Path("D:/o/B/B.mp4")
    assert Path(rq.renamed_output("D:/o/A.mp4", "B", False)) == Path("D:/o/B.mp4")
    assert Path(rq.renamed_output("D:/o/A.mp3", " C?. ", False)) == Path("D:/o/C_.mp3")


# ---- clip mở đầu: mỗi bản một clip đứng đầu riêng (đánh dấu sẵn A, B, C…) ----
def opener_project() -> Project:
    p = Project()
    p.video.order = "shuffle"
    p.video.clips = [ClipItem(f"v{i}.mp4") for i in range(8)]
    p.video.clips[5].opener = 1  # A
    p.video.clips[2].opener = 2  # B
    p.video.clips[7].opener = 3  # C
    return p


def test_openers_follow_mark_order_not_rows():
    assert rq.openers(opener_project()) == [5, 2, 7]


def test_with_opener_puts_clip_first_and_pins_it():
    p = opener_project()
    v, note = rq.with_opener(p, 2)
    assert v.video.clips[0].path == "v2.mp4" and v.video.clips[0].pinned
    assert v.video.clips[2].path == "v0.mp4" and not v.video.clips[2].pinned
    assert note == ""
    assert p.video.clips[0].path == "v0.mp4"  # bản gốc không đổi
    for seed in range(10):
        v.video.seed = seed
        assert first_round(v.video)[0] == 0  # dòng đầu (= v2) luôn phát đầu tiên


def test_with_opener_keeps_other_pins_and_reports_replaced_first_pin():
    p = opener_project()
    p.video.clips[4].pinned = True
    v, note = rq.with_opener(p, 5)
    assert v.video.clips[4].pinned and v.video.clips[4].path == "v4.mp4"
    assert note == ""
    p.video.clips[0].pinned = True  # anh đã ghim clip khác ở đầu: clip mở đầu thay chỗ đó, có báo
    v, note = rq.with_opener(p, 5)
    assert v.video.clips[0].path == "v5.mp4" and not v.video.clips[5].pinned and "v0" in note


def test_first_enabled_row_is_the_slot():
    p = opener_project()
    p.video.clips[0].enabled = False
    v, _ = rq.with_opener(p, 7)
    assert v.video.clips[1].path == "v7.mp4" and v.video.clips[0].path == "v0.mp4"


def test_next_opener_cycles_through_chained_versions():
    p = opener_project()
    assert rq.lead_opener(p) is None
    seen = []
    for _ in range(5):
        k = rq.next_opener(p)
        p, _ = rq.with_opener(p, k)
        seen.append(p.video.clips[rq.first_slot(p)].path)
    assert seen == ["v5.mp4", "v2.mp4", "v7.mp4", "v5.mp4", "v2.mp4"]


def test_describe_and_round_trip_opener():
    v, _ = rq.with_opener(opener_project(), 7)
    assert "mở đầu v7" in rq.describe(v)
    assert "mở đầu" not in rq.describe(opener_project())
    back = Project.from_dict(v.to_dict(None), None)
    assert [c.opener for c in back.video.clips] == [c.opener for c in v.video.clips]
    assert "opener" not in v.to_dict(None)["video"]["clips"][1]
