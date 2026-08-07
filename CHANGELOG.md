# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/).

> Versions 0.2.0 – 0.11.0 were development iterations that were never published
> as separate commits; they are listed individually because each one fixed a
> distinct, independently verified problem. Only `v0.1.0`, `v0.1.1` and `v0.12.0`
> exist as tags.

---

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
