"""
radar_model.py — the data-driven SDVX skill radar (NOTES / PEAK / TSUMAMI /
TRICKY / HAND-TRIP / ONE-HAND), a port of the SDVX Chart Editor's
`SkillRadarModel` (SDVXEditor.Core Patterns/ + Radar/RadarModel.cs).

    chart → 85 time-based pattern features → per-axis additive model
    (intercept + linear terms + regression trees) → clamp → round

The model file `radar_model.json` (next to this script) holds aggregate fitted
numbers only — regression weights, tree split thresholds on the features below
and leaf values — fitted on the official charts of the user's own game install.
It contains no chart data. Specification: the editor's docs/RADAR_MODEL.md; the
C# code is the reference implementation and this module follows it statement
by statement (same units, same order of floating-point operations), so both
give identical radar values for the same chart.

Measured against the official music_db radar (8,573 charts, song-grouped 5-fold
CV): MAE NOTES 0.10, PEAK 2.0, TSUMAMI 2.3, TRICKY 10.7, HAND-TRIP 2.8,
ONE-HAND 3.2 — the classic radar.py is at 13–43.

Input is a pulse-precise chart description (240 pulses per quarter note, like
kson) that ksh2vox's own parsers build next to their tick data
(`parsed["radar_input"]`, see `chart_input`). Ticks (48 per quarter) are not
precise enough: a ksh measure of 40 or 36 lines falls between ticks, and the
rhythm-grid features look at pulse mod 60 / 40.

Standard library only.
"""
from __future__ import annotations

import bisect
import json
import math
import os

__version__ = "0.1.0"

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "radar_model.json")
MODEL_SCHEMA = 1

RADAR_KEYS = ("notes", "peak", "tsumami", "tricky", "hand_trip", "one_hand")

PPQ = 240                      # pulses per quarter note (kson, the editor)
WHOLE = 4 * PPQ                # a 4/4 measure
SLAM_MAX_PULSES = WHOLE // 32  # 1/32 note: ksh writes a slam as two lines this far apart

# PatternAnalysis constants
JACK_GAP = 0.12
STREAM_GAP = 0.15
BURST_GAP = 0.07
DIRECTION_HYSTERESIS = 0.05
SLAM_NEAR_PULSES = 60
EPS = 1e-6
LANE_HAND = (0, 0, 1, 1, 0, 1)  # BT A, BT B, FX L left; BT C, BT D, FX R right


# ═════════════════════════════════════════════════════════════════════════════
# input: what ksh2vox's parsers record (pulse-precise)
# ═════════════════════════════════════════════════════════════════════════════
def new_input() -> dict:
    """An empty chart description; the parsers fill it.

    notes   [(lane 0..5, pulse, length)]        lane 0-3 BT A-D, 4/5 FX L/R
    lasers  [[section], [section]]  section = {"y": pulse, "w": 1|2,
            "points": [[ry, v, vf|None, (a, b)|None], …]}  values 0..1
            ksh_lasers  a .ksh fills this instead of "lasers": per lane
            [(width, [[pulse, v, curve|None], …])] as written, slams still
            to be collapsed (`finish_ksh_lasers`)
    bpm     [(pulse, bpm)]  in the order the editor's Chart.Beat.Bpm holds them
    stops   [(pulse, length)]
    scroll  [[pulse, v, vf|None]]
    end     explicit end pulse (ksh last bar line, editor kson end_pulse) or None
    spins   number of lane spins / half spins / swings
    """
    return {"notes": [], "lasers": [[], []], "bpm": [], "stops": [],
            "scroll": [], "end": None, "spins": 0}


def _prepared(inp: dict) -> dict:
    """A .ksh input carries its raw laser lines in "ksh_lasers"; collapse them."""
    if inp.get("ksh_lasers") is None:
        return inp
    out = dict(inp)
    out["lasers"] = finish_ksh_lasers(inp["ksh_lasers"])
    out["ksh_lasers"] = None
    return out


def _is_slam(pts, i) -> bool:
    """KshReader.IsSlam — K-Shoot's own writer rule (see ksh2vox._is_slam)."""
    if _dense_changes(pts, i + 1, +1) > 0:
        return False
    gap = pts[i + 1][0] - pts[i][0]
    if gap >= SLAM_MAX_PULSES:
        return True
    if _dense_changes(pts, i, -1) > 0:
        return False
    return i + 2 < len(pts) and pts[i + 2][0] - pts[i][0] <= 2 * SLAM_MAX_PULSES


def _dense_changes(pts, k, d) -> int:
    changes = 0
    n = k + d
    while 0 <= n < len(pts):
        a, b = (pts[k], pts[n]) if d > 0 else (pts[n], pts[k])
        if b[0] - a[0] >= SLAM_MAX_PULSES:
            break
        if b[1] != a[1]:
            changes += 1
        k, n = n, n + d
    return changes


def finish_ksh_lasers(raw_sections) -> list:
    """ksh laser sections [(width, [[pulse, v, curve], …]), …] per lane →
    sections in the `lasers` shape, slams collapsed exactly like
    KshReader.CollapseSlams (dense-movement rule on, baked curve points kept —
    the editor's radar reads a .ksh with CollapseBakedCurves = false)."""
    lasers = [[], []]
    for lane in range(2):
        for width, pts in raw_sections[lane]:
            if not pts:
                continue
            out = []
            i = 0
            while i < len(pts):
                p = pts[i]
                if i + 1 < len(pts):
                    q = pts[i + 1]
                    if q[1] != p[1] and q[0] - p[0] <= SLAM_MAX_PULSES and _is_slam(pts, i):
                        out.append([p[0], p[1], q[1], q[2] if q[2] is not None else p[2]])
                        i += 2
                        continue
                out.append([p[0], p[1], None, p[2]])
                i += 1
            y0 = out[0][0]
            lasers[lane].append({"y": y0, "w": width,
                                 "points": [[p[0] - y0, p[1], p[2], p[3]] for p in out]})
        lasers[lane].sort(key=lambda s: s["y"])
    return lasers


# ── kson (KsonReader shapes) ────────────────────────────────────────────────
def _num(x, default=0.0) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return default
    return float(x)


def _int(x, default=0) -> int:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return default
    return int(x)


def _kson_value(n):
    """Value slot: number, [v, vf], [v] or {v, vf} → (v, vf|None)."""
    if isinstance(n, list):
        if len(n) >= 2:
            return _num(n[0]), _num(n[1])
        if len(n) == 1:
            return _num(n[0]), None
        raise ValueError("empty value")
    if isinstance(n, dict):
        return _num(n.get("v")), (_num(n["vf"]) if "vf" in n and n["vf"] is not None else None)
    if isinstance(n, bool) or not isinstance(n, (int, float)):
        raise ValueError("expected number")
    return float(n), None


def _kson_curve(n):
    if isinstance(n, list) and len(n) >= 2:
        return _num(n[0]), _num(n[1])
    return None


def _kson_graph(entries) -> list:
    out = []
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict):
            inner = e.get("v")
            if isinstance(inner, dict):
                v, vf = _kson_value(inner)
            else:
                v, vf = _num(inner), (_num(e["vf"]) if e.get("vf") is not None else None)
            out.append([_int(e.get("y")), v, vf])
        elif isinstance(e, list) and e:
            v, vf = _kson_value(e[1] if len(e) > 1 else None)
            out.append([_int(e[0]), v, vf])
    out.sort(key=lambda p: p[0])
    return out


def _guard(fn, default):
    try:
        return fn()
    except (TypeError, ValueError, KeyError, IndexError, AttributeError):
        return default


def kson_input(doc: dict) -> dict:
    """The radar input of a kson document, read the way the editor's
    KsonReader reads it (raw pulses, explicit slams, curves, width)."""
    inp = new_input()
    note = doc.get("note") if isinstance(doc.get("note"), dict) else {}
    beat = doc.get("beat") if isinstance(doc.get("beat"), dict) else {}

    def lanes(key, count, base):
        src = note.get(key)
        res = []
        for lane in range(min(count, len(src) if isinstance(src, list) else 0)):
            for e in src[lane] if isinstance(src[lane], list) else []:
                if isinstance(e, dict):
                    res.append((base + lane, _int(e.get("y")), _int(e.get("l"))))
                elif isinstance(e, list):
                    res.append((base + lane, _int(e[0]), _int(e[1]) if len(e) > 1 else 0))
                else:
                    res.append((base + lane, _int(e), 0))
        return res

    inp["notes"] = _guard(lambda: lanes("bt", 4, 0), []) + _guard(lambda: lanes("fx", 2, 4), [])

    def sections():
        src = note.get("laser")
        out = [[], []]
        for lane in range(min(2, len(src) if isinstance(src, list) else 0)):
            for s in src[lane]:
                if isinstance(s, dict):
                    y, pts, w = s.get("y"), s.get("v"), s.get("w", s.get("wide"))
                else:
                    y = s[0]
                    pts = s[1] if len(s) > 1 else None
                    w = s[2] if len(s) > 2 else None
                sec = {"y": _int(y), "w": 1 if w is None else _int(w, 1), "points": []}
                for p in pts if isinstance(pts, list) else []:
                    if isinstance(p, dict):
                        v = _num(p.get("v"))
                        vf = _num(p["vf"]) if p.get("vf") is not None else None
                        c = (_num(p.get("a")), _num(p.get("b"))) \
                            if p.get("a") is not None or p.get("b") is not None else None
                        sec["points"].append([_int(p.get("ry")), v, vf, c])
                    else:
                        v, vf = _kson_value(p[1] if len(p) > 1 else None)
                        sec["points"].append([_int(p[0]), v, vf,
                                              _kson_curve(p[2] if len(p) > 2 else None)])
                sec["points"].sort(key=lambda q: q[0])
                out[lane].append(sec)
            out[lane].sort(key=lambda q: q["y"])
        return out

    inp["lasers"] = _guard(sections, [[], []])

    def by_pulse(entries, conv):
        res = []
        for e in entries if isinstance(entries, list) else []:
            if isinstance(e, dict):
                res.append((_int(e.get("y")), conv(e.get("v"))))
            elif isinstance(e, list):
                res.append((_int(e[0]), conv(e[1] if len(e) > 1 else None)))
            else:
                raise ValueError("ByPulse entry")
        return res

    inp["bpm"] = sorted(_guard(lambda: by_pulse(beat.get("bpm"), _num), []), key=lambda b: b[0])
    inp["stops"] = _guard(lambda: by_pulse(beat.get("stop"), _int), [])
    inp["scroll"] = _guard(lambda: _kson_graph(beat.get("scroll_speed")), [])

    impl = doc.get("impl") if isinstance(doc.get("impl"), dict) else {}
    ours = impl.get("sdvx-editor") if isinstance(impl.get("sdvx-editor"), dict) else {}
    ep = ours.get("end_pulse")
    if isinstance(ep, (int, float)) and not isinstance(ep, bool) and math.isfinite(ep):
        inp["end"] = int(ep)

    cam = doc.get("camera") if isinstance(doc.get("camera"), dict) else {}
    cc = cam.get("cam") if isinstance(cam.get("cam"), dict) else {}
    pat = cc.get("pattern") if isinstance(cc.get("pattern"), dict) else {}
    pl = pat.get("laser") if isinstance(pat.get("laser"), dict) else {}
    se = pl.get("slam_event") if isinstance(pl.get("slam_event"), dict) else {}
    for key in ("spin", "half_spin", "swing"):
        lst = se.get(key)
        if isinstance(lst, list) and all(isinstance(e, list) and e for e in lst):
            inp["spins"] += len(lst)
    return inp


# ═════════════════════════════════════════════════════════════════════════════
# .NET's List<T>.Sort
# ═════════════════════════════════════════════════════════════════════════════
# The reference sorts with List<T>.Sort(Comparison), an introsort that is not
# stable. Where keys tie, the resulting order decides the order of
# floating-point sums (laser travel events of the two knobs at the same time),
# and a sum one ulp off can flip a tree split whose threshold coincides with a
# training value (official chart 2282 MXM: laser_speed_peak 3.000000000000001
# against a threshold of exactly that, TRICKY 56 vs 57). So the same algorithm
# is used here (ArraySortHelper<T>.IntrospectiveSort, .NET 5+), on the same
# input order.
def _net_sort(a: list, cmp) -> None:
    n = len(a)
    if n > 1:
        _intro_sort(a, 0, n, 2 * (n.bit_length() - 1 + 1), cmp)


def _swap_if_greater(a, cmp, i, j):
    if cmp(a[i], a[j]) > 0:
        a[i], a[j] = a[j], a[i]


def _intro_sort(a, lo, hi, depth, cmp):
    size = hi - lo
    while size > 1:
        if size <= 16:
            if size == 2:
                _swap_if_greater(a, cmp, lo, lo + 1)
                return
            if size == 3:
                _swap_if_greater(a, cmp, lo, lo + 1)
                _swap_if_greater(a, cmp, lo, lo + 2)
                _swap_if_greater(a, cmp, lo + 1, lo + 2)
                return
            for i in range(lo, lo + size - 1):            # insertion sort
                t = a[i + 1]
                j = i
                while j >= lo and cmp(t, a[j]) < 0:
                    a[j + 1] = a[j]
                    j -= 1
                a[j + 1] = t
            return
        if depth == 0:
            _heap_sort(a, lo, size, cmp)
            return
        depth -= 1
        p = _pick_pivot_and_partition(a, lo, size, cmp)
        _intro_sort(a, p + 1, lo + size, depth, cmp)
        size = p - lo


def _pick_pivot_and_partition(a, lo, size, cmp) -> int:
    hi = lo + size - 1
    mid = lo + ((size - 1) >> 1)
    _swap_if_greater(a, cmp, lo, mid)
    _swap_if_greater(a, cmp, lo, hi)
    _swap_if_greater(a, cmp, mid, hi)
    pivot = a[mid]
    a[mid], a[hi - 1] = a[hi - 1], a[mid]
    left, right = lo, hi - 1
    while left < right:
        left += 1
        while cmp(a[left], pivot) < 0:
            left += 1
        right -= 1
        while cmp(pivot, a[right]) < 0:
            right -= 1
        if left >= right:
            break
        a[left], a[right] = a[right], a[left]
    if left != hi - 1:
        a[left], a[hi - 1] = a[hi - 1], a[left]
    return left


def _heap_sort(a, lo, n, cmp):
    for i in range(n >> 1, 0, -1):
        _down_heap(a, lo, i, n, cmp)
    for i in range(n, 1, -1):
        a[lo], a[lo + i - 1] = a[lo + i - 1], a[lo]
        _down_heap(a, lo, 1, i - 1, cmp)


def _down_heap(a, lo, i, n, cmp):
    d = a[lo + i - 1]
    while i <= n >> 1:
        child = 2 * i
        if child < n and cmp(a[lo + child - 1], a[lo + child]) < 0:
            child += 1
        if not cmp(d, a[lo + child - 1]) < 0:
            break
        a[lo + i - 1] = a[lo + child - 1]
        i = child
    a[lo + i - 1] = d


def _cmp(x, y) -> int:
    return (x > y) - (x < y)


# ═════════════════════════════════════════════════════════════════════════════
# timing (TimingMap, offset 0)
# ═════════════════════════════════════════════════════════════════════════════
class _Timing:
    def __init__(self, bpm_events):
        bpms = [(int(y), float(b)) for y, b in sorted(bpm_events, key=lambda e: e[0]) if b > 0]
        if not bpms or bpms[0][0] > 0:
            bpms.insert(0, (0, bpms[0][1] if bpms else 120.0))
        dedup = {}
        for y, b in bpms:                      # last value wins on duplicate pulses
            dedup[y] = b
        self.y = list(dedup.keys())
        self.v = list(dedup.values())
        self.start = [0.0] * len(self.y)
        for i in range(1, len(self.y)):
            self.start[i] = self.start[i - 1] + _pulses_to_ms(self.y[i] - self.y[i - 1], self.v[i - 1])

    def index(self, pulse) -> int:
        return max(0, bisect.bisect_right(self.y, math.floor(pulse)) - 1)

    def bpm_at(self, pulse) -> float:
        return self.v[self.index(pulse)]

    def sec(self, pulse) -> float:
        i = self.index(pulse)
        return (0 + self.start[i] + _pulses_to_ms(pulse - self.y[i], self.v[i])) / 1000.0

    def pulse_at(self, seconds) -> float:
        t = seconds * 1000.0 - 0
        lo, hi, i = 0, len(self.start) - 1, 0
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.start[mid] <= t:
                i = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return self.y[i] + (t - self.start[i]) * self.v[i] * PPQ / 60000.0


def _pulses_to_ms(pulses, bpm) -> float:
    return pulses * 60000.0 / (bpm * PPQ)


def _interval_pulses(bpm) -> int:
    """TickRules.IntervalPulses: 1/16 below 256 BPM, halved per octave above."""
    if not bpm > 0:
        bpm = 120
    octave = max(int(math.floor(math.log2(bpm))) - 7, 0)
    note_value = 16 / math.pow(2, octave)
    return max(1, int(round(WHOLE / note_value)))


def _hold_ticks(y, length, interval) -> list:
    ticks = []
    end = y + length
    t = y + interval
    while t < end - interval:
        ticks.append(t)
        t += interval
    if not ticks:
        ticks.append(y + int(length / 2))     # C# long division truncates
    return ticks


def _laser_ticks(sec, interval):
    ticks, slams = [], []
    pts = sec["points"]
    if not pts:
        return ticks, slams
    part_start = sec["y"]
    after_slam = False

    def add_part(a, b, skip_first):
        n = int((b - a) / interval) if b >= a else -int((a - b) / interval)
        for i in range(1 if skip_first else 0, n):
            ticks.append(a + i * interval)

    for p in pts:
        if not (p[2] is not None and p[2] != p[1]):
            continue
        at = sec["y"] + p[0]
        add_part(part_start, at, after_slam)
        slams.append(at)
        part_start = at
        after_slam = True
    add_part(part_start, sec["y"] + pts[-1][0], after_slam)
    return ticks, slams


# ═════════════════════════════════════════════════════════════════════════════
# PatternChart
# ═════════════════════════════════════════════════════════════════════════════
def _curve_apply(c, x) -> float:
    a, b = c
    if a == b:
        return x
    x = min(max(x, 0.0), 1.0)
    disc = a * a + (1 - 2 * a) * x
    den = a + math.sqrt(max(0.0, disc))
    t = x / den if den > 1e-12 else math.sqrt(x)
    return 2 * (1 - t) * t * b + t * t


class _Laser:
    __slots__ = ("side", "wide", "start", "end", "y", "pts", "points")

    def __init__(self, side, sec, sec_fn):
        self.side = side
        self.wide = sec["w"] == 2
        self.y = sec["y"]
        self.pts = sec["points"]
        # (pulse, t, v, after, slam)
        self.points = [(self.y + p[0], sec_fn(self.y + p[0]), p[1],
                        p[2] if p[2] is not None else p[1],
                        p[2] is not None and p[2] != p[1]) for p in self.pts]
        self.start = self.points[0][1]
        self.end = self.points[-1][1]

    def value_at(self, pulse) -> float:
        """CameraEvaluator.ValueAt."""
        pts = self.pts
        last = len(pts) - 1
        for i in range(last, -1, -1):
            y = self.y + pts[i][0]
            if y > pulse:
                continue
            after = pts[i][2] if pts[i][2] is not None else pts[i][1]
            if y == pulse or i == last:
                return after
            q = pts[i + 1]
            x = (pulse - y) / (q[0] - pts[i][0])
            c = pts[i][3]
            f = _curve_apply(c, x) if c is not None else x
            return after + (q[1] - after) * f
        return pts[0][1] if pts else 0.0

    def moving_at(self, pulse, window) -> bool:
        pts = self.points
        for p in pts:
            if p[4] and abs(p[0] - pulse) <= window:
                return True
        for i in range(len(pts) - 2, -1, -1):
            if pts[i][0] > pulse:
                continue
            return abs(pts[i + 1][2] - pts[i][3]) > 1e-6
        return False


class PatternChart:
    def __init__(self, inp: dict):
        self.input = inp
        timing = _Timing(inp.get("bpm") or [])
        self.timing = timing
        sec = timing.sec

        # Chart.Notes: per lane, sorted by pulse (NoteData.SortAll), lanes in
        # order BT A-D, FX L/R; then PatternChart's (pulse, lane) sort
        by_lane = [[] for _ in range(6)]
        for lane, y, ln in inp.get("notes") or []:
            by_lane[lane].append((y, ln))
        notes = []
        for lane in range(6):
            _net_sort(by_lane[lane], lambda a, b: _cmp(a[0], b[0]))
            for y, ln in by_lane[lane]:
                notes.append((sec(y), sec(y + ln), lane, ln > 0, y, y + ln))
        _net_sort(notes, lambda a, b: _cmp(a[4], b[4]) if a[4] != b[4] else _cmp(a[2], b[2]))
        self.notes = notes                     # (t, end, lane, hold, pulse, end_pulse)

        lasers = [[], []]
        for side in range(2):
            for s in (inp.get("lasers") or [[], []])[side]:
                if not s["points"]:
                    continue
                lasers[side].append(_Laser(side, s, sec))
            _net_sort(lasers[side], lambda a, b: _cmp(a.start, b.start))
        self.lasers = lasers

        units = []
        hold_ticks = laser_ticks = slams = 0
        for n in notes:
            if not n[3]:
                units.append(n[0])
                continue
            for t in _hold_ticks(n[4], n[5] - n[4], _interval_pulses(timing.bpm_at(n[4]))):
                units.append(sec(t))
                hold_ticks += 1
        for lane in lasers:
            for l in lane:
                ticks, sl = _laser_ticks({"y": l.y, "points": l.pts},
                                         _interval_pulses(timing.bpm_at(l.y)))
                for t in ticks:
                    units.append(sec(t))
                for s in sl:
                    units.append(sec(s))
                laser_ticks += len(ticks)
                slams += len(sl)
        units.sort()
        self.hold_ticks, self.laser_ticks, self.slams = hold_ticks, laser_ticks, slams
        self.unit_times = units

        last = 0.0
        for n in notes:
            last = max(last, n[1])
        for lane in lasers:
            for l in lane:
                last = max(last, l.end)
        duration = last
        end = inp.get("end")
        if end is not None:
            te = sec(end)
            if te >= 0.5 * last:
                duration = te
        self.duration = max(duration, 1.0)

    def sec(self, pulse) -> float:
        return self.timing.sec(pulse)


# ═════════════════════════════════════════════════════════════════════════════
# PatternAnalysis
# ═════════════════════════════════════════════════════════════════════════════
def _window_max(s, w) -> int:
    best = j = 0
    for i in range(len(s)):
        while s[j] <= s[i] - w:
            j += 1
        if i - j + 1 > best:
            best = i - j + 1
    return best


def _window_counts(s, w) -> list:
    vals = []
    j = 0
    for i in range(len(s)):
        while s[j] <= s[i] - w:
            j += 1
        vals.append(float(i - j + 1))
    vals.sort()
    return vals


def _window_sum_max(ev, w) -> float:
    best = total = 0.0
    j = 0
    for i in range(len(ev)):
        total += ev[i][1]
        while ev[j][0] <= ev[i][0] - w:
            total -= ev[j][1]
            j += 1
        best = max(best, total)
    return best


def _percentile(s, p) -> float:
    return s[int(math.floor(p * (len(s) - 1)))] if s else 0.0


def _kde_max(s, sigma) -> float:
    if not s:
        return 0.0
    best = 0.0
    lo = 0
    n = len(s)
    for i in range(n):
        x = s[i]
        acc = 0.0
        while s[lo] < x - 4 * sigma:
            lo += 1
        k = lo
        while k < n and s[k] <= x + 4 * sigma:
            d = (s[k] - x) / sigma
            acc += math.exp(-0.5 * d * d)
            k += 1
        best = max(best, acc)
    return best / (sigma * math.sqrt(2 * math.pi))


def _min_span_rate(s, k) -> float:
    if len(s) < 2:
        return 0.0
    if len(s) <= k:
        return (len(s) - 1) / max(0.05, s[-1] - s[0])
    best = math.inf
    for i in range(len(s) - k):
        best = min(best, s[i + k] - s[i])
    return k / max(best, 0.05)


def _merge(iv) -> list:
    out = []
    for a, b in sorted((x for x in iv if x[1] > x[0]), key=lambda x: x[0]):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _union_length(iv) -> float:
    total = 0.0
    for a, b in _merge(iv):
        total += b - a
    return total


def _intersection_length(a, b) -> float:
    total = 0.0
    i = j = 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if hi > lo:
            total += hi - lo
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return total


def _direction_changes(seq) -> int:
    if not seq:
        return 0
    d = changes = 0
    anchor = ext = seq[0]
    for x in seq[1:]:
        if d == 0:
            if abs(x - anchor) >= DIRECTION_HYSTERESIS:
                d = (x > anchor) - (x < anchor)
                ext = x
        elif d > 0:
            if x > ext:
                ext = x
            elif ext - x >= DIRECTION_HYSTERESIS:
                changes += 1
                d = -1
                ext = x
        else:
            if x < ext:
                ext = x
            elif x - ext >= DIRECTION_HYSTERESIS:
                changes += 1
                d = 1
                ext = x
    return changes


def _fraction_positive(a, b) -> float:
    if a > EPS and b > EPS:
        return 1.0
    if a <= EPS and b <= EPS:
        return 0.0
    z = a / (a - b)
    return z if a > b else 1 - z


def _far_time(s: _Laser) -> float:
    total = 0.0
    pts = s.points
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        dt = q[1] - p[1]
        if dt <= 0:
            continue
        a = p[3] - 0.5 if s.side == 0 else 0.5 - p[3]
        b = q[2] - 0.5 if s.side == 0 else 0.5 - q[2]
        total += dt * _fraction_positive(a, b)
    return total


def _crossed_time(pc: PatternChart) -> float:
    total = 0.0
    steps = 32
    for l in pc.lasers[0]:
        for r in pc.lasers[1]:
            a, b = max(l.start, r.start), min(l.end, r.end)
            if b <= a:
                continue
            dt = (b - a) / steps
            for k in range(steps):
                t = a + (k + 0.5) * dt
                pulse = pc.timing.pulse_at(t)
                if l.value_at(pulse) > r.value_at(pulse) + EPS:
                    total += dt
    return total


def _round_digits(x, digits) -> float:
    """.NET Math.Round(double, digits): scale, round half to even, unscale."""
    p = 10.0 ** digits
    return round(x * p) / p


def _tempo(pc: PatternChart):
    bpms = sorted([b for b in (pc.input.get("bpm") or []) if b[1] > 0], key=lambda b: b[0])
    if not bpms:
        return 0, 0.0, 0.0, 0.0
    changes = 0
    beat_len = 0.0
    for i in range(1, len(bpms)):
        if abs(bpms[i][1] - bpms[i - 1][1]) <= 0.01:
            continue
        changes += 1
        beat_len += abs(60.0 / bpms[i][1] - 60.0 / bpms[i - 1][1])
    time = {}
    end = pc.duration
    for i in range(len(bpms)):
        a = min(end, pc.sec(bpms[i][0]))
        b = min(end, pc.sec(bpms[i + 1][0])) if i + 1 < len(bpms) else end
        if b <= a:
            continue
        key = _round_digits(bpms[i][1], 2)
        time[key] = time.get(key, 0.0) + (b - a)
    if time:
        total = 0.0
        for v in time.values():
            total += v
        off_main = 1 - max(time.values()) / max(EPS, total)
        used = list(time.keys())
    else:
        off_main = 0.0
        used = [b[1] for b in bpms]
    ratio = math.log(max(used) / min(used))
    return changes, ratio, beat_len, off_main


def _scroll_changes(points) -> int:
    n = 0
    prev = 1.0
    for y, v, vf in sorted(points, key=lambda p: p[0]):
        after = vf if vf is not None else v
        if abs(v - prev) > EPS:
            n += 1
        if abs(after - v) > EPS:
            n += 1
        prev = after
    return n


def _trills(chords, hand) -> int:
    count = 0
    prev_lane = prev_prev_lane = -1
    prev_t = prev_prev_t = -math.inf
    for t, _, mask in chords:
        lane, k = -1, 0
        for l in range(6):
            if mask & (1 << l) and LANE_HAND[l] == hand:
                lane = l
                k += 1
        if k == 0:
            continue
        if k > 1:
            lane = -2
        if (lane >= 0 and prev_lane >= 0 and prev_prev_lane >= 0 and lane == prev_prev_lane
                and lane != prev_lane and t - prev_t <= STREAM_GAP and prev_t - prev_prev_t <= STREAM_GAP):
            count += 1
        prev_prev_lane, prev_prev_t = prev_lane, prev_t
        prev_lane, prev_t = lane, t
    return count


def _finite(v) -> float:
    v = float(v)
    return v if math.isfinite(v) else 0.0


def analyze(pc: PatternChart):
    """PatternAnalysis.Analyze → (ordered [(name, value)], note count, section count)."""
    f = []

    def add(name, v):
        f.append((name, _finite(v)))

    notes = pc.notes
    dur = pc.duration

    def per_sec(c):
        return c / dur

    # 1. volume
    chips = holds = bt_chips = fx_chips = bt_holds = fx_holds = 0
    hold_time = 0.0
    for n in notes:
        fx = n[2] >= 4
        if n[3]:
            holds += 1
            if fx:
                fx_holds += 1
            else:
                bt_holds += 1
            hold_time += n[1] - n[0]
        else:
            chips += 1
            if fx:
                fx_chips += 1
            else:
                bt_chips += 1
    add("dur", dur)
    add("chips_ps", per_sec(chips))
    add("holds_ps", per_sec(holds))
    add("bt_chips_ps", per_sec(bt_chips))
    add("fx_chips_ps", per_sec(fx_chips))
    add("bt_holds_ps", per_sec(bt_holds))
    add("fx_holds_ps", per_sec(fx_holds))
    add("hold_time_frac", hold_time / dur)
    add("chain_ps", per_sec(len(pc.unit_times)))
    add("hold_ticks_ps", per_sec(pc.hold_ticks))
    add("laser_ticks_ps", per_sec(pc.laser_ticks))

    # 2. chords and peaks
    chords = []                                # (t, pulse, mask)
    i = 0
    while i < len(notes):
        j, mask = i, 0
        while j < len(notes) and notes[j][4] == notes[i][4]:
            mask |= 1 << notes[j][2]
            j += 1
        chords.append((notes[i][0], notes[i][4], mask))
        i = j
    chord_t = [c[0] for c in chords]
    chord2 = chord3 = split = btfx = 0
    for _, _, mask in chords:
        k = bin(mask).count("1")
        if k >= 2:
            chord2 += 1
        if k >= 3:
            chord3 += 1
        l = r = False
        for lane in range(6):
            if mask & (1 << lane):
                if LANE_HAND[lane] == 0:
                    l = True
                else:
                    r = True
        if l and r:
            split += 1
        if (mask & 0x0F) and (mask & 0x30):
            btfx += 1
    n_chords = float(max(1, len(chords)))
    add("chord_ps", per_sec(len(chords)))
    add("chord2_frac", chord2 / n_chords)
    add("chord3_frac", chord3 / n_chords)
    add("split_chord_frac", split / n_chords)
    add("btfx_chord_frac", btfx / n_chords)

    note_t = [n[0] for n in notes]
    for w, name in ((0.5, "0.5"), (1.25, "1.25"), (2.5, "2.5"), (5.0, "5")):
        add(f"peak_chords_{name}", _window_max(chord_t, w) / w)
    for w, name in ((1.25, "1.25"), (2.5, "2.5")):
        add(f"peak_notes_{name}", _window_max(note_t, w) / w)
    add("peak_units_2.5", _window_max(pc.unit_times, 2.5) / 2.5)
    counts = _window_counts(chord_t, 1.25)
    add("chords_1.25_p90", _percentile(counts, 0.90) / 1.25)
    add("chords_1.25_p75", _percentile(counts, 0.75) / 1.25)
    add("chords_1.25_p50", _percentile(counts, 0.50) / 1.25)
    add("kde_chords_0.5", _kde_max(chord_t, 0.5))
    add("span_chords_8", _min_span_rate(chord_t, 8))
    add("span_chords_16", _min_span_rate(chord_t, 16))

    # 3. hands, jacks, trills, streams
    hand_t = ([], [])
    for t, _, mask in chords:
        l = r = False
        for lane in range(6):
            if mask & (1 << lane):
                if LANE_HAND[lane] == 0:
                    l = True
                else:
                    r = True
        if l:
            hand_t[0].append(t)
        if r:
            hand_t[1].append(t)
    hp0 = _window_max(hand_t[0], 1.25) / 1.25
    hp1 = _window_max(hand_t[1], 1.25) / 1.25
    add("hand_peak_max", max(hp0, hp1))
    add("hand_peak_min", min(hp0, hp1))
    hn0 = sum(1 for n in notes if LANE_HAND[n[2]] == 0)
    hn1 = len(notes) - hn0
    add("hand_balance", min(hn0, hn1) / float(max(1, max(hn0, hn1))))

    jack_inner = jack_outer = jack_fx = 0
    last_by_lane = [-math.inf] * 6
    for n in notes:
        gap = n[0] - last_by_lane[n[2]]
        if EPS < gap <= JACK_GAP:
            if n[2] in (1, 2):
                jack_inner += 1
            elif n[2] in (0, 3):
                jack_outer += 1
            else:
                jack_fx += 1
        last_by_lane[n[2]] = n[0]
    add("jack_ps", per_sec(jack_inner + jack_outer + jack_fx))
    add("jack_inner_ps", per_sec(jack_inner))
    add("jack_outer_ps", per_sec(jack_outer))
    add("jack_fx_ps", per_sec(jack_fx))
    add("trill_ps", per_sec(_trills(chords, 0) + _trills(chords, 1)))

    in_stream, run, bursts, irregular, gap_pairs = 0, 1, 0, 0, 0
    for i in range(1, len(chord_t) + 1):
        cont = i < len(chord_t) and chord_t[i] - chord_t[i - 1] <= STREAM_GAP
        if cont:
            run += 1
            continue
        if run >= 8:
            in_stream += run
        run = 1
    for i in range(1, len(chord_t)):
        if chord_t[i] - chord_t[i - 1] <= BURST_GAP:
            bursts += 1
    for i in range(1, len(chord_t) - 1):
        g1, g2 = chord_t[i] - chord_t[i - 1], chord_t[i + 1] - chord_t[i]
        if g1 > 1 or g2 > 1 or g1 <= EPS or g2 <= EPS:
            continue
        gap_pairs += 1
        lr = math.log2(max(g1, g2) / min(g1, g2))
        if abs(lr - round(lr)) > 0.1:
            irregular += 1
    add("stream_frac", in_stream / n_chords)
    add("burst_frac", bursts / n_chords)
    add("irregular_frac", irregular / float(max(1, gap_pairs)))

    # 4. rhythm grid
    off16 = triplet = odd = 0
    for n in notes:
        on16, on24 = n[4] % 60 == 0, n[4] % 40 == 0
        if not on16:
            off16 += 1
            if on24:
                triplet += 1
            else:
                odd += 1
    n_notes = float(max(1, len(notes)))
    add("offgrid16_frac", off16 / n_notes)
    add("triplet_frac", triplet / n_notes)
    add("odd_frac", odd / n_notes)

    # 5. holds and nesting
    hold_list = [n for n in notes if n[3]]
    nested = nested_same = nested_fx = 0
    for n in notes:
        if n[3]:
            continue
        any_, same, fxh = False, False, False
        for h in hold_list:
            if h[0] > n[0]:
                break
            if h[2] == n[2] or not (h[0] < n[0] - 0.001 and h[1] > n[0] + 0.001):
                continue
            any_ = True
            if LANE_HAND[h[2]] == LANE_HAND[n[2]]:
                same = True
            if h[2] >= 4:
                fxh = True
        nested += any_
        nested_same += same
        nested_fx += fxh
    add("nested_ps", per_sec(nested))
    add("nested_same_hand_ps", per_sec(nested_same))
    add("nested_fx_hold_ps", per_sec(nested_fx))
    add("nested_frac", nested / float(max(1, chips)))

    # 6. lasers
    all_sections = pc.lasers[0] + pc.lasers[1]
    laser_union = _union_length([(s.start, s.end) for s in all_sections])
    both = _intersection_length(_merge([(s.start, s.end) for s in pc.lasers[0]]),
                                _merge([(s.start, s.end) for s in pc.lasers[1]]))
    moving, travel_events, slam_times = [], [], []
    travel = slam_travel = wide_time = laser_time = 0.0
    dir_changes = slams = 0
    for s in all_sections:
        laser_time += s.end - s.start
        if s.wide:
            wide_time += s.end - s.start
        seq = []
        pts = s.points
        for i in range(len(pts)):
            p = pts[i]
            seq.append(p[2])
            if p[4]:
                slams += 1
                slam_travel += abs(p[3] - p[2])
                slam_times.append(p[1])
                seq.append(p[3])
            if i + 1 >= len(pts):
                continue
            q = pts[i + 1]
            dv = abs(q[2] - p[3])
            if dv > EPS:
                travel += dv
                travel_events.append((q[1], dv))
                if q[1] > p[1]:
                    moving.append((p[1], q[1]))
        dir_changes += _direction_changes(seq)
    _net_sort(travel_events, lambda a, b: _cmp(a[0], b[0]))
    slam_times.sort()
    add("laser_frac", laser_union / dur)
    add("laser_both_frac", both / dur)
    add("laser_moving_frac", _union_length(moving) / dur)
    add("laser_wide_frac", wide_time / laser_time if laser_time > 0 else 0)
    add("laser_sections_ps", per_sec(len(all_sections)))
    add("laser_travel_ps", per_sec(travel))
    add("laser_dirchg_ps", per_sec(dir_changes))
    add("slam_ps", per_sec(slams))
    add("slam_travel_ps", per_sec(slam_travel))
    add("laser_speed_peak", _window_sum_max(travel_events, 1.0))
    add("slam_peak_2", _window_max(slam_times, 2.0) / 2.0)
    far = 0.0
    for s in all_sections:
        far += _far_time(s)
    add("laser_far_frac", far / dur)
    add("laser_crossed_frac", _crossed_time(pc) / dur)

    # 7. knob + buttons
    oh_opp = oh_opp_chip = oh_opp_mov = oh_opp_hold = 0
    oh_same = oh_same_chip = oh_same_mov = oh_same_far = oh_both = 0
    opp_pulses, same_pulses = set(), set()
    opp_times, same_times = [], []
    ptr = [0, 0]
    for n in notes:
        t = n[0]
        opp = opp_mov = same = same_mov = same_far = False
        active = 0
        for side in range(2):
            lane = pc.lasers[side]
            while ptr[side] < len(lane) and lane[ptr[side]].end < t - EPS:
                ptr[side] += 1
            k = ptr[side]
            while k < len(lane) and lane[k].start <= t + EPS:
                s = lane[k]
                if s.end < t - EPS:
                    k += 1
                    continue
                active |= 1 << side
                mov = s.moving_at(n[4], SLAM_NEAR_PULSES)
                if LANE_HAND[n[2]] == side:
                    same = True
                    if mov:
                        same_mov = True
                    v = s.value_at(n[4])
                    if (v > 0.5 + EPS) if side == 0 else (v < 0.5 - EPS):
                        same_far = True
                else:
                    opp = True
                    if mov:
                        opp_mov = True
                break
        if active == 3:
            oh_both += 1
        if opp:
            oh_opp += 1
            if n[3]:
                oh_opp_hold += 1
            else:
                oh_opp_chip += 1
            if opp_mov:
                oh_opp_mov += 1
            opp_pulses.add(n[4])
            opp_times.append(t)
        if same:
            oh_same += 1
            if not n[3]:
                oh_same_chip += 1
            if same_mov:
                oh_same_mov += 1
            if same_far:
                oh_same_far += 1
            same_pulses.add(n[4])
            same_times.append(t)
    add("onehand_ps", per_sec(oh_opp))
    add("onehand_chip_ps", per_sec(oh_opp_chip))
    add("onehand_hold_ps", per_sec(oh_opp_hold))
    add("onehand_moving_ps", per_sec(oh_opp_mov))
    add("onehand_chord_ps", per_sec(len(opp_pulses)))
    add("onehand_peak_2.5", _window_max(opp_times, 2.5) / 2.5)
    add("handtrip_ps", per_sec(oh_same))
    add("handtrip_chip_ps", per_sec(oh_same_chip))
    add("handtrip_moving_ps", per_sec(oh_same_mov))
    add("handtrip_far_ps", per_sec(oh_same_far))
    add("handtrip_chord_ps", per_sec(len(same_pulses)))
    add("handtrip_peak_2.5", _window_max(same_times, 2.5) / 2.5)
    add("knob_both_notes_ps", per_sec(oh_both))
    add("knob_chord_frac", len(opp_pulses | same_pulses) / n_chords)

    # 8. tempo, stops, scroll (camera travel is not part of the radar, §4.4 of
    #    RADAR_MODEL.md: cam_* are left out — a missing feature counts as 0 and
    #    the radar model has no cam_* inputs; spins are)
    changes, logratio, beatlen, offmain = _tempo(pc)
    add("bpm_changes", changes)
    add("bpm_logratio", logratio)
    add("bpm_beatlen_pm", beatlen / dur * 60)
    add("bpm_offmain_frac", offmain)
    stops = pc.input.get("stops") or []
    stop_sec = 0.0
    for y, ln in stops:
        stop_sec += max(0.0, pc.sec(y + ln) - pc.sec(y))
    add("stops_pm", len(stops) / dur * 60)
    add("stop_frac", stop_sec / dur)
    add("scroll_changes_pm", _scroll_changes(pc.input.get("scroll") or []) / dur * 60)
    add("spins_pm", (pc.input.get("spins") or 0) / dur * 60)
    return f, len(notes), len(all_sections)


# ═════════════════════════════════════════════════════════════════════════════
# model
# ═════════════════════════════════════════════════════════════════════════════
_MODEL = None
_MODEL_ERROR = None


def load_model(path: str = MODEL_PATH):
    """The radar model, or None (error in `model_error()`). Cached."""
    global _MODEL, _MODEL_ERROR
    if _MODEL is not None or _MODEL_ERROR is not None:
        return _MODEL
    try:
        with open(path, encoding="utf-8") as fh:
            m = json.load(fh)
        if m.get("schema") != MODEL_SCHEMA:
            raise ValueError(f"radar model schema {m.get('schema')}, expected {MODEL_SCHEMA}")
        for key in RADAR_KEYS:
            axis = m["axes"][key]
            nf = len(axis.get("features") or [])
            for t in axis.get("trees") or []:
                n = len(t["f"])
                if n == 0 or any(len(t[k]) != n for k in ("t", "l", "r", "v")):
                    raise ValueError(f"{key}: tree arrays differ in length")
                for i, fi in enumerate(t["f"]):
                    if fi >= nf:
                        raise ValueError(f"{key}: tree feature index {fi} out of range")
                    if fi >= 0 and not (i < t["l"][i] < n and i < t["r"][i] < n):
                        raise ValueError(f"{key}: tree children must point forward")
            for lt in axis.get("linear") or []:
                if lt.get("transform", "id") not in ("id", "log1p"):
                    raise ValueError(f"{key}: unknown transform {lt.get('transform')}")
        _MODEL = m
    except FileNotFoundError:
        _MODEL_ERROR = f"{os.path.basename(path)} not found"
    except (OSError, ValueError, KeyError, TypeError) as e:
        _MODEL_ERROR = f"{os.path.basename(path)} unreadable: {e}"
    return _MODEL


def model_error():
    load_model()
    return _MODEL_ERROR


def _predict(axis: dict, feats: dict) -> float:
    y = axis.get("intercept", 0.0)
    for t in axis.get("linear") or []:
        if t["feature"] in feats:
            x = feats[t["feature"]]
            y += t["weight"] * (math.log(1 + max(0.0, x)) if t.get("transform") == "log1p" else x)
    trees = axis.get("trees") or []
    if trees:
        x = [feats.get(name, 0.0) for name in axis.get("features") or []]
        for t in trees:
            f, th, l, r, v = t["f"], t["t"], t["l"], t["r"], t["v"]
            i = 0
            for _ in range(64):
                fi = f[i]
                if fi < 0:
                    y += v[i]
                    break
                i = l[i] if x[fi] <= th[i] else r[i]
            else:
                raise ValueError("regression tree too deep or cyclic")
    lo = axis.get("min", -math.inf)
    hi = axis.get("max", math.inf)
    lo = -math.inf if lo is None else lo
    hi = math.inf if hi is None else hi
    return min(max(y, lo), hi)


def _round_away(x: float) -> int:
    """Math.Round(x, MidpointRounding.AwayFromZero)."""
    a = abs(x)
    r = math.floor(a)
    if a - r >= 0.5:
        r += 1
    return int(r if x >= 0 else -r)


def features(inp: dict) -> dict:
    return dict(analyze(PatternChart(_prepared(inp)))[0])


def compute_input(inp: dict) -> dict:
    """Radar of a radar input dict, ints keyed by RADAR_KEYS."""
    m = load_model()
    if m is None:
        raise RuntimeError(_MODEL_ERROR or "no radar model")
    f, n_notes, n_sections = analyze(PatternChart(_prepared(inp)))
    if n_notes == 0 and n_sections == 0:
        return {k: 0 for k in RADAR_KEYS}
    feats = dict(f)
    return {k: _round_away(_predict(m["axes"][k], feats)) for k in RADAR_KEYS}


def compute(parsed: dict) -> dict:
    """Radar of a chart parsed by ksh2vox (convert_chart / convert_kson)."""
    inp = parsed.get("radar_input")
    if inp is None:
        raise ValueError("chart has no radar_input (parsed by an older ksh2vox?)")
    return compute_input(inp)


def self_check() -> list:
    """Problems found on synthetic charts (empty list = ok); for --self-check."""
    bad = []
    if load_model() is None:
        return [model_error() or "no model"]
    if compute_input(new_input()) != {k: 0 for k in RADAR_KEYS}:
        bad.append("an empty chart is not all zero")
    inp = new_input()
    inp["bpm"] = [(0, 150.0)]
    for i in range(256):                       # 16ths over 16 measures, both hands
        inp["notes"].append((i % 4, i * 60, 0))
    inp["notes"].append((4, 0, 3840))
    inp["lasers"][1].append({"y": 3840, "w": 1, "points": [
        [0, 0.0, None, None], [960, 1.0, 0.0, None], [1920, 0.5, None, (0.2, 0.8)]]})
    inp["end"] = 16 * 960
    names = [n for n, _ in analyze(PatternChart(inp))[0]]
    want = set()
    for k in RADAR_KEYS:
        axis = load_model()["axes"][k]
        want |= set(axis.get("features") or []) | {t["feature"] for t in axis.get("linear") or []}
    missing = sorted(want - set(names))
    if missing:
        bad.append("features the model needs are not computed: " + ", ".join(missing))
    r = compute_input(inp)
    if not all(isinstance(v, int) and 0 <= v <= 200 for v in r.values()) or r["notes"] == 0:
        bad.append(f"synthetic chart gives {r}")
    if _round_away(2.5) != 3 or _round_away(-2.5) != -3 or _round_away(2.4999) != 2:
        bad.append("rounding is not half away from zero")
    return bad
