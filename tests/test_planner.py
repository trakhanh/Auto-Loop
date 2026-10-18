from fractions import Fraction

from loopstation.core import planner
from loopstation.core.audio_build import escape_filter_value
from loopstation.core.project import ClipItem, MusicSettings, MusicTrack, Project, VideoSettings

FPS = Fraction(24)
F = 192  # 8 giây


def make_vs(counts, **kw) -> VideoSettings:
    vs = VideoSettings(clips=[ClipItem(path=f"v{i}.mp4", count=n) for i, n in enumerate(counts)])
    for k, v in kw.items():
        setattr(vs, k, v)
    return vs


def frames_for(vs):
    return {i: F for i in range(len(vs.clips))}


def seg_total(plan, frames):
    return sum(s.frames for s in planner.segments(plan, frames))


def test_manual_sequence_matches_user_example():
    vs = make_vs([70, 1, 1, 70, 1, 70])
    fr = frames_for(vs)
    plan = planner.plan_video(vs, fr, FPS, None)
    assert plan.total_frames == 213 * F == seg_total(plan, fr)
    assert [(c, n) for c, n, _ in plan.all_plays()] == [(0, 70), (1, 1), (2, 1), (3, 70), (4, 1), (5, 70)]
    assert not any(plan.overlaps)


def test_zero_plays_skipped():
    vs = make_vs([2, 0, 3])
    plan = planner.plan_video(vs, frames_for(vs), FPS, None)
    assert {c for c, _, _ in plan.all_plays()} == {0, 2}


def test_repeat_sequence_exact_end():
    vs = make_vs([3, 1], length_mode="target", fill="repeat_sequence", exact_end=True)
    fr = frames_for(vs)
    plan = planner.plan_video(vs, fr, FPS, 100.0)  # 4 lần phát/vòng = 32s → 3 vòng + 4s
    assert plan.total_frames == 2400 == seg_total(plan, fr)
    assert plan.rounds == 4
    assert plan.ends == {12: 96}


def test_repeat_sequence_not_exact_ends_on_play_boundary():
    vs = make_vs([3, 1], fill="repeat_sequence", exact_end=False)
    plan = planner.plan_video(vs, frames_for(vs), FPS, 100.0)
    assert plan.total_frames % F == 0
    assert 2400 <= plan.total_frames < 2400 + F


def test_stretch_marked():
    vs = make_vs([1, 1, 1], fill="stretch_marked", exact_end=True)
    vs.clips[0].stretch = True
    vs.clips[2].stretch = True
    plan = planner.plan_video(vs, frames_for(vs), FPS, 3600.0)
    assert plan.total_frames == 3600 * 24
    plays = {}
    for c, n, _ in plan.all_plays():
        plays[c] = plays.get(c, 0) + n
    assert plays[1] == 1
    assert plays[0] == 225  # (3600-24)/2/8 = 223.5 → 1 + 224
    assert plays[2] == 224


def test_random_is_deterministic_with_seed():
    vs = make_vs([1, 1, 1, 1], order="shuffle", seed=42)
    for c in vs.clips:
        c.plays_mode, c.min, c.max = "random", 2, 9
    a = planner.plan_video(vs, frames_for(vs), FPS, None).all_plays()
    b = planner.plan_video(vs, frames_for(vs), FPS, None).all_plays()
    assert a == b
    vs.seed = 43
    c = planner.plan_video(vs, frames_for(vs), FPS, None).all_plays()
    assert a != c


def test_reshuffle_each_round_changes_order():
    vs = make_vs([1] * 6, order="shuffle", seed=7, fill="repeat_sequence", reshuffle_each_round=True)
    plan = planner.plan_video(vs, frames_for(vs), FPS, 6 * 8 * 5)
    rounds = {}
    for c, _, r in plan.all_plays():
        rounds.setdefault(r, []).append(c)
    assert len({tuple(v) for v in rounds.values()}) > 1


def test_no_clips_error():
    vs = make_vs([0, 0])
    assert planner.plan_video(vs, frames_for(vs), FPS, None).error


def test_loop_crossfade_segments():
    vs = make_vs([3])
    vs.clips[0].loop_xfade = 1.0
    fr = frames_for(vs)
    plan = planner.plan_video(vs, fr, FPS, None)
    assert plan.total_frames == 3 * F - 2 * 24
    segs = [(s.kind, s.start, s.end) for s in planner.segments(plan, fr)]
    assert segs == [("body", 0, 168), ("xfade", 168, 192), ("body", 24, 168),
                    ("xfade", 168, 192), ("body", 24, 192)]
    assert planner.segments(plan, fr)[-1].fade


def test_next_crossfade_only_between_different_clips():
    vs = make_vs([2, 1])
    vs.clips[0].next_xfade = 0.5
    fr = frames_for(vs)
    plan = planner.plan_video(vs, fr, FPS, None)
    assert plan.overlaps == [0, 12]
    assert plan.total_frames == 3 * F - 12 == seg_total(plan, fr)
    x = [s for s in planner.segments(plan, fr) if s.kind == "xfade"]
    assert x == [planner.Segment("xfade", 0, 180, 192, clip_b=1)]


def test_intro_outro_fixed_and_crossfaded():
    vs = make_vs([2, 1], order="shuffle", intro_xfade=1.0, outro_xfade=0.5)
    fr = frames_for(vs) | {planner.INTRO: 120, planner.OUTRO: 96}
    plan = planner.plan_video(vs, fr, FPS, None)
    assert plan.plays[0] == (planner.INTRO, -1) and plan.plays[-1] == (planner.OUTRO, -1)
    assert plan.total_frames == 120 + 3 * F + 96 - 24 - 12 == seg_total(plan, fr)


def test_target_includes_intro_outro_and_keeps_outro_whole():
    vs = make_vs([1, 1], fill="repeat_sequence", exact_end=True, intro_xfade=1, outro_xfade=1)
    vs.clips[0].next_xfade = vs.clips[1].next_xfade = 1
    fr = frames_for(vs) | {planner.INTRO: 120, planner.OUTRO: 96}
    plan = planner.plan_video(vs, fr, FPS, 100.0)
    assert plan.total_frames == 2400 == seg_total(plan, fr)
    assert plan.plays[-1][0] == planner.OUTRO
    assert len(plan.plays) - 1 not in plan.ends  # outro không bị cắt


def test_crossfade_too_long_is_clamped_with_warning():
    vs = make_vs([2])
    vs.clips[0].loop_xfade = 10
    plan = planner.plan_video(vs, frames_for(vs), FPS, None)
    assert plan.overlaps == [int(0.45 * F)]
    assert plan.warnings


def test_segments_always_add_up():
    import random
    rng = random.Random(1)
    for case in range(300):
        n = rng.randint(1, 5)
        vs = make_vs([rng.randint(0, 6) for _ in range(n)], seed=case,
                     order=rng.choice(["list", "shuffle"]),
                     fill=rng.choice(["repeat_sequence", "stretch_marked"]),
                     exact_end=rng.random() < 0.7, intro_xfade=rng.choice([0, 0.5, 3]),
                     outro_xfade=rng.choice([0, 1, 9]))
        for c in vs.clips:
            c.loop_xfade, c.next_xfade = rng.choice([0, 0.5, 2, 9]), rng.choice([0, 1, 4])
            c.stretch = rng.random() < 0.5
        fr = {i: rng.randint(30, 300) for i in range(n)}
        if rng.random() < 0.5:
            fr[planner.INTRO] = rng.randint(30, 200)
        if rng.random() < 0.5:
            fr[planner.OUTRO] = rng.randint(30, 200)
        target = rng.choice([None, rng.uniform(5, 400)])
        plan = planner.plan_video(vs, fr, FPS, target)
        if plan.error:
            continue
        segs = planner.segments(plan, fr)
        assert sum(s.frames for s in segs) == plan.total_frames, case
        assert all(s.frames > 0 and s.start >= 0 for s in segs), case
        assert all(s.end <= fr[s.clip] for s in segs), case
        assert all(s.frames <= fr[s.clip_b] for s in segs if s.kind == "xfade"), case
        if target is not None and vs.exact_end and plan.total_frames > round(target * 24):
            # chỉ được vượt khi lần phát cuối không thể cắt ngắn hơn
            assert plan.total_frames - round(target * 24) <= max(fr.values()), case


def ms_with(durs, **kw):
    ms = MusicSettings(tracks=[MusicTrack(path=f"t{i}.mp3") for i in range(len(durs))])
    for k, v in kw.items():
        setattr(ms, k, v)
    return ms, dict(enumerate(durs))


def test_music_crossfade_schedule_covers_total():
    ms, d = ms_with([40, 30, 35], crossfade=3)
    items = planner.plan_music(ms, d, 200)
    assert items[0].start == 0
    assert items[1].start == 37
    assert abs(items[-1].start + items[-1].duration - 200) < 1e-6
    assert [i.track for i in items[:4]] == [0, 1, 2, 0]


def test_music_no_repeat_adjacent():
    ms, d = ms_with([10, 10, 10], order="shuffle_no_repeat", crossfade=0, seed=3)
    items = planner.plan_music(ms, d, 1000)
    seq = [i.track for i in items]
    assert all(a != b for a, b in zip(seq, seq[1:]))


def test_music_disabled_track_excluded():
    ms, d = ms_with([10, 10, 10], crossfade=0)
    ms.tracks[1].enabled = False
    items = planner.plan_music(ms, d, 100)
    assert 1 not in {i.track for i in items}


def test_first_round_seconds():
    ms, d = ms_with([40, 30], crossfade=5)
    assert planner.first_round_seconds(ms, d) == 65


def test_project_roundtrip(tmp_path):
    p = Project(name="Thử")
    p.video.clips.append(ClipItem(path=str(tmp_path / "a b" / "Video 1.mp4"), count=70, stretch=True))
    p.video.clips.append(ClipItem(path=str(tmp_path / "v2.mp4"), plays_mode="random", min=3, max=9))
    p.music.tracks.append(MusicTrack(path=str(tmp_path / "Bài 1.mp3"), plays=2))
    f = tmp_path / "x.lsproj"
    p.save(str(f))
    q = Project.load(str(f))
    assert q.video.clips[0].path == p.video.clips[0].path
    assert q.video.clips[0].count == 70 and q.video.clips[0].stretch
    assert (q.video.clips[1].plays_mode, q.video.clips[1].min, q.video.clips[1].max) == ("random", 3, 9)
    assert q.music.tracks[0].plays == 2
    assert '"a b/Video 1.mp4"' in f.read_text(encoding="utf-8")  # lưu đường dẫn tương đối


def test_escape_filter_value():
    assert escape_filter_value("E:/a, b's [x].mp3") == "E\\\\:/a\\, b\\\\\\'s \\[x\\].mp3"


def test_music_no_stray_fragment_at_end():
    """Lỗi cũ: kết thúc đúng bằng tổng (sai số float) mở thêm một mẩu bài ~3s ở cuối."""
    import random
    rng = random.Random(5)
    for case in range(500):
        n = rng.randint(1, 6)
        ms, d = ms_with([rng.uniform(20, 240) for _ in range(n)], crossfade=rng.choice([0, 3, 5]),
                        order=rng.choice(["list", "shuffle", "shuffle_no_repeat"]), seed=case)
        rounds = rng.randint(1, 3)
        total = planner.rounds_seconds(ms, d, rounds) + rng.choice([0, 1e-9, -1e-9, 1e-4])
        items = planner.plan_music(ms, d, total)
        assert all(it.duration > 0.04 for it in items), case
        played = len(items)
        expected = sum(t.plays for t in ms.tracks) * rounds
        assert played == expected, (case, played, expected)


def test_ambient_layers_fade():
    from loopstation.core.audio_build import ambient_graph
    lines, labels = ambient_graph(["E:/rain.mp3"], [40], 100.0, fade_in=2, fade_out=5)
    assert "afade=t=in" in lines[0] and "afade=t=out:st=95" in lines[0] and labels == ["amb0"]


def test_queue_load_keeps_good_items_and_backs_up_bad_file(tmp_path):
    import json
    from loopstation.core import render_queue as rq
    good = rq.QueueItem(project=Project(name="A"), output="E:/x.mp4")
    f = tmp_path / "queue.json"
    f.write_text(json.dumps([good.to_dict(), {"project": {"video": {"seed": None}}, "output": "y"}]),
                 encoding="utf-8")
    items = rq.load(f)
    assert [i.project.name for i in items] == ["A"]
    assert (tmp_path / "queue.hong.json").is_file()
    f.write_text("{hỏng", encoding="utf-8")
    assert rq.load(f) == []


def test_unique_output(tmp_path):
    from loopstation.core.render_queue import unique_output
    p = tmp_path / "v.mp4"
    p.write_text("x")
    assert unique_output(str(p), set()).endswith("v_2.mp4")
    assert unique_output(str(tmp_path / "w.mp4"), {str(tmp_path / "w.mp4").lower()}).endswith("w_2.mp4")


def test_output_kind_roundtrip_and_video_only_ignores_music(tmp_path):
    p = Project(name="K", output_kind="video_only")
    f = tmp_path / "k.lsproj"
    p.save(str(f))
    assert Project.load(str(f)).output_kind == "video_only"
    d = p.to_dict()
    d["output_kind"] = "rác"
    assert Project.from_dict(d).output_kind == "video_music"


def test_trim_roundtrip(tmp_path):
    p = Project()
    p.video.clips.append(ClipItem(path=str(tmp_path / "a.mp4"), trim_start=2.0, trim_end=1.5))
    f = tmp_path / "t.lsproj"
    p.save(str(f))
    c = Project.load(str(f)).video.clips[0]
    assert (c.trim_start, c.trim_end) == (2.0, 1.5)
    d = p.to_dict()
    d["video"]["clips"][0].pop("trim")  # file cũ chưa có trường trim
    assert (Project.from_dict(d).video.clips[0].trim_start, Project.from_dict(d).video.clips[0].trim_end) == (0, 0)


def test_loops_for_duration():
    from loopstation.core.timeline import loops_for
    assert loops_for(600, 192, 0, FPS) == 75          # 8s × 75 = 10 phút
    assert loops_for(600, 192, 1.0, FPS) == 86        # mỗi lần nối chồng 1s → cần thêm lần phát
    assert loops_for(5, 192, 0, FPS) == 1
    assert loops_for(0, 192, 0, FPS) == 0


def test_duration_mode_roundtrip(tmp_path):
    p = Project()
    p.video.clips.append(ClipItem(path=str(tmp_path / "a.mp4"), plays_mode="duration", play_seconds=600))
    f = tmp_path / "d.lsproj"
    p.save(str(f))
    c = Project.load(str(f)).video.clips[0]
    assert (c.plays_mode, c.play_seconds) == ("duration", 600)
