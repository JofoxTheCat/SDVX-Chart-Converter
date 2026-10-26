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
__version__ = "0.17.0"

# 0.17.0 What used to be lost in VOX, each mapping measured on the 336 official
#        v13 charts: wide lasers (field 6 = 2; kson `w`, ksh laserrange=2x),
#        kson laser curves baked every 3 ticks with the curve type in field 8,
#        FX hold effects (#FXBUTTON EFFECT INFO per chart, hold index = block
#        position + 2), laser filters (field 5), tilt modes (#TILT MODE INFO
#        0/1/2) and manual tilt (Tilt rows), zoom_top/zoom_bottom as
#        CAM_RotX/CAM_Radi, scroll speed as ManualSpeed rows, stops as `4-`
#        BPM rows, and the chart editor's impl["sdvx-editor"].vox extras
#        (bg_no, #POSTEFFECT, #SPCONTROLER). Unrepresentable data (spins,
#        zoom_side, custom key sounds, …) is reported once per chart.
# 0.16.0 Two timing fixes, both found by diffing against official charts.
#        (1) Non-/4 time signatures: the VOX beat is the denominator note
#        (192/den ticks), so a 6/8 bar runs BB 1..6 with offsets 0..23. Every
#        measure used to be split at 48 ticks (BB 1..3, offsets up to 47).
#        (2) The chart's audio offset (ksh `o=`, kson audio.bgm.offset) was
#        ignored; 6 of the 8 sample songs have one (20..2514 ms). VOX has no
#        offset field, so it is now baked into the full-track audio: a
#        positive offset trims the lead, a negative one pads silence.
#        Also: every .ksh got a phantom last measure (the text after the final
#        "--"); kson ends with the last event's measure, or at the chart
#        editor's impl["sdvx-editor"]["end_pulse"]; kson 1.0 time_sig
#        [idx, [n, d]] no longer crashes; levels keep tenths (difnum 175);
#        an unreadable jacket no longer aborts the song. Slams: a .ksh pair
#        within 1/32 is a slam only by K-Shoot's own rule (_is_slam); a .kson
#        is never inferred from, only its explicit [v, vf] slams count.
# 0.15.0 Custom Songs tag. Every music_db entry now carries <tag id="100"/>
#        right after </difficulty>, the same element and position official
#        entries use for their folder tags (ids 1..44 in the running version,
#        so 100 never collides). A Custom Songs folder set up in spice2x picks
#        up exactly the songs carrying it; before, none of ours did, so that
#        folder stayed empty. On by default, --no-custom-tag turns it off. The
#        setting is recorded per song in the import map, so switching it
#        re-converts what was written the other way — the version bump makes
#        every already-imported song pick the tag up once.
# 0.14.0 Unchanged songs are skipped. A song is re-converted only when its
#        inputs changed (name+size+mtime of every chart/audio/image file), the
#        output went missing, its music_db entry is gone — or THIS converter
#        version differs from the one that produced it. That last condition is
#        the important one: without it, every bug fixed here (slams, CRLF,
#        jackets, credits) would silently never reach already-imported songs.
#        A re-run of an unchanged 9-song library drops from 3.2 s to 0.08 s.
#        --force converts regardless.
# 0.13.0 Stable song ids. Ids used to be positional (sorted folder order from
#        start_id), so importing one song that sorted early renumbered every
#        later song and the whole library had to be rebuilt. A folder → id map
#        next to the merged db now makes an id permanent; --only imports a
#        subset, and a single folder without --id also goes through the map.
#        Verified: adding the alphabetically first song to an 8-song library
#        leaves all 8 ids pointing at the same songs, and a full re-import is
#        a no-op. Also adds the progress= callback the V2 GUI will render from
#        (the print() output stays CLI-only and is meant to go away with V2).
# 0.12.0 .kson support (the newer K-Shoot format), preferred over .ksh when a
#        folder ships both — kson stores exact laser values instead of KSH's 51
#        steps and marks slams explicitly, so no 1/32-note heuristic is needed.
#        Verified against a chart present in both formats: notes, holds, laser
#        sections/points, slams and end position come out identical.
#        FIX: the jacket is now taken from the chart's own `jacket=` /
#        meta.jacket_filename instead of the first image in the folder, which
#        picked backgrounds (bg0.jpg, black.jpg) for 3 of 8 Nautica songs.
#        FIX: duplicate #BPM INFO line (a .ksh states its start tempo twice).
#        music_db <effected_by>/<illustrator> now carry the real credits from
#        `effect=`/`illustrator=` (ksh) or meta.chart_author/meta.jacket_author
#        (kson), per difficulty — they used to be a hard-coded '-'.
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
import collections
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import traceback
import unicodedata

try:                              # skill radar (radar.py next to this script)
    import radar as _radar
except ImportError:               # keep working standalone; radar stays 0
    _radar = None
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "template_v13.vox")

TPB = 48                     # ticks per quarter note; a VOX beat is 192/den (beat_ticks)
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
    # What follows the last "--" is a measure only if it holds chart lines.
    # Usually it is the #define_fx / #define_filter block, which used to be
    # counted as one more (empty) measure: AureoLe's MXM ended at 454,01,00
    # instead of 453,01,00 — one bar of 4/4 longer than the chart (the chart
    # editor's own ksh reader puts the end at 453 too).
    if any(re.match(r"^[0-9\-:]{4}\|", ln) for ln in cur):
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

    # 0.17.0: options beyond notes and timing (see the 0.17.0 block above)
    parsed = {"warnings": []}
    fx_defs, filter_defs = _ksh_defines(ksh_path)
    fx_events = [[], []]           # (tick, spec|None) from fx-l= / fx-r=
    filter_events = []             # (tick, code) from filtertype=
    if header.get("filtertype"):   # legacy header form
        filter_events.append((0, _laser_filter_code(parsed, header["filtertype"],
                                                    filter_defs)))
    tilt_events = []
    cam = {"zoom_top": [], "zoom_bottom": []}
    scroll, stops = [], []
    pending_width = [1, 1]         # laserrange_l/r=2x: widens the next section only
    laser_meta = [[], []]          # per section: {"wide", "curves", "filter"}
    open_width = [1, 1]
    # K-Shoot writes a curved ksh segment together with baked intermediate
    # points (the chart editor's KshReader documents this on ABYSS MOTION, the
    # only library chart with laser_*_curve), so a .ksh curve is already
    # approximated in the chart lines and is not baked a second time.

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
                if "=" in ln and not ln.startswith("//"):
                    _ksh_option(parsed, ln, tick + (li * ticks_in_measure // n),
                                fx_defs, filter_defs, fx_events, filter_events,
                                tilt_events, cam, scroll, stops, pending_width)
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
            if len(las) > 2 and re.search(r"[@S][()<>]", las[2:]):
                _warn(parsed, "lane spins / swings are not converted to VOX "
                              "yet — ignored")
            for k in range(2):
                ch = las[k] if k < len(las) else "-"
                v = _laser_val(ch)
                if v is None:                       # '-' → close any open section
                    if laser_open[k]:
                        laser[k].append(laser_open[k])
                        laser_meta[k].append({"wide": open_width[k], "curves": {}})
                        laser_open[k] = None
                elif v == ":":                      # continuation, no new point
                    pass
                else:
                    if laser_open[k] is None:
                        laser_open[k] = []
                        # `laserrange_x=2x` widens the NEXT section only: the
                        # section opening here consumes it (K-Shoot; the chart
                        # editor's KshReader resets pendingWidth at the same
                        # point, and its KshWriter repeats the option before
                        # every wide section). Never reset, every later section
                        # of that lane came out wide.
                        open_width[k] = pending_width[k]
                        pending_width[k] = 1
                    laser_open[k].append((t, v))
            li += 1
        tick += ticks_in_measure

    # close any laser section still open at the end of the chart
    for k in range(2):
        if laser_open[k]:
            laser[k].append(laser_open[k])
            laser_meta[k].append({"wide": open_width[k], "curves": {}})
            laser_open[k] = None

    # close dangling holds
    for k in range(4):
        if bt_hold[k] is not None:
            bt[k].append((bt_hold[k], tick - bt_hold[k]))
    for k in range(2):
        if fx_hold[k] is not None:
            fx[k].append((fx_hold[k], tick - fx_hold[k], 0))

    # FX hold effects: an fx-l=/fx-r= inside [start, end) of a hold names its
    # effect — the chart editor's KshReader attaches them the same way.
    for k in range(2):
        evs = sorted(fx_events[k], key=lambda e: e[0])
        new = []
        for t, ln, _ in fx[k]:
            spec = 0
            if ln > 0:
                hit = next((e for e in evs if t <= e[0] < t + ln), None)
                if hit and hit[1]:
                    spec = hit[1]
            new.append((t, ln, spec))
        fx[k] = new
    for k in range(2):
        for m, code in zip(laser_meta[k],
                           _section_filters(parsed, laser[k], filter_events)):
            m["filter"] = code

    end_tick = tick
    parsed.update({
        "header": header,
        "bt": bt, "fx": fx, "laser": laser,
        "bpm": bpm_events or [(0, 120.0)],
        "beat": beat_events,
        "end": end_tick,
        "laser_meta": laser_meta,
        "tilt": tilt_events,
        "cam": cam,
        "scroll": scroll,
        "stops": stops,
    })
    return parsed


def _ksh_option(parsed, line, t, fx_defs, filter_defs, fx_events,
                filter_events, tilt_events, cam, scroll, stops, pending_width):
    """One `key=value` option line of a .ksh body at tick `t` (0.17.0)."""
    key, value = (x.strip() for x in line.split("=", 1))
    if key in ("laserrange_l", "laserrange_r"):
        pending_width[0 if key[-1] == "l" else 1] = 2 if value == "2x" else 1
    elif key in ("fx-l", "fx-r"):
        fx_events[0 if key == "fx-l" else 1].append((t, _ksh_fx_spec(value, fx_defs)))
    elif key == "filtertype":
        filter_events.append((t, _laser_filter_code(parsed, value, filter_defs)))
    elif key == "tilt":
        ev = _tilt_events_ksh(value)
        if ev is None:
            _warn(parsed, f"unknown tilt value '{value}' ignored")
        elif ev[0] == "auto":
            tilt_events.append((t, "auto", ev[1]))
        elif tilt_events and tilt_events[-1][0] == t and tilt_events[-1][1] == "manual":
            p = tilt_events[-1]                 # second line: instant change
            tilt_events[-1] = (t, "manual", p[2], ev[1], None)
        else:
            tilt_events.append((t, "manual", ev[1], ev[1], None))
    elif key in ("zoom_top", "zoom_bottom"):
        try:
            _graph_add(cam[key], t, float(value))
        except ValueError:
            pass
    elif key in ("zoom_side", "center_split", "rotation_deg"):
        try:
            if float(value) != 0:
                _warn(parsed, f"camera '{key}' has no VOX counterpart — ignored")
        except ValueError:
            pass
    elif key == "scroll_speed":
        try:
            _graph_add(scroll, t, float(value))
        except ValueError:
            pass
    elif key == "stop":
        try:
            ln = int(float(value))          # 192 per 4/4 measure = VOX ticks
        except ValueError:
            ln = 0
        if ln > 0:
            stops.append((t, ln))
    elif key in ("fx-l_se", "fx-r_se", "chokkakuse"):
        _warn(parsed, "custom chip / slam sounds cannot be represented in VOX "
                      "— the game's default sounds play")
    elif key.startswith("fx:") or key.startswith("filter:") or key == "pfiltergain":
        _warn(parsed, "effect parameter changes / filter gain have no VOX "
                      "counterpart — ignored")


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
    meta = _obj(doc.get("meta"))
    bgm = _obj(_obj(doc.get("audio")).get("bgm"))
    preview = _obj(bgm.get("preview"))

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
    if "offset" in bgm:                 # ksh `o=`, same meaning (see _ffmpeg_window)
        header["o"] = str(bgm["offset"])
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
    # tick — the only slams a kson has. _collapse_slams is NOT run on kson:
    # two points closer than 1/32 here are authored movement, not a slam.
    # 0.17.0: a section's third element `w` (2 = wide) and a point's [a, b]
    # curve are kept in laser_meta; values stay 0..1 over the section's own
    # range — official wide sections use 0..1 too (19,604 v13 sections: width
    # constant within every one, values 0..1 at both widths).
    laser = [[], []]
    laser_meta = [[], []]
    for lane in range(2):
        for sec in (note.get("laser") or [[], []])[lane]:
            if isinstance(sec, dict):
                y, pts = sec.get("y", 0), sec.get("v") or []
                w = sec.get("w", 1)
            else:
                y, pts = sec[0], (sec[1] if len(sec) > 1 else [])
                w = sec[2] if len(sec) > 2 else 1
            out, curves = [], {}
            for pt in pts:
                ry, v, vf = _kson_point(pt)
                t = _kson_tick(y + ry)
                out.append((t, v * 50.0))
                if vf != v:
                    out.append((t, vf * 50.0))    # slam: same tick
                c = _kson_point_curve(pt)
                if c and c[0] != c[1]:
                    curves[len(out) - 1] = c      # shapes the segment after it
            if out:
                laser[lane].append(out)
                laser_meta[lane].append({"wide": 2 if w == 2 else 1,
                                         "curves": curves, "filter": 0})

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
        idx, n, d = _kson_time_sig(e)
        sig[idx] = (n, d)

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
    # the chart ends with the measure that holds the final event. On ABYSS
    # MOTION — the one ksh/kson pair among the samples — that equals the .ksh
    # end (102,01,00 both). Until 0.16.0 one more measure was added, which
    # matched only because the .ksh reader counted a phantom measure too.

    # A .ksh's own end can lie further out (AureoLe: 5½ measures of trailing
    # bars → 453 vs 448). The chart editor keeps that end when it writes kson,
    # as impl["sdvx-editor"]["end_pulse"] (kson pulses). Only that key is read;
    # files without it — every kson from K-Shoot — keep the rule above. A hint
    # before the last event is ignored rather than cutting notes off.
    hint = _obj(_obj(doc.get("impl")).get("sdvx-editor")).get("end_pulse")
    if isinstance(hint, (int, float)) and not isinstance(hint, bool) \
            and math.isfinite(hint) and _kson_tick(hint) >= last:
        # Bounded: a corrupt or hostile hint (1e15) would otherwise build one
        # measure entry per measure up to it and never finish. Real trailing
        # bars are a few measures (AureoLe: 5 1/2); 64 measures of 4/4 is plenty.
        tick = min(_kson_tick(hint), last + TPB * 4 * END_HINT_MAX_MEASURES)
        total = sum(int(TPB * 4 * n / d) for _, n, d in beat_events)
        while total < tick:                    # signatures up to that end
            cur = sig.get(mi, cur)
            beat_events.append((mi, cur[0], cur[1]))
            total += int(TPB * 4 * cur[0] / cur[1])
            mi += 1

    parsed = {
        "header": header,
        "bt": bt, "fx": fx, "laser": laser,
        "bpm": bpm_events or [(0, 120.0)],
        "beat": beat_events,
        "end": tick,
        "explicit_slams": True,      # never infer slams from point spacing
        "laser_meta": laser_meta,
        "warnings": [],
    }
    _kson_extras(parsed, doc)
    if "bg_no" in parsed.get("vox_extras", {}):
        header["bg_no"] = str(parsed["vox_extras"]["bg_no"])
    return parsed


def _kson_point_curve(pt):
    """The [a, b] curve of a kson laser point, or None."""
    try:
        if isinstance(pt, dict):
            return (_fnum(pt["a"]), _fnum(pt["b"])) if "a" in pt and "b" in pt else None
        if len(pt) > 2 and isinstance(pt[2], (list, tuple)) and len(pt[2]) >= 2:
            return (_fnum(pt[2][0]), _fnum(pt[2][1]))
    except (TypeError, KeyError):
        pass
    return None


def _kson_time_sig(e) -> tuple[int, int, int]:
    """One beat.time_sig entry → (measure idx, n, d).

    kson 1.0 writes ByMeasureIdx<TimeSig> as [idx, [n, d]]. Older writers
    used a flat [idx, n, d] and the object forms {idx, n, d} / {idx, v:{n, d}};
    all are accepted. The 1.0 form used to crash (int([n, d]))."""
    if isinstance(e, dict):
        v = e.get("v", e)
        if isinstance(v, (list, tuple)):
            n, d = v[0], v[1]
        else:
            n, d = v.get("n", 4), v.get("d", 4)
        return int(e.get("idx", 0)), int(n), int(d)
    if len(e) >= 2 and isinstance(e[1], (list, tuple, dict)):
        v = e[1]
        n, d = (v[0], v[1]) if isinstance(v, (list, tuple)) else \
               (v.get("n", 4), v.get("d", 4))
        return int(e[0]), int(n), int(d)
    return int(e[0]), int(e[1]), int(e[2])


# ─────────────────────────────────────────────────────────────────────────────
# 0.17.0 — chart data beyond notes and timing
# ─────────────────────────────────────────────────────────────────────────────
# Wide and curved lasers, FX hold effects, laser filters, tilt, camera, scroll
# speed and stops, plus the chart editor's VOX-only extras. Every mapping below
# was measured against the 336 official FORMAT VERSION 13 charts (and, where
# v13 has no example, against the older official charts the running game also
# plays). What could not be proven is written conservatively and listed under
# "Needs a play test" in CHANGELOG.md — nothing here may break a chart that
# converted fine before.

def _warn(parsed: dict, msg: str) -> None:
    """Record a conversion warning once per chart (printed by convert_song)."""
    lst = parsed.setdefault("warnings", [])
    if msg not in lst:
        lst.append(msg)


def _fnum(x, default=0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _fixed(v: float, digits: int) -> str:
    """`v` with a fixed number of decimals, never `-0.00`: a zero that came
    from a negative factor (zoom_bottom 0 × −1/100) or a tiny negative value
    would otherwise print its sign. Official charts write `0.00`."""
    s = f"{v:.{digits}f}"
    return s[1:] if s.startswith("-") and not s.strip("-0.") else s


def _obj(x) -> dict:
    """A kson object node, or {} when the file has something else there."""
    return x if isinstance(x, dict) else {}


def _seq(x) -> list:
    """A kson array node, or [] when the file has something else there."""
    return x if isinstance(x, (list, tuple)) else []


# Raised by malformed 0.17.0 subtrees (a string where a pulse belongs, a
# number where a list belongs, NaN/Infinity from a lenient JSON writer). Such
# a row is skipped with one warning per subtree; it must never end the song.
_BAD_DATA = (TypeError, ValueError, OverflowError, AttributeError, IndexError,
             KeyError)


def _curve_y(x: float, a: float, b: float) -> float:
    """kson curve: quadratic Bezier (0,0) → (a,b) → (1,1), y for a given x.

    Linear when a == b (spec default [0, 0]). Solves x(t) = 2(1-t)t·a + t² for
    t in the rationalised form t = x / (a + √(a² + (1-2a)x)), which stays
    stable at a = 0.5 and x = 0 (same formula as kson-rs `do_curve`)."""
    x = min(1.0, max(0.0, x))
    if a == b:
        return x
    d = a + math.sqrt(max(0.0, a * a + (1 - 2 * a) * x))
    t = x / d if d > 1e-12 else 0.0
    return 2 * (1 - t) * t * b + t * t


def _kson_graph(entries, on_bad=None) -> list:
    """kson GraphPoint[] → sorted [(tick, v, vf, curve|None)].

    Forms: [y, v], [y, [v, vf]] (instant change), optional third element
    [a, b] shaping the segment to the next point; object form {y, v, vf, a, b}.
    A malformed point is skipped and reported through `on_bad()`."""
    out = []
    for e in _seq(entries):
        try:
            if isinstance(e, dict):
                y, v = e.get("y", 0), e.get("v", 0.0)
                vf = e.get("vf", v)
                c = (e["a"], e["b"]) if "a" in e and "b" in e else None
            else:
                y = e[0]
                val = e[1] if len(e) > 1 else 0.0
                if isinstance(val, (list, tuple)):
                    v, vf = val[0], (val[1] if len(val) > 1 else val[0])
                else:
                    v = vf = val
                c = (tuple(e[2][:2]) if len(e) > 2 and isinstance(e[2], (list, tuple))
                     and len(e[2]) >= 2 else None)
            if isinstance(y, bool) or not isinstance(y, (int, float)):
                raise ValueError(y)
            pt = (_kson_tick(y), _fnum(v), _fnum(vf),
                  (_fnum(c[0]), _fnum(c[1])) if c else None)
        except _BAD_DATA:
            if on_bad:
                on_bad()
            continue
        out.append(pt)
    out.sort(key=lambda p: p[0])
    return out


def _graph_add(graph: list, tick: int, v: float) -> None:
    """ksh graph option: a second value on the same tick is an instant change."""
    if graph and graph[-1][0] == tick:
        t, v0, _, c = graph[-1]
        graph[-1] = (t, v0, v, c)
    else:
        graph.append((tick, v, v, None))


def _graph_pieces(points: list, step: int) -> list:
    """Graph → linear tweens [(tick, duration, from, to)].

    A straight segment is one tween; a curved one is cut into `step`-tick
    pieces (official camera rows are plain linear tweens). An instant change
    at the last point becomes a 0-tick tween, and so does a lone point."""
    pieces = []
    for i, (t, v, vf, c) in enumerate(points):
        if i + 1 >= len(points):
            if v != vf or len(points) == 1:
                pieces.append((t, 0, v, vf))
            break
        t1, v1 = points[i + 1][0], points[i + 1][1]
        if t1 <= t:
            continue
        if c and c[0] != c[1] and vf != v1:
            ticks = list(range(t, t1, max(1, step))) + [t1]
            for ta, tb in zip(ticks, ticks[1:]):
                ya = _curve_y((ta - t) / (t1 - t), *c)
                yb = _curve_y((tb - t) / (t1 - t), *c)
                pieces.append((ta, tb - ta, vf + (v1 - vf) * ya,
                               vf + (v1 - vf) * yb))
        else:
            pieces.append((t, t1 - t, vf, v1))
    return pieces


# ── FX hold effects ──────────────────────────────────────────────────────────
# #FXBUTTON EFFECT INFO holds exactly 12 blocks in all 336 official v13 charts
# (175 distinct tables). An FX hold names its effect by the 3rd field: block
# position + 2, so 2..13 — measured, v13 holds use exactly 2..13 (never 1), and
# the same rule is what VOX2KSH reads (`fx_num = data[1] - 2`). 0 = no effect.
#
# Block type ids (first number). Both public converters agree on 1/8 retrigger,
# 2 gate, 4 tape stop, 5 side chain, 6 wobble, 7 bit crusher, 9 pitch shift;
# the parameter layout confirms each (6: LPF sweep 500..18000 Hz, Q 1.4; 9:
# ±12 semitones). 3 and 12 are disputed: VoxCharger (a ksh→vox converter) says
# 3 = phaser, 12 = flanger; VOX2KSH guesses flanger / high-pass "by ear". The
# 3-row layout (mix, period, feedback, stereo width 90, hi-cut gain) is a
# phaser's, so VoxCharger's reading is used — flagged "needs play test".
#
# The rows are the official ones, never synthesised from KSM parameters: only
# the parameter that names the variant (wave length, reduction, pitch) is
# carried over, everything else is the most common official row of that type.
_FX_KSH_TYPES = {
    "Retrigger": "retrigger", "Gate": "gate", "Flanger": "flanger",
    "PitchShift": "pitch_shift", "BitCrusher": "bitcrusher",
    "Phaser": "phaser", "Wobble": "wobble", "TapeStop": "tapestop",
    "Echo": "echo", "SideChain": "sidechain", "SwitchAudio": "switch_audio",
    "PeakingFilter": "peaking_filter", "HighPassFilter": "high_pass_filter",
    "LowPassFilter": "low_pass_filter",
}
_KSH_PARAM_RENAMES = {"loFreq": "freq_1", "hiFreq": "freq_2", "Q": "q",
                      "overWrap": "overlap", "volume": "vol"}
_ZERO_ROW = "0,\t0,\t0,\t0,\t0,\t0,\t0"
# Slots replaced first when a chart needs an effect the default table lacks:
# the positions whose official content varies most (position 6 holds 14
# different types across the 336 charts, 10 holds 10, 8 holds 10).
_FX_FREE_SLOTS = (6, 10, 8, 7, 11, 9, 1, 4, 0, 5, 2, 3)


def _ksh_param_name(k: str) -> str:
    if k in _KSH_PARAM_RENAMES:
        return _KSH_PARAM_RENAMES[k]
    return re.sub(r"(?<!^)([A-Z])", r"_\1", k).lower()


def _effect_type_name(name: str) -> str:
    """ksh PascalCase or kson snake_case effect name → kson type name."""
    return _FX_KSH_TYPES.get(name, name)


def _invocation_params(etype: str, args: list) -> dict:
    """`fx-l=Name;a;b` arguments by effect type — the same rules as the chart
    editor's KshTables.InvocationParams (verified there on ABYSS MOTION)."""
    p = {}
    if not args or not args[0]:
        return p
    a0 = args[0]
    if etype in ("retrigger", "gate", "wobble"):
        p["wave_length"] = "1/" + a0
    elif etype == "echo":
        p["wave_length"] = "1/" + a0
        if len(args) > 1 and args[1]:
            p["feedback_level"] = args[1] + "%"
    elif etype == "pitch_shift":
        p["pitch"] = a0
    elif etype == "bitcrusher":
        p["reduction"] = a0 + "samples"
    elif etype == "tapestop":
        p["speed"] = a0 + "%"
    return p


def _on_part(s) -> str:
    """'Off>OnMin-OnMax' → 'OnMin-OnMax' (the value while the effect is on)."""
    s = str(s if s is not None else "")
    return s.split(">", 1)[1] if ">" in s else s


def _first_num(s):
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", _on_part(s))
    return float(m.group(1)) if m else None


def _range_nums(s) -> list:
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", _on_part(s))]


def _len_div(s):
    """A KSM length ('1/8', or a decimal measure fraction) → note divisor."""
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", _on_part(s))
    if m and float(m.group(1)) > 0:
        return float(m.group(2)) / float(m.group(1))
    v = _first_num(s)
    if v and 0 < v <= 4 and "ms" not in str(s) and "s" not in str(s).replace("samples", ""):
        return 1.0 / v
    return None


def _fx_block(spec: dict):
    """One effect → the first row of its VOX block (tab-joined), or None."""
    t, p = spec.get("type", ""), spec.get("params") or {}

    def div(key, default):
        n = _len_div(p.get(key)) if key in p else None
        n = n if n and n > 0 else default
        return max(1, int(round(n)))

    if t == "retrigger":
        n = _len_div(p.get("wave_length")) if "wave_length" in p else None
        if not n:
            n = _len_div(p.get("update_period")) if "update_period" in p else None
        n = max(1, int(round(n))) if n and n > 0 else 8
        fixed = {4: "1,4,95.00,2.00,1.00,0.85,0.15",
                 8: "1,8,95.00,2.00,1.00,0.75,0.10",
                 16: "8,16,95.00,2.00,1.00,0.87,0.13,0.00",
                 32: "8,32,95.00,8.00,1.00,0.85,0.15,0.00"}
        row = fixed.get(n) or (f"1,{n},95.00,2.00,1.00,0.85,0.15" if n < 16
                               else f"8,{n},95.00,2.00,1.00,0.87,0.13,0.00")
    elif t == "echo":
        row = f"1,{div('wave_length', 4)},100.00,4.00,0.60,1.00,0.85"
    elif t == "gate":
        row = f"2,98.00,{div('wave_length', 8)},1.00"
    elif t == "phaser":
        row = "3,75.00,2.00,0.50,90,2.00"
    elif t == "tapestop":
        row = "4,100.00,8.00,0.40"
    elif t == "sidechain":
        row = "5,90.00,1.00,45,50,60"
    elif t == "wobble":
        row = f"6,0,3,80.00,500.00,18000.00,{float(div('wave_length', 4)):.2f},1.40"
    elif t == "bitcrusher":
        nums = [abs(x) for x in _range_nums(p.get("reduction", ""))]
        r = next((x for x in nums if x > 0), 12.0)
        row = f"7,100.00,{int(round(r))}"
    elif t == "pitch_shift":
        v = _first_num(p.get("pitch", "")) if "pitch" in p else None
        row = f"9,72.00,{_fixed(v if v is not None else 12.0, 2)}"
    elif t == "flanger":
        row = "12,90.00,1200.00,1.00,3.00"
    else:
        return None
    return ",\t".join(row.split(","))


def _norm_row(row: str) -> str:
    return re.sub(r"\s+", "", row)


def _section_body(text: str, name: str):
    m = re.search(rf"(?ms)^#{re.escape(name)}[ \t]*\r?\n(.*?)^#END", text)
    return m.group(1) if m else None


def _replace_section(text: str, name: str, body: str) -> str:
    """Replace the rows of `#<name>` … `#END` (first occurrence, exact name —
    `#SPCONTROLER` never matches `#LOCKED_SPCONTROLER`)."""
    if body and not body.endswith("\n"):
        body += "\n"
    pat = re.compile(rf"(?ms)(^#{re.escape(name)}[ \t]*\r?\n)(.*?)(^#END)")
    return pat.sub(lambda m: m.group(1) + body + m.group(3), text, count=1)


def _fx_table(tpl: str, parsed: dict):
    """Per-chart #FXBUTTON EFFECT INFO and spec → hold index.

    Starts from the template's table (the official default layout: retrigger
    1/4, 1/8, 1/16, 1/6, gate 1/8, 1/4, phaser, tape stop, side chain, wobble,
    bit crusher). An effect equal to a default block uses it; anything else
    takes over a block no hold of this chart refers to. Returns (body, map)."""
    body = _section_body(tpl, "FXBUTTON EFFECT INFO") or ""
    blocks = [b.split("\n") for b in re.split(r"\n\s*\n", body.strip("\n")) if b.strip()]
    if len(blocks) != 12:
        return body, {}
    used, mapping, changed = set(), {}, False
    count = collections.Counter()
    for lane in parsed.get("fx", []):
        for ev in lane:
            spec = ev[2] if len(ev) > 2 else 0
            if not isinstance(spec, dict) or ev[1] <= 0:
                continue
            row = _fx_block(spec)
            if row is None:
                _warn(parsed, f"FX effect '{spec.get('name')}' (type "
                              f"{spec.get('type') or '?'}) has no VOX block — "
                              f"those holds play without an effect")
                continue
            count[row] += 1
    # Slot priority when more than 12 distinct effects compete: every effect
    # type gets one block first (its most used variant), then the remaining
    # variants by number of holds. A variant left over shares the nearest
    # block of its type (see below), so no type falls silent.
    fam = lambda r: _norm_row(r).split(",")[0]
    ranked = [r for r, _ in count.most_common()]
    heads, seen = [], set()
    for r in ranked:
        if fam(r) not in seen:
            heads.append(r)
            seen.add(fam(r))
    variants = [r for r in ranked if r not in heads]

    def default_slot(row):                   # template block equal to `row`
        for i, b in enumerate(blocks):
            if _norm_row(b[0]) == _norm_row(row) and \
                    all(_norm_row(r) == _norm_row(_ZERO_ROW) for r in b[1:]):
                return i
        return None
    defaults = {r: default_slot(r) for r in ranked}
    # Exact default blocks: every type's head first, then the further variants
    # — but a variant takes its default block only while enough blocks stay
    # free for the types that have none yet. Until this was fixed the variants
    # took their default blocks unconditionally, and 13 effects (4 retrigger,
    # 2 gate, phaser … pitch shift) left pitch shift without a block: its holds
    # played no effect at all. With up to 12 effects, or whenever every type
    # gets a block anyway, the result is exactly what it was before.
    for row in heads:
        if defaults[row] is not None:
            mapping[row] = defaults[row] + 2
            used.add(defaults[row])
    need = sum(1 for r in heads if r not in mapping)
    for row in variants:
        i = defaults[row]
        if i is not None and i not in used and 12 - len(used) - 1 >= need:
            mapping[row] = i + 2
            used.add(i)
    wanted = heads + variants
    for row in wanted:
        if row in mapping:
            continue
        free = next((i for i in _FX_FREE_SLOTS if i not in used), None)
        if free is None:                     # > 12 distinct effects
            def variant(r):                  # the parameter naming the variant
                f = _norm_row(r).split(",")
                try:
                    return float(f[-1] if f[0] in ("7", "9") else
                                 f[6] if f[0] == "6" else f[1] if f[0] in ("1", "8")
                                 else f[2] if f[0] == "2" else 0)
                except (ValueError, IndexError):
                    return 0.0
            same = [r for r in mapping if fam(r) == fam(row)]
            if same:
                best = min(same, key=lambda r: abs(variant(r) - variant(row)))
                mapping[row] = mapping[best]
                _warn(parsed, "more than 12 distinct FX effects — some holds "
                              "share the closest block of the same type")
            else:
                _warn(parsed, "more than 12 distinct FX effects — some holds "
                              "play without an effect")
            continue
        blocks[free] = [row, _ZERO_ROW]
        used.add(free)
        mapping[row] = free + 2
        changed = True
    if not changed:
        return body, mapping
    return "\n\n".join("\n".join(b) for b in blocks) + "\n\n", mapping


# ── laser filters (field 5) ──────────────────────────────────────────────────
# Laser field 5 is the knob filter: measured on 233,111 official v13 laser
# points it takes 0 (78 %), 2, 4, 5, 1, 6, 3 and is constant within 90 % of the
# sections. Both public converters read it the same way: 0 peak, 1/2 low-pass,
# 3/4 high-pass, 5 bit crusher, 6 none. Of each pair the official charts use 2
# and 4 far more often (27,291 vs 3,186; 10,548 vs 570), so those are written.
# The filter definitions themselves (#TAB EFFECT INFO) are the template's,
# which is byte-identical in 323 of 336 official charts.
_LASER_FILTERS = {"peak": 0, "peaking_filter": 0, "lpf1": 2,
                  "low_pass_filter": 2, "hpf1": 4, "high_pass_filter": 4,
                  "bitc": 5, "bitcrusher": 5}


def _laser_filter_code(parsed: dict, name: str, defs: dict) -> int:
    name = (name or "").strip()
    if name in _LASER_FILTERS:
        return _LASER_FILTERS[name]
    etype = _effect_type_name(defs.get(name, name))
    if etype in _LASER_FILTERS:
        return _LASER_FILTERS[etype]
    lst = parsed.setdefault("unmapped_laser_fx", [])
    if f"{name} ({etype or '?'})" not in lst:
        lst.append(f"{name} ({etype or '?'})")
    return 0


def _section_filters(parsed: dict, sections: list, events: list) -> list:
    """Filter code per section: the filter active at the section's start."""
    ev = sorted(events)
    out = []
    for sec in sections:
        code = 0
        if sec:
            start = sec[0][0]
            for t, c in ev:
                if t <= start:
                    code = c
                else:
                    break
        out.append(code)
    return out


# ── tilt ─────────────────────────────────────────────────────────────────────
# #TILT MODE INFO: 0 = normal auto tilt, 1 = bigger, 2 = keep bigger. 335 of
# 336 v13 charts carry a single `001,01,00 0`, so 0 is the default auto tilt,
# not "tilt off" (the template's 0 was always normal tilt). Modes 1 and 2 occur
# in the older official charts the game still plays (v10: 1575 / 606 rows) and
# both public converters read them as bigger / keep-bigger. VOX has no
# "zero" (auto tilt off) and no "biggest"; those fall back with a warning.
_TILT_MODES = {"normal": 0, "keep_normal": 0, "zero": 0, "bigger": 1,
               "big": 1, "biggest": 1, "keep_bigger": 2, "keep": 2,
               "keep_biggest": 2}


def _tilt_events_ksh(value: str):
    v = value.strip()
    if v in _TILT_MODES:
        return ("auto", v)
    try:
        return ("manual", float(v))
    except ValueError:
        return None


def _kson_tilt(entries, on_bad=None) -> list:
    """kson camera.tilt → [(tick, 'auto', name) | (tick, 'manual', v, vf, curve)].
    A malformed entry is skipped and reported through `on_bad()`."""
    out = []
    for e in _seq(entries):
        try:
            y, val = (e.get("y", 0), e.get("v")) if isinstance(e, dict) else (e[0], e[1])
            if isinstance(y, bool) or not isinstance(y, (int, float)):
                raise ValueError(y)
            t = _kson_tick(y)
        except _BAD_DATA:
            if on_bad:
                on_bad()
            continue
        curve = None
        if isinstance(val, (list, tuple)) and len(val) == 2 and \
                isinstance(val[1], (list, tuple)):          # [value, [a, b]]
            curve = (_fnum(val[1][0]), _fnum(val[1][1])) if len(val[1]) >= 2 else None
            val = val[0]
        if isinstance(val, str):
            out.append((t, "auto", val))
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            out.append((t, "manual", _fnum(val), _fnum(val), curve))
        elif isinstance(val, (list, tuple)) and len(val) == 2:
            a, b = val
            if isinstance(b, str):                          # [v, "auto-name"]
                out.append((t, "manual", _fnum(a), _fnum(a), None))
                out.append((t, "auto", b))
            else:                                           # [v, vf]
                out.append((t, "manual", _fnum(a), _fnum(b), curve))
    return out


def _tilt_emit(parsed: dict, events: list):
    """→ (TILT MODE rows [(tick, mode)], Tilt SPCONTROLER tweens)."""
    modes, tweens, manual = [(0, 0)], [], []

    def flush(reset_at=None):
        for t, d, a, b in _graph_pieces(manual, 12):
            tweens.append((t, d, _clamp_unit(parsed, a, "manual tilt"),
                           _clamp_unit(parsed, b, "manual tilt")))
        if reset_at is not None:
            last = _clamp_unit(parsed, manual[-1][2], "manual tilt")
            if last != 0:
                tweens.append((reset_at, 0, last, 0.0))

    for ev in sorted(events, key=lambda e: e[0]):
        if ev[1] == "auto":
            name = ev[2]
            if name not in _TILT_MODES:
                _warn(parsed, f"unknown tilt value '{name}' ignored")
                continue
            if name == "zero":
                _warn(parsed, "tilt 'zero' (auto tilt off) has no VOX mode — "
                              "written as normal tilt")
            elif name in ("biggest", "keep_biggest"):
                _warn(parsed, f"tilt '{name}' has no VOX mode — written as "
                              f"{'bigger' if name == 'biggest' else 'keep_bigger'}")
            if manual:
                flush(ev[0])
                manual = []
            modes.append((ev[0], _TILT_MODES[name]))
        else:
            manual.append((ev[0], ev[2], ev[3], ev[4]))
    if manual:
        flush()
    rows, last = [], None
    by_tick = {}
    for t, m in modes:
        by_tick[t] = m
    for t in sorted(by_tick):
        if by_tick[t] != last:
            rows.append((t, by_tick[t]))
            last = by_tick[t]
    return rows, tweens


def _clamp_unit(parsed: dict, v: float, what: str) -> float:
    """Official CAM_RotX / CAM_Radi / Tilt values never leave -1..1."""
    if v > 1.0 or v < -1.0:
        _warn(parsed, f"{what} beyond the official range ±1 — clamped")
        return max(-1.0, min(1.0, v))
    return v


# ── camera ───────────────────────────────────────────────────────────────────
# zoom_top ↔ CAM_RotX, zoom_bottom ↔ CAM_Radi: both public converters pair
# them this way. Official rows are linear tweens `pos NAME 2 dur from to 0 0`
# chaining one segment into the next; all 8,294 / 20,778 official values lie
# in -1..1. Units follow VoxCharger (zoom_top / 100, zoom_bottom / -100: a
# positive zoom_bottom brings the lane closer, i.e. less camera distance) and
# are clamped to ±1. zoom_side, center_split and rotation_deg have no VOX
# counterpart in any official chart.
CAM_SCALE = {"zoom_top": ("CAM_RotX", 1 / 100.0),
             "zoom_bottom": ("CAM_Radi", -1 / 100.0)}


def _cam_rows(parsed: dict) -> list:
    rows = []
    for key in ("zoom_top", "zoom_bottom"):
        pts = (parsed.get("cam") or {}).get(key) or []
        if not any(p[1] or p[2] for p in pts):
            continue
        name, k = CAM_SCALE[key]
        for t, d, a, b in _graph_pieces(pts, 12):
            rows.append((t, name, d, _clamp_unit(parsed, a * k, key),
                         _clamp_unit(parsed, b * k, key)))
    return rows


# ── scroll speed and stops ───────────────────────────────────────────────────
# Scroll speed is the row `ManualSpeed <type> 0 f<speed>` — a step function:
# the only official gradual change (2037 apocalypseray) writes one row per 6
# ticks. Official values never go below 0 and peak at 5730.
# Where it goes: three official charts use ManualSpeed. The only FORMAT
# VERSION 13 one (2330 kiskillilia MXM) and the v12 0271 vallis INF put it in
# #LOCKED_SPCONTROLER — an initial `001,01,00 ManualSpeed 0 0 f1.00`, type
# 2147483648 (0x80000000) on every row that leaves 1.00, type 0 on the rows
# back at 1.00. Only the v12 2037 has it in #SPCONTROLER (type 0). The v13
# form is written (_locked_rows); the rest of #SPCONTROLER is unaffected.
# A stop is the dedicated BPM INFO form: the stop starts with a row whose 3rd
# field is `4-` and ends at the next BPM row (62 rows in 14 official charts,
# all v10/v12 — which the running game plays; both public converters agree).
SPEED_STEP = 6
SPEED_MAX = 5730.0


SPEED_MAX_RAMP_ROWS = 1000   # per ramp; library max 92 steps, official max 14 rows
END_HINT_MAX_MEASURES = 64   # editor end_pulse may add at most this many trailing measures


def _speed_rows(parsed: dict, points: list) -> list:
    """Scroll speed graph → [(tick, speed)] step rows.

    Bounded so a malformed or extreme graph cannot stall the conversion: a
    ramp to a point millions of pulses away used to walk every 6th tick of it
    (hang.kson: 0.5 s at 48M pulses, minutes beyond). Rows at or past the
    chart end are dropped — nothing plays there — and a ramp longer than
    SPEED_MAX_RAMP_ROWS steps gets a coarser step (a multiple of 6) with one
    warning. The longest ramp in the library is 92 steps (ABYSS MOTION, 2.9
    measures) and the official 2037 ramps are 14 and 8 rows, so real charts
    never reach the cap."""
    end = parsed.get("end")
    if isinstance(end, int) and end > 0:
        points = [p for p in points if p[0] < end] + \
                 [p for p in points if p[0] >= end][:1]   # keeps the ramp's target
    raw = []
    for i, (t, v, vf, c) in enumerate(points):
        if isinstance(end, int) and end > 0 and t >= end:
            break
        if i + 1 < len(points):
            t1, v1 = points[i + 1][0], points[i + 1][1]
            if t1 <= t:
                continue
            if vf == v1:
                raw.append((t, vf))
                continue
            stop = min(t1, end) if isinstance(end, int) and end > 0 else t1
            step = SPEED_STEP
            if (stop - t) / SPEED_STEP > SPEED_MAX_RAMP_ROWS:
                step = -(-(stop - t) // (SPEED_MAX_RAMP_ROWS * SPEED_STEP)) * SPEED_STEP
                _warn(parsed, f"scroll speed ramp longer than "
                              f"{SPEED_MAX_RAMP_ROWS} steps — written with a "
                              f"coarser step")
            for tt in range(t, stop, step):
                x = (tt - t) / (t1 - t)
                y = _curve_y(x, *c) if c else x
                raw.append((tt, vf + (v1 - vf) * y))
        else:
            raw.append((t, vf))
    rows, last = [], 1.0
    for t, v in raw:
        if v < 0:
            _warn(parsed, "negative scroll speed (reverse scroll) never "
                          "appears in official charts — clamped to 0")
            v = 0.0
        if v > SPEED_MAX:
            v = SPEED_MAX
        v = round(v, 4)
        if v == last:
            continue
        rows.append((t, v))
        last = v
    return rows


def _fmt_speed(v: float) -> str:
    s = _fixed(v, 4).rstrip("0")
    head, _, tail = s.partition(".")
    return "f" + head + "." + tail.ljust(2, "0")


def _fmt_pe(v: float) -> str:
    s = _fixed(v, 4).rstrip("0")
    if s.endswith("."):
        s += "0"
    return s + "f"


# ── chart editor extras (impl["sdvx-editor"].vox) ────────────────────────────
def _editor_vox_extras(parsed: dict, doc: dict) -> dict:
    """Read the SDVX Chart Editor's VOX-only data (VoxExtras.cs / KsonWriter):
    bg_no, post_effect rows [y, name, param, from, to, length] and sp_controller
    rows [y, name, type, length, p1..p4]; y and length are kson pulses. Absent
    → {} and the template defaults stay. Anything malformed is skipped with
    one warning per list — a broken row must not cost the chart."""
    ours = _obj(_obj(_obj(doc.get("impl")).get("sdvx-editor")).get("vox"))
    out = {}
    bg = ours.get("bg_no")
    if isinstance(bg, int) and not isinstance(bg, bool) and 0 <= bg <= 65535:
        out["bg_no"] = bg
    elif bg is not None:
        _warn(parsed, "editor bg_no is not a number 0..65535 — ignored")

    def clean(s):
        # Names are written into a tab-separated row: only plain strings.
        if not isinstance(s, str) or not s or re.search(r"[\t\r\n]", s):
            raise ValueError(s)
        return s

    def pulse(x):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise ValueError(x)
        return _kson_tick(x)                  # NaN/inf raise ValueError/Overflow

    def rows(key, what):
        lst = ours.get(key)
        if lst is not None and not isinstance(lst, list):
            _warn(parsed, f"editor {what} data is not a list — ignored")
            return []
        return lst or []

    pe = []
    for r in rows("post_effect", "#POSTEFFECT"):
        try:
            y, name, param, a, b, ln = _seq(r)[:6]
            pe.append((pulse(y), clean(name), clean(param), _fnum(a), _fnum(b),
                       max(0, pulse(ln))))
        except _BAD_DATA:
            _warn(parsed, "an editor #POSTEFFECT row is malformed and was skipped")
    if pe:
        out["post_effect"] = pe
    sp = []
    for r in rows("sp_controller", "#SPCONTROLER"):
        try:
            r = _seq(r)
            y, name, typ, ln = r[:4]
            ps = [_fnum(x) for x in (list(r[4:8]) + [0, 0, 0, 0])[:4]]
            if isinstance(typ, bool) or not isinstance(typ, (int, float)):
                raise ValueError(typ)
            sp.append((pulse(y), clean(name), int(typ), max(0, pulse(ln)), ps))
        except _BAD_DATA:
            _warn(parsed, "an editor #SPCONTROLER row is malformed and was skipped")
    if sp:
        out["sp_controller"] = sp
    return out


def _kson_extras(parsed: dict, doc: dict) -> None:
    """Everything a .kson carries beyond notes and timing (0.17.0).

    Every subtree is read defensively: a node of the wrong type is treated as
    absent and a malformed row is skipped, each with one warning per subtree
    (_BAD_DATA). Until this was hardened, `"sp_controller": 5` or a string
    pulse raised and the whole song failed to convert."""
    beat = _obj(doc.get("beat"))
    audio = _obj(doc.get("audio"))
    cam = _obj(doc.get("camera"))
    ae = _obj(audio.get("audio_effect"))

    def bad(what):
        _warn(parsed, f"malformed {what} data in the .kson — those entries "
                      f"were skipped")

    def pulse(x):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise ValueError(x)
        return _kson_tick(x)

    # laser filters
    lae = _obj(ae.get("laser"))
    ldefs = {}
    for d in _kson_defs(lae.get("def")):
        t = d[1].get("type", d[0])
        ldefs[d[0]] = t if isinstance(t, str) else ""
    fev = []
    for name, ys in _obj(lae.get("pulse_event")).items():
        code = _laser_filter_code(parsed, name, ldefs)
        if not isinstance(ys, list):
            bad("laser effect")
            continue
        for y in ys:
            try:
                fev.append((pulse(_kson_y(y)), code))
            except _BAD_DATA:
                bad("laser effect")
    if lae.get("param_change") or lae.get("legacy"):
        _warn(parsed, "laser effect parameter changes / filter gain have no "
                      "VOX counterpart — ignored")
    for lane in range(2):
        meta = parsed["laser_meta"][lane]
        for m, code in zip(meta, _section_filters(parsed, parsed["laser"][lane], fev)):
            m["filter"] = code

    # FX hold effects
    fae = _obj(ae.get("fx"))
    defs = {d[0]: d[1] for d in _kson_defs(fae.get("def"))}
    events = [[], []]
    for name, lanes in _obj(fae.get("long_event")).items():
        if not isinstance(lanes, list):
            bad("FX effect")
            continue
        for lane in range(min(2, len(lanes))):
            if lanes[lane] is not None and not isinstance(lanes[lane], list):
                bad("FX effect")
                continue
            for e in lanes[lane] or []:
                try:
                    if isinstance(e, (list, tuple)):
                        y = e[0]
                        prm = e[1] if len(e) > 1 and isinstance(e[1], dict) else {}
                    elif isinstance(e, dict):
                        y, prm = e.get("y", 0), _obj(e.get("v"))
                    else:
                        y, prm = e, {}
                    events[lane].append((pulse(y), name, prm))
                except _BAD_DATA:
                    bad("FX effect")
    if fae.get("param_change"):
        _warn(parsed, "FX effect parameter changes over time have no VOX "
                      "counterpart — each hold uses its effect's start values")
    for lane in range(2):
        evs = sorted(events[lane], key=lambda e: e[0])
        new = []
        for t, ln, eff in parsed["fx"][lane]:
            spec = 0
            if ln > 0:
                hit = next((e for e in evs if t <= e[0] < t + ln), None)
                if hit:
                    d = defs.get(hit[1]) or {}
                    params = {**_obj(d.get("v")), **hit[2]}
                    etype = d.get("type", hit[1])
                    spec = {"name": hit[1],
                            "type": _effect_type_name(etype if isinstance(etype, str) else ""),
                            "params": params}
            new.append((t, ln, spec))
        parsed["fx"][lane] = new

    ks = _obj(audio.get("key_sound"))
    if _obj(ks.get("fx")).get("chip_event") or             _obj(ks.get("laser")).get("slam_event"):
        _warn(parsed, "custom chip / slam sounds cannot be represented in VOX "
                      "— the game's default sounds play")

    # tilt and camera
    def graph(entries, what):
        if entries is not None and not isinstance(entries, list):
            bad(what)
            return []
        return _kson_graph(entries, lambda: bad(what))

    tilt = cam.get("tilt")
    if tilt is not None and not isinstance(tilt, list):
        bad("camera tilt")
        tilt = []
    parsed["tilt"] = _kson_tilt(tilt, lambda: bad("camera tilt"))
    camcam = _obj(cam.get("cam"))
    body = _obj(camcam.get("body"))
    parsed["cam"] = {"zoom_top": graph(body.get("zoom_top"), "camera zoom_top"),
                     "zoom_bottom": graph(body.get("zoom_bottom"), "camera zoom_bottom")}
    for key in ("zoom_side", "zoom_size", "center_split", "split",
                "rotation_deg", "rotation_z"):
        g = body.get(key)
        if isinstance(g, dict):
            g = [x for v in g.values() for x in _seq(v)]
        if any(p[1] or p[2] for p in graph(g, f"camera {key}")):
            _warn(parsed, f"camera '{key}' has no VOX counterpart — ignored")
    if camcam.get("pattern"):
        _warn(parsed, "lane spins / swings are not converted to VOX yet — ignored")

    # scroll speed and stops
    parsed["scroll"] = graph(beat.get("scroll_speed"), "scroll speed")
    stops = []
    stop = beat.get("stop")
    if stop is not None and not isinstance(stop, list):
        bad("stop")
        stop = []
    for e in stop or []:
        try:
            y, ln = (e.get("y", 0), e.get("v", 0)) if isinstance(e, dict) else (e[0], e[1])
            if pulse(ln) > 0:
                stops.append((pulse(y), pulse(ln)))
        except _BAD_DATA:
            bad("stop")
    parsed["stops"] = stops

    parsed["vox_extras"] = _editor_vox_extras(parsed, doc)


def _kson_defs(defs) -> list:
    """kson `def`: [[name, {type, v}]] (1.0) or {name: {type, v}} (older)."""
    out = []
    if isinstance(defs, dict):
        defs = list(defs.items())
    for d in _seq(defs):
        try:
            name, body = d[0], d[1]
        except (IndexError, TypeError, KeyError):
            continue
        if isinstance(body, dict):
            out.append((str(name), body))
    return out


def _ksh_defines(path: str):
    """#define_fx / #define_filter lines → ({name: {type, v}}, {name: type})."""
    fx, flt = {}, {}
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln.startswith(("#define_fx", "#define_filter")):
                continue
            parts = ln.split(None, 2)
            if len(parts) < 3:
                continue
            params = {}
            for kv in parts[2].split(";"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    params[k.strip()] = v.strip()
            etype = _effect_type_name(params.pop("type", ""))
            v = {_ksh_param_name(k): val for k, val in params.items()}
            if parts[0] == "#define_fx":
                fx[parts[1]] = {"type": etype, "v": v}
            else:
                flt[parts[1]] = etype
    return fx, flt


def _ksh_fx_spec(value: str, defs: dict):
    """`fx-l=` value → effect spec dict, or None for 'no effect'."""
    if not value:
        return None
    args = value.split(";")
    name = args[0].strip()
    d = defs.get(name) or {}
    etype = _effect_type_name(d.get("type", name))
    params = dict(d.get("v") or {})
    params.update(_invocation_params(etype, [a.strip() for a in args[1:]]))
    return {"name": name, "type": etype, "params": params}


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
        for idx, (st, num, den) in enumerate(bounds):
            span = int(TPB * 4 * num / den)
            if st <= tick < st + span or idx == len(bounds) - 1:
                within = tick - st
                if span > 0 and within >= span:
                    # Past the last measure (the end position): continue with
                    # its signature instead of counting beats beyond the
                    # numerator. Official END POSITIONs never have BB > num;
                    # "077,05,00" in 4/4 is written "078,01,00" there.
                    idx += within // span
                    within %= span
                bl = beat_ticks(den)
                return f"{idx + 1:03d},{within // bl + 1:02d},{within % bl:02d}"
        return "001,01,00"
    return pos


def beat_ticks(den: int) -> int:
    """Ticks per VOX beat in a measure with denominator `den`.

    The VOX beat is the signature's denominator note, not the quarter note: a
    6/8 bar runs BB 1..6 with offsets 0..23. Measured over every official
    chart with a non-/4 signature: BB never exceeds the numerator, and offsets
    stay below 192/den (the 0.4 % that do not occur at the same rate in plain
    4/4 charts — an artefact of the official files, not a different beat).
    Splitting a 6/8 bar at 48 ticks gave BB 1..3 with offsets up to 47.

    A denominator that does not divide 192 (official charts contain /36 once,
    with every note on offset 0) has no integral beat; those keep the quarter
    split so offsets at least stay inside the measure."""
    whole = TPB * 4
    return whole // den if den > 0 and whole % den == 0 else TPB


def _check_positions() -> list[str]:
    """Known tick → position pairs, run by --self-check. A 4/4 bar (192 ticks),
    a 6/8 bar (144) and a 7/16 bar (84), laid out like 1211_beyondtheblue's
    6/8 and 0347_tlahuiz's 7/16. Returns the mismatches."""
    pos = _pos_fn([(0, 4, 4), (1, 6, 8), (2, 7, 16), (3, 4, 4)])
    cases = {0: "001,01,00", 191: "001,04,47",
             192: "002,01,00", 204: "002,01,12", 216: "002,02,00",
             192 + 5 * 24 + 12: "002,06,12",
             336: "003,01,00", 336 + 6 * 12 + 6: "003,07,06",
             420: "004,01,00", 612: "005,01,00", 612 + 192 + 50: "006,02,02"}
    return [f"{t}: {pos(t)} != {want}" for t, want in cases.items()
            if pos(t) != want]


def _check_extras() -> list[str]:
    """0.17.0 mappings, run by --self-check. Returns the mismatches."""
    bad = []
    if abs(_curve_y(0.25, 0.0, 1.0) - 0.75) > 1e-9 or _curve_y(0.3, 0.4, 0.4) != 0.3:
        bad.append("kson curve")
    tpl = open(TEMPLATE, encoding="latin-1").read()
    spec = lambda t, **p: {"name": t, "type": t, "params": p}
    parsed = {"fx": [[(0, 48, spec("retrigger", wave_length="1/8")),
                      (96, 48, spec("gate", wave_length="1/4")),
                      (192, 48, spec("flanger"))], []]}
    _, m = _fx_table(tpl, parsed)
    got = [m.get(_fx_block(e)) for _, _, e in parsed["fx"][0]]
    if got != [3, 7, 8]:
        bad.append(f"fx index {got} != [3, 7, 8]")
    rows = _bpm_lines({0: 120.0}, [(192, 96)], _pos_fn([(0, 4, 4)])).split("\n")
    if rows[1:] != ["002,01,00\t120.0000\t4-", "002,03,00\t120.0000\t4"]:
        bad.append("stop rows")
    # More than 12 distinct effects: every type keeps a block (pitch shift
    # used to be left with index 0).
    many = [spec("retrigger", wave_length=w) for w in ("1/4", "1/8", "1/6", "1/16")] + \
           [spec("gate", wave_length=w) for w in ("1/8", "1/4")] + \
           [spec(t) for t in ("phaser", "tapestop", "flanger", "sidechain")] + \
           [spec("wobble", wave_length="1/4"), spec("bitcrusher", reduction="10samples"),
            spec("pitch_shift", pitch="7")]
    parsed = {"fx": [[(i * 96, 48, e) for i, e in enumerate(many)], []]}
    _, m = _fx_table(tpl, parsed)
    if any(not m.get(_fx_block(e)) for e in many):
        bad.append("fx overflow: an effect type lost its block")
    # laserrange_l=2x widens the next section only.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        k = os.path.join(d, "w.ksh")
        with open(k, "w", encoding="utf-8") as fh:
            fh.write("title=t\nt=120\n--\nlaserrange_l=2x\n0000|00|0-\n0000|00|--\n"
                     "0000|00|0-\n0000|00|--\n--\n")
        widths = [x["wide"] for x in convert_chart(k)["laser_meta"][0]]
    if widths != [2, 1]:
        bad.append(f"laserrange reset {widths} != [2, 1]")
    # malformed editor data warns instead of raising
    try:
        p = {"warnings": []}
        _editor_vox_extras(p, {"impl": {"sdvx-editor": {"vox": {"sp_controller": 5}}}})
    except Exception as e:                      # noqa: BLE001
        bad.append(f"editor extras raise {type(e).__name__}")
    if _fixed(0.0 * -0.01, 2) != "0.00" or _fixed(-0.004, 2) != "0.00" \
            or _fixed(-0.5, 2) != "-0.50":
        bad.append("negative zero")
    # ManualSpeed → #LOCKED_SPCONTROLER (v13 form), editor POSTEFFECT length 0 → 0
    q = {"beat": [(0, 4, 4)], "bpm": [(0, 120.0)], "end": 192 * 3,
         "bt": [[], [], [], []], "fx": [[], []], "laser": [[], []],
         "scroll": [(192, 2.0, 2.0, None), (384, 1.0, 1.0, None)],
         "vox_extras": {"post_effect": [(0, "SimpleNoise", "WholeNoiseStrength", 0.0, 0.0, 0)]}}
    vox = emit_vox(q)
    locked = _section_body(vox.replace("\r\n", "\n"), "LOCKED_SPCONTROLER") or ""
    if "002,01,00\tManualSpeed\t2147483648\t0\tf2.00" not in locked or \
            "ManualSpeed" in (_section_body(vox.replace("\r\n", "\n"), "SPCONTROLER") or ""):
        bad.append("ManualSpeed placement")
    if "001,01,00\t2\t0\tSimpleNoise" not in vox:
        bad.append("POSTEFFECT length 0")
    # A scroll ramp to a point far away must stay bounded: clipped at the end,
    # and a long ramp inside the chart capped at SPEED_MAX_RAMP_ROWS steps.
    far = {"end": 192 * 4, "warnings": []}
    r1 = _speed_rows(far, [(0, 1.0, 1.0, None), (10 ** 9, 2.0, 2.0, None)])
    long_ = {"end": 10 ** 8, "warnings": []}
    r2 = _speed_rows(long_, [(0, 0.0, 0.0, None), (10 ** 8, 5000.0, 5000.0, None)])
    if any(t >= far["end"] for t, _ in r1) or len(r1) > 192 * 4 // SPEED_STEP \
            or len(r2) > SPEED_MAX_RAMP_ROWS + 1 or not long_["warnings"]:
        bad.append(f"scroll ramp bound ({len(r1)}, {len(r2)} rows)")
    return bad


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
    bpm_lines = _bpm_lines(bpm_uniq, parsed.get("stops") or [], pos)
    endpos = pos(parsed["end"])

    if parsed.get("unmapped_laser_fx"):
        _warn(parsed, "laser effects without a VOX laser filter, written as "
                      "the default peak filter: "
                      + ", ".join(parsed["unmapped_laser_fx"]))
    # TRACK1 = laser L, 8 = laser R
    infer = not parsed.get("explicit_slams")
    meta = parsed.get("laser_meta") or [None, None]
    t1 = _laser_track(parsed["laser"][0], pos, infer, meta[0])
    t8 = _laser_track(parsed["laser"][1], pos, infer, meta[1])
    # TRACK2 = FX-L, 7 = FX-R, with the per-chart effect table
    fx_body, fx_map = _fx_table(tpl, parsed)
    t2 = _fx_track(parsed["fx"][0], pos, fx_map)
    t7 = _fx_track(parsed["fx"][1], pos, fx_map)
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

    # 0.17.0 sections. Each is rewritten only when the chart has something to
    # say, so a chart without tilt/camera/effects keeps the template verbatim.
    if fx_body != _section_body(tpl, "FXBUTTON EFFECT INFO"):
        out = _replace_section(out, "FXBUTTON EFFECT INFO", fx_body)
    modes, tilt_tweens = _tilt_emit(parsed, parsed.get("tilt") or [])
    if modes != [(0, 0)]:
        out = _replace_section(out, "TILT MODE INFO", "\n".join(
            f"{pos(t)}\t{m}" for t, m in modes))
    sp = _spcontroler_rows(parsed, pos, tilt_tweens)
    if sp is not None:
        out = _replace_section(out, "SPCONTROLER", sp)
    locked = _locked_rows(parsed, pos)
    if locked is not None:
        out = _replace_section(out, "LOCKED_SPCONTROLER", locked)
    extras = parsed.get("vox_extras") or {}
    if extras.get("post_effect"):
        # Duration in ticks; an instant row is `0`, as in every official
        # mid-chart row (v13 2330: `073,01,00 2 0 SimpleNoise …`). `1ms` only
        # appears on the template's neutral rows at 001,01,00.
        out = _replace_section(out, "POSTEFFECT", "\n".join(
            f"{pos(t)}\t2\t{ln}\t{name}\t0\t0\t"
            f"{param}\t{_fmt_pe(a)}\t{_fmt_pe(b)}"
            for t, name, param, a, b, ln in sorted(extras["post_effect"],
                                                   key=lambda r: r[0])))
    return out.replace("\r\n", "\n").replace("\n", "\r\n")


def _bpm_lines(bpm_uniq: dict, stops: list, pos) -> str:
    """#BPM INFO rows; a stop starts with a `4-` row and ends at the next row
    (official form, see the 0.17.0 block). The end row repeats the tempo in
    force there, so the tempo map itself is untouched."""
    rows = {t: [b, "4"] for t, b in bpm_uniq.items()}
    ticks = sorted(rows)

    def bpm_at(t):
        cur = rows[ticks[0]][0] if ticks else 120.0
        for k in ticks:
            if k <= t:
                cur = rows[k][0]
            else:
                break
        return cur

    spans = []
    for t, ln in sorted(stops):
        if spans and t < spans[-1][1]:           # overlapping stops merge
            spans[-1][1] = max(spans[-1][1], t + ln)
        else:
            spans.append([t, t + ln])
    for s, e in spans:
        rows.setdefault(s, [bpm_at(s), "4"])[1] = "4-"
        for k in list(rows):                     # tempo changes inside a stop
            if s < k < e:
                rows[k][1] = "4-"
        if e not in rows:
            rows[e] = [bpm_at(e), "4"]
    return "\n".join(f"{pos(t)}\t{rows[t][0]:.4f}\t{rows[t][1]}"
                     for t in sorted(rows))


def _spcontroler_rows(parsed: dict, pos, tilt_tweens: list):
    """#SPCONTROLER body, or None to keep the template's rows untouched.

    Base rows are the template's (or the chart editor's own rows, which
    replace them), then camera, manual tilt and scroll speed — grouped by name
    and sorted by time, the way official files list them."""
    extras = parsed.get("vox_extras") or {}
    cam = _cam_rows(parsed)
    if not (cam or tilt_tweens or extras.get("sp_controller")):
        return None
    tpl = open(TEMPLATE, encoding="latin-1").read()
    base = (_section_body(tpl, "SPCONTROLER") or "").strip("\r\n").split("\n")
    if extras.get("sp_controller"):
        base = [f"{pos(t)}\t{name}\t{typ}\t{ln}\t" +
                "\t".join(_fixed(p, 2) for p in ps)
                for t, name, typ, ln, ps in sorted(extras["sp_controller"],
                                                   key=lambda r: r[0])]
    lines = [b for b in base if b.strip()]
    for name in ("CAM_RotX", "CAM_Radi"):
        lines += [f"{pos(t)}\t{name}\t2\t{d}\t{_fixed(a, 2)}\t{_fixed(b, 2)}\t0.00\t0.00"
                  for t, n, d, a, b in sorted(cam, key=lambda r: r[0]) if n == name]
    lines += [f"{pos(t)}\tTilt\t2\t{d}\t{_fixed(a, 2)}\t{_fixed(b, 2)}\t0.00\t0.00"
              for t, d, a, b in sorted(tilt_tweens, key=lambda r: r[0])]
    return "\n".join(lines)


SPEED_TYPE_CHANGED = 2147483648        # 0x80000000, see the scroll speed block


def _locked_rows(parsed: dict, pos):
    """#LOCKED_SPCONTROLER body with the scroll speed rows, or None to keep
    the template's rows untouched. Official v13 layout (2330): an initial
    1.00 row, type 0x80000000 while the speed differs from 1.00, type 0 on a
    row back at 1.00; the template's own rows (LIVE2D_OFF) follow."""
    speed = _speed_rows(parsed, parsed.get("scroll") or [])
    if not speed:
        return None
    if speed[0][0] != 0:
        speed = [(0, 1.0)] + speed
    tpl = open(TEMPLATE, encoding="latin-1").read()
    base = (_section_body(tpl, "LOCKED_SPCONTROLER") or "").strip("\r\n").split("\n")
    lines = [f"{pos(t)}\tManualSpeed\t{0 if v == 1.0 else SPEED_TYPE_CHANGED}"
             f"\t0\t{_fmt_speed(v)}\t0.00\t0.00\t0.00" for t, v in speed]
    return "\n".join(lines + [b for b in base if b.strip()])


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


def _fx_track(events, pos, fx_map=None):
    """FX lane. A hold's 3rd field is its effect block index (2..13, 0 = none,
    see _fx_table); chips keep 0."""
    fx_map = fx_map or {}

    def idx(ln, eff):
        if not ln:
            return 0
        if isinstance(eff, dict):
            row = _fx_block(eff)
            return fx_map.get(row, 0) if row else 0
        return eff if isinstance(eff, int) else 0
    return "\n".join(f"{pos(t)}\t{ln}\t{idx(ln, eff)}\t12" for t, ln, eff in events)


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
    two points on one position (measured: 2259 runs of 2, none longer).

    Not every change within 1/32 is a slam, though — densely authored movement
    is too (ABYSS MOTION: 129 "slams" on lane R where its own .kson marks 100).
    _is_slam applies the rule K-Shoot itself writes by. Only .ksh input goes
    through here; a .kson marks its slams explicitly (see _laser_track)."""
    out, i = [], 0
    while i < len(sec):
        t, v = sec[i]
        if i + 1 < len(sec):
            t2, v2 = sec[i + 1]
            if v2 != v and t2 - t <= SLAM_MAX_TICKS and _is_slam(sec, i):
                out.append((t, v))
                out.append((t, v2))          # same tick → slam
                i += 2
                continue
        out.append((t, v))
        i += 1
    return out


def _is_slam(sec, i) -> bool:
    """Is the candidate pair sec[i], sec[i+1] (a change within 1/32) a slam?

    K-Shoot Editor (libkson KshIOOut.cpp) writes a slam to .ksh as two lines
    exactly 1/32 apart, shorter only when the next point follows within 1/16
    of the slam's start. So:
      * a slam ends on a held value — no further change follows its second
        point closer than 1/32;
      * a pair exactly 1/32 long is then a slam;
      * a shorter pair is one only if no change precedes it closer than 1/32
        and a next point exists within 1/16 of its start.
    Measured across all 24 Nautica charts: the 3749 real slams are exactly
    1/32 long and none is followed by another change within 1/32, so every
    chart but ABYSS MOTION keeps its slam count; ABYSS lane R drops from 129
    to the 100 its .kson marks. Same rule as the SDVX Chart Editor's ksh
    reader (KshReader.IsSlam)."""
    if _dense_changes(sec, i + 1, +1):
        return False
    gap = sec[i + 1][0] - sec[i][0]
    if gap >= SLAM_MAX_TICKS:
        return True
    if _dense_changes(sec, i, -1):
        return False
    return i + 2 < len(sec) and sec[i + 2][0] - sec[i][0] <= 2 * SLAM_MAX_TICKS


def _dense_changes(sec, k, step) -> int:
    """Value changes walking from sec[k] in direction `step` (+1 / -1) for as
    long as neighbouring points are closer than 1/32."""
    changes, n = 0, k + step
    while 0 <= n < len(sec):
        a, b = (sec[k], sec[n]) if step > 0 else (sec[n], sec[k])
        if b[0] - a[0] >= SLAM_MAX_TICKS:
            break
        if b[1] != a[1]:
            changes += 1
        k, n = n, n + step
    return changes


def _laser_track(sections, pos, infer_slams: bool = True, meta=None):
    """Emit one VOX laser track from a list of sections.

    Segment marker (3rd field) per official v13 charts: 1 = section start,
    0 = middle, 2 = section end. Omitting the closing 2 leaves the laser on
    screen forever, drifting toward the next section's start — so every section
    must be closed. A one-point section is written twice (1 then 2) so it still
    has an end.

    Slam pairs are snapped onto one tick first, see _collapse_slams — for
    .ksh input only. A .kson states its slams (the [v, vf] value slot, already
    two points on one tick); inferring more there turned its dense 5-pulse
    points into fake slams (ABYSS lane R: 134 vs 100) and swallowed a real one.
    `infer_slams=False` emits kson points exactly as authored.

    Layout is 10 tab-separated fields, matching official v13 output:
    pos, value, seg, spin, filter, width, 0, curve, 0, 0.

    0.17.0 (`meta`, one dict per section): field 6 is the laser width, 1 or 2
    (`wide`); field 5 the knob filter (`filter`, see _LASER_FILTERS); a curved
    segment (`curves`: point index → (a, b)) is baked into points every 3
    ticks, exactly as official charts store curves: 140,336 official points
    that #TRACK ORIGINAL does not have, 94 % of them 3 ticks apart, every one
    carrying a curve type in field 8 (never 0). Of the official types 4 is an
    ease-out and 5 an ease-in sine (fitted on the baked values); a kson curve
    above the diagonal (b > a) is written 4, below it 5. The segment's start
    point carries the type too, as in official files. Slams and section ends
    are untouched: baking only fills the inside of a segment longer than
    3 ticks whose value changes."""
    out = []
    for si, sec in enumerate(sections):
        if not sec:
            continue
        m = (meta[si] if meta and si < len(meta) else None) or {}
        width = 2 if m.get("wide") == 2 else 1
        filt = int(m.get("filter", 0) or 0)
        curves = m.get("curves") or {}
        if len(sec) == 1:
            pts = sec * 2
        else:
            pts = _collapse_slams(sec) if infer_slams else sec
        rows = []
        for idx, (t, v) in enumerate(pts):
            c = curves.get(idx)
            if c and idx + 1 < len(pts) and c[0] != c[1]:
                t1, v1 = pts[idx + 1]
                if t1 - t > CURVE_STEP and v1 != v:
                    kind = 4 if c[1] > c[0] else 5
                    rows.append((t, v, kind))
                    for tt in range(t + CURVE_STEP, t1, CURVE_STEP):
                        y = _curve_y((tt - t) / (t1 - t), *c)
                        rows.append((tt, v + (v1 - v) * y, kind))
                    continue
            rows.append((t, v, 0))
        last = len(rows) - 1
        for idx, (t, v, kind) in enumerate(rows):
            seg = 1 if idx == 0 else (2 if idx == last else 0)
            out.append(f"{pos(t)}\t{_fixed(v / 50.0, 6)}\t{seg}\t0\t{filt}\t{width}"
                       f"\t0\t{kind}\t0\t0")
    return "\n".join(out)


CURVE_STEP = 3          # official baked curve points are 3 ticks apart


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


def _ffmpeg_window(ss: float | None, dur: float | None,
                   offset_ms: int = 0) -> tuple[list, list]:
    """ffmpeg (input options, output filter) for one encode.

    `ss`/`dur` cut a window (the preview). `offset_ms` is the chart's audio
    offset (ksh `o=`, kson `audio.bgm.offset`): per the KSH spec it "denotes
    the starting point of the song audio" and a larger value judges notes
    later, i.e. chart time 0 sits `offset_ms` into the audio file. VOX has no
    offset field — chart 0 is audio 0 — so the offset is baked into the audio:
    a positive one trims the lead, a negative one pads silence. Verified on
    Jumpy Star (o=2514, 100 BPM): the mp3 is silent until 3.729 s and the
    first note sits at chart 1.200 s, 1.200 + 2.514 = 3.714 s."""
    start = (ss or 0.0) + max(offset_ms, 0) / 1000.0
    pre = (["-ss", f"{start:.3f}"] if start else []) + \
          (["-t", f"{dur:.3f}"] if dur else [])
    post = ["-af", f"adelay=delays={-offset_ms}:all=1"] if offset_ms < 0 else []
    return pre, post


def chart_offset_ms(header: dict) -> int:
    """The chart's audio offset in ms (0 when absent or unparsable)."""
    try:
        return int(round(float(header.get("o", "") or 0)))
    except ValueError:
        return 0


def make_2dx(src: str, out_path: str,
             ss: float | None = None, dur: float | None = None,
             channels: int | None = None, offset_ms: int = 0) -> bool:
    """Audio → .2dx (Konami container, MS-ADPCM). Fully cross-platform: MS-ADPCM
    is encodable by ffmpeg on any OS, unlike WMA Pro. The game also looks for
    <id>_<ascii>.2dx (seen in soundvoltex.dll), so this avoids WMA entirely.
    `channels` overrides the global (e.g. mono for the preview).

    Layout: a 2dx container header (0x48) + a 1-entry offset table + one 2DX9
    sub-file (24-byte header + MS-ADPCM RIFF/WAV). `offset_ms`: see
    _ffmpeg_window."""
    import struct
    import tempfile
    ch = channels if channels is not None else AUDIO_CHANNELS
    if not shutil.which("ffmpeg"):
        print("  [WARN] ffmpeg not found – skipping audio.")
        return False
    wav = tempfile.mktemp(suffix=".wav")
    try:
        pre, post = _ffmpeg_window(ss, dur, offset_ms)
        cmd = ["ffmpeg", "-y"] + pre + ["-i", src, "-vn"] + post + [
               "-ac", str(ch), "-ar", "44100", "-c:a", "adpcm_ms", wav]
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


def _decode_wav(src: str, wav: str, ss, dur, offset_ms: int = 0) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    pre, post = _ffmpeg_window(ss, dur, offset_ms)
    cmd = ["ffmpeg", "-y"] + pre + ["-i", src, "-vn"] + post + [
           "-ac", str(AUDIO_CHANNELS), "-ar", "44100", "-map_metadata", "-1", wav]
    try:
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def make_s3v(ogg_path: str, out_path: str,
             ss: float | None = None, dur: float | None = None,
             channels: int | None = None, offset_ms: int = 0) -> bool:
    """Audio → .s3v (ASF container).

    Real Nabla .s3v files are ASF with **WMA Pro** (2ch / 44.1 kHz, 384k). WMA Pro
    is proprietary; ffmpeg can only DECODE it, and there is no native Linux
    encoder. So the actual encode is delegated to an external WMA Pro encoder
    configured via --wma-encoder (a template with {in}/{out}); on Linux that is a
    Windows encoder (native Windows box recommended — Wine's WMA Pro support is
    unreliable). If none is configured we ONLY produce a wmav2 placeholder, which
    this game rejects — so real audio needs the encoder. `ss`/`dur` trim a clip,
    `offset_ms` is the chart offset (see _ffmpeg_window)."""
    import shlex
    import tempfile

    if WMA_ENCODER_CMD:
        if not shutil.which("ffmpeg"):
            print("  [WARN] ffmpeg needed to decode the source before WMA-Pro "
                  "encoding – skipping audio.")
            return False
        wav = tempfile.mktemp(suffix=".wav")
        try:
            if not _decode_wav(ogg_path, wav, ss, dur, offset_ms):
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
    pre, post = _ffmpeg_window(ss, dur, offset_ms)
    cmd = (["ffmpeg", "-y"] + pre + ["-i", ogg_path, "-vn"] + post +
           ["-ac", str(channels if channels is not None else AUDIO_CHANNELS),
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
    scale in-game and on the result screen. Returns the source path used, or
    None when there is no usable jacket."""
    src = _resolve_jacket(src_folder, declared)
    if src is None:
        return
    try:
        from PIL import Image
    except ImportError:
        Image = None
    if Image is None:                                 # Pillow missing → copy as-is
        for suffix in _JACKET_SIZES:
            shutil.copyfile(src, os.path.join(
                out_folder, f"jk_{sid:04d}_{slot_label}{suffix}.png"))
        return src
    try:
        im = Image.open(src).convert("RGB")
        w, h = im.size
        if w != h:                                    # center-crop to square
            s = min(w, h)
            im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
        for suffix, size in _JACKET_SIZES.items():
            dst = os.path.join(out_folder, f"jk_{sid:04d}_{slot_label}{suffix}.png")
            im.resize((size, size), Image.LANCZOS).save(dst, "PNG")
    except Exception as e:
        # A corrupt or unreadable image (UnidentifiedImageError, truncated
        # file, decompression bomb) used to abort the whole song. Treat it
        # like a missing jacket: the song converts and shows no jacket.
        print(f"  [WARN] jacket {os.path.basename(src)} is unreadable "
              f"({type(e).__name__}: {e}) — song converted without a jacket.")
        for suffix in _JACKET_SIZES:                  # no half-written set
            dst = os.path.join(out_folder, f"jk_{sid:04d}_{slot_label}{suffix}.png")
            if os.path.exists(dst):
                os.remove(dst)
        return None
    return src


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

# Custom Songs folder tag. Official entries carry <tag id="N"/> right after
# </difficulty>; the running version uses ids 1..44 (measured on the merged
# music_db the game actually loaded), so 100 never collides with an official
# folder. A Custom Songs folder set up in spice2x collects exactly the songs
# carrying this tag — without it they stay invisible to it.
# Written by default; --no-custom-tag turns it off.
CUSTOM_TAG_ID = 100
WRITE_CUSTOM_TAG = True


def set_custom_tag(enabled: bool, tag_id: int = 100) -> None:
    """Switch the Custom Songs tag. The CLI and the V2 launcher bridge both go
    through here rather than poking the module globals."""
    global WRITE_CUSTOM_TAG, CUSTOM_TAG_ID
    WRITE_CUSTOM_TAG = bool(enabled)
    CUSTOM_TAG_ID = int(tag_id)


def _custom_tag_setting():
    """The tag a conversion writes right now, or None. Recorded per song in the
    import map, so switching it re-converts what was written the other way."""
    return CUSTOM_TAG_ID if WRITE_CUSTOM_TAG else None


def _u16(v) -> int:
    """Clamp to the u16 range modern music_db radar fields use. Old (omnimix-era)
    entries declare these as u8; current ∇ entries use u16, and reading a u8 node
    where the game expects u16 is why the radar stayed blank. Real values top out
    around 153, so this ceiling is never hit in practice."""
    try:
        return max(0, min(65535, int(round(v))))
    except (TypeError, ValueError):
        return 0


def _credit(value: str | None, encoding: str) -> str:
    """One credit field (illustrator / effected_by).

    Real entries carry the actual names, and both chart formats supply them —
    `effect=` / `illustrator=` in a .ksh, meta.chart_author /
    meta.jacket_author in a .kson. Empty stays '-', which is what every entry
    used to be. The text goes through the same cp932 folding as the title, so a
    Japanese effector name survives and an unmappable character cannot turn
    into a numeric reference."""
    s = (value or "").strip()
    if not s:
        return "-"
    return _xml_escape(cp932_safe(s, encoding))


def _diff_block(tag: str, difnum: int, rad: dict | None = None,
                credits: tuple[str, str] | None = None,
                encoding: str = "Shift_JIS") -> str:
    """One difficulty sub-block. Field order and types match the current ∇
    schema (verified against song 2403 of the running version): u16 radar
    values, no <label>. soundvoltex.dll also contains underscore variants
    (radar/hand_trip, radar/one_hand) and a max_exscore string, which
    RADAR_TAG_STYLE and EMIT_MAX_EXSCORE switch to without touching this logic.

    present chart → limited 3 (unlocked); difnum 0 → limited 0. `rad` holds the
    computed skill radar; without it the values stay 0. `credits` is the
    (effected_by, illustrator) pair for THIS difficulty — real songs credit a
    different effector per chart, which is why it is not taken from the song."""
    present = difnum > 0
    limited = 3 if present else 0
    r = rad or {}
    eff, illu = credits or ("", "")
    ht, oh = (("hand_trip", "one_hand") if RADAR_TAG_STYLE == "underscore"
              else ("hand-trip", "one-hand"))
    max_ex = ('\n        <max_exscore __type="s32">0</max_exscore>'
              if EMIT_MAX_EXSCORE else "")
    return f"""      <{tag}>
        <difnum __type="u8">{difnum}</difnum>
        <illustrator>{_credit(illu, encoding)}</illustrator>
        <effected_by>{_credit(eff, encoding)}</effected_by>
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


def chart_level(header: dict):
    """The chart's level — ksh `level=`, kson meta.level. An int when whole,
    else a float: ∇ levels carry tenths (17.5), and int() used to floor them."""
    try:
        v = float(header.get("level", 0) or 0)
    except ValueError:
        return 0
    return int(v) if v.is_integer() else v


def difnum(level) -> int:
    """level → music_db difnum (u8). ∇ stores tenths: 17.5 → 175. Measured on
    the running version's music_db: 1388 of 8581 official charts (16 %) have a
    difnum that is not a multiple of 10."""
    return max(0, min(255, int(round(float(level) * 10))))


def music_entry(sid, ascii_id, header, levels, radars=None,
                db_encoding: str = "Shift_JIS", credits=None, bg_no: int = 0):
    """Build a <music> entry matching the current ∇ music_db schema exactly.

    Verified field by field against real entries of the running game version
    (song 2403 of data/others/music_db.xml):
      * no <label> — that is the old omnimix-era format.
      * genre is u32; every radar value is u16; max_exscore is omitted.
      * difnum is level × 10 (∇ format), tenths included: 175 = 17.5.
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
    creds = credits or {}
    diffs = "\n".join(_diff_block(t, difnum(levels.get(i, 0)), rads.get(i),
                                  creds.get(i), db_encoding)
                      for t, i in order)
    # Same element and position as official entries: inside <music>, directly
    # after </difficulty>.
    tag = _custom_tag_setting()
    tag_xml = f'\n    <tag id="{tag}"/>' if tag is not None else ""
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
      <bg_no __type="u16">{max(0, min(65535, int(bg_no or 0)))}</bg_no>
      <genre __type="u32">16</genre>
      <is_fixed __type="u8">1</is_fixed>
      <version __type="u8">{DEFAULT_VERSION}</version>
      <demo_pri __type="s8">-2</demo_pri>
      <inf_ver __type="u8">{inf_ver}</inf_ver>
    </info>
    <difficulty>
{diffs}
    </difficulty>{tag_xml}
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


def song_ascii_id(header: dict, sid: int) -> str:
    """The <ascii> / folder name for a song. One source of truth, because both
    convert_song and the up-to-date check have to agree on it."""
    a = _ascii_id(header.get("title", ""))
    return f"nautica{sid}" if a == "song" else a   # all-non-ASCII → keep unique


def convert_song(folder: str, sid: int, out_root: str,
                 merged_path: str | None = None, db_encoding: str = "Shift_JIS",
                 progress=None):
    if sid > MAX_SONG_ID:
        print(f"[ERROR] id {sid} exceeds the game limit ({MAX_SONG_ID}). Ids above "
              f"3071 crash the game at boot. Use --base-db, or a lower --id.")
        _emit(progress, "song_failed", folder=os.path.basename(folder),
              song_id=sid, reason="id above the 3071 game limit")
        return None
    ksh_files = pick_charts(os.listdir(folder))
    if not ksh_files:
        print(f"[ERROR] no .ksh / .kson files in {folder}")
        _emit(progress, "song_failed", folder=os.path.basename(folder),
              song_id=sid, reason="no chart files")
        return None
    header0 = chart_header(os.path.join(folder, ksh_files[0]))
    ascii_id = song_ascii_id(header0, sid)
    song_dir = os.path.join(out_root, f"{sid:04d}_{ascii_id}")
    os.makedirs(song_dir, exist_ok=True)

    levels = {}
    radars = {}
    credits = {}                # slot → (effected_by, illustrator)
    audio_src = None
    audio_header = {}
    offsets = {}                # chart file → audio offset ms
    bg_no = 0                   # music_db <bg_no>: chart editor extra, else 0
    for kf in ksh_files:
        parsed = load_chart(os.path.join(folder, kf))
        res = _resolve_diff(kf, parsed["header"].get("difficulty"))
        if not res:
            print(f"  [skip] {kf}: unknown difficulty "
                  f"(file='{os.path.splitext(kf)[0]}', "
                  f"difficulty='{parsed['header'].get('difficulty','')}')")
            _emit(progress, "chart_skipped", folder=os.path.basename(folder),
                  chart=kf, reason="unknown difficulty")
            continue
        suffix, slot = res
        vox = emit_vox(parsed)
        for w in parsed.get("warnings") or []:     # once per chart
            print(f"  [warn] {kf}: {w}")
        if not bg_no and parsed.get("header", {}).get("bg_no"):
            try:
                bg_no = int(parsed["header"]["bg_no"])
            except ValueError:
                pass
        # newline="" is required: emit_vox already ends every line with CRLF.
        # Without it Windows text mode translates the \n again and the file
        # ends up with \r\r\n, which official .vox files never have — the
        # trailing CR then sticks to every section header (#TRACK1\r) and the
        # game's parser stops recognising them.
        with open(os.path.join(song_dir, f"{sid:04d}_{ascii_id}_{suffix}.vox"),
                  "w", encoding="latin-1", newline="") as fh:
            fh.write(vox)
        levels[slot] = chart_level(parsed["header"])
        credits[slot] = (parsed["header"].get("effect", ""),
                         parsed["header"].get("illustrator", ""))
        if _radar is not None:                  # skill radar for this chart
            try:
                radars[slot] = _radar.compute(parsed)
            except Exception as e:
                print(f"  [warn] radar failed for {kf}: {e}")
        jsrc = place_jackets(folder, song_dir, sid, slot + 1,
                             parsed["header"].get("jacket"))
        _emit(progress, "jacket_done", folder=os.path.basename(folder),
              song_id=sid, slot=slot,
              source=os.path.basename(jsrc) if jsrc else None)
        if audio_src is None:
            cand = _resolve_audio(folder, parsed["header"].get("m"))
            if cand:
                audio_src = cand
                audio_header = parsed["header"]
        offsets[kf] = chart_offset_ms(parsed["header"])
        print(f"  [ok] {kf} → {suffix}.vox (lv {levels.get(slot)})")
        _emit(progress, "chart_done", folder=os.path.basename(folder),
              song_id=sid, chart=kf, slot=slot, suffix=suffix,
              level=levels.get(slot))

    # audio: full track + a trimmed preview clip (.s3v = ASF/WMA-Pro).
    # ffmpeg reads any format, so ogg / mp3 / wav / flac / m4a / opus all work.
    if audio_src is None:
        audio_src = _resolve_audio(folder, None)
    if audio_src:
        print(f"  [audio] source: {os.path.basename(audio_src)}")
        ss, dur = _preview_window(audio_header)
        # The chart offset is baked into the full track. A song has ONE audio
        # file for all its charts, so the offset of the chart that named the
        # audio is used; charts that disagree get a warning (they will be off
        # by the difference). The preview needs nothing: `po` is a position
        # in the source file, and the preview is cut from the source.
        off = chart_offset_ms(audio_header)
        for kf, o in offsets.items():
            if o != off:
                print(f"  [WARN] {kf} has audio offset {o} ms, the audio is "
                      f"baked with {off} ms — that chart will be "
                      f"{o - off:+d} ms off.")
        ext = AUDIO_FORMAT
        writer = make_2dx if ext == "2dx" else make_s3v
        full = os.path.join(song_dir, f"{sid:04d}_{ascii_id}.{ext}")
        prev = os.path.join(song_dir, f"{sid:04d}_{ascii_id}_pre.{ext}")
        ok = writer(audio_src, full, offset_ms=off)
        writer(audio_src, prev, ss=ss, dur=dur)
        if ok:
            kind = "MS-ADPCM, cross-platform" if ext == "2dx" else "WMA"
            shift = (f", offset {off} ms "
                     f"{'trimmed' if off > 0 else 'padded'}") if off else ""
            print(f"  [ok] audio → .{ext} ({kind}{shift}, "
                  f"+preview {ss:.0f}s/{dur:.0f}s)")
        _emit(progress, "audio_done", folder=os.path.basename(folder),
              song_id=sid, ok=ok, fmt=ext, preview_start=ss, duration=dur,
              offset_ms=off)
    else:
        print("  [WARN] no audio file found in the song folder.")
        _emit(progress, "audio_done", folder=os.path.basename(folder),
              song_id=sid, ok=False, fmt=None, preview_start=None,
              duration=None)

    entry = music_entry(sid, ascii_id, header0, levels, radars, db_encoding,
                        credits, bg_no)

    # Automatically create/update the merged music_db so the song actually loads.
    total = None
    if merged_path:
        total = update_merged_db(merged_path, sid, entry, db_encoding)
        print(f"  [db] merged music_db updated → {merged_path} ({total} song(s))")

    print(f"[DONE] id {sid}: {song_dir}")
    _emit(progress, "song_done", folder=os.path.basename(folder), song_id=sid,
          song_dir=song_dir, charts=len(levels), total_songs_in_db=total)
    return entry


# ─────────────────────────────────────────────────────────────────────────────
# PROGRESS REPORTING — for the launcher V2 GUI
# ─────────────────────────────────────────────────────────────────────────────
# The print() calls are the CLI's presentation and are meant to disappear with
# V2. Anything a GUI needs to render goes through this callback instead, as
# plain data — no formatting, no terminal assumptions. A caller passes
# progress=fn to convert_song/convert_batch; fn(event: str, **fields) is called
# at every step worth showing. Never let a UI bug break an import, so failures
# inside the callback are swallowed.
#
# Events and their fields:
#   batch_start  total, mapped
#   song_start   index, total, folder, song_id, is_new
#   chart_done   folder, song_id, chart, slot, suffix, level
#   chart_skipped folder, chart, reason
#   jacket_done  folder, song_id, slot, source
#   audio_done   folder, song_id, ok, fmt, preview_start, duration, offset_ms
#   song_done    folder, song_id, song_dir, charts, total_songs_in_db
#   song_skipped index, total, folder, song_id      (unchanged, no work done)
#   song_failed  folder, song_id[, reason]   (also when a song raises)
#   batch_done   converted, new, skipped, map_path
def _emit(progress, event: str, **fields) -> None:
    if progress is None:
        return
    try:
        progress(event, **fields)
    except Exception as e:                      # a GUI must never abort a run
        print(f"  [warn] progress callback raised on '{event}': {e}")


def _default_merged_path(out_root: str) -> str:
    """layeredfs merges data_mods/<mod>/others/music_db.merged.xml into the base
    data/others/music_db.xml. With out = <mod>/music, the db lives in the
    sibling <mod>/others/ folder."""
    return os.path.join(os.path.dirname(os.path.abspath(out_root)),
                        "others", "music_db.merged.xml")


# ─────────────────────────────────────────────────────────────────────────────
# STABLE SONG IDS — folder → id, remembered across imports
# ─────────────────────────────────────────────────────────────────────────────
# Ids used to be positional: convert_batch walked the song folders in sorted
# order and numbered them from start_id. Adding one song that sorts early
# therefore SHIFTED every later id, so .vox filenames, jacket names and the
# music_db entries of already-imported songs no longer agreed — which is the
# only reason the whole library had to be deleted and rebuilt for every import.
# With the mapping below an id belongs to a song folder for good, so importing
# one song touches exactly that song.
IMPORT_MAP_NAME = "import_map.json"
IMPORT_MAP_VERSION = 1


def default_map_path(merged_path: str) -> str:
    """Where the mapping lives: next to the merged db, i.e. inside the mod
    folder (data_mods/nautica/import_map.json).

    It is deliberately NOT stored next to ksh2vox.py. The mapping only has
    meaning together with the music_db.merged.xml and the .vox/jacket files it
    describes; if the two can drift apart you get exactly the class of bug that
    already cost us two debugging rounds (stale ids surviving a re-import).
    Keeping them in one folder means "delete data_mods/nautica" stays the
    documented full reset, and copying or backing up the mod folder keeps the
    ids. It also survives the converter being bundled into the launcher, where
    the script directory can be a read-only temporary extraction path.
    Pass map_path explicitly to put it somewhere else."""
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(merged_path)), "..",
                     IMPORT_MAP_NAME))


def load_import_map(path: str) -> dict:
    """Read the folder → id mapping; a missing or unreadable file yields an
    empty one so a first import just works."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"version": IMPORT_MAP_VERSION, "songs": {}}
    if not isinstance(data, dict) or "songs" not in data:
        return {"version": IMPORT_MAP_VERSION, "songs": {}}
    return data


def save_import_map(path: str, imap: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    imap["version"] = IMPORT_MAP_VERSION
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(imap, fh, ensure_ascii=False, indent=2, sort_keys=True)


def map_key(folder: str) -> str:
    """Identity of a song folder. The folder name is stable across re-imports
    of the same Nautica pack and stays readable in the file; renaming a folder
    is treated as a new song (and is the documented way to force a new id)."""
    return os.path.basename(os.path.abspath(folder))


# Files that can change the output. Anything else in a song folder (readme,
# .txt, leftover archives) is ignored so it cannot trigger pointless work.
_FINGERPRINT_EXTS = CHART_EXTS + AUDIO_EXTS + (".png", ".jpg", ".jpeg")


def folder_fingerprint(folder: str) -> str:
    """Cheap identity of a song folder's inputs: name + size + mtime of every
    file that feeds the conversion.

    Metadata, not content — the same approach build tools use. Copying a
    library changes mtimes and forces a re-import, which is the harmless
    direction (extra work, never stale output). Content hashing would read
    every multi-MB audio file on each check for no real gain."""
    parts = []
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(_FINGERPRINT_EXTS):
            continue
        try:
            st = os.stat(os.path.join(folder, name))
        except OSError:
            continue
        parts.append(f"{name}\x00{st.st_size}\x00{st.st_mtime_ns}")
    return hashlib.sha1("\x01".join(parts).encode("utf-8")).hexdigest()


def is_up_to_date(imap: dict, folder: str, out_root: str,
                  merged_ids=None) -> bool:
    """True when this song can be skipped entirely.

    Every condition has to hold:
      * the folder is mapped and its input fingerprint is unchanged,
      * it was converted by THIS converter version — otherwise every bug we
        fix (slams, CRLF, jackets, credits …) would silently never reach
        already-imported songs, which is the worst possible failure here,
      * the output folder still exists and holds at least one .vox,
      * the merged db still has an entry for that id.
    """
    entry = (imap.get("songs") or {}).get(map_key(folder))
    if not isinstance(entry, dict) or not isinstance(entry.get("id"), int):
        return False
    if entry.get("converter") != __version__:
        return False
    # The tag lives in the merged db entry, which is only rewritten when the
    # song converts — so a changed setting must invalidate the skip.
    if entry.get("tag") != _custom_tag_setting():
        return False
    if entry.get("source") != folder_fingerprint(folder):
        return False
    ascii_id = entry.get("ascii")
    if not ascii_id:
        return False
    song_dir = os.path.join(out_root, f"{entry['id']:04d}_{ascii_id}")
    if not os.path.isdir(song_dir):
        return False
    if not any(f.lower().endswith(".vox") for f in os.listdir(song_dir)):
        return False
    if merged_ids is not None and entry["id"] not in merged_ids:
        return False
    return True


def record_import(imap: dict, folder: str, sid: int, song_dir: str) -> None:
    """Remember what was converted, so the next run can skip it."""
    entry = imap.setdefault("songs", {}).setdefault(map_key(folder), {})
    entry["id"] = sid
    entry["ascii"] = os.path.basename(song_dir).split("_", 1)[-1]
    entry["source"] = folder_fingerprint(folder)
    entry["converter"] = __version__
    entry["tag"] = _custom_tag_setting()


def assign_song_id(imap: dict, folder: str, floor_id: int) -> tuple[int, bool]:
    """Return (id, is_new) for a song folder, remembering the choice.

    `floor_id` is the first id that is safe to use — one above every real
    (non-custom) song, from --base-db. Already-mapped songs keep their id even
    if floor_id moved, unless that id would now collide with a real song, in
    which case it is reallocated and the caller re-converts that song."""
    songs = imap.setdefault("songs", {})
    key = map_key(folder)
    entry = songs.get(key)
    if isinstance(entry, dict) and isinstance(entry.get("id"), int):
        if entry["id"] >= floor_id and entry["id"] <= MAX_SONG_ID:
            return entry["id"], False
        print(f"  [warn] remembered id {entry['id']} for '{key}' is no longer "
              f"safe (real songs now reach {floor_id - 1}) — reassigning")
    taken = {e["id"] for e in songs.values()
             if isinstance(e, dict) and isinstance(e.get("id"), int)}
    sid = floor_id
    while sid in taken:
        sid += 1
    songs[key] = {"id": sid}
    return sid, True


def _release_failed_id(imap: dict, path: str, sid: int, out_root: str) -> None:
    """A song that failed on its first import gives its id back: no half entry
    (id only, no source/converter) is left in the import map - it would be
    saved with the next good song - and an output folder it left empty is
    removed. A song that was imported before keeps its id and its files."""
    imap.get("songs", {}).pop(map_key(path), None)
    names = os.listdir(out_root) if os.path.isdir(out_root) else []
    for name in names:
        full = os.path.join(out_root, name)
        if name.startswith(f"{sid:04d}_") and os.path.isdir(full) and not os.listdir(full):
            os.rmdir(full)


def convert_batch(parent: str, start_id: int, out_root: str,
                  merged_path: str, db_encoding: str = "Shift_JIS",
                  map_path: str | None = None, only: list | None = None,
                  progress=None, force: bool = False):
    """Convert song sub-folders under `parent` (each containing .ksh or .kson).

    Ids come from the import map, so re-running this is safe: songs keep the id
    they were given, and only genuinely new folders consume a new one. Pass
    `only` (a list of folder names) to import a subset without touching the
    rest — that is the launcher's per-song import path.

    Songs whose inputs and converter version are unchanged and whose output is
    still in place are skipped (see is_up_to_date); force=True converts
    everything regardless.

    A song that raises is reported (song_failed with a reason) and the batch
    goes on. Returns {converted, new, skipped, failed: [{folder, song_id,
    reason}], map_path}, or None when there was nothing to convert."""
    subs = sorted(d for d in os.listdir(parent)
                  if os.path.isdir(os.path.join(parent, d))
                  and any(f.lower().endswith(CHART_EXTS)
                          for f in os.listdir(os.path.join(parent, d))))
    if only is not None:
        wanted = {os.path.basename(o.rstrip("/\\")) for o in only}
        missing = wanted - set(subs)
        for m in sorted(missing):
            print(f"[WARN] requested song '{m}' has no chart files under {parent}")
        subs = [d for d in subs if d in wanted]
    if not subs:
        print(f"[ERROR] no song sub-folders with .ksh / .kson found under {parent}")
        return
    map_path = map_path or default_map_path(merged_path)
    imap = load_import_map(map_path)
    known = len(imap.get("songs", {}))
    # Read the merged db once: a song is only "done" if its entry is still in
    # there, and re-reading it per song would be wasteful in a big library.
    merged_ids = set(_read_existing_entries(merged_path)) if merged_path else None
    print(f"[BATCH] {len(subs)} song(s) under {parent}; "
          f"{known} already mapped, ids from {start_id}\n")
    done = new = skipped = 0
    failed = []
    _emit(progress, "batch_start", total=len(subs), mapped=known)
    for i, d in enumerate(subs):
        path = os.path.join(parent, d)
        if not force and is_up_to_date(imap, path, out_root, merged_ids):
            sid = imap["songs"][map_key(path)]["id"]
            skipped += 1
            print(f"── [{i + 1}/{len(subs)}] {d}  (id {sid}) — unchanged, skipped")
            _emit(progress, "song_skipped", index=i, total=len(subs),
                  folder=d, song_id=sid)
            continue
        sid, is_new = assign_song_id(imap, path, start_id)
        tag = "new" if is_new else "known"
        print(f"── [{i + 1}/{len(subs)}] {d}  (id {sid}, {tag})")
        _emit(progress, "song_start", index=i, total=len(subs),
              folder=d, song_id=sid, is_new=is_new)
        # One song that raises (a malformed chart the readers do not expect)
        # must not end the batch: it is reported like any failed song —
        # song_failed with folder, song_id and reason — and the next song
        # converts. It is not recorded in the import map, so the next run
        # tries it again.
        try:
            entry = convert_song(path, sid, out_root, merged_path, db_encoding,
                                 progress=progress)
        except Exception as e:                  # noqa: BLE001 — per-song guard
            reason = f"{type(e).__name__}: {e}"
            print(f"[ERROR] {d}: conversion failed — {reason}")
            traceback.print_exc(file=sys.stderr)
            failed.append({"folder": d, "song_id": sid, "reason": reason})
            _emit(progress, "song_failed", folder=d, song_id=sid, reason=reason)
            if is_new:
                _release_failed_id(imap, path, sid, out_root)
            print()
            continue
        if entry:
            done += 1
            new += 1 if is_new else 0
            header = chart_header(os.path.join(path, pick_charts(os.listdir(path))[0]))
            record_import(imap, path, sid,
                          f"{sid:04d}_{song_ascii_id(header, sid)}")
            save_import_map(map_path, imap)     # persist per song, not at the end
        else:
            failed.append({"folder": d, "song_id": sid, "reason": None})
            _emit(progress, "song_failed", folder=d, song_id=sid)
            if is_new:
                _release_failed_id(imap, path, sid, out_root)
        print()
    print(f"[BATCH DONE] {done} song(s) imported ({new} new), {skipped} unchanged"
          f"{f', {len(failed)} FAILED' if failed else ''}; "
          f"merged db: {merged_path}\n              id map: "
          f"{os.path.normpath(map_path)}")
    _emit(progress, "batch_done", converted=done, new=new, skipped=skipped,
          map_path=map_path)
    return {"converted": done, "new": new, "skipped": skipped,
            "failed": failed, "map_path": map_path}


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
    ap.add_argument("--map", default=None,
                    help=f"folder→id map (default <mod>/{IMPORT_MAP_NAME}, next "
                         f"to the merged db). Ids are remembered here, so a "
                         f"re-import keeps every song's id and only new folders "
                         f"get a new one.")
    ap.add_argument("--only", nargs="+", metavar="FOLDER", default=None,
                    help="with --batch: import only these song folders and "
                         "leave every other song untouched")
    ap.add_argument("--no-custom-tag", action="store_true",
                    help=f'do not write <tag id="{CUSTOM_TAG_ID}"/> into the music_db '
                         "entries (written by default; a Custom Songs folder in "
                         "the game collects the songs that carry it)")
    ap.add_argument("--custom-tag-id", type=int, default=CUSTOM_TAG_ID,
                    help=f"tag id to write (default {CUSTOM_TAG_ID}; official "
                         "songs use 1..44)")
    ap.add_argument("--force", action="store_true",
                    help="convert even songs whose inputs are unchanged "
                         "(they are skipped by default). A converter version "
                         "bump already forces a re-convert on its own.")
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
        print(f'  custom tag  : <tag id="{CUSTOM_TAG_ID}"/> written by default '
              f"(--no-custom-tag to skip)")
        bad = _check_positions()
        print("  positions   : " + ("ok (x/8 beat = 24 ticks, x/16 = 12)" if not bad
                                    else "FAILED — " + "; ".join(bad)))
        bad = _check_extras()
        print("  0.17 extras : " + ("ok (curve bake, FX block index + overflow, stop "
                                    "rows, laserrange reset, malformed editor data, "
                                    "-0.00, ManualSpeed in LOCKED_SPCONTROLER, "
                                    "POSTEFFECT length 0, scroll ramp bound)"
                                    if not bad else "FAILED — " + "; ".join(bad)))
        try:
            from PIL import Image  # noqa: F401
            print("  Pillow      : found (jackets resized to 300/676/108)")
        except ImportError:
            print("  Pillow      : MISSING — jackets will not be resized")
        return

    global WMA_ENCODER_CMD, AUDIO_FORMAT, AUDIO_CHANNELS
    global RADAR_TAG_STYLE, EMIT_MAX_EXSCORE
    set_custom_tag(not a.no_custom_tag, a.custom_tag_id)
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
        result = convert_batch(a.folder, start_id, a.out, merged, a.db_encoding,
                               map_path=a.map, only=a.only, force=a.force)
        if result["failed"]:
            sys.exit(1)             # scripts can tell a partly failed batch
    elif a.id is not None:
        # explicit --id wins: single-song conversion at exactly that id
        convert_song(a.folder, start_id, a.out, merged, a.db_encoding)
    else:
        # a single folder without --id still goes through the map, so importing
        # one song on its own gets the same stable id it would get in a batch
        map_path = a.map or (default_map_path(merged) if merged else None)
        if map_path is None:
            ap.error("single-song import needs --id when the merged db is "
                     "disabled (--db none), because there is nowhere to "
                     "remember the id")
        imap = load_import_map(map_path)
        merged_ids = set(_read_existing_entries(merged)) if merged else None
        if not a.force and is_up_to_date(imap, a.folder, a.out, merged_ids):
            sid = imap["songs"][map_key(a.folder)]["id"]
            print(f"[skip] {map_key(a.folder)} (id {sid}) is unchanged and "
                  f"already converted with ksh2vox {__version__}. "
                  f"Use --force to convert it anyway.")
            return
        sid, is_new = assign_song_id(imap, a.folder, start_id)
        print(f"[id] {map_key(a.folder)} → "
              f"id {sid} ({'new' if is_new else 'from map'})")
        if convert_song(a.folder, sid, a.out, merged, a.db_encoding):
            header = chart_header(os.path.join(
                a.folder, pick_charts(os.listdir(a.folder))[0]))
            record_import(imap, a.folder, sid,
                          f"{sid:04d}_{song_ascii_id(header, sid)}")
            save_import_map(map_path, imap)


if __name__ == "__main__":
    main()
