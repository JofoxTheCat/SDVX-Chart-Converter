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
__version__ = "0.1.0"

import argparse
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "template_v13.vox")

TPB = 48                     # VOX ticks per beat (offset 0..47)
# KSH difficulty file name → (vox suffix, music_db diff index, slot label)
DIFF_MAP = {
    "nov": ("1n", 0), "adv": ("2a", 1), "exh": ("3e", 2),
    "inf": ("4i", 3), "grv": ("4i", 3), "hvn": ("4i", 3),
    "vvd": ("4i", 3), "xcd": ("4i", 3), "nbl": ("4i", 3),
    "mxm": ("5m", 4),
}


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
    laser = [[], []]               # laser points: (tick, val0_50, seg)
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
            # Lasers: 2 chars
            for k in range(2):
                v = _laser_val(las[k]) if k < len(las) else None
                if isinstance(v, int):
                    laser[k].append((t, v))
            li += 1
        tick += ticks_in_measure

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
    bpm_lines = "\n".join(f"{pos(t)}\t{b:.4f}\t4" for t, b in parsed["bpm"])
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


def _laser_track(points, pos):
    out = []
    prev = None
    for idx, (t, v) in enumerate(points):
        seg = 1 if prev is None else (2 if idx == len(points) - 1 else 0)
        out.append(f"{pos(t)}\t{v / 50.0:.6f}\t{seg}\t0\t0\t1\t0\t0\t0\t0\t12")
        prev = t
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


def make_s3v(ogg_path: str, out_path: str,
             ss: float | None = None, dur: float | None = None) -> bool:
    """ogg → .s3v (ASF container) via ffmpeg.

    Real Nabla .s3v files are ASF with **WMA Pro** audio (2ch / 44.1 kHz). We
    try wmapro first to match; if this ffmpeg build can't encode it we fall back
    to wmav2 (always available). `ss`/`dur` trim a segment (used for the preview).
    """
    if not shutil.which("ffmpeg"):
        print("  [WARN] ffmpeg not found – skipping audio. Install ffmpeg and "
              "re-run; .s3v is an ASF/WMA-Pro container (2ch/44100).")
        return False
    pre = (["-ss", f"{ss:.3f}"] if ss else []) + (["-t", f"{dur:.3f}"] if dur else [])
    for codec in ("wmapro", "wmav2"):
        cmd = (["ffmpeg", "-y"] + pre + ["-i", ogg_path,
               "-vn", "-ac", "2", "-ar", "44100",
               "-c:a", codec, "-b:a", "192k", "-f", "asf", out_path])
        try:
            subprocess.run(cmd, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            continue
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


def place_jackets(src_folder: str, out_folder: str, sid: int, slot_label: int):
    """Copy jacket(s). If 3 sizes exist use them, else reuse one for all sizes
    (no resizing, per project preference)."""
    imgs = [f for f in os.listdir(src_folder)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))]
    if not imgs:
        return
    base = imgs[0]
    src = os.path.join(src_folder, base)
    for suffix in ("", "_b", "_s"):
        dst = os.path.join(out_folder, f"jk_{sid:04d}_{slot_label}{suffix}.png")
        shutil.copyfile(src, dst)


def music_entry(sid, ascii_id, header, levels):
    """Build a music_db <music> entry. levels: {slot_index: level_int}."""
    def lvl(i): return levels.get(i, 0)
    title = header.get("title", "Unknown")
    artist = header.get("artist", "Unknown")
    return f"""  <music id="{sid}">
    <info>
      <label>{sid}</label>
      <title_name>{title}</title_name>
      <ascii>{ascii_id}</ascii>
      <artist_name>{artist}</artist_name>
      <bpm_min __type="u32">{int(float(header.get('t','120').split('-')[0]))*100}</bpm_min>
      <bpm_max __type="u32">{int(float(header.get('t','120').split('-')[-1]))*100}</bpm_max>
      <inf_ver __type="u8">0</inf_ver>
    </info>
    <difficulty>
      <novice>   <difnum __type="u8">{lvl(0)}</difnum></novice>
      <advanced> <difnum __type="u8">{lvl(1)}</difnum></advanced>
      <exhaust>  <difnum __type="u8">{lvl(2)}</difnum></exhaust>
      <infinite> <difnum __type="u8">{lvl(3)}</difnum></infinite>
      <maximum>  <difnum __type="u8">{lvl(4)}</difnum></maximum>
    </difficulty>
  </music>"""


def convert_song(folder: str, sid: int, out_root: str):
    ksh_files = [f for f in os.listdir(folder) if f.lower().endswith(".ksh")]
    if not ksh_files:
        print(f"[ERROR] no .ksh files in {folder}")
        return
    header0 = parse_ksh(os.path.join(folder, ksh_files[0]))[0]
    ascii_id = _ascii_id(header0.get("title", os.path.basename(folder)))
    song_dir = os.path.join(out_root, f"{sid:04d}_{ascii_id}")
    os.makedirs(song_dir, exist_ok=True)

    levels = {}
    audio_src = None
    audio_header = {}
    for kf in ksh_files:
        stem = os.path.splitext(kf)[0].lower()
        key = next((k for k in DIFF_MAP if k in stem), None)
        if not key:
            print(f"  [skip] {kf}: unknown difficulty name")
            continue
        suffix, slot = DIFF_MAP[key]
        parsed = convert_chart(os.path.join(folder, kf))
        vox = emit_vox(parsed)
        open(os.path.join(song_dir, f"{sid:04d}_{ascii_id}_{suffix}.vox"),
             "w", encoding="latin-1").write(vox)
        try:
            levels[slot] = int(parsed["header"].get("level", 0))
        except ValueError:
            levels[slot] = 0
        place_jackets(folder, song_dir, sid, slot + 1)
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
        ok = make_s3v(audio_src, os.path.join(song_dir, f"{sid:04d}_{ascii_id}.s3v"))
        ss, dur = _preview_window(audio_header)
        make_s3v(audio_src, os.path.join(song_dir, f"{sid:04d}_{ascii_id}_pre.s3v"),
                 ss=ss, dur=dur)
        if ok:
            print(f"  [ok] audio → .s3v (+ preview {ss:.0f}s/{dur:.0f}s)")
    else:
        print("  [WARN] no audio file found in the song folder.")

    print(f"\n[DONE] {song_dir}")
    print("\nAdd this entry to your music_db.merged.xml:\n")
    print(music_entry(sid, ascii_id, header0, levels))


def main():
    ap = argparse.ArgumentParser(description="KSH (Nautica) → VOX v13 (Nabla) converter")
    ap.add_argument("folder", help="KSH song folder (contains .ksh + .ogg + jacket)")
    ap.add_argument("--id", type=int, required=True, help="song id (use a free range, e.g. 9001+)")
    ap.add_argument("--out", default="./data_mods/nautica/music",
                    help="output root (default ./data_mods/nautica/music)")
    a = ap.parse_args()
    convert_song(a.folder, a.id, a.out)


if __name__ == "__main__":
    main()
