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
