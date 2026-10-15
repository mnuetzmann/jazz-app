#!/usr/bin/env python3
"""Maintain tracks.csv: one row per song file, holding the details the announcer
may mention. Run `python3 tracks.py` after adding songs: new files get a row
pre-filled from their style; rows you have edited are never overwritten.
Rows for files you deleted are kept until you run `python3 tracks.py --prune`.

Columns: category, file, title, take, tempo, bpm, mood, instruments, notes
  tempo       slow (up to 80 BPM) | medium (81-115) | fast (116+)
  instruments comma-separated, only what you know is in the recording
  notes       anything else the host may say (e.g. "3/4 time")
"""
import csv
import os
import re
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
CSV_PATH = ROOT / "tracks.csv"
MUSIC = Path(os.environ.get("MUSIC_DIR", ROOT / "music")).resolve()
AUDIO_EXT = {".mp3", ".m4a", ".wav"}
FIELDS = ["category", "file", "title", "take", "tempo", "bpm", "mood", "instruments", "notes"]

# Defaults are read from each style's prompt (the style.txt in its folder). Mureka may
# not follow a prompt exactly, so the host should speak of them as "a ..." not as facts
# about specific moments in a recording.
STYLE_DEFAULTS = {
    "bebop-swing": {"tempo": "fast", "bpm": "124", "mood": "energetic, elegant",
                    "instruments": "tenor saxophone, trumpet, piano, upright bass, drums",
                    "notes": "late-1940s bebop-influenced style; sax, piano and trumpet solos"},
    "classic-swing": {"tempo": "medium", "bpm": "108", "mood": "lively, sophisticated",
                      "instruments": "trombone, tenor saxophone, piano, upright bass, drums",
                      "notes": "1950s small-combo style; trombone and tenor sax solos"},
    "cool-jazz": {"tempo": "slow", "bpm": "80", "mood": "relaxed, intimate",
                  "instruments": "jazz guitar, vibraphone, upright bass, drums",
                  "notes": "early-1950s cool jazz quartet; no piano or horns"},
    "jazz-blues": {"tempo": "medium", "bpm": "94", "mood": "bluesy, playful",
                   "instruments": "trombone, piano, tenor saxophone, upright bass, drums",
                   "notes": "12-bar blues; early-1950s style"},
    "jazz-noir": {"tempo": "slow", "bpm": "72", "mood": "moody, haunting",
                  "instruments": "muted trumpet, piano, upright bass, drums",
                  "notes": "late-night, minor key; opens with solo bass; no saxophone"},
    "jazz-waltz": {"tempo": "medium", "bpm": "108", "mood": "gentle, romantic",
                   "instruments": "piano, clarinet, upright bass, drums",
                   "notes": "3/4 time; no trumpet or trombone"},
    "muted-trumpet": {"tempo": "medium", "bpm": "86", "mood": "relaxed, sophisticated",
                      "instruments": "muted trumpet, piano, upright bass, drums",
                      "notes": "late-1940s quartet style"},
    "piano-trio": {"tempo": "slow", "bpm": "76", "mood": "laid-back, romantic",
                   "instruments": "piano, upright bass, drums",
                   "notes": "after-hours trio; short bass solo; no horns"},
    "romantic-ballads": {"tempo": "slow", "bpm": "62", "mood": "romantic, unhurried",
                         "instruments": "tenor saxophone, piano, upright bass, drums",
                         "notes": "late-1940s ballad; rubato piano introduction"},
    "sax-ballads": {"tempo": "slow", "bpm": "68", "mood": "mellow, lyrical",
                    "instruments": "tenor saxophone, piano, upright bass, drums",
                    "notes": "1940s-50s lounge ballad style"},
}


def style_folders():
    """[(collection, folder)] for every style folder. music/<Collection>/<style>/ is a style inside a named
    collection (the usual layout); music/<style>/ holding songs directly also works (collection "")."""
    out = []
    if not MUSIC.is_dir():
        return out
    for top in sorted(p for p in MUSIC.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if any(f.suffix.lower() in AUDIO_EXT for f in top.iterdir() if f.is_file()):
            out.append(("", top))
        else:
            out += [(top.name, sub) for sub in sorted(p for p in top.iterdir() if p.is_dir() and not p.name.startswith("."))]
    return out


def style_id(folder):
    """A style's id: its path under music/ ('jazz-noir' or 'Champagne_Ballroom/Easy_Foxtrot')."""
    return folder.relative_to(MUSIC).as_posix()


def split_name(stem):
    """'Fifty_Second Street Express (1)' -> ('Fifty Second Street Express', 2)."""
    m = re.search(r"\s\((\d+)\)$", stem)
    take = int(m.group(1)) + 1 if m else 1
    title = (stem[: m.start()] if m else stem).replace("_", " ").strip()
    return title, take


def load():
    """Return {(category, file): row} from tracks.csv ({} if missing)."""
    if not CSV_PATH.is_file():
        return {}
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        return {(r["category"], r["file"]): r for r in csv.DictReader(f)}


def follow_moves(rows, folders):
    """A style folder that moved (jazz-noir -> Jazz/jazz-noir) keeps its rows, edits and all: a row whose
    style no longer exists goes to the one style folder with the same name that holds its song."""
    by_name = {}
    for _, folder in folders:
        by_name.setdefault(folder.name, []).append(folder)
    current = {style_id(f) for _, f in folders}
    moved = 0
    for (cat, name), row in list(rows.items()):
        if cat in current:
            continue
        homes = [f for f in by_name.get(cat.split("/")[-1], []) if (f / name).is_file()]
        if len(homes) == 1:  # only when it is unambiguous
            new = style_id(homes[0])
            if (new, name) not in rows:
                del rows[(cat, name)]
                row["category"] = new
                rows[(new, name)] = row
                moved += 1
    return moved


def sync(prune=False):
    rows = load()
    moved = follow_moves(rows, style_folders())
    added = 0
    present = set()
    for _, folder in style_folders():
        cat = style_id(folder)
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() not in AUDIO_EXT:
                continue
            key = (cat, f.name)
            present.add(key)
            if key not in rows:
                title, take = split_name(f.stem)
                row = {k: "" for k in FIELDS}
                row.update(STYLE_DEFAULTS.get(cat) or STYLE_DEFAULTS.get(folder.name, {}))
                row.update(category=cat, file=f.name, title=title, take=take)
                rows[key] = row
                added += 1
    missing = [k for k in rows if k not in present]
    if prune:
        for k in missing:
            del rows[k]
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as out:
        w = csv.DictWriter(out, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for key in sorted(rows, key=lambda k: (k[0], rows[k]["title"].lower(), k[1])):
            w.writerow(rows[key])
    print(f"{CSV_PATH.name}: {len(rows)} rows ({added} added{f', {len(missing)} removed' if prune else ''}{f', {moved} followed a moved folder' if moved else ''}).")
    if not prune:
        for cat, name in missing:
            print(f"  no longer in music/: {cat}/{name} (run `python3 tracks.py --prune` to remove)")


if __name__ == "__main__":
    import sys
    sync(prune="--prune" in sys.argv)
