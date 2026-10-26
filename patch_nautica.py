#!/usr/bin/env python3
"""
patch_nautica.py — add a "Nautica" slot to the Asphyxia SDVX plugin (22vv0 / kfc
7.1.6 fork), mirroring the "Omnimix" slot everywhere it is referenced.

Nautica gets its own upload slot (8_mdb.xml) and an info.nautica tag, but its
charts are imported into the ∇ (version 7) difficulty index — because the game
server reads difficulty[gameVersion] (7 for ∇). A separate index 8 would be
invisible to the game. So slot 8 is the file source + the tag; dstVer (=7) is
where the data lands.

What it changes:
  * index.ts            – new "music_db.xml (Nautica)" upload slot (8_mdb.xml)
  * handlers/webui.ts   – import slot 8 as ∇ (dstVer), tag info.nautica
  * handlers/common.ts  – collect nautica ids + "Nautica Songs" quick-filter
  * songs list.pug      – visible "Nautica" column header
  * songslist.js        – "Nautica" Yes/No column

Run once from anywhere (idempotent, writes a .bak before first edit per file):

    python patch_nautica.py /path/to/plugin
"""
import os
import sys

__version__ = "1.0.0"

CRLF = "\r\n"
LF = "\n"

# (rel, old, new, marker, label, all_occurrences)
PATCHES = [
    # 1. upload slot
    ("index.ts",
     "  R.DataFile('./webui/asset/uploads/0_mdb.xml', {name: 'music_db.xml (Omnimix)', desc: 'SDVX7 compatible mdb', accept: 'text/xml, .xml'});",
     "  R.DataFile('./webui/asset/uploads/0_mdb.xml', {name: 'music_db.xml (Omnimix)', desc: 'SDVX7 compatible mdb', accept: 'text/xml, .xml'});" + CRLF +
     "  R.DataFile('./webui/asset/uploads/8_mdb.xml', {name: 'music_db.xml (Nautica)', desc: 'SDVX7 compatible custom charts', accept: 'text/xml, .xml'});",
     "8_mdb.xml", "upload slot", False),

    # 2. import loop range
    ("handlers/webui.ts",
     "for (let ver = 0; ver <= 7; ver++) {",
     "for (let ver = 0; ver <= 8; ver++) {",
     "ver <= 8", "import loop range", False),

    # 3. dstVer: slot 8 imports as ∇ (7)
    ("handlers/webui.ts",
     "      if(!IO.Exists('./webui/asset/uploads/' + ver + '_mdb.xml')) continue" + CRLF,
     "      if(!IO.Exists('./webui/asset/uploads/' + ver + '_mdb.xml')) continue" + CRLF +
     "      let dstVer = ver === 8 ? 7 : ver  // Nautica (slot 8) imports into the nabla (v7) index" + CRLF,
     "let dstVer = ver === 8 ? 7 : ver", "dstVer redirect", False),

    # 4. override picks ∇ for dstVer 7 (incl. nautica)
    ("handlers/webui.ts",
     "let musicOverride = ver === 7 ? MUSIC_OVERRIDE7 : MUSIC_OVERRIDE6",
     "let musicOverride = dstVer === 7 ? MUSIC_OVERRIDE7 : MUSIC_OVERRIDE6",
     "dstVer === 7 ? MUSIC_OVERRIDE7", "music override", False),

    # 5. log label
    ("handlers/webui.ts",
     "logLine('Importing ' + ((ver === 0) ? 'omnimix' : 'SDVX' + ver) + ' mdb')",
     "logLine('Importing ' + ((ver === 0) ? 'omnimix' : (ver === 8) ? 'nautica' : 'SDVX' + ver) + ' mdb')",
     "(ver === 8) ? 'nautica'", "log label", False),

    # 6. levelDiv = 10 for the nabla index (covers nautica via dstVer)
    ("handlers/webui.ts",
     "        if(ver === 7) levelDiv = 10",
     "        if(dstVer === 7) levelDiv = 10",
     "if(dstVer === 7) levelDiv = 10", "nautica levelDiv", False),

    # 7. route both switches through dstVer (GLOBAL)
    ("handlers/webui.ts",
     "switch (ver) {",
     "switch (dstVer) {",
     "switch (dstVer)", "switch on dstVer", True),

    # 8. store difficulty at dstVer index (GLOBAL)
    ("handlers/webui.ts",
     "dif[ver] = {",
     "dif[dstVer] = {",
     "dif[dstVer] = {", "difficulty index", True),

    # 9. tag NEW songs
    ("handlers/webui.ts",
     "              ...ver === 0 && {'omnimix': ver === 0}," + CRLF,
     "              ...ver === 0 && {'omnimix': ver === 0}," + CRLF +
     "              ...ver === 8 && {'nautica': true}," + CRLF,
     "{'nautica': true}", "tag new songs", False),

    # 10. tag EXISTING songs (update branch) before writing difficulty back
    ("handlers/webui.ts",
     "          prevAssetMdb['mdb']['music'][ind]['difficulty'] = dif" + CRLF,
     "          if(ver === 8) prevAssetMdb['mdb']['music'][ind]['info']['nautica'] = true" + CRLF +
     "          prevAssetMdb['mdb']['music'][ind]['difficulty'] = dif" + CRLF,
     "['info']['nautica'] = true", "tag existing songs", False),

    # 11. common.ts: declare nautList (LF)
    ("handlers/common.ts",
     "    let omniList: number[] = []",
     "    let omniList: number[] = []" + LF + "    let nautList: number[] = []",
     "nautList: number[]", "nautList declaration", False),

    # 12. common.ts: collect nautica ids (LF)
    ("handlers/common.ts",
     "        if (absVersion >= 6 && ('omnimix') in songData.info) omniList.push(id)  // lazy",
     "        if (absVersion >= 6 && ('omnimix') in songData.info) omniList.push(id)  // lazy" + LF +
     "        if (absVersion >= 6 && ('nautica') in songData.info) nautList.push(id)  // lazy",
     "('nautica') in songData.info", "collect nautica ids", False),

    # 13. common.ts: Nautica Songs quick-filter, id 2 (LF)
    ("handlers/common.ts",
     "      if(omniList.length > 0) {" + LF + "        extend.push({" + LF + "          id: 1," + LF +
     "          type: 3," + LF + "          params: [" + LF + "            4," + LF + "            0," + LF +
     "            0," + LF + "            0," + LF + "            0," + LF + "            '!'," + LF +
     "            ''," + LF + "            ''," + LF + "            omniList.join(',')," + LF +
     "            \"Omnimix Songs\"," + LF + "          ]" + LF + "        })" + LF + "      }",
     "      if(omniList.length > 0) {" + LF + "        extend.push({" + LF + "          id: 1," + LF +
     "          type: 3," + LF + "          params: [" + LF + "            4," + LF + "            0," + LF +
     "            0," + LF + "            0," + LF + "            0," + LF + "            '!'," + LF +
     "            ''," + LF + "            ''," + LF + "            omniList.join(',')," + LF +
     "            \"Omnimix Songs\"," + LF + "          ]" + LF + "        })" + LF + "      }" + LF + LF +
     "      if(nautList.length > 0) {" + LF + "        extend.push({" + LF + "          id: 2," + LF +
     "          type: 3," + LF + "          params: [" + LF + "            4," + LF + "            0," + LF +
     "            0," + LF + "            0," + LF + "            0," + LF + "            '!'," + LF +
     "            ''," + LF + "            ''," + LF + "            nautList.join(',')," + LF +
     "            \"Nautica Songs\"," + LF + "          ]" + LF + "        })" + LF + "      }",
     "Nautica Songs", "nautica quick-filter", False),

    # 14. songs list.pug header (CRLF)
    ("webui/songs list.pug",
     "            th Omnimix" + CRLF,
     "            th Omnimix" + CRLF + "            th Nautica" + CRLF,
     "th Nautica", "table header", False),

    # 15. songslist.js column (CRLF)
    ("webui/asset/js/songslist.js",
     "            { data: 'omni' }," + CRLF,
     "            { data: 'omni' }," + CRLF + "            { data: 'naut' }," + CRLF,
     "{ data: 'naut' }", "column definition", False),

    # 16. songslist.js value (CRLF)
    ("webui/asset/js/songslist.js",
     "                temp_data.omni = 'omnimix' in mdata['info'] ? 'Yes' : 'No'" + CRLF,
     "                temp_data.omni = 'omnimix' in mdata['info'] ? 'Yes' : 'No'" + CRLF +
     "                temp_data.naut = 'nautica' in mdata['info'] ? 'Yes' : 'No'" + CRLF,
     "temp_data.naut", "column value", False),
]


def main():
    if len(sys.argv) != 2:
        print("usage: python patch_nautica.py /path/to/plugin"); sys.exit(1)
    root = sys.argv[1]
    if not os.path.isfile(os.path.join(root, "index.ts")):
        print(f"[ERROR] {root} has no index.ts - not the plugin folder."); sys.exit(1)

    backed_up, applied, skipped, failed = set(), 0, 0, 0
    for rel, old, new, marker, label, all_occ in PATCHES:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            print(f"[FAIL] {rel}: file not found ({label})"); failed += 1; continue
        with open(path, encoding="utf-8", newline="") as fh:   # preserve CRLF/LF
            text = fh.read()
        if marker in text:
            print(f"[skip] {rel}: already patched ({label})"); skipped += 1; continue
        n = text.count(old)
        if n == 0 or (not all_occ and n != 1):
            print(f"[FAIL] {rel}: anchor for '{label}' found {n}x "
                  f"(expected {'>=1' if all_occ else 1})"); failed += 1; continue
        if rel not in backed_up:
            with open(path + ".bak", "w", encoding="utf-8", newline="") as bf:
                bf.write(text)
            backed_up.add(rel)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text.replace(old, new) if all_occ else text.replace(old, new, 1))
        suffix = f" ({n}x)" if all_occ else ""
        print(f"[ok]   {rel}: {label}{suffix}"); applied += 1

    print(f"\nDone. applied={applied} skipped={skipped} failed={failed}")
    if failed == 0 and applied > 0:
        print("\nNext: upload your Nautica music_db.merged.xml to the new "
              "'music_db.xml (Nautica)' slot, then update the WebUI assets\n"
              "(button in Asphyxia, or the launcher's offline updater).")
        print("If your setup runs compiled JS, re-transpile the plugin afterwards.")
    elif failed:
        print("Some patches failed (plugin source differs). Touched files have a "
              ".bak; restore from it if needed.")


if __name__ == "__main__":
    main()
