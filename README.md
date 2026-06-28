# sdvx-chart-importer

Convert user-generated **K-Shoot/USC (Nautica)** charts into **SOUND VOLTEX ∇
(Nabla)** songs for **spice2x**. It produces a complete song folder (`.vox`
charts, `.s3v` audio, jackets) plus a ready-to-paste `music_db` entry, so a
Nautica song can be dropped into a `data_mods` overlay and played.

Built from a direct comparison of real Nabla `.vox` and Nautica `.ksh` charts —
**not** based on the outdated `boringcactus/ksh2vox`. Target format is **VOX
FORMAT VERSION 13** (Nabla / SDVX VII).

> Companion to the [SDVX7-Launcher](https://github.com/JofoxTheCat/SDVX7-Launcher).
> Standalone for now; a future launcher GUI can pull this in as a dependency and
> wire it to Nautica.

## Usage

```
python ksh2vox.py <ksh_song_folder> --id 9001 --out ./data_mods/nautica/music
```

- `<ksh_song_folder>`: one `.ksh` per difficulty (`nov/adv/exh/mxm`, optionally
  `inf`), the audio (`.ogg`) and the jacket(s).
- `--id`: a free song id — use a high range (e.g. `9001+`) so it never clashes
  with the base game or omnimix.
- Output: `<out>/<id>_<ascii>/` containing `_1n/_2a/_3e/_4i/_5m.vox`, the `.s3v`
  audio + preview, and `jk_<id>_<n>.png` jackets. The `<music>` entry is printed
  to stdout.

Then: add the printed `<music>` block to your `music_db.merged.xml`, place the
song folder under your `data_mods/.../music/`, and make sure the launcher loads
the ifs hook (`"spice_hooks": ["ifs_hook.dll"]` or `"load_ifs_hook": true`).

## What converts cleanly vs. by default

| Part | Result |
|------|--------|
| Timing / BPM / time signatures | exact (both tick-based; KSH line → VOX 48-tick grid) |
| BT notes (chip + hold) | exact |
| FX notes (chip + hold) | positions exact; **effect = default** |
| Laser paths | scaled exactly (KSH 0–50 → VOX 0.0–1.0) |
| Laser slams / spins, FX/filter effects, camera/tilt | **defaults** (from `template_v13.vox`) |

The error-prone parts intentionally fall back to neutral defaults — fine-tuning
is a job for a later editor pass, not the auto-importer.

## Audio

Nautica charts ship with different audio containers (`.ogg`, `.mp3`, `.wav`,
`.flac`, `.m4a`, `.opus`, …). Since **ffmpeg** decodes all of them, any of these
works as input — the source is taken from the KSH `m=` tag (KSM `;`-layered
lists and wrong extensions are tolerated) or auto-detected in the folder.

The output `.s3v` is an **ASF container with WMA-Pro** audio (2ch / 44.1 kHz):
ffmpeg tries `wmapro`, falling back to `wmav2`. A trimmed **preview** clip is
written from the KSH `po`/`plength` tags. ffmpeg must be on your PATH; without it
the charts and jackets still convert and audio is skipped with a warning.

## Jackets

If three jacket sizes are present they are used as-is; otherwise the single
available image is reused for all sizes (no resizing).

## Requirements

- Python 3.10+ (standard library only — no pip packages)
- **ffmpeg** on PATH (for audio)

## Notes & scope

- Custom songs need a local/compatible **Asphyxia** that serves the custom ids
  (recent plugins may have dropped omnimix songdata search), and the WebUI song
  assets may need updating.
- `template_v13.vox` is a generic default scaffold (effect/camera sections only,
  no chart notes) used to emit valid v13 files.
- **Legitimate use only:** your own or user-generated Nautica charts. Do not use
  this to extract or redistribute proprietary game data. SOUND VOLTEX and KONAMI
  trademarks belong to their respective owners; this is an unofficial,
  non-commercial fan tool.

## License

MIT — see [LICENSE](LICENSE).
