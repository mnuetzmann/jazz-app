"""Announcer scripts. The server writes the words, so the browser can never
make the (paid) voice say arbitrary text. Lines only use library facts
(style names, and the details in tracks.csv), never invented history."""
import random
import re
from collections import deque

WELCOME = [
    "Good evening, and welcome to The Midnight Jazz Room.",
    "Well, good evening. You're tuned to The Midnight Jazz Room, and the night is young.",
    "Welcome in. This is The Midnight Jazz Room. Settle back, and let's have some music.",
    "Good evening, friend. You've found The Midnight Jazz Room. Make yourself comfortable.",
    "The lights are low, the music is easy, and this is The Midnight Jazz Room. Welcome.",
    "Hello, and welcome to The Midnight Jazz Room. Let's make the evening a gentle one.",
]

ASK = [
    "We've had some beautiful music tonight. What are you in the mood for next? Perhaps {options}. Or just tell me what you see on the screen.",
    "Well now, that was a lovely stretch. Where shall we go from here? {options}, or anything else on the screen. Or I can keep things just as they are.",
    "Tell me, what would you like to hear next? I could do {options}. Your choice, friend.",
    "That's a fine set behind us. Now, what suits your mood? {options}, or anything on the screen. Take your time.",
    "So, where to next? I have {options}, and plenty more on the screen. Or say the word, and I'll stay right here.",
    "The night is still ours. What shall we hear? Maybe {options}. Or something else entirely, just ask.",
]

CHOSEN = [
    "{label}. Coming right up.",
    "{label} it is. Let's go.",
    "Now that sounds like a fine idea. {label}, coming your way.",
    "Ah, {label}. Good choice. Here we go.",
    "{label}, friend. Let me set that up for you.",
    "You've got it. Some {label}, and not a moment too soon.",
]

AUTO = [
    "Well, I'll choose for us. Here's some {label}.",
    "Not a word? That's all right. I have just the thing, some {label}.",
    "I'll pick one for you. Let's try {label}.",
    "Quiet night? Then let me take the wheel. Some {label}, coming up.",
    "I'll surprise you with a little {label}. I think it suits the hour.",
    "Allow me. Here's some {label} to carry us along.",
]

# Introductions use only facts from tracks.csv. {lead} = first two instruments listed,
# {a_mood} = first mood word with its article, {pace} = a phrase for the tempo.
# Nothing about specific moments in a recording, and no claims of history.
INTRO = [
    "Here's one called {title}. {Lead} out front, with {a_mood} feel.",
    "This is {title}, {a_mood} number with {lead} leading the way.",
    "Up next, {title}. {Pace} {style}, with {lead} in the spotlight.",
    "{title}. Settle back for some {style}, with {lead}.",
    "Let's slip into {title}, {a_mood} one for the late hours, featuring {lead}.",
    "Coming up, {title}. Some {pace} {style}, with {lead} to carry us along.",
    "Here's {title}, with {lead} taking the lead.",
    "Now, {title}. {Lead}, and {a_mood} feel to carry us along.",
    "Let's keep the evening going with {title}. {Pace} {style}, featuring {lead}.",
    "I think you'll enjoy this next one. It's called {title}, with {lead} and {a_mood} feel.",
    "Next on the program, {title}. {Lead} at the front of the band.",
    "This one's called {title}. Some {style} for you, with {lead} up front.",
    "Here comes {title}, {a_mood} piece featuring {lead}.",
    "{title}, coming your way. {Pace} {style}, with {lead}.",
]

# Introductions for real recordings say only what the file itself says: the artist, and sometimes the album.
# Nothing about instruments, mood or history that we cannot know.
INTRO_REAL = [
    "Here's {title}, from {artist}.",
    "Up next, {title}, by {artist}.",
    "{artist}, with {title}.",
    "This is {title}, from {artist}.",
    "Here's {artist} with {title}.",
    "Next, {title}. That's {artist}.",
]
INTRO_REAL_ALBUM = [
    "Here's {title}, from the album {album}, by {artist}.",
    "{title}, from {album}. That's {artist}.",
]

# Said before an introduction, naming the song that just finished (same set only).
BACK = [
    "That was {prev}.",
    "That one was {prev}.",
    "You've been listening to {prev}.",
    "That was {prev}, here on The Midnight Jazz Room.",
    "{prev}, just now, on The Midnight Jazz Room.",
]

# Atmosphere only: no facts, no weather, nothing about the listener's situation.
REMARKS = [
    "Take your time. The night is ours.",
    "Pour yourself something nice.",
    "The hour is late, and the music is easy.",
    "No hurry at all this evening.",
    "Let the day slip away.",
    "Sit back and let the room fill with music.",
    "Nothing but easy listening from here.",
]

# Radio touches that cost almost nothing: a fixed handful of station IDs, and one line per hour
# (24 hours x a few wordings, so the saved clips fill in and stay free to replay).
STATION_IDS = [
    "You're listening to The Midnight Jazz Room.",
    "This is The Midnight Jazz Room.",
    "The Midnight Jazz Room, music for the long hours.",
    "You're tuned to The Midnight Jazz Room.",
    "The Midnight Jazz Room, still going strong.",
    "Stay with us here on The Midnight Jazz Room.",
]
HOUR_LINES = [
    "It's {time}{part}, here on The Midnight Jazz Room.",
    "{Time}{part}. You're listening to The Midnight Jazz Room.",
    "The time is {time}{part}. This is The Midnight Jazz Room.",
]
_NUMBERS = ["twelve", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven"]


def hour_texts(hour):
    """Every wording of the top-of-the-hour line for an hour 0-23."""
    if hour in (0, 12):
        time, part = ("midnight" if hour == 0 else "noon"), ""
    else:
        time = f"{_NUMBERS[hour % 12]} o'clock"
        part = (" in the morning" if 5 <= hour < 12 else " in the afternoon" if 12 < hour < 18
                else " in the evening" if 18 <= hour < 22 else " at night")
    return [t.format(time=time, Time=time[:1].upper() + time[1:], part=part) for t in HOUR_LINES]


# Backup lines with no style, song or title in them, so they are true whatever is playing.
# `python3 fallback.py prepare` voices them once; they stand in when the voice is unavailable.
GENERIC = {
    "chosen": [
        "You've got it. Coming right up.",
        "Now that sounds like a fine idea. Here we go.",
        "Good choice. Let's go.",
    ],
    "auto": [
        "Well, I'll choose for us. Here we go.",
        "Not a word? That's all right. I have just the thing.",
        "I'll pick one for you. Let's see how this sounds.",
    ],
}

PACE = {"slow": "slow and easy", "medium": "medium-tempo", "fast": "up-tempo"}

# Stock phrases that must not be heard twice close together, even in different kinds
# of announcement (e.g. "coming your way" in a reply and again in the next introduction).
PHRASE_GROUPS = {
    "coming": r"coming (right )?up|coming your way|here comes",
    "settle": r"settle back|sit back|make yourself comfortable",
    "night": r"the night|late hours|the hour is late|this evening|tonight",
    "friend": r"\bfriend\b",
    "easy": r"\beasy\b",
    "station": r"midnight jazz room",
}
_last = {}
_recent_groups = deque(maxlen=3)  # phrase groups used in the last few announcements
_intros_since_remark = 3


def _groups(text):
    return {g for g, rx in PHRASE_GROUPS.items() if re.search(rx, text, re.I)}


def _pick(kind, options):
    """Random choice that avoids repeating the previous pick of the same kind, and
    avoids stock phrases used in the last few announcements of any kind."""
    recent = set().union(*_recent_groups) if _recent_groups else set()
    choices = [o for o in options if o != _last.get(kind) and not (_groups(o) & recent)]
    choices = choices or [o for o in options if o != _last.get(kind)] or options
    _last[kind] = random.choice(choices)
    _recent_groups.append(_groups(_last[kind]))
    return _last[kind]


def _a(word):
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


def _style_text(style, lead):
    """The style name, unless it repeats the instruments ('muted trumpet' + 'muted trumpet and piano')."""
    words = [w for w in style.lower().split() if w != "jazz" and len(w) >= 4]
    return "jazz" if any(w in lead.lower() for w in words) else style


def _intro(track, style, previous=None):
    global _intros_since_remark
    instruments = [i.strip() for i in track.get("instruments", "").split(",") if i.strip()]
    lead = " and ".join(instruments[:2])
    moods = [m.strip() for m in track.get("mood", "").split(",") if m.strip()]
    pace = PACE.get(track.get("tempo", ""), "")
    # Drop templates whose facts we do not have, instead of inventing something.
    need = {"{lead}": lead, "{Lead}": lead, "{a_mood}": moods, "{pace}": pace, "{Pace}": pace}
    usable = [t for t in INTRO if all(v for k, v in need.items() if k in t)]
    # A real recording that names its artist: say that, and only that (AI-made songs never get this).
    artist = (track.get("artist") or "").strip() if track.get("origin") == "real" else ""
    album = (track.get("album") or "").strip()
    if not album or len(album) > 45 or "disc" in album.lower() or album.lower() == artist.lower():
        album = ""  # too long or awkward to say aloud
    if artist:
        usable += INTRO_REAL + (INTRO_REAL_ALBUM if album else [])
    if not usable:
        core = "Here's {title}.".format(title=track["title"])
    else:
        core = _pick("intro", usable).format(
            title=track["title"], style=_style_text(style, lead), lead=lead,
            Lead=lead[:1].upper() + lead[1:],
            a_mood=_a(moods[0]) if moods else "", pace=pace, Pace=pace[:1].upper() + pace[1:],
            artist=artist, album=album,
        )
    parts = []
    back = bool(previous) and random.random() < 0.45
    if back:
        parts.append(_pick("back", BACK).format(prev=previous["title"]))
    parts.append(core)
    # A short atmospheric remark now and then: never twice within three introductions.
    _intros_since_remark += 1
    if _intros_since_remark >= 3 and random.random() < (0.1 if back else 0.3):
        parts.append(_pick("remark", REMARKS))
        _intros_since_remark = 0
    return " ".join(parts)


def _join(items):
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + ", or " + items[-1]


def build_text(body, categories):
    """Return the announcement text for a request body, or None if invalid."""
    kind = body.get("kind")
    labels = {c["id"]: c["label"] for c in categories}
    if kind == "welcome":
        return _pick("welcome", WELCOME)
    if kind == "ask":
        # only the styles on screen: the current collection's (when the player says which one it is showing)
        pool = [c for c in categories if c.get("collection") == body["collection"]] if "collection" in body else categories
        others = [c["label"] for c in pool if c["id"] != body.get("current")]
        if not others:
            return None
        picks = random.sample(others, min(3, len(others)))
        return _pick("ask", ASK).format(options=_join(picks))
    if kind in ("chosen", "auto"):
        label = labels.get(body.get("category"))
        if not label:
            return None
        return _pick(kind, CHOSEN if kind == "chosen" else AUTO).format(label=label)
    if kind == "stationid":
        return _pick("stationid", STATION_IDS)
    if kind == "hour":
        hour = body.get("hour")
        if not isinstance(hour, int) or isinstance(hour, bool) or not 0 <= hour <= 23:
            return None
        return _pick("hour", hour_texts(hour))
    if kind == "intro":
        cat = next((c for c in categories if c["id"] == body.get("category")), None)
        track = cat and next((t for t in cat["tracks"] if t["url"] == body.get("url")), None)
        if not track:
            return None
        # the song that just finished may be from another style (Shuffle, Auto and playlists mix them)
        previous = next((t for c in categories for t in c["tracks"] if t["url"] == body.get("previous")), None)
        return _intro(track, cat["label"], previous)
    return None
