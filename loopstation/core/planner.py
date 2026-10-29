"""Tính timeline video và lịch phát nhạc. Thuần Python, không gọi ffmpeg."""
from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from .project import ClipItem, MusicSettings, VideoSettings

MAX_ROUNDS = 100_000
INTRO, OUTRO = -1, -2  # khoá đặc biệt trong `frames` cho intro/outro
MAX_XF_RATIO = 0.45  # crossfade tối đa = 45% clip ngắn hơn, để mỗi lần phát còn phần thân
MAX_XF_SECONDS = 59.9  # bộ lọc xfade của ffmpeg chỉ nhận tối đa 60 giây


# ======================= VIDEO =======================

@dataclass
class VideoPlan:
    plays: list[tuple[int, int]] = field(default_factory=list)  # (clip, vòng); intro/outro có vòng -1
    overlaps: list[int] = field(default_factory=list)  # số frame chồng (crossfade) giữa lần phát j và j+1
    ends: dict[int, int] = field(default_factory=dict)  # lần phát bị cắt ngắn: chỉ số → frame kết thúc
    total_frames: int = 0
    sequence_frames: int = 0  # độ dài một chuỗi (vòng đầu, kể cả intro/outro)
    rounds: int = 0
    fps: Fraction = Fraction(30)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def total_seconds(self) -> float:
        return float(Fraction(self.total_frames) / self.fps) if self.fps else 0.0

    @property
    def sequence_seconds(self) -> float:
        return float(Fraction(self.sequence_frames) / self.fps) if self.fps else 0.0

    def all_plays(self) -> list[tuple[int, int, int]]:
        """Gộp các lần phát liền nhau: (clip, số lần, vòng)."""
        out: list[list[int]] = []
        for clip, rnd in self.plays:
            if out and out[-1][0] == clip and out[-1][2] == rnd:
                out[-1][1] += 1
            else:
                out.append([clip, 1, rnd])
        return [tuple(x) for x in out]

    @property
    def body_plays(self) -> int:
        return sum(1 for c, _ in self.plays if c >= 0)


@dataclass(frozen=True)
class Segment:
    """Một khối video để encode: phần thân của một lần phát, hoặc đoạn crossfade."""
    kind: str  # "body" | "xfade"
    clip: int
    start: int  # body: frame [start, end) của clip; xfade: đuôi clip A [start, end)
    end: int
    clip_b: int = 0  # xfade: clip B, lấy frame [0, end - start)
    fade: bool = False  # body cuối cùng: mờ dần

    @property
    def frames(self) -> int:
        return self.end - self.start


def resolve_round(clips: list[ClipItem], order: str, rng: random.Random) -> list[tuple[int, int]]:
    """Một vòng: danh sách (chỉ số clip, số lần phát) sau khi xử lý thứ tự và ngẫu nhiên."""
    idx = [i for i, c in enumerate(clips) if c.enabled]
    if order == "shuffle":
        rng.shuffle(idx)
    out = []
    for i in idx:
        c = clips[i]
        if c.plays_mode == "random":
            lo, hi = sorted((max(0, c.min), max(0, c.max)))
            n = rng.randint(lo, hi)
        else:
            n = max(0, c.count)
        if n > 0:
            out.append((i, n))
    return out


class _Builder:
    """Nối dần các lần phát, theo dõi vị trí kết thúc (đã trừ phần chồng crossfade)."""

    def __init__(self, frames: dict[int, int], xf):
        self.frames, self.xf = frames, xf
        self.plays: list[tuple[int, int]] = []
        self.overlaps: list[int] = []
        self.end = 0

    def add(self, clip: int, rnd: int) -> None:
        f = self.frames[clip]
        if self.plays:
            o = self.xf(self.plays[-1][0], clip)
            self.overlaps.append(o)
            self.end += f - o
        else:
            self.end = f
        self.plays.append((clip, rnd))

    def end_with(self, clip: int) -> int:
        if not self.plays:
            return self.frames[clip]
        return self.end + self.frames[clip] - self.xf(self.plays[-1][0], clip)


def _make_xf(vs: VideoSettings, clips: list[ClipItem], frames: dict[int, int], fps: Fraction,
             warnings: list[str]):
    cache: dict[tuple[int, int], int] = {}

    def name(k: int) -> str:
        return {INTRO: "Intro", OUTRO: "Outro"}.get(k) or Path(clips[k].path).stem

    def xf(a: int, b: int) -> int:
        if (a, b) in cache:
            return cache[(a, b)]
        if a == INTRO:
            d = vs.intro_xfade
        elif b == OUTRO:
            d = vs.outro_xfade
        elif a == b:
            d = clips[a].loop_xfade
        else:
            d = clips[a].next_xfade
        o = max(0, round(d * fps))
        lim = min(int(MAX_XF_RATIO * min(frames[a], frames[b])), int(MAX_XF_SECONDS * fps))
        if o > lim:
            what = f"giữa các lần loop của {name(a)}" if a == b else f"{name(a)} → {name(b)}"
            warnings.append(f"Crossfade {what} ({d:g}s) quá dài so với clip — tự giảm còn "
                            f"{float(Fraction(lim) / fps):.1f}s.")
            o = lim
        cache[(a, b)] = o
        return o

    return xf


def plan_video(
    vs: VideoSettings,
    frames: dict[int, int],
    fps: Fraction,
    target_seconds: float | None,
) -> VideoPlan:
    """`frames`: số frame của mỗi clip (theo chỉ số; INTRO/OUTRO nếu có) ở fps xuất.
    `target_seconds`: None = thủ công, ngược lại là thời lượng mục tiêu (gồm cả intro/outro)."""
    plan = VideoPlan(fps=fps)
    clips = [c if i in frames else ClipItem(path=c.path, enabled=False) for i, c in enumerate(vs.clips)]
    rng = random.Random(vs.seed)
    round1 = resolve_round(clips, vs.order, rng)
    if not round1:
        plan.error = "Chưa có clip nào được bật với số lần phát > 0."
        return plan
    xf = _make_xf(vs, clips, frames, fps, plan.warnings)
    has_in, has_out = INTRO in frames, OUTRO in frames

    def fresh() -> _Builder:
        b = _Builder(frames, xf)
        if has_in:
            b.add(INTRO, -1)
        return b

    def total_with_outro(b: _Builder) -> int:
        return b.end_with(OUTRO) if has_out else b.end

    def add_items(b: _Builder, items, stop_at: int | None) -> bool:
        """Thêm các lần phát; dừng ngay khi đủ `stop_at` frame. Trả về True nếu đã đủ."""
        for i, n, r in items:
            for _ in range(n):
                b.add(i, r)
                if stop_at is not None and total_with_outro(b) >= stop_at:
                    return True
        return False

    seq = fresh()
    add_items(seq, [(i, n, 0) for i, n in round1], None)
    plan.sequence_frames = total_with_outro(seq)

    target = None if target_seconds is None else max(1, round(target_seconds * fps))
    b = fresh()
    if target is None:
        add_items(b, [(i, n, 0) for i, n in round1], None)
    elif vs.fill == "stretch_marked":
        items = _stretch(clips, round1, frames, target, plan, xf, fresh, total_with_outro, add_items)
        add_items(b, items, target if vs.exact_end else None)
    else:
        cur, r = round1, 0
        while r < MAX_ROUNDS:
            if add_items(b, [(i, n, r) for i, n in cur], target):
                break
            r += 1
            cur = (resolve_round(clips, vs.order, rng) if vs.reshuffle_each_round else round1) or round1
    if has_out:
        b.add(OUTRO, -1)

    plan.plays, plan.overlaps = b.plays, b.overlaps
    total = b.end
    if target is not None and vs.exact_end and total > target:
        total = _trim_end(plan, frames, total, target, has_out)
    plan.total_frames = total
    if target is not None and total < target:
        plan.warnings.append("Tổng thời lượng ngắn hơn mục tiêu.")
    elif target is not None and vs.exact_end and total > target:
        extra = float(Fraction(total - target) / fps)
        plan.warnings.append(f"Không cắt được đúng thời lượng vì crossfade ở lần phát cuối — video dài hơn "
                             f"mục tiêu {extra:.1f}s.")
    plan.rounds = len({r for c, r in plan.plays if c >= 0})
    return plan


def _stretch(clips, round1, frames, target, plan, xf, fresh, total_with_outro, add_items):
    """Tăng số lần phát của các clip tick 'Tự giãn' để tổng ≈ target."""
    stretch = [i for i, _ in round1 if clips[i].stretch]
    if not stretch:
        plan.warnings.append("Không có clip nào tick 'Tự giãn' — giữ nguyên số lần phát trong bảng.")
        return [(i, n, 0) for i, n in round1]
    base = fresh()
    add_items(base, [(i, 1 if i in stretch else n, 0) for i, n in round1], None)
    remaining = target - total_with_outro(base)
    if remaining <= 0:
        plan.warnings.append("Các clip không giãn đã dài hơn thời lượng mục tiêu.")
    share = max(0, remaining) / len(stretch)
    out = []
    for i, n in round1:
        if i in stretch:
            step = max(1, frames[i] - xf(i, i))
            n = 1 + math.ceil(share / step)
        out.append((i, n, 0))
    return out


def _trim_end(plan: VideoPlan, frames: dict[int, int], total: int, target: int, has_out: bool) -> int:
    """Cắt bớt lần phát cuối cùng của phần thân để tổng đúng `target`."""
    n = len(plan.plays)
    j = n - 1 - (1 if has_out else 0)
    if j < 0 or plan.plays[j][0] < 0:
        return total
    f = frames[plan.plays[j][0]]
    left = plan.overlaps[j - 1] if j > 0 else 0
    right = plan.overlaps[j] if j < n - 1 else 0
    # phần thân được phép bằng 0 (chỉ còn hai đoạn crossfade nối liền)
    new_end = max(f - (total - target), left + right, 1)
    plan.ends[j] = new_end
    return total - (f - new_end)


def segments(plan: VideoPlan, frames: dict[int, int]) -> list[Segment]:
    """Chia timeline thành các khối: thân mỗi lần phát + đoạn crossfade giữa hai lần phát."""
    out: list[Segment] = []
    n = len(plan.plays)
    for j, (clip, _) in enumerate(plan.plays):
        left = plan.overlaps[j - 1] if j > 0 else 0
        right = plan.overlaps[j] if j < n - 1 else 0
        end = plan.ends.get(j, frames[clip])
        if end - right > left:
            out.append(Segment("body", clip, left, end - right, fade=(j == n - 1)))
        if right:
            out.append(Segment("xfade", clip, end - right, end, clip_b=plan.plays[j + 1][0]))
    return out


def round_order(plan: VideoPlan, r: int = 0) -> list[tuple[int, int]]:
    """Thứ tự clip trong lượt `r` (mặc định lượt đầu): [(chỉ số clip, số lần phát liền nhau)…] — xem trước khi trộn."""
    out: list[tuple[int, int]] = []
    for clip, n, rr in plan.all_plays():
        if clip < 0 or rr != r:
            continue
        if out and out[-1][0] == clip:
            out[-1] = (clip, out[-1][1] + n)
        else:
            out.append((clip, n))
    return out


def describe_rounds(plan: VideoPlan, names: list[str], max_rounds: int = 20) -> str:
    """Mô tả thứ tự phát theo từng vòng, để người dùng xem trước."""
    if plan.error:
        return plan.error

    def nm(c: int) -> str:
        return {INTRO: "Intro", OUTRO: "Outro"}.get(c) or names[c]

    plays = plan.all_plays()
    lines = []
    if plays and plays[0][0] == INTRO:
        lines.append("Mở đầu: Intro")
    rounds: dict[int, list[tuple[int, int]]] = {}
    for clip, n, r in plays:
        if clip >= 0:
            lst = rounds.setdefault(r, [])
            if lst and lst[-1][0] == clip:
                lst[-1] = (clip, lst[-1][1] + n)
            else:
                lst.append((clip, n))
    for r in sorted(rounds)[:max_rounds]:
        parts = [nm(c) + (f" ×{n}" if n > 1 else "") for c, n in rounds[r]]
        lines.append(f"Lượt {r + 1}: " + " → ".join(parts))
    if len(rounds) > max_rounds:
        lines.append(f"… và {len(rounds) - max_rounds} lượt nữa")
    if plays and plays[-1][0] == OUTRO:
        lines.append("Kết thúc: Outro")
    xfs = sum(1 for o in plan.overlaps if o)
    if xfs:
        lines.append(f"\n{xfs} chỗ nối có crossfade.")
    return "\n".join(lines)


# ======================= NHẠC =======================

@dataclass
class MusicItem:
    track: int  # chỉ số trong project.music.tracks
    start: float  # giây trên timeline
    duration: float  # độ dài dùng (có thể bị cắt ở bài cuối)


def music_round(ms: MusicSettings, rng: random.Random, prev_last: int | None) -> list[int]:
    seq: list[int] = []
    first: dict[str, int] = {}
    for i, t in enumerate(ms.tracks):
        if t.enabled and t.plays > 0:
            # xáo ngẫu nhiên: cùng một file nhân bản nhiều dòng = thêm lượt phát của bài đó (không phát 2 lần liền)
            k = i if ms.order == "list" else first.setdefault(os.path.normcase(t.path), i)
            seq += [k] * t.plays
    if not seq or ms.order == "list":
        return seq
    rng.shuffle(seq)
    if ms.order == "shuffle_no_repeat" and len(set(seq)) > 1:
        for _ in range(200):
            if _no_repeat_ok(seq, prev_last):
                break
            rng.shuffle(seq)
        else:
            seq = _spread(seq, prev_last)
    return seq


def _no_repeat_ok(seq: list[int], prev_last: int | None) -> bool:
    if prev_last is not None and seq[0] == prev_last:
        return False
    return all(a != b for a, b in zip(seq, seq[1:]))


def _spread(seq: list[int], prev_last: int | None) -> list[int]:
    """Xếp tham lam: luôn chọn bài còn nhiều lượt nhất, khác bài vừa phát."""
    counts: dict[int, int] = {}
    for x in seq:
        counts[x] = counts.get(x, 0) + 1
    out, last = [], prev_last
    while counts:
        cands = sorted(counts, key=lambda k: (-counts[k], seq.index(k)))
        pick = next((c for c in cands if c != last), cands[0])
        out.append(pick)
        counts[pick] -= 1
        if not counts[pick]:
            del counts[pick]
        last = pick
    return out


def _step(ms: MusicSettings) -> float:
    """Khoảng chồng (+) hoặc khoảng lặng (−) giữa hai bài."""
    return ms.crossfade if ms.crossfade > 0 else -ms.gap


def first_round_seconds(ms: MusicSettings, durations: dict[int, float]) -> float:
    seq = music_round(ms, random.Random(ms.seed), None)
    seq = [i for i in seq if i in durations]
    if not seq:
        return 0.0
    return sum(durations[i] for i in seq) - _step(ms) * (len(seq) - 1)


def rounds_seconds(ms: MusicSettings, durations: dict[int, float], rounds: int) -> float:
    """Độ dài khi phát đúng `rounds` lượt playlist (theo cùng thứ tự ngẫu nhiên như khi xuất)."""
    rng = random.Random(ms.seed)
    seq, prev = [], None
    for _ in range(rounds):
        r = [i for i in music_round(ms, rng, prev) if i in durations]
        if not r:
            break
        seq += r
        prev = r[-1]
    if not seq:
        return 0.0
    return sum(durations[i] for i in seq) - _step(ms) * (len(seq) - 1)


def _place_pins(ms: MusicSettings, seq: list[int], durations: dict[int, float], total: float,
                rng: random.Random) -> list[int]:
    """Lượt đầu: đưa bài ghim lên đầu, hoặc chèn vào vị trí ngẫu nhiên trong phần chắc chắn được phát."""
    pins = [i for i, t in enumerate(ms.tracks) if t.pinned and i in seq]
    if not pins:
        return seq
    rest = list(seq)
    for i in pins:
        rest.remove(i)  # bỏ một lần xuất hiện; nếu bài phát nhiều lần/lượt thì các lần còn lại vẫn ngẫu nhiên
    if ms.pin_pos != "random":
        return _fix_repeats(pins + rest, set(range(len(pins))), ms)
    step = _step(ms)
    budget = total - sum(durations[i] - step for i in pins)  # chừa chỗ cho bài ghim
    fit, t = 0, 0.0
    for i in rest:
        t += durations[i] - step
        if t >= budget:
            break
        fit += 1
    best = None
    for _attempt in range(12):  # ô ngẫu nhiên có thể khiến không xếp được "không lặp liền" → thử ô khác
        out: list[tuple[int, bool]] = [(i, False) for i in rest]
        f = fit
        for i in pins:
            out.insert(rng.randint(0, min(f, len(out))), (i, True))
            f += 1
        cand = _fix_repeats([i for i, _ in out], {k for k, (_, pin) in enumerate(out) if pin}, ms)
        reps = sum(a == b for a, b in zip(cand, cand[1:]))
        if best is None or reps < best[0]:
            best = (reps, cand)
        if not reps or ms.order != "shuffle_no_repeat":
            break
    return best[1]


def _fix_repeats(seq: list[int], fixed: set[int], ms: MusicSettings) -> list[int]:
    """Kiểu "xáo không lặp liền": đổi chỗ các bài KHÔNG ghim để không bài nào phát 2 lần liền nhau
    (bài ghim giữ nguyên vị trí). Không gỡ được hết (quá ít bài) thì lấy cách xếp ít chỗ lặp nhất."""
    if ms.order != "shuffle_no_repeat" or len(set(seq)) < 2:
        return seq

    def n_bad(x: list[int]) -> int:
        return sum(a == b for a, b in zip(x, x[1:]))

    if not n_bad(seq):
        return seq
    s = list(seq)

    def bad(j: int) -> bool:
        return (j > 0 and s[j] == s[j - 1]) or (j + 1 < len(s) and s[j] == s[j + 1])

    for j in range(1, len(s)):  # 1) đổi chỗ cục bộ: giữ gần nguyên thứ tự đã xáo
        if s[j] != s[j - 1]:
            continue
        cand = j if j not in fixed else (j - 1 if j - 1 not in fixed else None)
        if cand is None:
            continue
        for m in range(len(s)):
            if m in fixed or m == cand or s[m] == s[cand]:
                continue
            s[cand], s[m] = s[m], s[cand]
            if not (bad(cand) or bad(m)):
                break
            s[cand], s[m] = s[m], s[cand]
    if not n_bad(s):
        return s
    # 2) xếp lại các ô không ghim: luôn lấy bài còn nhiều lượt nhất, khác bài bên trái (và bài ghim bên phải)
    counts: dict[int, int] = {}
    for k in range(len(s)):
        if k not in fixed:
            counts[s[k]] = counts.get(s[k], 0) + 1
    g = list(s)
    for k in range(len(g)):
        if k in fixed:
            continue
        left = g[k - 1] if k > 0 else None
        right = g[k + 1] if k + 1 < len(g) and k + 1 in fixed else None
        cands = sorted(counts, key=lambda t: (-counts[t], seq.index(t)))
        pick = next((t for t in cands if t != left and t != right), next((t for t in cands if t != left), cands[0]))
        g[k] = pick
        counts[pick] -= 1
        if not counts[pick]:
            del counts[pick]
    return min((s, g), key=n_bad)


def plan_music(ms: MusicSettings, durations: dict[int, float], total: float) -> list[MusicItem]:
    rng = random.Random(ms.seed)
    pin_rng = random.Random(ms.seed * 31 + 7)
    items: list[MusicItem] = []
    start, prev = 0.0, None
    step = _step(ms)
    for r in range(MAX_ROUNDS):
        seq = [i for i in music_round(ms, rng, prev) if i in durations]
        if r == 0:
            seq = _place_pins(ms, seq, durations, total, pin_rng)
        if not seq:
            return items
        for i in seq:
            d = durations[i]
            end = start + d
            if items and total - start < 0.05:  # chỉ còn phần lẻ do làm tròn → không mở thêm bài
                return items
            if end >= total - 1e-3:
                items.append(MusicItem(i, start, max(0.0, min(d, total - start))))
                return items
            items.append(MusicItem(i, start, d))
            start = end - step
            prev = i
    return items


def music_variant(ms: MusicSettings, seed: int) -> MusicSettings:
    """Một bản trong nhiều bản: cùng bài, thứ tự xáo theo `seed` (thứ tự cố định trong bảng → xáo không lặp liền)."""
    import copy
    v = copy.copy(ms)
    v.seed = seed
    v.versions = 1
    if v.order == "list":
        v.order = "shuffle_no_repeat"
    return v


def version_seeds(ms: MusicSettings, durations: dict[int, float], total: float, n: int) -> tuple[list[int], bool]:
    """Chọn hạt giống ngẫu nhiên cho `n` bản sao cho thứ tự phát của các bản khác nhau, và (khi đủ bài) mỗi bản
    mở đầu bằng một bài khác (không tính bài ghim ở đầu). Trả về (seeds, có_trùng)."""
    if n <= 1:
        return [ms.seed], False
    key = (n, ms.seed, ms.order, ms.crossfade, ms.gap, ms.pin_pos, round(total, 3),
           tuple((t.enabled, t.plays, t.pinned) for t in ms.tracks), tuple(sorted(durations.items())))
    if key in _seed_cache:
        seeds, dup = _seed_cache[key]
        return list(seeds), dup
    res = _version_seeds(ms, durations, total, n)
    if len(_seed_cache) > 64:
        _seed_cache.clear()
    _seed_cache[key] = (list(res[0]), res[1])
    return res


_seed_cache: dict[tuple, tuple[list[int], bool]] = {}
SEED_TRIES = 150  # số lần thử tìm thứ tự mới cho mỗi bản


def _version_seeds(ms: MusicSettings, durations: dict[int, float], total: float, n: int) -> tuple[list[int], bool]:
    pins = {i for i, t in enumerate(ms.tracks) if t.pinned}
    pool = {i for i, t in enumerate(ms.tracks) if t.enabled and t.plays > 0 and i in durations and i not in pins}
    want_new_opener = len(pool) >= n
    seeds, orders, openers = [], set(), set()
    dup = False
    active = {i for i, t in enumerate(ms.tracks) if t.enabled and t.plays > 0 and i in durations}
    exhausted = len(active) < 2  # 1 bài: mọi bản giống nhau, khỏi thử
    for k in range(n):
        chosen = None
        for attempt in range(0 if exhausted else SEED_TRIES):
            s = (ms.seed + k * 1_000_003 + attempt * 7_919) % 2_147_483_647
            order = tuple(it.track for it in plan_music(music_variant(ms, s), durations, total))
            opener = next((t for t in order if t not in pins), None)
            if order in orders:
                continue
            if want_new_opener and opener in openers and attempt < SEED_TRIES * 2 // 3:
                continue
            chosen = (s, order, opener)
            break
        if chosen is None:
            exhausted = True  # đã hết thứ tự mới: các bản sau không tìm nữa (tránh treo giao diện)
        if chosen is None:  # quá ít bài để mọi bản khác nhau
            dup = True
            s = (ms.seed + k * 1_000_003) % 2_147_483_647
            order = tuple(it.track for it in plan_music(music_variant(ms, s), durations, total))
            chosen = (s, order, None)
        seeds.append(chosen[0])
        orders.add(chosen[1])
        openers.add(chosen[2])
    return seeds, dup


def validate_music(ms: MusicSettings, durations: dict[int, float]) -> str | None:
    used = [durations[i] for i, t in enumerate(ms.tracks) if t.enabled and t.plays > 0 and i in durations]
    if not used:
        return None
    if ms.crossfade > 0 and ms.crossfade * 2 > min(used):
        return f"Crossfade {ms.crossfade:g}s quá dài: phải ≤ một nửa bài ngắn nhất ({min(used) / 2:.1f}s)."
    return None
