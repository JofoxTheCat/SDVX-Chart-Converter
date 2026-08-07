#!/usr/bin/env python3
"""
sdvx-chart-importer — convert a K-Shoot/USC (Nautica) KSH song into a SOUND
VOLTEX ∇ (Nabla, VOX FORMAT VERSION 13) song folder for spice2x, plus a
music_db <music> entry.

This is a fresh implementation based on a direct comparison of real Nabla .vox
charts and Nautica .ksh charts (NOT the outdated boringcactus/ksh2vox). It
converts the parts that map deterministically — timing, BT/FX notes (chip+hold),
and laser paths — and uses sane DEFAULTS for the lossy parts (FX/laser effects,
camera/tilt) which come from the bundled template_v13.vox. Audio (.ogg) is
transcoded to .s3v (ASF / WMA-Pro, 2ch 44.1 kHz) via ffmpeg, incl. a trimmed
preview clip.

Usage:
    python ksh2vox.py <ksh_song_folder> --id 9001 [--out ./data_mods/nautica/music]

A KSH song folder holds one .ksh per difficulty (nov/adv/exh/mxm[/inf]) plus the
audio (.ogg) and jacket(s). The output is  <out>/<id>_<ascii>/  with the .vox
charts, .s3v audio and jackets, and a printed <music> entry to add to
music_db.merged.xml.

Only for legitimate use: your own or user-generated Nautica charts. Do not use it
to extract or redistribute proprietary game data.
"""
__version__ = "0.12.0"

# 0.12.0 .kson support (the newer K-Shoot format), preferred over .ksh when a
#        folder ships both — kson stores exact laser values instead of KSH's 51
#        steps and marks slams explicitly, so no 1/32-note heuristic is needed.
#        Verified against a chart present in both formats: notes, holds, laser
#        sections/points, slams and end position come out identical.
#        FIX: the jacket is now taken from the chart's own `jacket=` /
#        meta.jacket_filename instead of the first image in the folder, which
#        picked backgrounds (bg0.jpg, black.jpg) for 3 of 8 Nautica songs.
#        FIX: duplicate #BPM INFO line (a .ksh states its start tempo twice).
# 0.11.0 FIX: slams were converted as very fast movements. KSH writes a slam as
#        two laser values on adjacent lines, and those were emitted at their two
#        distinct ticks, so the game interpolated between them — the laser slid
#        instead of snapping and the slam sound never played. Official charts
#        put both points on the SAME position (measured: 2259 such pairs in five
#        songs, never a run of three). Pairs closer than 1/32 note are now
#        collapsed onto the first point's tick; see _collapse_slams.
# 0.10.0 FIX: .vox files were written with \r\r\n. emit_vox() already ends every
#        line with CRLF and the file was then opened in Windows text mode, so
#        the \n got translated a second time. Official charts of the running
#        game version (2403_esperanza, datecode 2026071400) contain \r\n only;
#        the stray CR sticks to every section header and breaks the parser.
#        FIX: titles the db encoding cannot store no longer become XML numeric
#        character references. cp932 has no Ø, so &#216; was emitted;
#        ifs_layeredfs resolves that to raw byte 0xD8 = ﾘ in Shift_JIS and the
#        title renders wrong. Unmappable characters are now folded to a close
#        cp932 equivalent (see cp932_safe) before writing.
# 0.9.0  FIX: lasers never ended. The parser ignored '-' (laser off), so a whole
#        lane became one section: only the first point got a start marker and
#        only the last an end, leaving lasers on screen drifting to the next
#        one. Real sections are now tracked and each emits 1 (start) / 0 / 2
#        (end); laser lines also match the official 10-field v13 layout.
# 0.8.0  match the CURRENT music_db format (verified against a live ∇ db):
#        radar values are u16 (not u8 — this is why the radar stayed blank),
#        genre u32, version 7, demo_pri -2, no <label>; radar axes with no
#        contribution now write 0 instead of the render floor of 10
# 0.7.0  --radar-names (hyphen/underscore) and --max-exscore for the newer
#        music_db radar spelling soundvoltex.dll also accepts
# 0.6.0  reference SPCONTROLER as the default BG/camera setup; --self-check
# 0.5.0  skill radar computed per chart (radar.py) and written to music_db
# 0.4.0  cross-platform audio: .2dx / MS-ADPCM (default), mono; --audio-format,
#        --audio-channels, pluggable --wma-encoder for .s3v
# 0.3.0  jacket resizing to the game's sizes (300 / 676 / 108 px)
# 0.2.0  safe song ids (--base-db, hard 3071 limit), real music_db schema
#        (label, u8 genre/radar, no empty <maximum>), version 6, difnum x10,
#        KSM difficulty names, Shift_JIS titles
# 0.1.0  initial KSH -> VOX v13 converter + music_db.merged.xml

import argparse
import json
import os
import re
import shutil
import subprocess
import unicodedata

try:                              # skill radar (radar.py next to this script)
    import radar as _radar
except ImportError:               # keep working standalone; radar stays 0
    _radar = None
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "template_v13.vox")

TPB = 48                     # VOX ticks per beat (offset 0..47)
# KSH difficulty file name → (vox suffix, music_db diff index, slot label)
# Difficulty resolution. A chart's slot is taken from (1) the filename stem, then
# (2) the KSH `difficulty=` header — covering both SDVX-style names (nov/adv/exh/
# mxm), KSM/USC names (light/challenge/extended/infinite) and single-letter
# filenames (n/a/e/i/m). Each maps to (vox suffix, music_db slot index 0-4).
_DIFF_ALIASES = {
    # SDVX names
    "nov": ("1n", 0), "novice": ("1n", 0),
    "adv": ("2a", 1), "advanced": ("2a", 1),
    "exh": ("3e", 2), "exhaust": ("3e", 2),
    "inf": ("4i", 3), "infinite": ("4i", 3),
    "grv": ("4i", 3), "gravity": ("4i", 3),
    "hvn": ("4i", 3), "heaven": ("4i", 3), "heavenly": ("4i", 3),
    "vvd": ("4i", 3), "vivid": ("4i", 3),
    "xcd": ("4i", 3), "exceed": ("4i", 3),
    "nbl": ("4i", 3), "nabla": ("4i", 3),
    "mxm": ("5m", 4), "maximum": ("5m", 4),
    # KSM / KSH header names
    "light": ("1n", 0), "challenge": ("2a", 1), "extended": ("3e", 2),
    # single-letter filenames
    "n": ("1n", 0), "l": ("1n", 0),
    "a": ("2a", 1), "c": ("2a", 1),
    "e": ("3e", 2),
    "i": ("4i", 3), "g": ("4i", 3), "h": ("4i", 3),
    "v": ("4i", 3), "x": ("4i", 3), "b": ("4i", 3),
    "m": ("5m", 4),
}
# longer names checked as substrings of a filename (e.g. "mysong_exh.ksh")
_DIFF_SUBSTR = ("novice", "advanced", "exhaust", "infinite", "gravity",
                "heavenly", "heaven", "vivid", "exceed", "nabla", "maximum",
                "challenge", "extended", "light",
                "nov", "adv", "exh", "inf", "grv", "hvn", "vvd", "xcd",
                "nbl", "mxm")


def _resolve_diff(filename: str, header_diff: str | None):
    """Return (vox_suffix, slot) for a chart, or None if undeterminable."""
    stem = os.path.splitext(os.path.basename(filename))[0].lower().strip()
    if stem in _DIFF_ALIASES:                 # exact: single letters + names
        return _DIFF_ALIASES[stem]
    for key in _DIFF_SUBSTR:                  # substring: "song_exh"
        if key in stem:
            return _DIFF_ALIASES[key]
    hd = (header_diff or "").strip().lower()  # fall back to KSH difficulty=
    if hd in _DIFF_ALIASES:
        return _DIFF_ALIASES[hd]
    if hd in ("0", "1", "2", "3", "4"):       # numeric KSH difficulty
        return (("1n", 0), ("2a", 1), ("3e", 2), ("4i", 3), ("5m", 4))[int(hd)]
    return None


# ── KSH laser char ↔ 0..50 ───────────────────────────────────────────────────
def _laser_val(ch: str):
    if ch in ("-",):
        return None            # no laser
    if ch == ":":
        return ":"             # continuation
    o = ord(ch)
    if 48 <= o <= 57:   return o - 48          # 0-9   → 0-9
    if 65 <= o <= 90:   return o - 65 + 10     # A-Z   → 10-35
    if 97 <= o <= 111:  return o - 97 + 36     # a-o   → 36-50
    return None


def parse_ksh(path: str):
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        raw = fh.read().replace("\r\n", "\n").split("\n")
    header, body = {}, []
    i = 0
    while i < len(raw) and raw[i].strip() != "--":
        if "=" in raw[i]:
            k, v = raw[i].split("=", 1)
            header[k.strip()] = v.strip()
        i += 1
    i += 1
    # measures: a list of dicts {lines: [...], beat: (n,d)}
    measures, cur = [], []
    for ln in raw[i:]:
        s = ln.rstrip()
        if s == "--":
            measures.append(cur)
            cur = []
        else:
            cur.append(s)
    if cur:
        measures.append(cur)
    return header, measures


def _measure_lengths(measures):
    """Return per-measure (beat_num, beat_den) honouring inline `beat=` options."""
    num, den = 4, 4
    out = []
    for m in measures:
        for ln in m:
            mt = re.match(r"beat=(\d+)/(\d+)", ln)
            if mt:
                num, den = int(mt.group(1)), int(mt.group(2))
        out.append((num, den))
    return out


def convert_chart(ksh_path: str) -> dict:
    """Parse a .ksh and return the 8 VOX track bodies + beat/bpm/endpos strings."""
    header, measures = parse_ksh(ksh_path)
    beats = _measure_lengths(measures)

    bt = [[], [], [], []]          # chip/hold events per BT lane: (tick,len)
    fx = [[], []]                  # FX lane: (tick,len,effect)
    laser = [[], []]               # per lane: list of sections, each [(tick, val0_50)]
    laser_open = [None, None]      # section currently being built, per lane
    bpm_events = []                # (tick, bpm)
    beat_events = []               # (measure_idx, num, den)

    # initial bpm
    if header.get("t"):
        try:
            bpm_events.append((0, float(header["t"].split("-")[0])))
        except ValueError:
            pass

    tick = 0
    bt_hold = [None] * 4           # open hold start tick per BT lane
    fx_hold = [None] * 2

    for mi, m in enumerate(measures):
        num, den = beats[mi]
        ticks_in_measure = int(TPB * 4 * num / den)
        chart_lines = [ln for ln in m if re.match(r"^[0-9\-:]{4}\|", ln)]
        n = len(chart_lines) or 1
        beat_events.append((mi, num, den))
        li = 0
        for ln in m:
            mt = re.match(r"t=([0-9.]+)", ln)
            if mt:
                bpm_events.append((tick + (li * ticks_in_measure // n), float(mt.group(1))))
            if not re.match(r"^[0-9\-:]{4}\|", ln):
                continue
            t = tick + (li * ticks_in_measure // n)
            parts = ln.split("|")
            btf, fxf, las = parts[0], parts[1], parts[2] if len(parts) > 2 else "--"
            # BT: 1=chip, 2=hold
            for k in range(4):
                c = btf[k]
                if c == "1":
                    bt[k].append((t, 0))
                elif c == "2":
                    if bt_hold[k] is None:
                        bt_hold[k] = t
                elif bt_hold[k] is not None:
                    bt[k].append((bt_hold[k], t - bt_hold[k])); bt_hold[k] = None
            # FX: 1=hold, 2=chip
            for k in range(2):
                c = fxf[k]
                if c == "2":
                    fx[k].append((t, 0, 0))
                elif c == "1":
                    if fx_hold[k] is None:
                        fx_hold[k] = t
                elif fx_hold[k] is not None:
                    fx[k].append((fx_hold[k], t - fx_hold[k], 0)); fx_hold[k] = None
            # Lasers: 2 chars. A section runs from its first value until the
            # lane shows '-' (laser off); ':' keeps the current section open
            # without adding a control point. Without these boundaries every
            # lane would collapse into one endless laser.
            for k in range(2):
                ch = las[k] if k < len(las) else "-"
                v = _laser_val(ch)
                if v is None:                       # '-' → close any open section
                    if laser_open[k]:
                        laser[k].append(laser_open[k])
                        laser_open[k] = None
                elif v == ":":                      # continuation, no new point
                    pass
                else:
                    if laser_open[k] is None:
                        laser_open[k] = []
                    laser_open[k].append((t, v))
            li += 1
        tick += ticks_in_measure

    # close any laser section still open at the end of the chart
    for k in range(2):
        if laser_open[k]:
            laser[k].append(laser_open[k])
            laser_open[k] = None

    # close dangling holds
    for k in range(4):
        if bt_hold[k] is not None:
            bt[k].append((bt_hold[k], tick - bt_hold[k]))
    for k in range(2):
        if fx_hold[k] is not None:
            fx[k].append((fx_hold[k], tick - fx_hold[k], 0))

    end_tick = tick
    return {
        "header": header,
        "bt": bt, "fx": fx, "laser": laser,
        "bpm": bpm_events or [(0, 120.0)],
        "beat": beat_events,
        "end": end_tick,
    }


# ─────────────────────────────────────────────────────────────────────────────
# KSON (the newer K-Shoot format) — same chart data, JSON instead of text
# ─────────────────────────────────────────────────────────────────────────────
# kson counts time in pulses, 240 per quarter note (so a 4/4 measure is 960);
# we count 48 ticks per beat. Both are quarter-note based, so the conversion is
# a plain scale factor and stays correct under any time signature.
KSON_PPQN = 240


def _kson_tick(pulse) -> int:
    return int(round(pulse * TPB / KSON_PPQN))


def _kson_y(entry):
    """Pulse of a note entry. libkson writes a bare int for a chip and
    [y, length] for a hold; the spec's object form uses {'y':…, 'l':…}."""
    if isinstance(entry, dict):
        return entry.get("y", 0)
    if isinstance(entry, list):
        return entry[0]
    return entry


def _kson_len(entry):
    if isinstance(entry, dict):
        return entry.get("l", 0)
    if isinstance(entry, list):
        return entry[1] if len(entry) > 1 else 0
    return 0


def _kson_point(pt):
    """One laser control point → (ry, v, vf).

    Both serialisations occur in the wild. The spec's object form is
    {'ry':…, 'v':…, 'vf':…, 'a':…, 'b':…}; K-Shoot Editor / libkson writes the
    compact array [ry, v, [a, b]] — and encodes a SLAM by putting a two-element
    list in the value slot: [ry, [v, vf], [a, b]]. Verified against the .ksh of
    the same chart: kson point [0, [0.375, 0.125], …] is exactly the KSH slam
    19→6 (of 50) at that pulse, and the per-lane point counts differ by exactly
    the number of KSH slams (lane 0: 157 KSH points vs 127 kson points, 30
    slams). `a`/`b` are curve control values — the VOX side has no equivalent,
    so they are dropped like the KSH curve information already is."""
    if isinstance(pt, dict):
        v = pt.get("v", 0.0)
        return pt.get("ry", 0), v, pt.get("vf", v)
    ry = pt[0]
    val = pt[1] if len(pt) > 1 else 0.0
    if isinstance(val, list):                     # [v, vf] → slam
        return ry, val[0], (val[1] if len(val) > 1 else val[0])
    return ry, val, val


def parse_kson(path: str):
    """Read a .kson and return (header, doc) with a KSH-shaped header dict.

    The header keys mirror the .ksh ones the rest of the pipeline already reads
    (title/artist/level/difficulty/t/m/po/plength), so difficulty resolution,
    audio lookup, preview trimming and the music_db entry all work unchanged."""
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        doc = json.load(fh)
    meta = doc.get("meta") or {}
    bgm = (doc.get("audio") or {}).get("bgm") or {}
    preview = bgm.get("preview") or {}

    bpms = [float(_kson_y(e) if isinstance(e, (int, float)) else
                  (e.get("v") if isinstance(e, dict) else e[1]))
            for e in ((doc.get("beat") or {}).get("bpm") or [])]
    bpms = [b for b in bpms if b > 0] or [120.0]
    lo, hi = min(bpms), max(bpms)
    t = f"{lo:g}" if lo == hi else f"{lo:g}-{hi:g}"

    header = {
        "title": meta.get("title", ""),
        "artist": meta.get("artist", ""),
        "level": str(meta.get("level", 0)),
        # kson stores 0..3; _resolve_diff maps those the same way it maps a
        # numeric KSH `difficulty=`. The filename still wins (see §9) — kson
        # has no separate MXM value either, exactly like KSH's `infinite`.
        "difficulty": str(meta.get("difficulty", "")),
        "t": t,
        "m": bgm.get("filename", ""),
        "jacket": meta.get("jacket_filename", ""),
        "effect": meta.get("chart_author", ""),
        "illustrator": meta.get("jacket_author", ""),
    }
    if "offset" in preview:
        header["po"] = str(preview["offset"])
    if "duration" in preview:
        header["plength"] = str(preview["duration"])
    return header, doc


def convert_kson(path: str) -> dict:
    """Parse a .kson into the same structure convert_chart() returns."""
    header, doc = parse_kson(path)
    note = doc.get("note") or {}
    beat = doc.get("beat") or {}

    bt = [[], [], [], []]
    for lane in range(4):
        for e in (note.get("bt") or [[]] * 4)[lane] if note.get("bt") else []:
            bt[lane].append((_kson_tick(_kson_y(e)),
                             _kson_tick(_kson_len(e))))
    fx = [[], []]
    for lane in range(2):
        for e in (note.get("fx") or [[]] * 2)[lane] if note.get("fx") else []:
            # effect index defaulted to 0, same as the .ksh path
            fx[lane].append((_kson_tick(_kson_y(e)),
                             _kson_tick(_kson_len(e)), 0))

    # Lasers. kson already groups points into sections, which is exactly our
    # internal shape — no '-'/':' bookkeeping needed. Values are 0..1 floats;
    # we scale to the 0..50 domain the KSH path uses (_laser_track divides by
    # 50 again), keeping them float so native kson precision is not rounded
    # away to KSH's 51 steps. A slam point expands to two points on the SAME
    # tick, which is what _collapse_slams would otherwise have to infer.
    laser = [[], []]
    for lane in range(2):
        for sec in (note.get("laser") or [[], []])[lane]:
            if isinstance(sec, dict):
                y, pts = sec.get("y", 0), sec.get("v") or []
            else:
                y, pts = sec[0], (sec[1] if len(sec) > 1 else [])
            out = []
            for pt in pts:
                ry, v, vf = _kson_point(pt)
                t = _kson_tick(y + ry)
                out.append((t, v * 50.0))
                if vf != v:
                    out.append((t, vf * 50.0))    # slam: same tick
            if out:
                laser[lane].append(out)

    bpm_events = []
    for e in (beat.get("bpm") or []):
        if isinstance(e, dict):
            bpm_events.append((_kson_tick(e.get("y", 0)), float(e.get("v", 120))))
        else:
            bpm_events.append((_kson_tick(e[0]), float(e[1])))
    bpm_events.sort()

    # Time signatures are per measure index; build the per-measure list
    # _pos_fn expects. It derives the measure count from the highest index, so
    # every measure up to the end of the chart needs an entry.
    sig = {}
    for e in (beat.get("time_sig") or []):
        if isinstance(e, dict):
            sig[int(e.get("idx", 0))] = (int(e.get("n", 4)), int(e.get("d", 4)))
        else:
            sig[int(e[0])] = (int(e[1]), int(e[2]))

    last = 0
    for lane in bt + fx:
        for ev in lane:
            last = max(last, ev[0] + ev[1])
    for lane in laser:
        for s in lane:
            last = max(last, max(t for t, _ in s))

    beat_events, cur, tick, mi = [], (4, 4), 0, 0
    while True:
        cur = sig.get(mi, cur)
        beat_events.append((mi, cur[0], cur[1]))
        tick += int(TPB * 4 * cur[0] / cur[1])
        mi += 1
        if tick > last:
            break
    # kson has no explicit end marker (a .ksh ends with its last measure), so
    # the chart ends one measure after the final note.
    cur = sig.get(mi, cur)
    beat_events.append((mi, cur[0], cur[1]))
    tick += int(TPB * 4 * cur[0] / cur[1])

    return {
        "header": header,
        "bt": bt, "fx": fx, "laser": laser,
        "bpm": bpm_events or [(0, 120.0)],
        "beat": beat_events,
        "end": tick,
    }


CHART_EXTS = (".ksh", ".kson")


def load_chart(path: str) -> dict:
    """Parse a chart of either format into the common structure."""
    if path.lower().endswith(".kson"):
        return convert_kson(path)
    return convert_chart(path)


def chart_header(path: str) -> dict:
    """Header only — used to name the song before any chart is converted."""
    if path.lower().endswith(".kson"):
        return parse_kson(path)[0]
    return parse_ksh(path)[0]


def pick_charts(names):
    """One chart file per difficulty, preferring .kson over a same-named .ksh.

    Nautica packs increasingly ship both for the same chart (azalea_MXM.ksh +
    azalea_MXM.kson). Converting both would emit the same difficulty twice."""
    charts = [f for f in names if f.lower().endswith(CHART_EXTS)]
    kson_stems = {os.path.splitext(f)[0].lower()
                  for f in charts if f.lower().endswith(".kson")}
    return sorted(f for f in charts
                  if f.lower().endswith(".kson")
                  or os.path.splitext(f)[0].lower() not in kson_stems)


# ── tick → VOX "MMM,BB,OO" (measure/beat/offset), honouring time signatures ───
def _pos_fn(beat_events):
    # build measure boundaries in ticks
    bounds = []      # (start_tick, num, den)
    t = 0
    last = (4, 4)
    sig = {mi: (n, d) for mi, n, d in beat_events}
    nmeas = max(sig) + 1 if sig else 1
    for mi in range(nmeas):
        last = sig.get(mi, last)
        num, den = last
        bounds.append((t, num, den))
        t += int(TPB * 4 * num / den)

    def pos(tick):
        m = 0
        for idx, (st, num, den) in enumerate(bounds):
            span = int(TPB * 4 * num / den)
            if st <= tick < st + span or idx == len(bounds) - 1:
                within = tick - st
                beat = within // TPB
                off = within % TPB
                return f"{idx + 1:03d},{beat + 1:02d},{off:02d}"
        return "001,01,00"
    return pos


def emit_vox(parsed: dict) -> str:
    tpl = open(TEMPLATE, encoding="latin-1").read()
    pos = _pos_fn(parsed["beat"])

    beat_lines = _beat_info(parsed)
    # One BPM entry per tick, last value wins. A .ksh states its starting tempo
    # twice — once in the `t=` header, once as an inline `t=` on the first chart
    # line — which produced a duplicated #BPM INFO line. kson has no such
    # duplication; deduping here fixes both paths.
    bpm_uniq = {}
    for t, b in parsed["bpm"]:
        bpm_uniq[t] = b
    bpm_lines = "\n".join(f"{pos(t)}\t{bpm_uniq[t]:.4f}\t4"
                          for t in sorted(bpm_uniq))
    endpos = pos(parsed["end"])

    # TRACK1 = laser L, 8 = laser R
    t1 = _laser_track(parsed["laser"][0], pos)
    t8 = _laser_track(parsed["laser"][1], pos)
    # TRACK2 = FX-L, 7 = FX-R
    t2 = _fx_track(parsed["fx"][0], pos)
    t7 = _fx_track(parsed["fx"][1], pos)
    # TRACK3-6 = BT A-D
    t3, t4, t5, t6 = (_bt_track(parsed["bt"][k], pos) for k in range(4))

    out = (tpl
           .replace("{{BEAT}}", beat_lines)
           .replace("{{BPM}}", bpm_lines)
           .replace("{{ENDPOS}}", endpos)
           .replace("{{TRACK1}}", t1).replace("{{TRACK2}}", t2)
           .replace("{{TRACK3}}", t3).replace("{{TRACK4}}", t4)
           .replace("{{TRACK5}}", t5).replace("{{TRACK6}}", t6)
           .replace("{{TRACK7}}", t7).replace("{{TRACK8}}", t8))
    return out.replace("\r\n", "\n").replace("\n", "\r\n")


def _beat_info(parsed):
    pos = _pos_fn(parsed["beat"])
    # one entry per signature change (first measure always present)
    lines, last = [], None
    t = 0
    sig = {mi: (n, d) for mi, n, d in parsed["beat"]}
    nmeas = max(sig) + 1 if sig else 1
    cur = (4, 4)
    for mi in range(nmeas):
        cur = sig.get(mi, cur)
        if cur != last:
            lines.append(f"{mi + 1:03d},01,00\t{cur[0]}\t{cur[1]}")
            last = cur
    return "\n".join(lines)


def _bt_track(events, pos):
    return "\n".join(f"{pos(t)}\t{ln}\t0\t12" for t, ln in events)


def _fx_track(events, pos):
    return "\n".join(f"{pos(t)}\t{ln}\t{(eff if ln else 0)}\t12" for t, ln, eff in events)


# A laser that changes value within a 1/32 note is a slam (直角レーザー), not a
# fast movement. Same constant as radar.py's SLAM_MAX_TICKS, which is ported
# from kshoot-tools — 48 ticks per beat, so 6 ticks = 1/32 note.
SLAM_MAX_TICKS = TPB // 8


def _collapse_slams(sec):
    """Snap slam pairs onto a single tick.

    Official v13 charts encode a slam as two control points with the **same**
    position, e.g.

        006,01,00  0.000000  1     ← laser sits at 0
        006,01,00  1.000000  0     ← and is already at 1, same instant

    KSH cannot express that: it writes the two values on adjacent lines, so the
    points come out 1/32 note apart. Emitting them at those two positions makes
    the game interpolate — the laser slides very fast instead of snapping, and
    the slam sound never plays. Collapsing the pair onto the FIRST point's tick
    is what produces a real slam.

    Why the first point: measured over the Nautica charts, the first point of a
    slam pair sits on a beat (offset 0) 2335 times and on the 8th (offset 24)
    1079 times, while the second point never lands on a strong position — it is
    always the 1/32 afterwards. The slam is played on the beat.

    Pairs are consumed two at a time, so a chain of near points becomes a run of
    separate slams rather than a pile-up. Official charts never put more than
    two points on one position (measured: 2259 runs of 2, none longer)."""
    out, i = [], 0
    while i < len(sec):
        t, v = sec[i]
        if i + 1 < len(sec):
            t2, v2 = sec[i + 1]
            if v2 != v and t2 - t <= SLAM_MAX_TICKS:
                out.append((t, v))
                out.append((t, v2))          # same tick → slam
                i += 2
                continue
        out.append((t, v))
        i += 1
    return out


def _laser_track(sections, pos):
    """Emit one VOX laser track from a list of sections.

    Segment marker (3rd field) per official v13 charts: 1 = section start,
    0 = middle, 2 = section end. Omitting the closing 2 leaves the laser on
    screen forever, drifting toward the next section's start — so every section
    must be closed. A one-point section is written twice (1 then 2) so it still
    has an end.

    Slam pairs are snapped onto one tick first, see _collapse_slams.

    Layout is 10 tab-separated fields, matching official v13 output:
    pos, value, seg, 0, 0, 1, 0, 0, 0, 0."""
    out = []
    for sec in sections:
        if not sec:
            continue
        pts = _collapse_slams(sec) if len(sec) > 1 else sec * 2
        last = len(pts) - 1
        for idx, (t, v) in enumerate(pts):
            seg = 1 if idx == 0 else (2 if idx == last else 0)
            out.append(f"{pos(t)}\t{v / 50.0:.6f}\t{seg}\t0\t0\t1\t0\t0\t0\t0")
    return "\n".join(out)


# ── audio + jackets + packaging ──────────────────────────────────────────────
def _ascii_id(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "song"


# Any container ffmpeg can read works as a source; this list is only used to
# pick a sensible file when the KSH `m=` tag is missing/wrong.
AUDIO_EXTS = (".ogg", ".mp3", ".wav", ".flac", ".m4a", ".aac", ".opus",
              ".wma", ".s3v")


def _resolve_audio(folder: str, m_tag: str | None) -> str | None:
    """Resolve the source audio file.

    Order: the KSH `m=` tag (KSM may list several layered files separated by
    `;` — we take the first that exists), then the first audio file in the
    folder by AUDIO_EXTS preference. ffmpeg decodes whatever container it is, so
    ogg / mp3 / wav / flac / m4a / opus / wma all convert the same way.
    """
    if m_tag:
        for name in re.split(r"[;,]", m_tag):
            name = name.strip().strip('"')
            if not name:
                continue
            p = os.path.join(folder, name)
            if os.path.exists(p):
                return p
            # tolerate a wrong extension in the tag: match by stem
            stem = os.path.splitext(name)[0].lower()
            for f in os.listdir(folder):
                if os.path.splitext(f)[0].lower() == stem and \
                        f.lower().endswith(AUDIO_EXTS):
                    return os.path.join(folder, f)
    # fallback: first present audio file, by extension preference
    files = os.listdir(folder)
    for ext in AUDIO_EXTS:
        for f in files:
            if f.lower().endswith(ext):
                return os.path.join(folder, f)
    return None


def make_2dx(src: str, out_path: str,
             ss: float | None = None, dur: float | None = None,
             channels: int | None = None) -> bool:
    """Audio → .2dx (Konami container, MS-ADPCM). Fully cross-platform: MS-ADPCM
    is encodable by ffmpeg on any OS, unlike WMA Pro. The game also looks for
    <id>_<ascii>.2dx (seen in soundvoltex.dll), so this avoids WMA entirely.
    `channels` overrides the global (e.g. mono for the preview).

    Layout: a 2dx container header (0x48) + a 1-entry offset table + one 2DX9
    sub-file (24-byte header + MS-ADPCM RIFF/WAV)."""
    import struct
    import tempfile
    ch = channels if channels is not None else AUDIO_CHANNELS
    if not shutil.which("ffmpeg"):
        print("  [WARN] ffmpeg not found – skipping audio.")
        return False
    wav = tempfile.mktemp(suffix=".wav")
    try:
        pre = (["-ss", f"{ss:.3f}"] if ss else []) + (["-t", f"{dur:.3f}"] if dur else [])
        cmd = ["ffmpeg", "-y"] + pre + ["-i", src, "-vn", "-ac", str(ch),
               "-ar", "44100", "-c:a", "adpcm_ms", wav]
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wav_bytes = open(wav, "rb").read()
    except Exception as e:
        print(f"  [WARN] MS-ADPCM encode failed ({e}).")
        return False
    finally:
        if os.path.exists(wav):
            os.remove(wav)

    # 2DX9 sub-file: "2DX9" | headerSize(0x18) | dataSize | 12 bytes of fields | wav
    fields = struct.pack("<hhhhi", -1, 64, -1, 0, 0)     # track, vol, ?, ?, loop
    entry = b"2DX9" + struct.pack("<II", 0x18, len(wav_bytes)) + fields + wav_bytes
    # container header (0x48) + offset table (one u32) then the entry
    name = os.path.splitext(os.path.basename(out_path))[0].encode("ascii", "ignore")[:16]
    header = name.ljust(16, b"\x00") + struct.pack("<II", 0x48, 1) + b"\x00" * 0x30
    offset_table = struct.pack("<I", 0x48 + 4)           # entry starts right after
    with open(out_path, "wb") as fh:
        fh.write(header + offset_table + entry)
    return True



# with {in} (a decoded wav) and {out} (the .s3v to write). WMA Pro is proprietary
# and only Microsoft can encode it (Media Foundation / WMF), so on Linux this
# points at a Windows encoder — natively on Windows, or via a Windows box. ffmpeg
# CANNOT encode wmapro on any platform; wmav2 is only a placeholder the game may
# reject. Everything else the converter produces is fully cross-platform.
WMA_ENCODER_CMD: str | None = None

# Audio output format: '2dx' (MS-ADPCM, fully cross-platform via ffmpeg — the
# default) or 's3v' (ASF/WMA Pro, needs --wma-encoder, Windows-only). The game
# looks for both <id>_<ascii>.2dx and .s3v.
AUDIO_FORMAT = "2dx"
# Audio channel count: 2 = stereo (faithful, default), 1 = mono (guaranteed
# equal on both sides — use if the game decodes stereo .2dx imbalanced).
# Mono is the default: it is what plays correctly in-game (verified). The game's
# .2dx path renders stereo imbalanced (one side louder), so both the full track
# and the preview are encoded mono. --audio-channels stereo is available for
# experimentation.
AUDIO_CHANNELS = 1

# music_db radar tag spelling. soundvoltex.dll contains BOTH "radar/hand-trip"
# and "radar/hand_trip" (likewise one-hand/one_hand), so old and new db formats
# differ. "hyphen" matches the verified-booting omnimix db and is the default.
RADAR_TAG_STYLE = "hyphen"          # or "underscore"
# The dll also references max_exscore, which the old omnimix db omits.
EMIT_MAX_EXSCORE = False


def _decode_wav(src: str, wav: str, ss, dur) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    pre = (["-ss", f"{ss:.3f}"] if ss else []) + (["-t", f"{dur:.3f}"] if dur else [])
    cmd = ["ffmpeg", "-y"] + pre + ["-i", src, "-vn", "-ac", str(AUDIO_CHANNELS),
           "-ar", "44100", "-map_metadata", "-1", wav]
    try:
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def make_s3v(ogg_path: str, out_path: str,
             ss: float | None = None, dur: float | None = None,
             channels: int | None = None) -> bool:
    """Audio → .s3v (ASF container).

    Real Nabla .s3v files are ASF with **WMA Pro** (2ch / 44.1 kHz, 384k). WMA Pro
    is proprietary; ffmpeg can only DECODE it, and there is no native Linux
    encoder. So the actual encode is delegated to an external WMA Pro encoder
    configured via --wma-encoder (a template with {in}/{out}); on Linux that is a
    Windows encoder (native Windows box recommended — Wine's WMA Pro support is
    unreliable). If none is configured we ONLY produce a wmav2 placeholder, which
    this game rejects — so real audio needs the encoder. `ss`/`dur` trim a clip."""
    import shlex
    import tempfile

    if WMA_ENCODER_CMD:
        if not shutil.which("ffmpeg"):
            print("  [WARN] ffmpeg needed to decode the source before WMA-Pro "
                  "encoding – skipping audio.")
            return False
        wav = tempfile.mktemp(suffix=".wav")
        try:
            if not _decode_wav(ogg_path, wav, ss, dur):
                print("  [WARN] could not decode source audio.")
                return False
            parts = [p.replace("{in}", wav).replace("{out}", out_path)
                     for p in shlex.split(WMA_ENCODER_CMD, posix=(os.name != "nt"))]
            subprocess.run(parts, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return os.path.isfile(out_path) and os.path.getsize(out_path) > 0
        except Exception as e:
            print(f"  [WARN] WMA-Pro encoder failed ({e}); no audio written.")
            return False
        finally:
            if os.path.exists(wav):
                os.remove(wav)

    # No external encoder → wmav2 placeholder (the game likely rejects this).
    if not shutil.which("ffmpeg"):
        print("  [WARN] ffmpeg not found – skipping audio.")
        return False
    pre = (["-ss", f"{ss:.3f}"] if ss else []) + (["-t", f"{dur:.3f}"] if dur else [])
    cmd = (["ffmpeg", "-y"] + pre + ["-i", ogg_path,
           "-vn", "-ac", str(channels if channels is not None else AUDIO_CHANNELS),
           "-ar", "44100", "-map_metadata", "-1",
           "-c:a", "wmav2", "-b:a", "384k", "-f", "asf", out_path])
    try:
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("  [note] audio is wmav2 PLACEHOLDER — this game needs WMA Pro. "
              "Pass --wma-encoder to produce real audio (see README).")
        return True
    except Exception:
        print(f"  [WARN] ffmpeg could not encode audio for {os.path.basename(ogg_path)}.")
        return False


def _preview_window(header: dict) -> tuple[float | None, float | None]:
    """KSH preview offset/length (ms) → (start_s, dur_s). Default ~10 s clip."""
    try:
        po = float(header.get("po", "")) / 1000.0
    except ValueError:
        po = None
    try:
        pl = float(header.get("plength", "")) / 1000.0
    except ValueError:
        pl = None
    if po is None and pl is None:
        return (0.0, 10.0)              # sensible default preview
    return (po or 0.0, pl or 10.0)


_JACKET_SIZES = {"": 300, "_b": 676, "_s": 108}   # normal / big / small (px, square)


def _resolve_jacket(src_folder: str, declared: str | None) -> str | None:
    """Pick the jacket image for one chart.

    The chart names its own jacket — `jacket=` in a .ksh, meta.jacket_filename
    in a .kson — and that name is the only reliable source. Song folders often
    hold several images (backgrounds, layer art), so taking the first file
    alphabetically picks the wrong one: measured over the Nautica charts,
    'Canto IX' would use HoS.png instead of jacket.png, and galvanizer_p3p and
    thedevilincarnate_p3p would use the background (bg0.jpg / black.jpg)
    instead of jak.png. Charts may also declare a different jacket per
    difficulty (AureoLe uses MXM.jpg for its MXM), which the jk_<id>_<n>
    output layout already supports."""
    imgs = [f for f in os.listdir(src_folder)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))]
    if not imgs:
        return None
    if declared:
        name = os.path.basename(declared.strip().replace("\\", "/"))
        for f in imgs:                                 # exact, then case-fold
            if f == name:
                return os.path.join(src_folder, f)
        for f in imgs:
            if f.lower() == name.lower():
                return os.path.join(src_folder, f)
        print(f"  [warn] declared jacket '{name}' not found in the song folder; "
              f"falling back to {imgs[0]}")
    elif len(imgs) > 1:
        print(f"  [warn] no jacket declared and {len(imgs)} images present "
              f"({', '.join(sorted(imgs)[:4])}) — using {imgs[0]}")
    return os.path.join(src_folder, imgs[0])


def place_jackets(src_folder: str, out_folder: str, sid: int, slot_label: int,
                  declared: str | None = None):
    """Write the three jacket sizes the game expects, resized to exact dimensions:
    jk_<id>_<n>.png = 300x300, jk_<id>_<n>_b.png = 676x676, jk_<id>_<n>_s.png =
    108x108. Non-square sources are center-cropped first so they aren't distorted.
    Without resizing the game renders the raw (often huge) jacket at the wrong
    scale in-game and on the result screen."""
    src = _resolve_jacket(src_folder, declared)
    if src is None:
        return
    try:
        from PIL import Image
        im = Image.open(src).convert("RGB")
        w, h = im.size
        if w != h:                                    # center-crop to square
            s = min(w, h)
            im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
        for suffix, size in _JACKET_SIZES.items():
            dst = os.path.join(out_folder, f"jk_{sid:04d}_{slot_label}{suffix}.png")
            im.resize((size, size), Image.LANCZOS).save(dst, "PNG")
    except ImportError:                               # Pillow missing → copy as-is
        for suffix in _JACKET_SIZES:
            shutil.copyfile(src, os.path.join(
                out_folder, f"jk_{sid:04d}_{slot_label}{suffix}.png"))


def _xml_escape(s: str) -> str:
    """Escape only the XML-special characters. Non-ASCII (Japanese etc.) is left
    as real characters so the file encoding (shift_jis, like the base music_db)
    writes actual bytes — the game renders those, but NOT XML numeric character
    references."""
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# Characters Nautica titles like to use that cp932 has no code point for.
# Without this they used to fall through to errors='xmlcharrefreplace', which
# emits e.g. &#216; for Ø — ifs_layeredfs then resolves that reference to raw
# byte 0xD8, which in Shift_JIS is the halfwidth katakana ﾘ. The title renders
# wrong in game (verified in data_mods/_cache/others/music_db.xml). Mapping to a
# close cp932-representable character keeps the title readable instead.
CP932_FALLBACKS = {
    "Ø": "O", "ø": "o", "Æ": "AE", "æ": "ae", "Å": "A", "å": "a",
    "Þ": "TH", "þ": "th", "Ð": "D", "ð": "d", "ß": "ss", "Œ": "OE",
    "œ": "oe", "Ł": "L", "ł": "l", "Đ": "D", "đ": "d",
    "‐": "-", "‑": "-", "⁃": "-", "−": "-",
    "˚": "°", " ": " ", " ": " ", " ": " ",
}


def cp932_safe(s: str, encoding: str = "cp932") -> str:
    """Replace characters the target db encoding cannot represent.

    Numeric character references are NOT an option here — the game does not
    resolve them (CLAUDE.md §4.3), so anything unmappable has to be substituted
    before the file is written. Known look-alikes are mapped, unicode
    decomposition catches most accented letters, and whatever is left becomes
    '?' with a warning so it is visible instead of silently mojibake."""
    if encoding.lower().replace("-", "_") not in ("shift_jis", "sjis", "cp932"):
        return s
    out, dropped = [], []
    for ch in s:
        try:
            ch.encode(encoding)
            out.append(ch)
            continue
        except UnicodeEncodeError:
            pass
        rep = CP932_FALLBACKS.get(ch)
        if rep is None:
            # strip combining marks: é → e, ū → u, …
            rep = "".join(c for c in unicodedata.normalize("NFKD", ch)
                          if not unicodedata.combining(c))
            try:
                rep.encode(encoding)
            except UnicodeEncodeError:
                rep = ""
        if not rep:
            rep = "?"
            dropped.append(ch)
        out.append(rep)
    if dropped:
        print(f"  [warn] title/artist has characters {encoding} cannot store: "
              f"{' '.join(dropped)} → replaced with '?'")
    return "".join(out)


DEFAULT_VERSION = 7          # Current ∇ songs really are version 7 (confirmed
                             # against a live music_db). An earlier theory blamed
                             # version 7 for the boot crash; disassembling
                             # soundvoltex.dll proved the actual cause was song
                             # ids above 3071 (see MAX_SONG_ID).

# The game's per-song difficulty table is [6 difficulties][3072 songs][164 bytes],
# indexed by song id. An id above 3071 (0xBFF) overflows it: the bounds check skips
# the pointer setup but the write still happens → access violation at boot. Song
# ids MUST be <= 3071. (Confirmed by disassembling soundvoltex.dll.)
MAX_SONG_ID = 3071


def _u16(v) -> int:
    """Clamp to the u16 range modern music_db radar fields use. Old (omnimix-era)
    entries declare these as u8; current ∇ entries use u16, and reading a u8 node
    where the game expects u16 is why the radar stayed blank. Real values top out
    around 153, so this ceiling is never hit in practice."""
    try:
        return max(0, min(65535, int(round(v))))
    except (TypeError, ValueError):
        return 0


def _diff_block(tag: str, difnum: int, rad: dict | None = None) -> str:
    """One difficulty sub-block. Defaults match the known-good (omnimix) schema:
    hyphenated radar tags, u8 values, no max_exscore. soundvoltex.dll also
    contains underscore variants (radar/hand_trip, radar/one_hand) and a
    max_exscore string, which newer ∇ entries may use instead — RADAR_TAG_STYLE
    and EMIT_MAX_EXSCORE switch to those without touching this logic.

    present chart → limited 3 (unlocked); difnum 0 → limited 0. `rad` holds the
    computed skill radar; without it the values stay 0."""
    present = difnum > 0
    limited = 3 if present else 0
    r = rad or {}
    ht, oh = (("hand_trip", "one_hand") if RADAR_TAG_STYLE == "underscore"
              else ("hand-trip", "one-hand"))
    max_ex = ('\n        <max_exscore __type="s32">0</max_exscore>'
              if EMIT_MAX_EXSCORE else "")
    return f"""      <{tag}>
        <difnum __type="u8">{difnum}</difnum>
        <illustrator>-</illustrator>
        <effected_by>-</effected_by>
        <price __type="s32">-1</price>
        <limited __type="u8">{limited}</limited>
        <jacket_print __type="s32">-2</jacket_print>
        <jacket_mask __type="s32">0</jacket_mask>{max_ex}
        <radar>
          <notes __type="u16">{_u16(r.get('notes', 0))}</notes>
          <peak __type="u16">{_u16(r.get('peak', 0))}</peak>
          <tsumami __type="u16">{_u16(r.get('tsumami', 0))}</tsumami>
          <tricky __type="u16">{_u16(r.get('tricky', 0))}</tricky>
          <{ht} __type="u16">{_u16(r.get('hand_trip', 0))}</{ht}>
          <{oh} __type="u16">{_u16(r.get('one_hand', 0))}</{oh}>
        </radar>
      </{tag}>"""


def music_entry(sid, ascii_id, header, levels, radars=None,
                db_encoding: str = "Shift_JIS"):
    """Build a <music> entry matching the current ∇ music_db schema exactly.

    Verified field by field against real entries of the running game version
    (song 2403 of data/others/music_db.xml):
      * no <label> — that is the old omnimix-era format.
      * genre is u32; every radar value is u16; max_exscore is omitted.
      * difnum is level × 10 (∇ format).
      * novice/advanced/exhaust are always emitted; infinite/maximum are emitted
        ONLY when that chart exists (difnum > 0). A real db never emits an empty
        <maximum> — doing so makes the game try to load a non-existent MXM chart
        and crash at boot.

    Titles/artists are folded to characters the db encoding can actually store,
    because numeric character references are not an option (see cp932_safe)."""
    title = _xml_escape(cp932_safe(header.get("title", "Unknown"), db_encoding))
    artist = _xml_escape(cp932_safe(header.get("artist", "Unknown"), db_encoding))
    bpm = header.get("t", "120")
    bpm_lo = int(float(bpm.split("-")[0]) * 100)
    bpm_hi = int(float(bpm.split("-")[-1]) * 100)
    inf_ver = 2 if levels.get(3, 0) > 0 else 0      # 4th slot present → INF
    # always nov/adv/exh; infinite/maximum only when the chart exists
    order = [("novice", 0), ("advanced", 1), ("exhaust", 2)]
    if levels.get(3, 0) > 0:
        order.append(("infinite", 3))
    if levels.get(4, 0) > 0:
        order.append(("maximum", 4))
    rads = radars or {}
    diffs = "\n".join(_diff_block(t, levels.get(i, 0) * 10, rads.get(i))
                      for t, i in order)
    return f"""  <music id="{sid}">
    <info>
      <title_name>{title}</title_name>
      <title_yomigana></title_yomigana>
      <artist_name>{artist}</artist_name>
      <artist_yomigana></artist_yomigana>
      <ascii>{ascii_id}</ascii>
      <bpm_max __type="u32">{bpm_hi}</bpm_max>
      <bpm_min __type="u32">{bpm_lo}</bpm_min>
      <distribution_date __type="u32">20260101</distribution_date>
      <volume __type="u16">91</volume>
      <bg_no __type="u16">0</bg_no>
      <genre __type="u32">16</genre>
      <is_fixed __type="u8">1</is_fixed>
      <version __type="u8">{DEFAULT_VERSION}</version>
      <demo_pri __type="s8">-2</demo_pri>
      <inf_ver __type="u8">{inf_ver}</inf_ver>
    </info>
    <difficulty>
{diffs}
    </difficulty>
  </music>"""


def _read_existing_entries(path: str) -> dict:
    """Parse existing <music id=…> blocks from a merged db into {id: block}."""
    if not os.path.exists(path):
        return {}
    for enc in ("cp932", "shift_jis", "utf-8"):
        try:
            with open(path, encoding=enc, errors="ignore") as fh:
                content = fh.read()
            break
        except Exception:
            content = ""
    out = {}
    for mb in re.finditer(r'(<music id="(\d+)">.*?</music>)', content, re.DOTALL):
        out[int(mb.group(2))] = mb.group(1)
    return out


def update_merged_db(merged_path: str, sid: int, entry_xml: str,
                     encoding: str = "Shift_JIS") -> int:
    """Create or update music_db.merged.xml, adding/replacing this song's entry.
    Returns the total number of songs in the merged db. ifs_layeredfs merges
    this file into the base music_db at load time (root <mdb>, one <music> per
    song).

    Matches the real (working) music_db: declared 'Shift_JIS', written as cp932
    bytes (a shift_jis superset that also covers e.g. the fullwidth tilde ～).
    These are real bytes — the game renders them; do NOT use XML numeric
    character references (the game doesn't resolve them). For a UTF-8 base, pass
    encoding='utf-8'."""
    os.makedirs(os.path.dirname(os.path.abspath(merged_path)), exist_ok=True)
    entries = _read_existing_entries(merged_path)
    entries[sid] = entry_xml                       # add or replace
    body = "\n".join(entries[k] for k in sorted(entries))
    doc = (f'<?xml version="1.0" encoding="{encoding}"?>\n'
           f'<mdb>\n{body}\n</mdb>\n')
    # cp932 superset for any shift_jis spelling; utf-8 stays utf-8
    write_codec = ("cp932" if encoding.lower().replace("-", "_") in
                   ("shift_jis", "sjis", "cp932") else encoding)
    # errors='replace', never 'xmlcharrefreplace': a numeric reference like
    # &#216; is not resolved by the game, and ifs_layeredfs turns it into a raw
    # byte that renders as a completely different character. music_entry()
    # already folded unmappable characters via cp932_safe(), so this only
    # catches text that came in through a different path.
    with open(merged_path, "w", encoding=write_codec,
              errors="replace", newline="") as fh:
        fh.write(doc)
    return len(entries)


def convert_song(folder: str, sid: int, out_root: str,
                 merged_path: str | None = None, db_encoding: str = "Shift_JIS"):
    if sid > MAX_SONG_ID:
        print(f"[ERROR] id {sid} exceeds the game limit ({MAX_SONG_ID}). Ids above "
              f"3071 crash the game at boot. Use --base-db, or a lower --id.")
        return None
    ksh_files = pick_charts(os.listdir(folder))
    if not ksh_files:
        print(f"[ERROR] no .ksh / .kson files in {folder}")
        return None
    header0 = chart_header(os.path.join(folder, ksh_files[0]))
    ascii_id = _ascii_id(header0.get("title", os.path.basename(folder)))
    if ascii_id == "song":                 # all-non-ASCII title → keep it unique
        ascii_id = f"nautica{sid}"
    song_dir = os.path.join(out_root, f"{sid:04d}_{ascii_id}")
    os.makedirs(song_dir, exist_ok=True)

    levels = {}
    radars = {}
    audio_src = None
    audio_header = {}
    for kf in ksh_files:
        parsed = load_chart(os.path.join(folder, kf))
        res = _resolve_diff(kf, parsed["header"].get("difficulty"))
        if not res:
            print(f"  [skip] {kf}: unknown difficulty "
                  f"(file='{os.path.splitext(kf)[0]}', "
                  f"difficulty='{parsed['header'].get('difficulty','')}')")
            continue
        suffix, slot = res
        vox = emit_vox(parsed)
        # newline="" is required: emit_vox already ends every line with CRLF.
        # Without it Windows text mode translates the \n again and the file
        # ends up with \r\r\n, which official .vox files never have — the
        # trailing CR then sticks to every section header (#TRACK1\r) and the
        # game's parser stops recognising them.
        with open(os.path.join(song_dir, f"{sid:04d}_{ascii_id}_{suffix}.vox"),
                  "w", encoding="latin-1", newline="") as fh:
            fh.write(vox)
        try:
            levels[slot] = int(parsed["header"].get("level", 0))
        except ValueError:
            levels[slot] = 0
        if _radar is not None:                  # skill radar for this chart
            try:
                radars[slot] = _radar.compute(parsed)
            except Exception as e:
                print(f"  [warn] radar failed for {kf}: {e}")
        place_jackets(folder, song_dir, sid, slot + 1,
                      parsed["header"].get("jacket"))
        if audio_src is None:
            cand = _resolve_audio(folder, parsed["header"].get("m"))
            if cand:
                audio_src = cand
                audio_header = parsed["header"]
        print(f"  [ok] {kf} → {suffix}.vox (lv {levels.get(slot)})")

    # audio: full track + a trimmed preview clip (.s3v = ASF/WMA-Pro).
    # ffmpeg reads any format, so ogg / mp3 / wav / flac / m4a / opus all work.
    if audio_src is None:
        audio_src = _resolve_audio(folder, None)
    if audio_src:
        print(f"  [audio] source: {os.path.basename(audio_src)}")
        ss, dur = _preview_window(audio_header)
        ext = AUDIO_FORMAT
        writer = make_2dx if ext == "2dx" else make_s3v
        full = os.path.join(song_dir, f"{sid:04d}_{ascii_id}.{ext}")
        prev = os.path.join(song_dir, f"{sid:04d}_{ascii_id}_pre.{ext}")
        ok = writer(audio_src, full)
        writer(audio_src, prev, ss=ss, dur=dur)
        if ok:
            kind = "MS-ADPCM, cross-platform" if ext == "2dx" else "WMA"
            print(f"  [ok] audio → .{ext} ({kind}, +preview {ss:.0f}s/{dur:.0f}s)")
    else:
        print("  [WARN] no audio file found in the song folder.")

    entry = music_entry(sid, ascii_id, header0, levels, radars, db_encoding)

    # Automatically create/update the merged music_db so the song actually loads.
    if merged_path:
        total = update_merged_db(merged_path, sid, entry, db_encoding)
        print(f"  [db] merged music_db updated → {merged_path} ({total} song(s))")

    print(f"[DONE] id {sid}: {song_dir}")
    return entry


def _default_merged_path(out_root: str) -> str:
    """layeredfs merges data_mods/<mod>/others/music_db.merged.xml into the base
    data/others/music_db.xml. With out = <mod>/music, the db lives in the
    sibling <mod>/others/ folder."""
    return os.path.join(os.path.dirname(os.path.abspath(out_root)),
                        "others", "music_db.merged.xml")


def convert_batch(parent: str, start_id: int, out_root: str,
                  merged_path: str, db_encoding: str = "Shift_JIS"):
    """Convert every song sub-folder under `parent` (each containing .ksh or
    .kson files), assigning sequential ids from start_id. Builds one merged db
    for the lot."""
    subs = sorted(d for d in os.listdir(parent)
                  if os.path.isdir(os.path.join(parent, d))
                  and any(f.lower().endswith(CHART_EXTS)
                          for f in os.listdir(os.path.join(parent, d))))
    if not subs:
        print(f"[ERROR] no song sub-folders with .ksh / .kson found under {parent}")
        return
    print(f"[BATCH] {len(subs)} song(s) under {parent}, ids from {start_id}\n")
    sid = start_id
    done = 0
    for d in subs:
        print(f"── [{done + 1}/{len(subs)}] {d}  (id {sid})")
        if convert_song(os.path.join(parent, d), sid, out_root,
                        merged_path, db_encoding):
            done += 1
            sid += 1
        print()
    print(f"[BATCH DONE] {done} song(s) imported; merged db: {merged_path}")


def _max_existing_id(path: str) -> int:
    """Highest song id in a base music_db (json or xml). Used to pick custom ids
    that sit just above all real songs — avoiding both collisions and the array
    overflow that very high ids (e.g. 9001) trigger in the game at boot."""
    data = open(path, "rb").read()
    head = data[:200].lstrip()
    if head[:1] == b"{":                       # music_db.json
        import json as _json
        db = _json.loads(data.decode("utf-8", "replace"))
        ids = [int(m["id"]) for m in db.get("mdb", {}).get("music", [])
               if not (isinstance(m.get("info"), dict) and m["info"].get("nautica"))]
    else:                                       # music_db.xml / .merged.xml
        for enc in ("cp932", "shift_jis", "utf-8"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = data.decode("utf-8", "replace")
        ids = [int(i) for i in re.findall(r'<music id="(\d+)"', text)]
    return max(ids) if ids else 0


def main():
    ap = argparse.ArgumentParser(
        description="sdvx-chart-importer — Nautica KSH → SDVX ∇ (VOX v13) + music_db")
    ap.add_argument("--self-check", action="store_true",
                    help="print version + which optional parts are active, then exit")
    ap.add_argument("folder", nargs="?", help="a KSH song folder, or (with --batch) a parent "
                                    "folder of many song folders")
    ap.add_argument("--id", type=int, default=None,
                    help="song id (single) or starting id (--batch). Omit when "
                         "using --base-db. Keep ids just above your real max, NOT "
                         "9001+ (very high ids overflow the game's song array).")
    ap.add_argument("--base-db", default=None,
                    help="path to your real music_db.json (in the plugin) or "
                         "music_db.xml; auto-assigns ids starting just above the "
                         "highest real song id (safe: no collision, no overflow)")
    ap.add_argument("--out", default="./data_mods/nautica/music",
                    help="song output root (default ./data_mods/nautica/music)")
    ap.add_argument("--db", default=None,
                    help="music_db.merged.xml path "
                         "(default <out>/../others/music_db.merged.xml; "
                         "'none' disables auto-merge)")
    ap.add_argument("--db-encoding", default="Shift_JIS",
                    help="merged db encoding (default Shift_JIS, matches the real music_db; use utf-8 if your base is UTF-8)")
    ap.add_argument("--radar-names", choices=("hyphen", "underscore"),
                    default="hyphen",
                    help="music_db radar tag spelling: hand-trip/one-hand "
                         "(default, matches a known-good db) or hand_trip/one_hand "
                         "(the other form soundvoltex.dll accepts)")
    ap.add_argument("--max-exscore", action="store_true",
                    help="also emit <max_exscore> in each difficulty block")
    ap.add_argument("--audio-format", choices=("2dx", "s3v"), default="2dx",
                    help="'2dx' = MS-ADPCM, works on Linux+Windows via ffmpeg "
                         "(default); 's3v' = WMA Pro, needs --wma-encoder (Windows)")
    ap.add_argument("--audio-channels", choices=("mono", "stereo"), default="mono",
                    help="mono (default — what the game actually plays correctly; "
                         "equal on both sides) or stereo (the game's .2dx path "
                         "renders this imbalanced)")
    ap.add_argument("--wma-encoder", default=None,
                    help="external WMA Pro encoder command template, with {in} "
                         "(decoded wav) and {out} (.s3v). e.g. Windows: "
                         "\"MfEncoder.exe {in} {out}\"; Linux via a Windows box. "
                         "Without it, audio is only a wmav2 placeholder the game "
                         "rejects. WMA Pro can't be encoded by ffmpeg/on Linux.")
    ap.add_argument("--batch", action="store_true",
                    help="treat <folder> as a parent of many song folders")
    a = ap.parse_args()

    if a.self_check:
        print(f"ksh2vox {__version__}")
        if _radar is None:
            print("  skill radar : NOT AVAILABLE — radar.py is missing next to "
                  "this script, so radar values will be written as 0")
        else:
            print(f"  skill radar : radar.py {getattr(_radar, '__version__', '?')} loaded")
        tpl = os.path.isfile(TEMPLATE)
        print(f"  template    : {'found' if tpl else 'MISSING'} ({TEMPLATE})")
        print(f"  audio       : {a.audio_format}, "
              f"{'mono' if a.audio_channels == 'mono' else 'stereo'} (defaults)")
        print(f"  ffmpeg      : {'found' if shutil.which('ffmpeg') else 'MISSING'}")
        try:
            from PIL import Image  # noqa: F401
            print("  Pillow      : found (jackets resized to 300/676/108)")
        except ImportError:
            print("  Pillow      : MISSING — jackets will not be resized")
        return

    global WMA_ENCODER_CMD, AUDIO_FORMAT, AUDIO_CHANNELS
    global RADAR_TAG_STYLE, EMIT_MAX_EXSCORE
    RADAR_TAG_STYLE = a.radar_names
    EMIT_MAX_EXSCORE = a.max_exscore
    WMA_ENCODER_CMD = a.wma_encoder
    AUDIO_FORMAT = a.audio_format
    AUDIO_CHANNELS = 1 if a.audio_channels == "mono" else 2

    if a.base_db:
        start_id = _max_existing_id(a.base_db) + 1
        print(f"[id] base-db max id {start_id - 1} → assigning custom ids from {start_id}")
    elif a.id is not None:
        start_id = a.id
    else:
        ap.error("provide --id <n> or --base-db <music_db.json|xml>")

    if start_id > MAX_SONG_ID:
        ap.error(f"start id {start_id} exceeds the game limit {MAX_SONG_ID}. Song ids "
                 f"above 3071 crash the game at boot. Pick lower ids; if --base-db "
                 f"reports a max near 3071 your db is nearly full and there's no safe "
                 f"room for custom songs.")

    if a.db is None:
        merged = _default_merged_path(a.out)
    elif a.db.lower() == "none":
        merged = None
    else:
        merged = a.db

    if a.batch:
        convert_batch(a.folder, start_id, a.out, merged, a.db_encoding)
    else:
        convert_song(a.folder, start_id, a.out, merged, a.db_encoding)


if __name__ == "__main__":
    main()
