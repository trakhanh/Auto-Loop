from loopstation.core import planner
from loopstation.core.project import MusicSettings, MusicTrack, Project


def make(n=10, dur=180.0, **kw):
    ms = MusicSettings(tracks=[MusicTrack(f"s{i}.mp3") for i in range(n)], crossfade=0.0, **kw)
    return ms, {i: dur for i in range(n)}


def order(ms, durs, total):
    return [it.track for it in planner.plan_music(ms, durs, total)]


def test_versions_differ_and_open_differently():
    ms, durs = make(order="shuffle_no_repeat", seed=5)
    seeds, dup = planner.version_seeds(ms, durs, 1800, 4)
    assert not dup and len(set(seeds)) == 4
    orders = [order(planner.music_variant(ms, s), durs, 1800) for s in seeds]
    assert len({tuple(o) for o in orders}) == 4
    assert len({o[0] for o in orders}) == 4  # mỗi bản mở đầu một bài khác
    for o in orders:
        assert sorted(o) == list(range(10))  # cùng 10 bài, chỉ khác thứ tự


def test_list_order_becomes_shuffled_for_versions():
    ms, durs = make(order="list")
    seeds, _ = planner.version_seeds(ms, durs, 1800, 3)
    orders = [order(planner.music_variant(ms, s), durs, 1800) for s in seeds]
    assert len({tuple(o) for o in orders}) == 3


def test_pinned_first_in_every_version():
    ms, durs = make(n=60, order="shuffle_no_repeat", seed=9)
    ms.tracks[42].pinned = True
    seeds, _ = planner.version_seeds(ms, durs, 3600, 4)  # 1 giờ = 20 bài trong 60 bài
    for s in seeds:
        o = order(planner.music_variant(ms, s), durs, 3600)
        assert o[0] == 42


def test_pinned_random_is_always_inside_file():
    ms, durs = make(n=60, order="shuffle", pin_pos="random")
    ms.tracks[7].pinned = ms.tracks[33].pinned = True
    positions = set()
    for seed in range(40):
        ms.seed = seed
        o = order(ms, durs, 3600)
        assert 7 in o and 33 in o
        positions.add(o.index(7))
    assert len(positions) > 5  # thật sự ngẫu nhiên, không luôn ở đầu


def test_too_few_tracks_reports_duplicates():
    ms, durs = make(n=2, order="shuffle")
    _, dup = planner.version_seeds(ms, durs, 360, 4)
    assert dup


def test_save_load_versions_and_pins(tmp_path):
    p = Project()
    p.music.tracks = [MusicTrack(str(tmp_path / "a.mp3"), pinned=True), MusicTrack(str(tmp_path / "b.mp3"))]
    p.music.versions, p.music.pin_pos = 4, "random"
    f = tmp_path / "x.lsproj"
    p.save(str(f))
    q = Project.load(str(f))
    assert q.music.versions == 4 and q.music.pin_pos == "random"
    assert [t.pinned for t in q.music.tracks] == [True, False]
