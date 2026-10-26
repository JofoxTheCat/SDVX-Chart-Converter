"""
radar.py — SDVX skill-radar values (NOTES / PEAK / TSUMAMI / TRICKY / HAND-TRIP /
ONE-HAND) computed from a parsed KSH chart.

The scaling formulas and the 10..1000 clamp are ported verbatim from
kshoot-tools' `src/radar.ts` (MIT, rhythm-gaming/kshoot-tools). The raw chart
statistics that feed them live in the separate `kshoot.js` library, whose source
is not vendored here, so those are reimplemented from the documented semantics of
its stat output:

    notes: N (C chips + H holds) | max density: D | lasers: L (M moving + S slams)
    one hand: O | hand trip: W | jacks: J (BC: b, ADLR: a) | sofulan: F

Upstream itself notes "TODO: find more accurate formulas for TRICKY and other
values", so these numbers approximate the in-game radar rather than reproducing
Konami's exact values — which is still far better than writing zeros (a zero
radar collapses the hexagon to a point in-game).

Tunables are module constants so they can be adjusted without touching logic.
"""
from __future__ import annotations

__version__ = "0.1.1"

TPB = 48                     # ticks per beat (matches ksh2vox)

PEAK_WINDOW_S = 1.0          # sliding window for peak note density
# A jack is a *rapid* same-lane repeat, not merely a close one. Upstream's stat
# output is very selective (Astar MXM19: 21 jacks across 1104 notes, ~2%), so
# this is a tight wall-clock threshold rather than a note-value one — that keeps
# it BPM-independent.
JACK_MAX_GAP_S = 0.12
SLAM_MAX_TICKS = TPB // 8    # laser value change within this span = slam
# KSH records a laser value on every chart line while the knob is held, so points
# are dense; a gap larger than this means the laser stopped. Being generous here
# would keep a knob "active" across rests and inflate ONE-HAND / HAND-TRIP.
LASER_GAP_TICKS = TPB // 2

RADAR_KEYS = ("notes", "peak", "tsumami", "tricky", "hand_trip", "one_hand")


# ── tick ↔ time ──────────────────────────────────────────────────────────────
def _bpm_changes(bpm_events):
    """One BPM per tick, the later event in the list wins — exactly what
    ksh2vox.emit_vox writes to #BPM INFO — sorted by tick. Plain sorting kept
    same-tick duplicates: ksh2vox < 0.17.1 emitted a ranged ksh header
    (`t=35-321`) as an extra event at tick 0, which counted as a tempo change
    (inflated TRICKY) and, sorted by value, let the higher BPM win the timing."""
    uniq = {}
    for t, b in bpm_events:
        uniq[t] = b
    return sorted(uniq.items())


def _tick_to_seconds_fn(bpm_events):
    """Build tick→seconds using the chart's BPM changes.
    bpm_events: [(tick, bpm), ...] (unsorted ok)."""
    ev = _bpm_changes(bpm_events) or [(0, 120.0)]
    if ev[0][0] != 0:
        ev.insert(0, (0, ev[0][1]))
    # cumulative seconds at each bpm change
    cum = [0.0]
    for i in range(1, len(ev)):
        d_ticks = ev[i][0] - ev[i - 1][0]
        bpm = ev[i - 1][1] or 120.0
        cum.append(cum[-1] + d_ticks / TPB * 60.0 / bpm)

    def to_s(tick: int) -> float:
        lo, hi = 0, len(ev) - 1
        while lo < hi:                      # last change at or before `tick`
            mid = (lo + hi + 1) // 2
            if ev[mid][0] <= tick:
                lo = mid
            else:
                hi = mid - 1
        bpm = ev[lo][1] or 120.0
        return cum[lo] + (tick - ev[lo][0]) / TPB * 60.0 / bpm

    return to_s


# ── raw statistics ───────────────────────────────────────────────────────────
def _laser_sections(laser_lane):
    """[(start_tick, end_tick)] for one lane. The parser now hands us real
    sections (it tracks where the KSH lane shows '-'), so this just takes their
    extents — no gap guessing."""
    out = []
    for sec in laser_lane:
        if sec:
            ticks = [t for t, _v in sec]
            out.append((min(ticks), max(ticks)))
    return out


def _laser_value_at(laser_lane, tick):
    """Laser position (0..50) at `tick`, or None when that laser is idle.
    Only looks inside the section covering `tick`."""
    for sec in laser_lane:
        if not sec:
            continue
        ticks = [t for t, _v in sec]
        if min(ticks) <= tick <= max(ticks):
            prev = None
            for t, v in sec:
                if t > tick:
                    break
                prev = v
            return prev
    return None


def raw_stats(parsed: dict) -> dict:
    """Raw per-chart statistics (the inputs the radar formulas expect)."""
    bt, fx, laser = parsed["bt"], parsed["fx"], parsed["laser"]
    to_s = _tick_to_seconds_fn(parsed["bpm"])
    duration = max(to_s(parsed["end"]), 1e-6)

    # button lanes in kshoot order: 0-3 = BT A-D, 4-5 = FX L/R
    lanes = [list(l) for l in bt] + [[(t, ln) for t, ln, *_ in fx[0]],
                                     [(t, ln) for t, ln, *_ in fx[1]]]

    chips = holds = 0
    note_times = []
    for lane in lanes:
        for t, length in lane:
            if length > 0:
                holds += 1
            else:
                chips += 1
            note_times.append(to_s(t))
    notes_total = chips + holds

    # peak density: most notes inside any PEAK_WINDOW_S sliding window
    note_times.sort()
    peak = 0
    j = 0
    for i, t in enumerate(note_times):
        while note_times[j] < t - PEAK_WINDOW_S:
            j += 1
        peak = max(peak, i - j + 1)

    # lasers: slams (near-instant value changes) and slanted CHAINS — a run of
    # consecutive moving segments counts once, matching radar.ts's
    # `slant_laser_chains` (not one per segment).
    slams = moving = 0
    for lane in laser:
        for sec in lane:                       # chains never span two sections
            in_chain = False
            for (t0, v0), (t1, v1) in zip(sec, sec[1:]):
                if v1 == v0:                   # flat → chain ends
                    in_chain = False
                    continue
                if t1 - t0 <= SLAM_MAX_TICKS:
                    slams += 1
                    in_chain = False
                else:
                    if not in_chain:
                        moving += 1
                        in_chain = True

    # one-hand / hand-trip: notes played while a knob is being held
    sections = [( _laser_sections(laser[0]), 0), (_laser_sections(laser[1]), 1)]
    one_hand = wrong_side = 0
    for lane_idx, lane in enumerate(lanes):
        # playfield side of this lane: BT A,B + FX L = left; BT C,D + FX R = right
        lane_left = lane_idx in (0, 1, 4)
        for t, _length in lane:
            active = None
            for secs, li in sections:
                if any(s <= t <= e for s, e in secs):
                    active = li
                    break
            if active is None:
                continue
            one_hand += 1
            pos = _laser_value_at(laser[active], t)
            if pos is None:
                continue
            knob_left = pos < 25            # knob currently on the left half
            if knob_left == lane_left:      # hand hovers over the note's side
                wrong_side += 1

    # jacks: rapid same-lane repeats (wall-clock, so BPM-independent)
    bc_jacks = adlr_jacks = 0
    for lane_idx, lane in enumerate(lanes):
        times = sorted(to_s(t) for t, _ in lane)
        n = sum(1 for a, b in zip(times, times[1:])
                if 0 < b - a <= JACK_MAX_GAP_S)
        if lane_idx in (1, 2):              # BT B/C = inner lanes
            bc_jacks += n
        else:                               # BT A/D + FX L/R = outer lanes
            adlr_jacks += n

    # sofulan: how strongly note spacing is distorted by BPM changes
    ev = _bpm_changes(parsed["bpm"]) or [(0, 120.0)]
    bpm_inverse_differences = sum(
        abs(1.0 / (b[1] or 120.0) - 1.0 / (a[1] or 120.0))
        for a, b in zip(ev, ev[1:]))

    return {
        "duration": duration,
        "chips": chips, "holds": holds, "notes_total": notes_total,
        "peak_note_density": peak,
        "slams": slams, "moving_lasers": moving,
        "one_hand_notes": one_hand, "wrong_side_notes": wrong_side,
        "bc_jacks": bc_jacks, "adlr_jacks": adlr_jacks,
        "bpm_inverse_differences": bpm_inverse_differences,
    }


# ── radar values (formulas ported from radar.ts) ─────────────────────────────
def _from_raw(r: dict) -> dict:
    """radar.ts RadarStat.fromRaw — scaling of the raw per-second rates."""
    return {
        "notes": (16.663 * r["notes"] + 38.798) / 1.5,
        "peak": (2.1644 * r["peak"] + 42.113) / 1.5,
        "tsumami": (20 * r["tsumami"] + 18) / 1.5,
        "one_hand": (64.817 * r["one_hand"]) / 1.5 + 10,
        "hand_trip": (168.25 * r["hand_trip"]) / 1.5 + 10,
        "tricky": (177.18 * r["tricky"]) / 1.5 + 10,
    }


def _clamp(stat: dict) -> dict:
    """radar.ts RadarStat.clamp — every value into [10, 1000]."""
    return {k: 1000.0 if v >= 1000 else (10.0 if v < 10 else v)
            for k, v in stat.items()}


def compute(parsed: dict) -> dict:
    """Radar values for a parsed chart, as ints keyed by RADAR_KEYS.

    Axes with no raw contribution return 0 rather than the clamp floor of 10:
    real music_db entries write 0 there (e.g. a NOVICE chart with no one-hand
    sections), and radar.ts's floor exists for hexagon rendering, not the db."""
    s = raw_stats(parsed)
    d = s["duration"]
    raw = {
        "notes": s["notes_total"] / d,
        "peak": s["peak_note_density"],
        "tsumami": (s["moving_lasers"] + s["slams"]) / d,
        "one_hand": s["one_hand_notes"] / d,
        "hand_trip": s["wrong_side_notes"] / d,
        "tricky": (s["bc_jacks"] + 2 * s["adlr_jacks"]
                   + 4000 * s["bpm_inverse_differences"]) / d,
    }
    clamped = _clamp(_from_raw(raw))
    return {k: (0 if raw[k] == 0 else int(round(clamped[k]))) for k in RADAR_KEYS}


def empty() -> dict:
    """Radar for a chart with no data — the clamped floor (10), not zeros."""
    return {k: int(round(v)) for k, v in _clamp(_from_raw(
        {k: 0 for k in RADAR_KEYS})).items() if k in RADAR_KEYS}
