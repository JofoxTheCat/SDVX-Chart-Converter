# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/).

> Versions 0.2.0 – 0.11.0 were development iterations that were never published
> as separate commits; they are listed individually because each one fixed a
> distinct, independently verified problem. Only `v0.1.0`, `v0.1.1` and `v0.12.0`
> exist as tags.

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
