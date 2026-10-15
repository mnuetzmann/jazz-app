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

# Defaults are read from each style's prompt (music/<style>/style.txt). Mureka may
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


def sync(prune=False):
    rows = load()
    added = 0
    present = set()
    for folder in sorted(p for p in MUSIC.iterdir() if p.is_dir()):
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() not in AUDIO_EXT:
                continue
            key = (folder.name, f.name)
            present.add(key)
            if key not in rows:
                title, take = split_name(f.stem)
                row = {k: "" for k in FIELDS}
                row.update(STYLE_DEFAULTS.get(folder.name, {}))
                row.update(category=folder.name, file=f.name, title=title, take=take)
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
    print(f"{CSV_PATH.name}: {len(rows)} rows ({added} added{f', {len(missing)} removed' if prune else ''}).")
    if not prune:
        for cat, name in missing:
            print(f"  no longer in music/: {cat}/{name} (run `python3 tracks.py --prune` to remove)")


if __name__ == "__main__":
    import sys
    sync(prune="--prune" in sys.argv)
