#!/usr/bin/env python3
"""
webui_assets.py — update the Asphyxia SDVX plugin's WebUI assets so the server
knows the imported Nautica custom songs, WITHOUT needing Asphyxia to be running.

Why this works offline: the patched plugin's game handler reads
`webui/asset/json/music_db.json` on every `common` request (it is not cached at
startup). So regenerating that file is enough for the server to pick up new
songs the next time the game boots — no web interface, no running server.

Two strategies, offline preferred:

  offline_update()    – parse the Nautica music_db.merged.xml, copy it into the
                        plugin's upload slot (8_mdb.xml) and merge its songs into
                        music_db.json at difficulty index 7 (∇/version 7, what
                        the game reads), tagged info.nautica. No Asphyxia.

  background_update()  – FALLBACK ONLY: launch Asphyxia headless, trigger the
                        plugin's "Update WebUI Assets" event over HTTP, stop it.
                        Used only if offline_update can't be applied.

Designed to be called ONCE when the user leaves the "Import Songs/Charts" screen
(not per song): it always reprocesses the whole Nautica db, so batching is free.

Launcher integration (later):
    import webui_assets
    # ... while importing, just mark dirty:
    webui_assets.mark_dirty(state)
    # ... on leaving the import screen, flush once:
    webui_assets.flush(state, plugin_dir, nautica_mdb, asphyxia_exe=exe)

CLI:
    python webui_assets.py <plugin_dir> <nautica_mdb.xml> [--diff-index 7]
"""
from __future__ import annotations

__version__ = "0.3.0"
# 0.3.0  offline_update overwrites existing nautica entries (title/version were
#        kept from the previous import via setdefault, which left songs at
#        version 6 → parseSongData dropped them) and prunes stale nautica ids
# 0.2.0  --max-id helper, --remove revert, encoding-tolerant mdb reader
# 0.1.0  offline music_db.json update + background fallback + batching

import json
import os
import re
import shutil
import sys

# The game reads difficulty[Math.abs(getVersion)]; ∇ (datecode >= 2025122400)
# resolves to 7. Custom Nautica charts are ∇-format, so they live at index 7.
DEFAULT_DIFF_INDEX = 7
UPLOAD_SLOT = "8_mdb.xml"          # mirrors the patched plugin's Nautica slot

# music_db.json difficulty keys, in the plugin's order.
_DIFF_KEYS = ("novice", "advanced", "exhaust", "maximum", "infinite", "ultimate")
# our generated mdb's <difficulty> child tags → music_db.json keys
_SRC_SLOTS = ("novice", "advanced", "exhaust", "infinite", "maximum")


# ── parse our own Nautica merged db ──────────────────────────────────────────
def _parse_nautica_mdb(path: str):
    """Yield dicts for each <music> in the Nautica merged db (our cp932 XML)."""
    import xml.etree.ElementTree as ET
    # try cp932/shift_jis (our default, like the real db) then utf-8
    raw = None
    for enc in ("cp932", "shift_jis", "utf-8"):
        try:
            raw = open(path, encoding=enc).read()
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        raw = open(path, encoding="utf-8", errors="replace").read()
    raw = re.sub(r"<\?xml[^>]*\?>", "", raw, count=1)   # drop decl (multibyte enc)
    root = ET.fromstring(raw)
    for mus in root.findall("music"):
        info = mus.find("info")
        diff = mus.find("difficulty")
        if info is None or diff is None:
            continue

        def itext(tag, default=""):
            el = info.find(tag)
            return el.text if (el is not None and el.text is not None) else default

        def difnum(slot):
            el = diff.find(slot)
            if el is None:
                return 0
            dn = el.find("difnum")
            try:
                return int(dn.text) if dn is not None and dn.text else 0
            except ValueError:
                return 0

        yield {
            "id": mus.get("id", "0"),
            "title_name": itext("title_name", "Unknown"),
            "version": itext("version", "7"),
            "inf_ver": itext("inf_ver", "0"),
            "distribution_date": itext("distribution_date", ""),
            "difnums": {s: difnum(s) for s in _SRC_SLOTS},
        }


def _diff_block(difnums: dict, level_div: int = 10) -> dict:
    """Build the music_db.json difficulty dict (string levels = difnum/level_div).
    Mirrors the plugin's case 6/7 import."""
    def lv(slot):
        v = difnums.get(slot, 0)
        q = v / level_div
        return str(int(q)) if q == int(q) else str(q)
    return {
        "novice": lv("novice"),
        "advanced": lv("advanced"),
        "exhaust": lv("exhaust"),
        "maximum": lv("maximum") if difnums.get("maximum") else "0",
        "infinite": lv("infinite") if difnums.get("infinite") else "0",
        "ultimate": "0",                    # KSH→∇ conversion has no ULT charts
    }


# ── offline update (preferred) ───────────────────────────────────────────────
def remove_nautica(plugin_dir: str, *, drop_upload: bool = True) -> dict:
    """Revert: strip every nautica-tagged song from music_db.json and (optionally)
    delete the 8_mdb.xml upload slot. Use this to test whether the boot crash goes
    away without our server-side changes. Returns {'removed': n}."""
    json_path = os.path.join(plugin_dir, "webui", "asset", "json", "music_db.json")
    removed = 0
    if os.path.isfile(json_path):
        with open(json_path, encoding="utf-8") as fh:
            db = json.load(fh)
        music = db.get("mdb", {}).get("music", [])
        kept = [m for m in music
                if not (isinstance(m.get("info"), dict) and m["info"].get("nautica"))]
        removed = len(music) - len(kept)
        db["mdb"]["music"] = kept
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(db, fh, ensure_ascii=False, indent=4)
    if drop_upload:
        slot = os.path.join(plugin_dir, "webui", "asset", "uploads", UPLOAD_SLOT)
        if os.path.isfile(slot):
            os.remove(slot)
    return {"removed": removed, "json": json_path}


def max_song_id(plugin_dir: str) -> int:
    """Highest real song id in the plugin's music_db.json (nautica songs excluded).
    Custom ids must stay above this (no collision) but not too far above (the game
    indexes a fixed-size song array — very high ids like 9001 overflow it)."""
    json_path = os.path.join(plugin_dir, "webui", "asset", "json", "music_db.json")
    with open(json_path, encoding="utf-8") as fh:
        db = json.load(fh)
    ids = [int(m["id"]) for m in db.get("mdb", {}).get("music", [])
           if not (isinstance(m.get("info"), dict) and m["info"].get("nautica"))]
    return max(ids) if ids else 0


def offline_update(plugin_dir: str, nautica_mdb: str, *,
                   diff_index: int = DEFAULT_DIFF_INDEX,
                   place_upload: bool = True,
                   prune: bool = True) -> dict:
    """Merge the Nautica songs into the plugin's music_db.json offline.

    This function always sees the COMPLETE Nautica db (the converter rewrites
    music_db.merged.xml as a whole), so it owns every nautica-tagged entry:
    existing ids are overwritten field for field and, with prune=True, songs
    tagged nautica that the merged db no longer contains are dropped.

    Both matter. A re-import that reassigns ids used to leave the previous run's
    title and — worse — its <version> behind, because the entry was only ever
    updated with setdefault. The plugin's parseSongData() compares
    info.version against the game version and returns NO unlock entries when
    they differ, so a song stuck at version 6 silently never appears in game.

    Returns {'updated': n, 'added': a, 'removed': r, 'json': path}. Raises on
    hard failure (missing music_db.json) so the caller can fall back to
    background_update."""
    json_path = os.path.join(plugin_dir, "webui", "asset", "json", "music_db.json")
    if not os.path.isfile(json_path):
        raise FileNotFoundError(
            "music_db.json not found — run a full WebUI Asset Update once in "
            "Asphyxia first (it is generated from your uploaded music_db.xml).")

    # mirror the upload slot so an in-app asset update would see the same file
    if place_upload:
        slot = os.path.join(plugin_dir, "webui", "asset", "uploads", UPLOAD_SLOT)
        os.makedirs(os.path.dirname(slot), exist_ok=True)
        shutil.copyfile(nautica_mdb, slot)

    with open(json_path, encoding="utf-8") as fh:
        db = json.load(fh)
    music = db.setdefault("mdb", {}).setdefault("music", [])
    by_id = {m["id"]: m for m in music}

    updated = added = 0
    seen_ids = set()
    for song in _parse_nautica_mdb(nautica_mdb):
        block = _diff_block(song["difnums"])
        seen_ids.add(song["id"])
        entry = by_id.get(song["id"])
        if entry is None:                                   # new song
            dif = [{} for _ in range(max(8, diff_index + 1))]
            dif[diff_index] = block
            music.append({
                "id": song["id"],
                "info": {
                    "title_name": song["title_name"],
                    "version": song["version"],
                    "nautica": True,
                    "inf_ver": song["inf_ver"],
                    "distribution_date": song["distribution_date"],
                },
                "difficulty": dif,
            })
            added += 1
        else:                                               # overwrite in place
            dif = entry.setdefault("difficulty", [])
            while len(dif) <= diff_index:
                dif.append({})
            dif[diff_index] = block
            info = entry.setdefault("info", {})
            info["nautica"] = True
            # every one of these must be assigned, not setdefault: the id may
            # have been reused by a different song in this import round.
            info["title_name"] = song["title_name"]
            info["version"] = song["version"]
            info["distribution_date"] = song["distribution_date"]
            info["inf_ver"] = song["inf_ver"]
            updated += 1

    removed = 0
    if prune:
        kept = [m for m in music
                if not (isinstance(m.get("info"), dict)
                        and m["info"].get("nautica")
                        and m.get("id") not in seen_ids)]
        removed = len(music) - len(kept)
        music = kept

    db["mdb"]["music"] = music
    # match the plugin's JSON.stringify(prevAssetMdb, null, 4)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(db, fh, ensure_ascii=False, indent=4)
    return {"updated": updated, "added": added, "removed": removed,
            "json": json_path}


# ── background fallback (only if offline can't be applied) ────────────────────
def background_update(plugin_dir: str, asphyxia_exe: str, *,
                      host: str = "127.0.0.1", port: int = 8083,
                      timeout: float = 60.0) -> bool:
    """FALLBACK: start Asphyxia headless, fire the plugin's asset-update WebUI
    event over HTTP, then stop Asphyxia. Returns True on success.

    The offline path above should make this unnecessary; this exists only for
    environments where music_db.json can't be regenerated without the server."""
    import subprocess
    import time
    import urllib.error
    import urllib.request

    proc = None
    try:
        proc = subprocess.Popen(
            [asphyxia_exe],
            cwd=os.path.dirname(os.path.abspath(asphyxia_exe)) or None,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        base = f"http://{host}:{port}"
        # wait for the web server to come up
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                urllib.request.urlopen(base + "/", timeout=2)
                break
            except urllib.error.URLError:
                time.sleep(1)
        else:
            return False
        # Asphyxia WebUI events post to /<plugin>/_/<event>. The exact path can
        # vary by Asphyxia build, so we try the known shapes and accept any 2xx.
        payloads = [
            (f"{base}/sdvx/_/copyResourcesFromGame", b"{}"),
            (f"{base}/_/copyResourcesFromGame", b"{}"),
        ]
        for url, body in payloads:
            try:
                req = urllib.request.Request(
                    url, data=body, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if 200 <= resp.status < 300:
                        return True
            except urllib.error.URLError:
                continue
        return False
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except Exception:
                proc.kill()


def update_assets(plugin_dir: str, nautica_mdb: str, *,
                  asphyxia_exe: str | None = None,
                  diff_index: int = DEFAULT_DIFF_INDEX) -> dict:
    """Offline first; fall back to a background server update only if that fails
    and an Asphyxia executable was provided."""
    try:
        res = offline_update(plugin_dir, nautica_mdb, diff_index=diff_index)
        res["mode"] = "offline"
        return res
    except Exception as e:
        if not asphyxia_exe:
            raise
        ok = background_update(plugin_dir, asphyxia_exe)
        return {"mode": "background", "ok": ok, "error": str(e)}


# ── batching helpers (call flush once on leaving the import screen) ───────────
def mark_dirty(state: dict) -> None:
    """Record that songs were imported; does NOT update assets yet."""
    state["assets_dirty"] = True


def flush(state: dict, plugin_dir: str, nautica_mdb: str, *,
          asphyxia_exe: str | None = None,
          diff_index: int = DEFAULT_DIFF_INDEX) -> dict | None:
    """Update assets once, only if something was imported. Call this when the
    user leaves the import screen — NOT after each individual import."""
    if not state.get("assets_dirty"):
        return None
    res = update_assets(plugin_dir, nautica_mdb,
                        asphyxia_exe=asphyxia_exe, diff_index=diff_index)
    state["assets_dirty"] = False
    return res


def _main(argv):
    if len(argv) < 2:
        print("usage:\n"
              "  python webui_assets.py <plugin_dir> <nautica_mdb.xml> [--diff-index 7]\n"
              "  python webui_assets.py <plugin_dir> --remove   (strip nautica songs to test a clean boot)")
        return 1
    plugin_dir = argv[0]
    if "--max-id" in argv:
        mid = max_song_id(plugin_dir)
        print(f"highest real song id in music_db.json: {mid}")
        print(f"→ convert your charts with a safe start id, e.g.  --id {mid + 1}")
        return 0
    if "--remove" in argv:
        res = remove_nautica(plugin_dir)
        print(f"[ok] removed {res['removed']} nautica song(s) from music_db.json "
              f"and deleted the {UPLOAD_SLOT} slot.")
        print("Now boot the game (Asphyxia restart if it is running). If it boots, "
              "the crash is from our server-side data, not your game files.")
        return 0
    mdb = argv[1]
    di = DEFAULT_DIFF_INDEX
    if "--diff-index" in argv:
        di = int(argv[argv.index("--diff-index") + 1])
    res = offline_update(plugin_dir, mdb, diff_index=di,
                         prune="--no-prune" not in argv)
    print(f"[ok] music_db.json updated offline: +{res['added']} new, "
          f"{res['updated']} updated, -{res['removed']} stale → {res['json']}")
    print("The server reads music_db.json per request, so it will see the songs "
          "on the next game boot. (Restart Asphyxia if it is already running.)")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
