#!/usr/bin/env python3
"""Stand-in announcements for when the voice service is unavailable (credits used up, no
internet, a bad key). The saved clips are labelled by what they say, and the closest one that is
still true is played instead; if there is none, the announcement is skipped and the music goes on.

  python3 fallback.py reindex   label every saved clip (runs by itself when the server starts)
  python3 fallback.py prepare   voice the generic backup lines once (uses a few hundred credits)
  python3 fallback.py status    what is saved, by kind
"""
import hashlib
import itertools
import random
import sys
from collections import Counter
from pathlib import Path

import announcer
import tts

LEGACY_MODELS = ("eleven_multilingual_v2", "eleven_v3", "eleven_turbo_v2_5", "eleven_v4")


def _voice_ids():
    return list(dict.fromkeys(tts.voices().values()))


def _models():
    """The model in use now, and the ones earlier clips may have been made with."""
    return list(dict.fromkeys([tts._setting("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"), *LEGACY_MODELS]))


def _key(voice_id, model_id, text):
    return hashlib.sha256(f"{voice_id}|{model_id}|{text}".encode()).hexdigest()[:24]


def candidates(categories):
    """Every sentence the announcer can say, with what it is: yields (text, meta)."""
    for t in announcer.WELCOME:
        yield t, {"kind": "welcome"}
    for kind, pool in (("chosen", announcer.CHOSEN), ("auto", announcer.AUTO)):
        for c in categories:
            for t in pool:
                yield t.format(label=c["label"]), {"kind": kind, "category": c["id"]}
        for t in announcer.GENERIC[kind]:
            yield t, {"kind": kind, "generic": True}
    ids = [c["id"] for c in categories]
    for current in ids + [None]:
        others = [c["label"] for c in categories if c["id"] != current]
        for picks in itertools.permutations(others, min(3, len(others))):
            for t in announcer.ASK:
                yield t.format(options=announcer._join(list(picks))), {"kind": "ask"}
    for c in categories:
        titles = sorted({t["title"] for t in c["tracks"]})
        for track in c["tracks"]:
            instruments = [i.strip() for i in track.get("instruments", "").split(",") if i.strip()]
            lead = " and ".join(instruments[:2])
            moods = [m.strip() for m in track.get("mood", "").split(",") if m.strip()]
            pace = announcer.PACE.get(track.get("tempo", ""), "")
            need = {"{lead}": lead, "{Lead}": lead, "{a_mood}": moods, "{pace}": pace, "{Pace}": pace}
            usable = [t for t in announcer.INTRO if all(v for k, v in need.items() if k in t)]
            cores = [t.format(title=track["title"], style=announcer._style_text(c["label"], lead), lead=lead,
                              Lead=lead[:1].upper() + lead[1:], a_mood=announcer._a(moods[0]) if moods else "",
                              pace=pace, Pace=pace[:1].upper() + pace[1:]) for t in usable]
            cores = cores or [f"Here's {track['title']}."]
            backs = [""] + [b.format(prev=p) for b in announcer.BACK for p in titles if p != track["title"]]
            remarks = [""] + announcer.REMARKS
            meta = {"kind": "intro", "category": c["id"], "url": track["url"]}
            for core in cores:
                for back in backs:
                    for remark in remarks:
                        yield " ".join(x for x in (back, core, remark) if x), meta


def reindex(categories):
    """Label the saved clips by working out which sentence each one is (no network, no credits)."""
    have = {p.stem for p in tts.CACHE.glob("*.mp3")}
    index = tts.load_index()
    todo = have - set(index)
    if not todo:
        return 0
    found = {}
    voices, models = _voice_ids(), _models()
    for text, meta in candidates(categories):
        for v in voices:
            for m in models:
                k = _key(v, m, text)
                if k in todo:
                    entry = found.setdefault(k, {"voice": v, "model": m, "text": text})
                    entry.update({a: b for a, b in meta.items() if a != "url"})
                    if "url" in meta:
                        entry.setdefault("urls", [])
                        if meta["url"] not in entry["urls"]:
                            entry["urls"].append(meta["url"])
    with tts._index_lock:
        index = tts.load_index()
        index.update(found)
        tts.save_index(index)
    return len(found)


def pick(kind, body, voice, categories):
    """The best saved clip to play in place of a new one, or None to skip the announcement."""
    _, voice_id = tts.resolve_voice(voice)
    index = tts.load_index()
    ours = [(k, e) for k, e in index.items() if e.get("voice") == voice_id and (tts.CACHE / f"{k}.mp3").is_file()]

    def choose(match):
        options = [k for k, e in ours if match(e)]
        return tts.CACHE / f"{random.choice(options)}.mp3" if options else None

    if kind == "welcome":
        return choose(lambda e: e.get("kind") == "welcome")
    if kind == "ask":
        return choose(lambda e: e.get("kind") == "ask")
    if kind in ("chosen", "auto"):
        category = body.get("category")
        return (choose(lambda e: e.get("kind") == kind and e.get("category") == category)
                or choose(lambda e: e.get("kind") == kind and e.get("generic")))
    if kind == "intro":  # only an introduction of this very song is true; otherwise say nothing
        url = body.get("url")
        return choose(lambda e: e.get("kind") == "intro" and url in (e.get("urls") or [e.get("url")]))
    return None


def prepare():
    """Voice the generic backup lines in every announcer voice. Needs working credits."""
    done = 0
    for name in tts.voices():
        for kind, lines in announcer.GENERIC.items():
            for text in lines:
                tts.speak(text, name, {"kind": kind, "generic": True})
                done += 1
    return done


def status():
    index = tts.load_index()
    names = {v: n for n, v in tts.voices().items()}
    clips = {p.stem for p in tts.CACHE.glob("*.mp3")}
    print(f"Saved clips: {len(clips)}; labelled: {len(clips & set(index))}")
    by = Counter((names.get(e.get("voice"), "other voice"), e.get("kind", "?") + (" (generic)" if e.get("generic") else ""))
                 for k, e in index.items() if k in clips)
    for (voice, kind), n in sorted(by.items()):
        print(f"  {voice:<28} {kind:<18} {n}")


if __name__ == "__main__":
    import server  # the library of songs, to know which sentences are possible
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "reindex":
            print(f"labelled {reindex(server.scan_library())} clip(s)")
            status()
        elif cmd == "prepare":
            print(f"voiced {prepare()} backup line(s) (lines already saved cost nothing)")
            status()
        elif cmd == "status":
            status()
        else:
            print(__doc__)
    except tts.TTSError as e:
        sys.exit(f"Error: {e.friendly}  ({e})")
