# sdvx-chart-importer

Convert user-generated **K-Shoot/USC (Nautica)** charts into **SOUND VOLTEX ∇
(Nabla)** songs for **spice2x**. It produces a complete song folder (`.vox`
charts, `.2dx` audio, jackets) *and* maintains the `music_db` entry, so a Nautica
song can be dropped into a `data_mods` overlay and played.

Built from a direct comparison of real Nabla `.vox` charts, a live `music_db` and
Nautica `.ksh`/`.kson` charts — **not** based on the outdated
`boringcactus/ksh2vox`. Target format is **VOX FORMAT VERSION 13** (Nabla /
SDVX VII).

> Companion to the [SDVX7-Launcher](https://github.com/JofoxTheCat/SDVX7-Launcher).
> Standalone for now; a future launcher GUI can pull this in as a dependency and
> wire it to Nautica.

## Quick check

```
python ksh2vox.py --self-check
```

Prints the version and which optional parts are active — skill radar, template,
ffmpeg, Pillow. Run this first whenever something behaves unexpectedly; a missing
`radar.py` or a stale copy of the script explains most surprises.

## Usage

Whole Nautica pack at once (a parent folder of many song folders):

```
python ksh2vox.py <pack_folder> --batch \
  --base-db "<asphyxia>/plugins/sdvx@asphyxia/webui/asset/json/music_db.json" \
  --out ./data_mods/nautica/music
```

Single song:

```
python ksh2vox.py <ksh_song_folder> --base-db <music_db.json|music_db.xml> \
  --out ./data_mods/nautica/music
```

- `<ksh_song_folder>`: one `.ksh` or `.kson` per difficulty
  (`nov/adv/exh/mxm`, optionally `inf`), the audio (any format ffmpeg reads) and
  the jacket(s).
- `--base-db`: your real `music_db.json` (from the Asphyxia plugin) or
  `music_db.xml`. Ids are assigned automatically starting just above the highest
  real song id — no collision, no overflow. **Strongly preferred over `--id`.**
- `--id`: a free song id (single) or the **starting** id (`--batch`). Only use
  this if you know your id range is safe — see the limit below.
- `--out`: song output root. Each song lands in `<out>/<id>_<ascii>/` with
  `_1n/_2a/_3e/_4i/_5m.vox`, the `.2dx` audio + preview, and `jk_<id>_<n>.png`.

> **Delete the previous output folder before re-converting.** The merged db is
> merged *per id*, so entries from an earlier run — especially ones with ids
> outside your current range — survive and can crash the game at boot.

### Song ids are capped at 3071

This is a hard limit in `soundvoltex.dll`, not a convention. The per-song
difficulty table is `[6 difficulties][3072 songs][164 bytes]` and is indexed by
song id; ids above 3071 skip the pointer setup but are written anyway, which
faults. High ranges like `9001+` **will crash the game at boot**. The importer
enforces the limit, and `--base-db` picks safe ids for you.

### The merged music_db is built automatically

The importer **creates and maintains `music_db.merged.xml` for you** — no manual
copy-paste. By default it is written next to the songs at
`<out>/../others/music_db.merged.xml` (i.e. `data_mods/nautica/others/`), which
is exactly where **ifs_layeredfs** merges it into the base
`data/others/music_db.xml`. Each run adds or replaces that song's `<music>`
entry, so re-running the same id is safe.

- `--db <path>`: write the merged db somewhere else.
- `--db none`: disable auto-merge (just emit the song files).
- `--db-encoding`: defaults to `shift_jis`, which is what the game reads. Titles
  are written as cp932 bytes; characters cp932 cannot represent are folded to a
  close equivalent (`Ø` → `O`, accents stripped) rather than escaped, because the
  game does not resolve XML numeric character references.
- `--radar-names {hyphen,underscore}`: radar tag spelling. Both are accepted by
  `soundvoltex.dll`; the default matches a known-good db.
- `--max-exscore`: also emit `<max_exscore>`. Off by default — the value could
  not be derived reliably from official charts, and a wrong one distorts EX-score
  grading.

Then make sure the launcher loads the ifs hook
(`"spice_hooks": ["ifs_hook.dll"]` or `"load_ifs_hook": true`) and the songs
appear in-game.

## Chart formats

Both K-Shoot formats are read. When a folder ships a `.ksh` **and** a `.kson` of
the same name, the `.kson` wins: it stores exact laser values instead of KSH's
51 steps and marks slams explicitly, so no heuristics are involved.

Difficulty slots are resolved from the **filename first**, then the chart's
`difficulty=` header — that order matters, because charts exist whose file is
named `mxm` while the header still says `infinite`.

## What converts cleanly vs. by default

| Part | Result |
|------|--------|
| Timing / BPM / time signatures | exact (both tick-based; KSH line → VOX 48-tick grid) |
| BT notes (chip + hold) | exact |
| FX notes (chip + hold) | positions exact; hold effects mapped to the chart's 12-block effect table (since 0.17.0) |
| Laser paths | scaled exactly (KSH 0–50 → VOX 0.0–1.0) |
| Laser sections / slams | sections opened and closed correctly; slams snap |
| Wide lasers (`laserrange_*=2x`, kson `w`) | width 2, values over the wide range (0.17.0); a ksh `laserrange` widens only the next section |
| Laser curves (kson `[a, b]`) | baked into points every 3 ticks like official charts (0.17.0); a `.ksh` already carries K-Shoot's own baked points |
| Laser filters (`filtertype`, kson `pulse_event`) | peak / low-pass / high-pass / bit crusher (0.17.0); other laser effects fall back to peak with a warning |
| Tilt | auto modes normal / bigger / keep_bigger, manual tilt as `Tilt` rows (0.17.0) |
| Camera `zoom_top` / `zoom_bottom` | `CAM_RotX` / `CAM_Radi` rows, clamped to the official ±1 (0.17.0) |
| Scroll speed / stops | `ManualSpeed` rows in `#LOCKED_SPCONTROLER` (official v13 form) / `4-` BPM rows (0.17.0) |
| Skill radar | computed per chart (see below) |
| Effect parameter changes, spins, `zoom_side`, `center_split`, custom key sounds | not representable — reported once per chart |

Each mapping was measured against the official v13 charts; the ones that still
need an in-game test are listed in `CHANGELOG.md` under 0.17.0. A chart without
any of these keeps the template's defaults verbatim.

Charts saved by the SDVX Chart Editor can carry VOX-only data in
`impl["sdvx-editor"].vox` (background `bg_no`, `#POSTEFFECT` and
`#SPCONTROLER` rows); it is used when present. Malformed entries there are
skipped with a warning. In a batch, a song whose conversion fails is reported
and the remaining songs still convert.

## Skill radar

`radar.py` computes the six radar axes (notes, peak, tsumami, tricky, hand-trip,
one-hand) per chart and writes them into `music_db`. The scaling formulas and the
10–1000 clamp are ported from [kshoot-tools](https://github.com/123jimin/kshoot-tools)'
`radar.ts` (MIT); the underlying statistics are reimplemented and calibrated
against reference numbers from real songs.

These are approximations — upstream itself notes that a more accurate TRICKY
formula is still open — but the values land inside the range of real songs on
every axis. `radar.py` is optional: if it is missing, conversion still works and
all radar values are `0`, which collapses the in-game hexagon to a point.

## Audio

Nautica charts ship with different audio containers (`.ogg`, `.mp3`, `.wav`,
`.flac`, `.m4a`, `.opus`, …). Since **ffmpeg** decodes all of them, any of these
works as input — the source is taken from the KSH `m=` tag (KSM `;`-layered lists
and wrong extensions are tolerated) or auto-detected in the folder.

The output is **`.2dx` with MS-ADPCM audio, mono** — the configuration that is
verified working in-game and that ffmpeg can produce on Windows *and* Linux. A
trimmed **preview** clip is written from the KSH `po`/`plength` tags.

- `--audio-channels stereo` exists for experiments; the game's `.2dx` path
  renders stereo imbalanced (one channel louder), which is why mono is the
  default.
- `--audio-format s3v` writes the official ASF/WMA-Pro container instead. ffmpeg
  **cannot encode WMA Pro on any platform**, so this requires an external encoder
  via `--wma-encoder "<cmd> {in} {out}"`. Without one you get a `wmav2`
  placeholder that the game plays as silence.

Without ffmpeg on PATH, charts and jackets still convert and audio is skipped
with a warning.

## Jackets

The jacket is taken from the chart's own `jacket=` / `meta.jacket_filename`
field. With **Pillow** installed it is written in the three sizes the game
expects — 300×300, 676×676 and 108×108 — centre-cropping non-square sources
first. Without Pillow the source image is copied through unresized.

## Requirements

- Python 3.10+
- **Pillow** (`pip install -r requirements.txt`) — jacket resizing
- **ffmpeg** on PATH — audio

`ksh2vox.py`, `radar.py` and `template_v13.vox` must sit in the same folder.

## Notes & scope

- Custom songs need a local/compatible **Asphyxia** that serves the custom ids,
  and the WebUI song assets may need updating.
- `template_v13.vox` is a generic default scaffold (effect/camera sections only,
  no chart notes) used to emit valid v13 files. Its tables are the defaults; a
  chart's own effects, tilt and camera replace the matching sections.
- **Legitimate use only:** your own or user-generated Nautica charts. Do not use
  this to extract or redistribute proprietary game data. SOUND VOLTEX and KONAMI
  trademarks belong to their respective owners; this is an unofficial,
  non-commercial fan tool.

## License

MIT — see [LICENSE](LICENSE).
