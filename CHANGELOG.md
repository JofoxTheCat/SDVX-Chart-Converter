# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/).

> Versions 0.2.0 – 0.11.0 were development iterations that were never published
> as separate commits; they are listed individually because each one fixed a
> distinct, independently verified problem. Only `v0.1.0`, `v0.1.1` and `v0.12.0`
> exist as tags.

---

## [0.20.1] - 2026-10-27

Bug-fix release: two faults found right after v0.20.0 was published (the
fixes were meant to go into 0.20.0 but the tag was already public). Output
changes only for charts with a manual tilt that jumps inside one stretch
(library: Aegleseeker MXM, one row) and for songs whose remembered id lies
below the new id floor; the version bump re-converts every song once.

### Fixed
- **Song ids collided with real songs.** Ids start one above the highest real
  song id of `--base-db`, and the documented base was the plugin's
  `music_db.json`. That file is written by Asphyxia's WebUI asset update and
  lags behind a game update: for game build 2026071400 it ends at 2384 (35
  real songs missing) while the game's `data/others/music_db.xml` reaches
  2403, so the first import got **2385 — a real song**. Now:
  - `--base-db` is repeatable and the floor is the maximum over all bases
    (`max_real_id(paths, own_db)` for importers; `base_db_ids()` reports per
    file; `_max_existing_id(path)` stays for older callers). Custom songs never
    count: nautica-tagged json entries as before, a `*.merged.xml` / the
    converter's own merged db as a whole, and in any other xml (layeredfs's
    `_cache/others/music_db.xml` holds real songs and ours merged) the entries
    whose id and title match the own merged db.
  - A remembered id below the floor was reassigned before, but only if the
    song was not skipped as unchanged — `is_up_to_date` now takes `floor_id`
    and refuses such an id. The old id is also retired at once: its entry
    leaves `music_db.merged.xml` (layeredfs would lay it over the real song)
    and its output folder `<old id>_<ascii>` is removed; before, both stayed.
  - Verified on a scratch copy of the 24-chart library: json alone → ids
    2385–2392 (the old result), json + the game's xml → 2404–2411; a library
    imported at 2385–2392 re-run with both bases moves every song to
    2404–2411 with a warning, leaves exactly those 8 entries in the merged db
    and 8 folders, is byte-identical to a fresh import at 2404, and a further
    run skips all 8. `--self-check` line "song ids".
- **A manual tilt that jumps inside one stretch ramped instead.** kson
  `[y, [1.0, -1.0]]` (or two ksh `tilt=` lines on one tick) became two chained
  rows of one block with the value jumping between them. Under the Tilt
  grammar read out of the DLL (each row adds a key at its time with its
  *from* value, the block's last row also its end with *to*; durations in
  between are ignored) the key 1.0 at the jump was lost and
  the game ramped from the previous key into -1.0. The official encoding of an
  instant change is a **0-tick row** `t 0 old new` followed by the next row at
  the same tick from `new`: all 31 zero-duration Tilt rows of the official
  charts (12 charts, 10 songs) change the value, 30 are followed that way, the
  22 that do not open a block chain from the previous row's `to` (e.g. 0272
  4i `002,04,00 Tilt 2 0 0.25 -0.25 0.00 0.00`, then `002,04,00 Tilt 2 48
  -0.25 -0.25 0.00 0.00`). Two blocks touching at one tick with a different
  value occur only twice (one chart), so the jump stays inside its block. The
  last point of a stretch already had that row. Library: only Aegleseeker MXM
  changes, by one row (`038,02,24 Tilt 2 0 -0.30 0.30 0.00 0.00`, the ksh
  jump -0.3 → 0.3 at line 2370/2371); the other 23 chart files and all
  audio, jackets and the db are byte-identical. `--self-check` line
  "0.19 camera" has the case.

## [0.20.0] - 2026-10-27

Game effects for "full creative freedom" in the SDVX Chart Editor — but only
effects the game actually executes. Basis: the reverse-engineered VOX parser
and consumers of the running `soundvoltex.dll` (Ghidra, 2026-10-27; notes
outside the repo) and a survey of all 8,602 official charts. Charts that use
none of these features convert **byte-identically** to 0.19.0 (all 24 library
charts diffed).

### Added
- **#POSTEFFECT, complete.** Rows are `pos type len Effect stage index Param
  from to` (9 fields). The editor's rows now carry the **stage** (0 = the
  background's effect stage, 1 = "Overall"/lane stage; stages exist only where
  the song's background defines them, see bg_no below), the **instance
  index** (5th field — the official 2087 drives two ColorConversions in one
  stage with index 0 and 1; it was written as a constant 0 before) and a
  length in ticks **or `<n>ms`**. The 2nd field is parsed but never read by
  the game; `2` is written as before. All eight effects: ChromaticAberration,
  ColorConversion (Mode 0 grayscale, 1 sepia, 2 negative, 3 negative +
  complement, 4 hue rotation; Strength %, mode 4 degrees), RadicalBlur,
  SimpleNoise, CrtMonitorEffect, LuminousEffect, SetFrameLabel, RandomShake.
  `ChromaticAberration` is written with its correct name; the official
  misspelling `ChromaticAbberation` (109 rows) only works because unknown names
  fall back to effect 0 — it is accepted on input as an alias. Any other
  unknown effect name is dropped with a warning (it would silently become a
  chromatic aberration).
- **SPCONTROLER commands** (`impl["sdvx-editor"].vox.commands`): `LaneY`
  (lane slide/hide, value/1024), `BIL_RotZ` (`d` degrees), `Morphing2`
  (×0.125, shape unknown), `BAR` / `BAROFF` (bar lines), `SpecialN` kinds
  LANECOL, LANECLEARCOL, FRAME, SE, SE2, LIVE2D, NEMSYS, SIDEBG, EXMC_LABEL,
  EXMC_PARAM, RENDER_PRESET, DISABLE_PRE_EFFECT_LINE, EXBG, EXBGTEX. Values are
  VOX tokens (`f`/`i`/`x`/`d` prefixes and table names) and are written
  verbatim after validation; every row has exactly the 8 whitespace fields the
  parser requires (`%d,%d,%d\t%s%s\t%d\t%s\t%s\t%s\t%s` — any other count and
  the game drops the row silently). They are appended after the base,
  camera and tilt rows and never replace the template's Realize rows (the
  older `sp_controller` list still does).
- **Dead commands are refused.** LaneX, GEO_RotZ/RotX, Tilt_Mag, 3D_Scroll,
  Morphing0/1/3, HudY, AIRL/AIRR_ScaX, CAM_PosY/PosZ … and the SpecialN kinds
  LANEMODEL0..3, LANEDISP, SIDE, ADJRVZ, EXBGROTF … are parsed by the game and
  then never read; written, they would be invisible. They are dropped with a
  warning.
- **#BPM OPTION** (`RepresentativeBpm <float>` — overrides the tempo the
  game's hi-speed is based on; `ConstantScroll 0|1`), written right after
  `#BPM INFO` like the 26 official files that have it.
- **Note scripts**: `#SCRIPT_DEFINE` (`@SCRIPTSTART <id>` … `@SCRIPTEND`) and
  `#SCRIPTED_TRACK1..8` (`pos <id> [<id> …]`). Statements are validated
  against the grammar of the official scripts (1751, 2330): `$targetStep`,
  `$offsetX` or `$offsetY` `=` an arithmetic expression over numbers (optional
  `f`), `$targetStep`, `$offsetX`, `$offsetY`, `$currentStep`, `+ - * /`,
  parentheses, optional `when <expr> <op> <expr>` with `== != < <= > >=`. A
  script with an invalid line is dropped; an assignment whose track has no
  note starting exactly at that position is dropped (the game attaches it to
  that note only). Only scripts that are used are written.
- **ksh carries all of it**: `lane_toggle=<len>` (native KSM option, len in
  1/192 of a measure) becomes `LaneY 2 <len> 0.00 1024.00` / `1024.00 0.00`,
  alternating hide/show — the mapping VoxCharger and VOX2KSH use, and the
  official rows' shape (0791 `LaneY 2 240 0.00 1024.00`, tutorial comment
  「レーン消える」/「レーン復帰」). The chart editor writes everything else as
  comment lines after the first `--`, which K-Shoot skips:
  `//#vox_pe|stage|index|len|Effect|Param|from|to` (len ticks or `<n>ms`),
  `//#vox_sp|Name|type|len|p1|p2|p3|p4`, `//#vox_bpm|Key|Value`,
  `//#vox_script|id|statement`, `//#vox_scripted|track|id[,id…]`; the position
  is the line's own. `bg_no=<n>` in the ksh header is the music_db background
  (it was already read as a header key; now documented).
- `--self-check` reports "0.20 effects": exact rows for a kson and a ksh with
  every new feature, dead commands dropped, 8 fields per row, official script
  lines accepted, malformed ones refused.

### Needs an in-game test
Every one of these parses exactly like official rows, but what it looks like
has not been seen yet:
1. Any #POSTEFFECT on a background without its own effect stages (bg_no 0,
   or a common one like 5): every official chart that uses post effects has a
   dedicated background (bg_no 92–118, one on 5). On bg 0 they may do nothing.
2. Which stage covers the lane vs. the background on a given bg; is the HUD
   untouched?
3. LaneY: does +1024 slide the lane down or up, −1024 the other way?
4. Morphing2's visual; BIL_RotZ's target (lane, jacket billboard or
   background).
5. ConstantScroll; DISABLE_PRE_EFFECT_LINE / RENDER_PRESET.

## [0.19.0] - 2026-10-27

Camera work that 0.17/0.18 still dropped, measured on all 8,602 official charts
of the running game version (every `data/music/*/*.vox`: FORMAT VERSION 10:
5,577, 12: 2,689, 13: 336). The public converters VoxCharger (ksh → vox), VOX2KSH
(TsFreddie) and vox2ksh (zacharied) were read as second opinions; where only
they can say what something means, it is marked as a hypothesis.

### Added
- **Lane spins → laser field 4.** ksh `@(` `@)` (spin), `@<` `@>` (half spin),
  `S<` `S>` (swing) and kson `camera.cam.pattern.laser.slam_event`
  (`spin` / `half_spin` / `swing`) are written as the VOX spin type on the
  **first point of the slam** at the spin's position — where official charts
  put it.

  What the official data proves:

  | id | rows | charts | on a slam's 1st point | slam left / right | v13 rows | earliest song version (NOV/ADV/EXH/MXM) |
  |---|---|---|---|---|---|---|
  | 1 | 9,232 | 4,568 | 9,221 | 4,658 / 4,563 | 710 | 1 |
  | 2 | 3,194 | 1,653 | 3,182 | 1,603 / 1,579 | 14 | 2 |
  | 3 | 4,617 | 2,623 | 4,545 | 2,247 / 2,298 | 5 | 1 |
  | 4 | 34 | 33 | 34 | 22 / 12 | 6 | 3 |
  | 5 | 2,272 | 1,473 | 2,271 | 1,113 / 1,158 | 131 | 2 |
  | 6 | 395 | 213 | 395 | 180 / 215 | 132 | 6 (EXCEED GEAR) |
  | 7 | 122 | 83 | 120 | 59 / 61 | 58 | 6 (EXCEED GEAR) |

  - 99.5 % of the 19,866 non-zero values sit on the first point of a
    same-position pair; the rest are 9 + 11 + 9 + 1 + 2 rows on a pair's
    second point and 66 on a lone point (63 of them in one chart, 1697 MXM).
  - **The id carries no direction**: every id sits on left and right slams
    alike, so the turn direction is the slam's own.
  - **The id carries no length**: no id prefers a time signature (3.7–4.7 %
    of the spins of ids 1, 2, 3 and 5 alike sit in a 3/4 bar), so each id is
    a fixed animation. A spin at the same position on both lanes is rare (95
    positions, 91 of them with the same id twice).

  What the ids *mean* comes from the converters (hypothesis):

  | id | VOX2KSH (vox → ksh) | vox2ksh | VoxCharger | written for |
  |---|---|---|---|---|
  | 1 | `@(192` (one measure) | MEASURE | Measure (every `@(`) | spin ≥ 136 |
  | 2 | `@(48` | HALF_MEASURE | HalfMeasure (`@<`) | spin < 68 |
  | 3 | `@(96` | THREE_BEAT | ThreeBeat (`@(` ≤ 144) | spin 68–135 |
  | 4 | `@(432` + two extra turns of tilt | CANCER | TripleMeasure | — |
  | 5 | `@<96` | SWING → `@<` | Swing (`S`, short `@<`) | half spin, swing |
  | 6, 7 | — | — | — | — |

  All three rank the spin durations the same way, 2 < 3 < 1 < 4, so a K-Shoot
  spin (always one turn, the length scales its speed) becomes 2, 3 or 1 by
  length — boundaries at the geometric means of VOX2KSH's lengths (48 | 68 |
  96 | 136 | 192, in 1/192 of a measure). Type 4 adds turns K-Shoot does not
  have, so a long spin stays 1. A half spin is 5 (two of three converters). A
  swing is 5 too: VoxCharger is the only converter that writes swings at all,
  and 6/7 — the newest types — are known to none of them, so they are never
  written.
  - A spin needs a slam at its position; without one it is dropped with a
    warning. A slam turning the other way still takes the spin (the VOX
    direction is the slam's, warned). Both lanes slamming at the spin's
    position: the lane turning the spin's way, left first.
  - One warning per chart lists the spins whose length is more than 1.5× off
    their type's nominal length (VOX2KSH's) and every swing (scale / repeat /
    decay are not representable).
  - Library (8 songs, 24 charts): 187 authored spins → 180 written (type 1: 49,
    2: 44, 3: 29, 5: 58), 7 without a slam dropped, 15 against their slam's
    direction. Of the 180 library spins with a slam, 165 turn the slam's way —
    the direction convention (`(`/`<` = left = falling value) is the editor's
    KshReader's and VOX2KSH's.
- **Tilt block marker (row field 7).** Official Tilt rows form blocks: every
  row inside a block starts where the previous one ends (13,882 of 13,882) and
  continues its value; field 7 marks the block — **2 first row, 0 middle,
  3 last row, 1 a block of one row**.

  | field 7 | rows | grammar position |
  |---|---|---|
  | 0 | 12,295 | inside a block (12,204) |
  | 2 | 1,682 | opens a block (1,681) |
  | 3 | 1,678 | closes it (1,677) |
  | 1 | 1,116 | a whole block (1,116) |

  978 of the 987 official charts with Tilt rows follow this without a single
  exception; one chart (0706 kitasaitama EXH) has 89 middle rows outside any
  block, eight have one stray row or a block still open at the end. Between
  blocks there is a gap in 1,811 of 1,902 cases and the next block starts from
  a different value in 533 — the value is not carried over, i.e. outside a
  block the automatic tilt applies (the grammar is measured, this meaning is
  the hypothesis). Field 7 is Tilt-only: CAM_RotX / CAM_Radi rows carry 0
  there (62,991 / 160,383 rows).

  ksh2vox now groups its Tilt rows the same way and marks them. A manual value
  that is held — until the next auto mode, or to the chart end — gets a hold
  row (from = to) that ends the block, as official charts do (0061 retrospec
  INF holds 0.50 for 5,168 ticks to its end). Until now a 0-tick reset row
  (last → 0) stood at the auto mode instead, and a value held to the chart end
  had no row at all. A lone manual point is one hold row (type 1), no longer a
  0-tick row plus nothing.

### Not representable (unchanged, now with evidence)
Every SPCONTROLER row type of the official charts, by rows / charts:
CAM_Radi 160,380, CAM_RotX 63,000, Realize 17,216, Tilt 16,771, AIRL/AIRR_ScaX
8,605 / 8,601, SpecialN 4,719 (EXMC labels, sound effects, Live2D), BAROFF
1,334, BIL_RotZ 287 (4 charts), BAR 56, LaneY 51, HudY 48, ManualSpeed 30,
Morphing2 16, BGROT 4. The DLL also names CAM_PosY, CAM_PosZ, Tilt_Mag,
3D_Scroll, BIL_H and Morphing0/1/3 — used by no official chart.
- **zoom_side** (sideways lane shift): no row type moves the lane sideways.
- **center_split**: nothing comparable. Morphing2 (0 → 0.8 tweens, 5 charts)
  is a lane morph of unknown shape.
- **rotation_deg**: `BIL_RotZ` rotates in degrees (`d0` → `d-45` tweens;
  0271 vallis INF steps it every 3 ticks) — but the developers' own comments in the tutorial chart (0840) call
  it the *billboard* (「ビルボードを 0°→-45°」), in 4 charts only, and VOX2KSH
  reads it as manual tilt. Not solid enough to write.
- `LaneY 0 → 1024` is the lane hiding (tutorial comment 「レーン消える」 / 「レーン
  復帰」, ksh `lane_toggle` in VoxCharger and VOX2KSH) — not part of this
  release.

### Found, not changed
- **Realize defaults.** 6,909 charts start with `Realize 3 36.12 60.12 110.12`
  / `Realize 4 0.62 0.72 1.03` (v13: 331 of 336), 1,492 with the template's
  `17.12 … / 0.28 0.72 1.57` — and those are the songs of game versions 1 and
  2 (1,460 of 1,573 charts there; from version 3 on 36.12 has 6,936 of 7,012).
  The tutorial chart comments name the rows: Realize 3 = `CAMERA_RadiusYZ`,
  Realize 4 = `SPC_TARGET_CAMERA_RotX`. The template keeps its values (verified
  working in game); switching to the current default is a camera play test.
- **Manual tilt sign.** All three converters flip the sign between ksh and VOX
  (VoxCharger `vox = -ksh` "untested", vox2ksh `ksh = -vox`, VOX2KSH
  `ksh = -1.5 × vox`); ksh2vox writes `vox = +ksh` since 0.17.0 (that release
  called it "the VOX2KSH reading", which it is not). Left as it is pending the
  play test below.

### Verified
- Full library conversion (8 songs, 24 charts) against 0.18.0: audio, jackets,
  music_db and every non-camera line byte-identical; the `.vox` files differ
  only in laser field 4 (180 rows) and in Tilt rows (4 charts: Aegleseeker MXM,
  GΛLVΛNIZER MXM, The Devil Incarnate EXH / MXM — field 7 markers, 5 hold rows
  added, 5 reset rows removed; 201 Tilt rows before and after). `import_map.json` differs only in `converter`.
  Non-spin warnings identical. §6 rules hold: laser starts = ends, ≤ 2 points
  per position, 10 laser fields, values 0..1, CRLF only, every spin id on a
  slam's first point, every Tilt block well-formed.
- **Round trip of the official charts** (all 7,001 files with a spin, 19,768
  spins on a slam): VOX → SDVX Chart Editor VoxReader → kson → ksh2vox.
  - With the editor's VoxReader as it is (every id read as a nominal one-beat
    spin, direction right): the spin survives on 19,054 (96.4 %; 714 more land
    on the other lane of a two-lane slam), but the type is right only for the
    3,066 type-2 spins (15.5 %) — one beat is type 2.
  - With the ids read back through this table (1 → spin 192, 2 → 48, 3 → 96,
    5 → half spin 96, direction = the slam's): 18,550 of the 19,219 spins of
    types 1/2/3/5 come back with the same type on the same slam (96.5 %); the
    other 669 come back on the other lane of a two-lane slam. Types 4, 6 and 7
    (549) are not written by design.
- `--self-check` checks the spin types by kind and length, ksh suffix and kson
  `slam_event` parsing, the spin on a slam's first point, the warning for a
  spin without a slam, and the Tilt block markers with hold rows.

### Needs a play test
1. Spin types 1/2/3/5 — does a K-Shoot spin look right, and is a swing as
   type 5 acceptable?
2. Tilt blocks: does the game release to auto tilt at a block end (3 / 1)?
3. Manual tilt sign and scale (see "Found, not changed").

- Bumped because the `.vox` output changes: every song re-converts once on the
  next import.

---

## [0.18.0] - 2026-10-26

### Changed
- **Skill radar from a fitted model.** The music_db `<radar>` values now come
  from `radar_model.py`, a port of the SDVX Chart Editor's data-driven radar:
  85 time-based pattern features per chart (chord density over 1.25 s, hold
  seconds, knob time and travel, notes played while the *other* / the *same*
  hand's knob moves, tempo changes, …) and one additive model per axis —
  intercept, linear terms and gradient-boosted regression trees — read from
  `radar_model.json`. The model file was fitted by the editor's calibrator on
  the official charts of the user's own game install and holds aggregate
  numbers only (weights, split thresholds, leaf values), no chart data.
  Values are on the music_db scale and clamped to 0..200 like official ones
  (radar.py wrote up to 336).

  Accuracy against the official music_db radar, 8,573 charts, 5-fold CV grouped
  by song (from the model file's own metrics):

  | Axis | classic radar.py MAE / r | model CV MAE / r | hold-out (id ≥ 2100) MAE |
  |---|---|---|---|
  | NOTES | 13.4 / 0.996 | **0.10** / 1.000 | 0.14 |
  | PEAK | 28.4 / 0.920 | **2.00** / 0.996 | 2.21 |
  | TSUMAMI | 27.7 / 0.434 | **2.34** / 0.987 | 2.14 |
  | TRICKY | 24.4 / 0.567 | **10.7** / 0.825 | 12.6 |
  | HAND-TRIP | 42.6 / 0.787 | **2.81** / 0.972 | 2.91 |
  | ONE-HAND | 10.5 / 0.935 | **3.22** / 0.989 | 3.22 |

  TRICKY stays the weakest axis: part of it is era-dependent and not in the
  chart, and camera features are deliberately not model inputs (fan charts use
  the camera at any difficulty; with them a fan NOV out-scored its own MXM).
- `radar.py` is unchanged and stays available as `--radar classic`
  (`set_radar_mode("classic")` for importers). Without `radar_model.py` or
  `radar_model.json` the converter falls back to it with one warning per run.
  The radar in use is recorded per song in `import_map.json` (`"radar"`), so
  switching re-converts exactly the songs written the other way.
- The parsers record a pulse-precise chart description next to their tick data
  (`parsed["radar_input"]`, 240 pulses per quarter): ticks cannot hold a line of
  a 40- or 36-line ksh measure (galvanizer, AureoLe), and the rhythm-grid
  features look at pulse mod 60 / 40. It is read the way the editor's
  KshReader / KsonReader read the file (ksh slams by the same 1/32 rule with the
  dense-movement exception, `laser_l/r_curve` kept on its point, explicit kson
  slams, curves and widths, lane spins counted). The VOX path never reads it.
- When ksh2vox is loaded by file path (the V2 launcher bridge), `radar_model.py`
  is taken from beside `ksh2vox.py`; before the launcher knows the new file it
  still gets the model radar instead of silently falling back.

### Verified
- **Parity with the editor.** All 25 chart files of the Nautica library (24 +
  the ABYSS MOTION `.ksh` twin): every one of the 85 features equals the
  editor's `PatternAnalysis` bit for bit, and the six radar values equal
  `SkillRadarModel.EstimateFile`. The editor test
  `RadarTests.LibraryChartsMatchRadarModelPy` checks this without tolerance;
  `LibraryChartsMatchRadarPy` (classic port vs radar.py) still passes 25/25.
  One detail needed for that: the editor sorts with .NET's unstable introsort,
  and the tie order of laser travel events at the same instant decides a
  floating-point sum — on official chart 2282 MXM `laser_speed_peak` came out
  one ulp off, exactly on a tree threshold, TRICKY 57 instead of 56. The port
  now sorts with the same algorithm.
- **All 8,572 official charts** with a music_db radar, read by the editor's
  VoxReader, written as kson and converted by ksh2vox: 8,572 / 8,572 identical
  to the editor (on the VOX and on the kson). In-sample MAE against music_db
  (these are the training charts, so lower than the CV numbers above): NOTES
  0.10, PEAK 1.53, TSUMAMI 1.75, TRICKY 8.08, HAND-TRIP 1.64, ONE-HAND 2.26;
  radar.py on the same charts 13.4 / 28.4 / 27.7 / 24.4 / 42.6 / 10.4.
- Full conversion of the library with 0.17.1 and 0.18.0: every `.vox`, `.2dx`
  and jacket is byte-identical; the merged music_db differs only inside
  `<radar>`, `import_map.json` only in `converter` and the new `radar`.
  `--radar classic` reproduces the 0.17.1 music_db byte for byte. Laser
  sections close (1s = 2s per track), same-position runs are 1 or 2, no
  `\r\r\n`, no empty `<maximum>`.
- Speed: the 8-song library converts in 4.2 s (3.9 s with 0.17.1, ffmpeg
  included); the radar itself is ~5 ms per chart (8,572 charts in 46 s).
- `--self-check` reports the model (version, generation date, training size)
  and checks it on synthetic charts: empty chart all zero, every feature the
  model needs is computed, values in range, half-away-from-zero rounding.

| Chart | 0.17.1 radar.py (N / P / Ts / Tr / HT / OH) | 0.18.0 model |
|---|---|---|
| ABYSS MOTION 192.333 INF | 110 / 61 / 47 / 40 / 162 / 126 | 115 / 128 / 76 / 56 / 98 / 105 |
| Aegleseeker[20.9] MXM | 143 / 74 / 46 / 39 / 336 / 268 | 165 / 200 / 107 / 115 / 86 / 114 |
| ΛμreoLe=RushOVER=E ~for Λnge EXH | 125 / 67 / 40 / 140 / 167 / 154 | 140 / 160 / 70 / 110 / 58 / 115 |
| ΛμreoLe=RushOVER=E ~for Λnge MXM | 150 / 86 / 41 / 292 / 187 / 165 | 179 / 192 / 60 / 114 / 64 / 106 |
| Canto IX Boss 10 Battle Them NOV | 38 / 38 / 18 / 24 / 0 / 0 | 15 / 33 / 25 / 29 / 0 / 3 |
| Canto IX Boss 10 Battle Them ADV | 58 / 41 / 20 / 24 / 41 / 45 | 40 / 59 / 45 / 43 / 8 / 48 |
| Canto IX Boss 10 Battle Them EXH | 76 / 53 / 21 / 24 / 80 / 73 | 66 / 98 / 55 / 53 / 28 / 66 |
| Canto IX Boss 10 Battle Them MXM | 97 / 57 / 22 / 54 / 132 / 120 | 97 / 144 / 66 / 67 / 94 / 104 |
| Jumpy star NOV | 34 / 34 / 17 / 0 / 0 / 0 | 11 / 22 / 55 / 24 / 0 / 1 |
| Jumpy star ADV | 57 / 40 / 17 / 0 / 58 / 44 | 44 / 57 / 47 / 35 / 0 / 33 |
| Jumpy star EXH | 61 / 43 / 20 / 0 / 56 / 51 | 49 / 65 / 59 / 38 / 0 / 44 |
| Jumpy star MXM | 74 / 51 / 20 / 0 / 102 / 85 | 69 / 81 / 78 / 40 / 69 / 84 |
| GΛLVΛNIZER NOV | 48 / 40 / 18 / 0 / 18 / 13 | 30 / 39 / 25 / 7 / 0 / 6 |
| GΛLVΛNIZER ADV | 71 / 48 / 24 / 31 / 57 / 44 | 61 / 79 / 34 / 43 / 0 / 28 |
| GΛLVΛNIZER EXH | 102 / 55 / 37 / 33 / 161 / 135 | 107 / 128 / 62 / 52 / 24 / 68 |
| GΛLVΛNIZER MXM | 126 / 60 / 40 / 114 / 287 / 237 | 143 / 161 / 86 / 77 / 74 / 107 |
| The Devil Incarnate NOV | 46 / 43 / 17 / 0 / 12 / 12 | 26 / 47 / 26 / 8 / 0 / 6 |
| The Devil Incarnate ADV | 82 / 48 / 21 / 13 / 31 / 30 | 72 / 101 / 18 / 45 / 1 / 32 |
| The Devil Incarnate EXH | 118 / 54 / 26 / 47 / 114 / 107 | 126 / 134 / 39 / 58 / 35 / 91 |
| The Devil Incarnate MXM | 146 / 76 / 37 / 180 / 199 / 175 | 169 / 200 / 53 / 108 / 91 / 123 |
| じゃすと・べりー・くいっくりー！ NOV | 45 / 34 / 14 / 0 / 11 / 11 | 27 / 27 / 16 / 5 / 0 / 2 |
| じゃすと・べりー・くいっくりー！ ADV | 59 / 40 / 18 / 0 / 24 / 25 | 43 / 46 / 42 / 13 / 0 / 22 |
| じゃすと・べりー・くいっくりー！ EXH | 99 / 51 / 33 / 0 / 184 / 154 | 104 / 111 / 49 / 40 / 17 / 81 |
| じゃすと・べりー・くいっくりー！ INF | 107 / 51 / 31 / 11 / 183 / 154 | 112 / 112 / 55 / 47 / 16 / 85 |

- Bumped because the music_db output changes: every song re-converts once on
  the next import.

---

## [0.17.1] - 2026-10-26

### Fixed
- **Ranged ksh tempo header inflated TRICKY.** A .ksh whose header declares a
  tempo range (`t=35-321`) and whose first inline tempo is `t=321` was parsed
  to the BPM events `[(0, 35), (0, 321), …]`: the range's low value became a
  tempo at tick 0. `emit_vox` keeps one BPM per tick (last wins), so the VOX was
  always right, but `radar.py` read the raw list and counted a spurious
  |1/321 − 1/35| tempo change into TRICKY. A ranged header is now what it is in
  K-Shoot (libkson's `InsertBPMChange` skips a value with a `-`): the
  song-select display range only, never a tempo event. If the first inline
  tempo comes after tick 0 it applies from tick 0 (libkson, the chart editor);
  only a chart with no inline tempo at all falls back to the range's low value.
  A plain header (`t=180`) is unchanged. The music_db `bpm_min`/`bpm_max`
  display range still comes from the header, as before.
- `radar.py` 0.1.1 dedupes same-tick BPM events (last wins, exactly what
  `emit_vox` writes to `#BPM INFO`) before computing timing and the tempo-change
  statistic. Plain sorting also let the *higher* of two same-tick tempos win
  the tick → seconds mapping.

### Verified
- Full conversion of the 8-song / 24-chart Nautica library with 0.17.0 and
  0.17.1 into scratch folders: every `.vox`, `.2dx` and jacket is byte-identical
  (BPM INFO unchanged); the merged music_db differs only in TRICKY, and
  `import_map.json` only in `converter`. NOTES, PEAK, TSUMAMI, HAND-TRIP,
  ONE-HAND and `bpm_min`/`bpm_max` are unchanged everywhere.

  | Chart | header / first inline | TRICKY 0.17.0 → 0.17.1 |
  |---|---|---|
  | AureoLe EXH | `35-321` / `321` | 171 → 140 |
  | AureoLe MXM | `35-321` / `321` | 323 → 292 |
  | Canto IX NOV | `70-97` / `91` | 32 → 24 |
  | Canto IX ADV | `70-97` / `91` | 32 → 24 |
  | Canto IX EXH | `70-97` / `91` | 33 → 24 |
  | Canto IX MXM | `70-97` / `91` | 62 → 54 |

  Aegleseeker (`234-1872` / `234`) is unchanged: the low value equals the first
  inline tempo, so the old extra event was no change.
- `--self-check` covers the ranged header (inline tempo at 0, later, absent)
  and the radar dedupe.
- Bumped because the music_db output changes: every song re-converts once on
  the next import (the converter version is part of the `import_map.json`
  up-to-date check).

---

## [0.17.0] - 2026-10-26

Everything below used to be dropped on the way to VOX. Each mapping was
measured against the 336 official FORMAT VERSION 13 charts of the running game
version (and, where v13 has no example, against the older official charts the
same game still plays). Public converters were read as a second opinion:
VoxCharger (ksh → vox) and VOX2KSH (vox → ksh).

### Added
- **Wide lasers.** Laser field 6 is the width: kson section `w` = 2 or ksh
  `laserrange_l/r=2x` writes `2`. In a .ksh the option widens the **next
  section only** — the section that opens consumes it (K-Shoot; the chart
  editor's KshReader resets it at the same point and its KshWriter repeats the
  option before every wide section). Measured: the width is constant within
  all 19,604 official sections, and wide sections store their values in 0..1
  like normal ones, so values are written unscaled.
- **Laser curves (.kson).** A point's `[a, b]` curve is baked into points every
  3 ticks, the way official charts store curves: 140,336 official points exist
  in `#TRACK1/8` but not in `#TRACK ORIGINAL`, 94 % of them 3 ticks apart, all
  with a curve type in field 8 (never 0). Fitting the baked values shows type 4
  is an ease-out and type 5 an ease-in sine; a curve above the diagonal
  (b > a) is written 4, below it 5. Slams and section ends are untouched. A
  `.ksh` curve is not baked again: K-Shoot writes curved ksh segments together
  with its own baked points.
- **FX hold effects.** Each chart gets its own `#FXBUTTON EFFECT INFO` (all
  official v13 charts have exactly 12 blocks) and every FX hold the index of
  its block: block position + 2, i.e. 2..13 — official holds use exactly
  2..13, and VOX2KSH reads them as `index - 2`. The table starts as the
  template's (the official default layout); an effect equal to a default block
  uses it, others replace blocks no hold refers to. Rows are official rows:
  only the parameter naming the variant (wave length, reduction, pitch) is
  carried over. With more than 12 distinct effects every effect type gets a
  block first: a further variant keeps its default block only while enough
  blocks stay free for the types without one, and leftover variants share the
  nearest block of their type.
  Retrigger, Echo, Gate, Phaser, TapeStop, SideChain, Wobble, BitCrusher,
  PitchShift and Flanger are mapped; others play without an effect (warning).
  ksh `fx-l=`/`fx-r=` with `#define_fx` and kson `long_event`/`def` are read.
- **Laser filters.** Laser field 5: 0 peak, 2 low-pass, 4 high-pass, 5 bit
  crusher, taken from ksh `filtertype=` (and `#define_filter`) or kson
  `laser.pulse_event`, per section. Official v13: 0 on 78 % of the points,
  2 and 4 far more common than 1 and 3 (27,291 vs 3,186; 10,548 vs 570).
  `#TAB EFFECT INFO` stays the template's — byte-identical in 323 of 336
  official charts. Retrigger/gate/… laser effects have no laser filter and
  fall back to peak (one warning listing them).
- **Tilt.** `#TILT MODE INFO` follows ksh `tilt=` / kson `camera.tilt`:
  normal 0, bigger 1, keep_bigger 2. 0 is the normal auto tilt — 335 of 336 v13
  charts carry only `001,01,00 0`, so the template never had tilt switched off.
  `zero` and `biggest` have no VOX mode and fall back with a warning. Manual
  tilt values become `Tilt` tweens in `#SPCONTROLER` (same units as ksh, the
  VOX2KSH reading), clamped to the official range ±1, reset to 0 when an auto
  mode follows.
- **Camera.** `zoom_top` → `CAM_RotX`, `zoom_bottom` → `CAM_Radi`, as linear
  tweens chained segment to segment like the official rows (curved segments
  in 12-tick pieces). Units: zoom_top / 100 and zoom_bottom / −100
  (VoxCharger), clamped to ±1 — every official value lies in −1..1.
- **Scroll speed and stops.** kson `beat.scroll_speed` / ksh `scroll_speed`
  become `ManualSpeed` rows in `#LOCKED_SPCONTROLER`, the official v13 form:
  of the three official charts with ManualSpeed, the only FORMAT VERSION 13
  one (2330 kiskillilia MXM) and the v12 0271 vallis INF put it there, with an
  initial `001,01,00 ManualSpeed 0 0 f1.00`, type `2147483648` (0x80000000) on
  every row that leaves 1.00 and type `0` on rows back at 1.00; only the v12
  2037 apocalypseray uses `#SPCONTROLER`. The rows are a step function with one
  row per 6 ticks on ramps — the form of 2037's gradual change. Negative speeds
  never occur officially: clamped to 0 with a warning; capped at 5730, the
  official maximum. kson `beat.stop` / ksh `stop=` become the official stop
  form: a `4-` BPM row at the start, a plain row at the end (62 such rows in
  14 official charts).
- **Chart editor extras.** kson `impl["sdvx-editor"].vox` (SDVX Chart Editor):
  `bg_no` → music_db `<bg_no>`, `post_effect` rows replace the template's
  `#POSTEFFECT`, `sp_controller` rows replace its base `#SPCONTROLER` rows.
  A post effect's length is written in ticks, an instant one as `0` like every
  official mid-chart row (`1ms` appears only on the template's rows at
  `001,01,00`). Without them nothing changes. Malformed editor data (a number
  where a list belongs, a non-string name, NaN/Infinity) is skipped with one
  warning per list.
- One warning per chart for what VOX cannot hold: lane spins/swings,
  zoom_side, center_split, rotation_deg, custom chip/slam sounds, effect
  parameter changes, pfiltergain.
- Every 0.17 kson subtree (audio effects, camera, tilt, scroll speed, stops,
  editor extras) is read defensively: a node of the wrong type counts as
  absent and a malformed entry is skipped with one warning.
- `convert_batch` catches an exception per song: the song is reported as
  `song_failed` (folder, song_id, reason `"<Type>: <message>"`), is not
  recorded in the import map (the next run retries it) and the batch goes on.
  It now returns `{converted, new, skipped, failed: [{folder, song_id,
  reason}], map_path}`; the progress events keep their shape.
- `--self-check` checks curve baking, FX block indices and overflow, stop
  rows, the `laserrange` reset, malformed editor data, `-0.00`, ManualSpeed
  placement, the POSTEFFECT length and the scroll-ramp bound.

### Fixed (found by an independent verification before release)
- **`laserrange_l/r=2x` never reset.** Once a lane had one wide section, every
  later section of that lane came out wide: 1,961 wide sections across the 24
  library .ksh charts for 890 `laserrange_*=2x` lines. Now the counts are equal
  in every chart, and ABYSS MOTION's .ksh and .kson agree on the width of
  every section (lane L 13 wide, lane R 18; before, the .ksh had 45 / 55).
- **FX table overflow priority.** With more than 12 distinct effects the
  variants took their default blocks before every type had one: 13 effects
  (4 retrigger, 2 gate, phaser, tape stop, wobble, flanger, bit crusher, side
  chain, pitch shift) left pitch shift with index 0, i.e. no effect. Now it
  gets a block and a gate variant shares instead. Library output is unchanged
  (no library chart was short of a block; still 0 holds without one).
- **Malformed 0.17 data raised.** `{"impl": {"sdvx-editor": {"vox":
  {"sp_controller": 5}}}}` → TypeError; 25 of 27 hand-made malformed cases
  (a number for `camera.tilt`, a string pulse in `beat.stop`, a list as
  effect type, Infinity …) ended the song, now all 27 convert with a warning. A mutation fuzz of the 0.17 subtrees (900 mutations of 6
  editor-written kson files) went from 44 crashes in those subtrees to 0, no
  hangs.
- **`-0.00`.** `CAM_Radi` at zoom_bottom 0 was written `-0.00` (zoom_bottom ×
  −1/100); 658 such values over the library. Every fixed-decimal float
  (SPCONTROLER rows, laser values, pitch shift, ManualSpeed, POSTEFFECT) now
  prints a zero as `0.00`.
- **ManualSpeed** moved from `#SPCONTROLER` to `#LOCKED_SPCONTROLER` in the v13
  form described above (ABYSS MOTION: 16 rows + the initial row).
- **POSTEFFECT length 0** was written `1ms`; now `0`, as official.
- **Scroll-speed ramps were unbounded.** A ramp to a point millions of pulses
  away walked every 6th tick of it and wrote rows far past END POSITION
  (`scroll_speed: [[0, 1.0], [48000000, 2.0]]`: 10,194 lines, 0.5 s; ten times
  the distance takes minutes). Rows at or past the chart end are dropped now,
  and a ramp longer than 1000 steps gets a coarser step (a multiple of 6) with
  one warning. The longest ramp in the library is 92 steps (ABYSS MOTION,
  2.9 measures) and the official 2037 ramps are 14 and 8 rows, so no real
  chart is affected (library output byte-identical). Same repro: 193 lines,
  0.00 s.
- **A huge editor `end_pulse` never finished.** `impl["sdvx-editor"].end_pulse`
  built one measure entry per measure up to it (9.6e9 pulses: 7.3 s, 1e15:
  no result after 40 s). The hint may now add at most 64 measures after the
  last event (`END_HINT_MAX_MEASURES`); real trailing bars are a few measures
  (AureoLe: 5½). Repro at 1e15 and 1e18: 0.01 s.
- **A failed song kept its new id.** The map entry it was given (id only, no
  source or converter) was saved with the next good song, and an empty
  `<id>_<ascii>` folder stayed in the output. A song that fails on its first
  import now gives the id back and its empty folder is removed; a song that
  was imported before keeps both. Verified: good/bad/good batch → ids 2800 and
  2801 for the two good songs, no leftover folder.
- **`--batch` returned exit code 0 with failed songs.** It now exits 1 when any
  song failed, so scripts can tell.

### Verified
- All 24 library charts convert; every `.vox` passes the §6 checks (CRLF only,
  10 laser fields, section starts = ends, at most 2 points per position,
  values 0..1); notes, BPM, signatures, end positions and laser geometry are
  identical to 0.16.0 apart from the new baked curve points.
- After the fixes above, compared with the unfixed 0.17.0 output of the same
  library: audio, jackets, music_db and import map byte-identical; in the .vox
  files only laser field 6 (5,007 rows 2 → 1), `-0.00` → `0.00` (658 values)
  and the 16 ManualSpeed rows (one chart) differ. Warnings identical.
- The SDVX Chart Editor's VOX tests (reader + export, 32) pass against it.

### Needs a play test
1. FX effect sound in general, and blocks 3 (phaser) / 12 (flanger): the two
   public converters disagree on these ids.
2. FX overflow (> 12 effects): holds sharing the nearest block of their type.
3. Laser filter codes 2/4 vs 1/3 for low-/high-pass.
4. Wide lasers: width 2 with values over 0..1, and only the sections the
   chart marks (the reset above).
5. Baked kson curves: shape, and whether the game reads the curve type in
   field 8 at all.
6. Camera units (/100) and sign of `zoom_bottom`; manual tilt sign and units.
7. Tilt modes 1/2 (bigger / keep_bigger) — they occur only in v10 charts.
8. `ManualSpeed` in `#LOCKED_SPCONTROLER` with type 0x80000000 — the flag's
   meaning is unknown; it is copied from the two official LOCKED examples.
9. Stops via `4-` — official only in v10/v12 charts, not in any v13 one.
10. Editor `#POSTEFFECT` rows with a length (v12 official rows use tick
    lengths 18–768 and `500ms`/`2000ms`; v13 ones only `0` and `1ms`).

## [0.16.0] - 2026-10-25

### Fixed
- **Time signatures other than x/4.** The VOX beat is the signature's
  denominator note — 192/den ticks — so a 6/8 bar runs `BB` 1..6 with offsets
  0..23. Every measure used to be split at 48 ticks, giving a 6/8 bar `BB` 1..3
  with offsets up to 47. Measured over every official chart with a non-/4
  signature: `BB` never exceeds the numerator and offsets stay below 192/den
  (the 0.4 % that do not occur at the same rate in plain 4/4 charts). A
  denominator that does not divide 192 keeps the quarter split.
- **END POSITION past the last measure.** The end position was written as an
  extra beat of the last measure (`077,05,00` in 4/4). Official charts never
  have `BB` above the numerator; it is now `078,01,00`, the same tick.
- **Every .ksh chart was one measure too long.** Whatever followed the last
  `--` became a measure — the empty string after the file's final newline, or
  the `#define_fx` / `#define_filter` block. It now counts only if it holds
  chart lines. Verified on all 24 sample charts: the measure count equals the
  number of `--` lines and the end still lies after the last note. Every
  END POSITION moves one measure earlier (AureoLe 454 → 453, Jumpy Star
  078 → 077); the chart editor's own ksh reader puts the end at the same place.
- **kson end.** kson has no end marker. The chart now ends with the measure
  holding the last event (one measure more was added before, which matched
  the .ksh only because of the phantom measure above). On ABYSS MOTION, the
  sample with both formats, .ksh and .kson both end at `102,01,00`. A .ksh's
  trailing bars cannot be recovered from a K-Shoot kson; the chart editor
  stores them as `impl["sdvx-editor"]["end_pulse"]` (kson pulses), which is
  now read when present and not before the last event. Other kson files are
  unaffected.
- **kson 1.0 time signatures crashed the conversion.** The spec writes
  `beat.time_sig` as `[idx, [n, d]]`; the reader called `int([n, d])`. Now
  the spec form, the flat `[idx, n, d]` and the object forms `{idx, n, d}` /
  `{idx, v: {n, d}}` are all accepted (tested with each; none of the sample
  kson files has a time signature).
- **Levels with tenths were floored.** ∇ difnums carry tenths (175 = 17.5);
  1388 of 8581 official charts (16 %) are not a multiple of 10. ksh `level=`
  and kson `meta.level` are now read as numbers and `difnum = round(level×10)`.
- **Fake slams from dense laser movement.** Every value change within 1/32
  note, taken in pairs, became a slam. Now a .ksh pair is a slam only by the
  rule K-Shoot writes slams by (libkson `KshIOOut.cpp`): no further change
  within 1/32 after it; exactly 1/32 long, or shorter only with no change
  within 1/32 before it and a next point within 1/16 of its start. All
  Nautica charts except ABYSS MOTION keep their slam counts exactly (verified
  per lane); ABYSS lane R drops from 129 to 100, which is what its .kson marks.
- **kson slams are no longer inferred.** A .kson states its slams (`[v, vf]`);
  running the ksh heuristic on it turned ABYSS lane R's dense 5-pulse points
  into 35 fake slams (134 = 100 − 1 + 35) and lost the real one at pulse 74160. kson points are now
  emitted as authored: ABYSS gives exactly 80 / 100, matching the file.
- **An unreadable jacket aborted the whole song.** A corrupt image
  (`UnidentifiedImageError` and the like) is now reported and the song
  converts without that jacket, as if none were present.
- **Audio offset was ignored.** KSH `o=` / kson `audio.bgm.offset` — per the
  KSH spec the starting point of the song audio, a larger value judging notes
  later — was never read, so 6 of the 8 sample songs (20, 22, 45, 80, 2514 ms)
  played out of sync. VOX has no offset field, so the offset is now baked into
  the full-track audio: a positive one trims the lead, a negative one pads
  silence. Verified on Jumpy Star (`o=2514`, 100 BPM): the source is silent
  until 3.729 s and the first note sits at 1.200 s chart time; the converted
  `.2dx` now starts sounding at 1.215 s and is exactly 2.514 s shorter. A
  synthetic `o=-500` copy starts at 4.229 s. The preview is unchanged — `po`
  is a position in the source file and the preview is cut from the source.
  Charts of one song with different offsets get a warning (one audio file per
  song; none of the samples do this).

### Added
- `--self-check` now checks tick → position for 4/4, 6/8 and 7/16 measures.
- `audio_done` progress event carries `offset_ms`.

### Needs a play test
- The offset sign and the x/8 split are verified against the spec, the audio
  and the official files, not yet in game.
- Ends are now tighter: as the .ksh says, often less than a measure after the
  last note. Official charts usually leave 1–3 measures. What the game does at
  END POSITION (cut the music? wait for the audio?) has not been observed.

## [0.15.0] - 2026-10-25

### Added
- **Custom Songs tag.** Every `music_db` entry now carries `<tag id="100"/>`
  directly after `</difficulty>` — the element and position official entries
  use for their folder tags. The running game version uses tag ids 1–44, so
  100 never collides. A Custom Songs folder set up in spice2x collects exactly
  the songs that carry this tag; without it none of ours were picked up and the
  folder stayed empty.
- `--no-custom-tag` turns the tag off; `--custom-tag-id` picks another id.
  `set_custom_tag()` does the same for callers that import the module (the V2
  launcher bridge).

### Changed
- The tag setting is recorded per song in `import_map.json`. Switching it
  re-converts exactly the songs written the other way, and the version bump
  makes every already-imported song pick the tag up once. Verified on a scratch
  library: default run writes the tag, an identical re-run skips, a
  `--no-custom-tag` run re-converts and drops it, the next default run
  re-converts and restores it.

## [0.14.0] - 2026-08-09

### Added
- Unchanged songs are skipped. A song re-converts only when its inputs changed
  (name, size and mtime of every chart/audio/image file), its output or
  `music_db` entry went missing, or it was produced by a different converter
  version — so a fixed bug always reaches songs that are already imported.
  `--force` converts regardless. An unchanged 9-song library re-runs in 0.08 s
  instead of 3.2 s.

## [0.13.0] - 2026-08-09

### Added
- **Stable song ids.** A folder → id map (`import_map.json`, next to the merged
  db) makes an id permanent. Ids used to be positional, so importing one song
  that sorted early renumbered every later song and the whole library had to be
  rebuilt. Verified: adding the alphabetically first song to an 8-song library
  leaves all 8 ids on the same songs; a full re-import changes nothing.
- `--only` imports a subset; `progress=` callback for the V2 launcher.

## [0.12.0] - 2026-08-07

### Added
- **`.kson` support** — the newer K-Shoot format is now parsed natively and is
  preferred over `.ksh` when a song folder ships both. `.kson` stores exact laser
  values instead of KSH's 51 steps and marks slams explicitly, so the 1/32-note
  slam heuristic is not needed there. Verified against a chart available in both
  formats: notes, holds, laser sections/points, slams and end position come out
  identical.
- `radar.py` and `template_v13.vox` are now part of the repository. Both are
  required at runtime and were previously missing from a fresh clone — the
  template because a `.gitignore` rule silently swallowed it (see below), and
  `radar.py` because it had never been added.
- `CHANGELOG.md` (this file).
- `.gitattributes` marking `*.vox` as non-text, so the bundled template checks
  out byte-identical on Windows and Linux instead of being line-ending-normalized
  per platform.

### Fixed
- **Jackets were picked from the wrong file.** The jacket is now taken from the
  chart's own `jacket=` header / `meta.jacket_filename` instead of the first
  image found in the folder, which selected backgrounds (`bg0.jpg`,
  `black.jpg`) for 3 of 8 test songs.
- Duplicate `#BPM INFO` line when a `.ksh` states its start tempo twice.
- `.gitignore`: `!template_v13.vox` carried a trailing comment on the same line.
  Git does not support trailing comments in `.gitignore`, so the negation never
  matched and `*.vox` kept the template out of the repository.

### Changed
- `requirements.txt` now lists Pillow (jacket resizing) and describes the actual
  audio path. It previously claimed the project had no third-party dependencies
  and produced WMA Pro `.s3v` audio.
- README rewritten to match the current behaviour.

---

## [0.11.0]

### Fixed
- **Laser slams were converted as very fast slides.** KSH writes a slam as two
  laser values on adjacent lines, and both were emitted at their two distinct
  ticks, so the game interpolated between them: the laser slid instead of
  snapping and the slam sound never played. Official charts put both points on
  the *same* position (measured: 2259 such pairs across five songs, never a run
  of three). Pairs closer together than a 1/32 note are now collapsed onto the
  first point's tick.

## [0.10.0]

### Fixed
- **`.vox` files were written with `\r\r\n`.** `emit_vox()` already terminates
  every line with CRLF, and the file was then opened in Windows text mode, so
  the `\n` was translated a second time. Official charts of the running game
  version contain `\r\n` only; the stray `CR` sticks to every section header and
  the game's parser stops matching them.
- **Titles no longer become XML numeric character references.** cp932 has no `Ø`,
  so `&#216;` was emitted; `ifs_layeredfs` resolves that to raw byte `0xD8`,
  which is halfwidth katakana `ﾘ` in Shift_JIS — `ΛμreoLe=RushØVER=E` rendered as
  `ΛμreoLe=RushﾘVER=E`. Unmappable characters are now folded to a close cp932
  equivalent before writing.

## [0.9.0]

### Fixed
- **Lasers never ended.** The parser ignored `-` (laser off), so an entire lane
  became a single section: only the first point received a start marker and only
  the last an end marker, leaving lasers on screen drifting toward the next
  section. Real sections are now tracked and each emits `1` (start) / `0`
  (middle) / `2` (end).

### Changed
- Laser lines now match the official 10-field VOX v13 layout.

## [0.8.0]

### Changed
- Match the **current** `music_db` format, verified against a live ∇ database:
  radar values are `u16` (not `u8` — this is why the in-game skill radar stayed
  blank), `genre` is `u32`, `version` is `7`, `demo_pri` is `-2`, and there is no
  `<label>` element.
- Radar axes with no contribution now write `0` instead of the render floor
  of `10`.

## [0.7.0]

### Added
- `--radar-names {hyphen,underscore}` for the two radar tag spellings
  `soundvoltex.dll` accepts.
- `--max-exscore` to emit `<max_exscore>` in each difficulty block.

## [0.6.0]

### Added
- `--self-check`: prints the version and which optional parts are active
  (radar module, template, ffmpeg, Pillow), then exits.

### Changed
- The default background/camera setup (`SPCONTROLER`) is now taken verbatim from
  a reference chart.

## [0.5.0]

### Added
- Skill radar computed per chart via `radar.py` and written into `music_db`.
  Scaling formulas are ported from kshoot-tools' `radar.ts` (MIT).

## [0.4.0]

### Added
- `--audio-format {2dx,s3v}`, `--audio-channels {mono,stereo}` and a pluggable
  `--wma-encoder` for `.s3v`.

### Changed
- **Cross-platform audio:** output is now `.2dx` / MS-ADPCM, mono, by default.
  ffmpeg can encode this on both Windows and Linux. `.s3v` is WMA Pro, which
  ffmpeg cannot encode on any platform; the `wmav2` fallback was tested in-game
  and produced silence.

## [0.3.0]

### Added
- Jacket resizing to the sizes the game expects (300 / 676 / 108 px), via Pillow.
  Non-square sources are centre-cropped first.

## [0.2.0]

### Added
- `--base-db`: song ids are assigned automatically just above the highest real
  song id in your own `music_db`.

### Fixed
- **Hard song id limit of 3071.** Established by disassembling
  `soundvoltex.dll`: the per-song difficulty table is
  `[6 difficulties][3072 songs][164 bytes]` and is indexed by song id. Ids above
  3071 skip the pointer setup but are written anyway, causing an access
  violation. Ids like the previously suggested `9001+` crash the game at boot.
- An empty `<maximum>` block is no longer emitted. It makes the game load a
  non-existent MXM chart and crash at boot; real entries emit `infinite` and
  `maximum` only when that chart exists.

### Changed
- Real `music_db` schema, `difnum` = level × 10, KSM difficulty names, Shift_JIS
  titles.

---

## [0.1.1] - 2026-06-28

### Added
- `music_db.merged.xml` creation and maintenance — entries are added or replaced
  per song id, so re-running the same id is safe.

## [0.1.0] - 2026-06-28

### Added
- Initial KSH → VOX v13 converter.

[0.12.0]: https://github.com/JofoxTheCat/SDVX-Chart-Converter/releases/tag/v0.12.0
[0.1.1]: https://github.com/JofoxTheCat/SDVX-Chart-Converter/releases/tag/v0.1.1
[0.1.0]: https://github.com/JofoxTheCat/SDVX-Chart-Converter/releases/tag/v0.1.0
