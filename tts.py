#!/usr/bin/env python3
"""ElevenLabs text-to-speech for the announcer. Standard library only.

  python3 tts.py voices            list your voices (find the Midnight Jazz Host voice_id)
  python3 tts.py models            list models available to your account (find the model_id)
  python3 tts.py say "Good evening."   generate speech, print the saved file path
  python3 tts.py usage             characters used today and this month, and your ElevenLabs balance

Settings come from .env (see .env.example). The API key never leaves this server.
"""
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
CACHE = ROOT / "cache" / "announcements"
USAGE = ROOT / "cache" / "usage.json"
INDEX = CACHE / "index.json"  # what each saved clip says, so one can stand in when the voice is unavailable
API = "https://api.elevenlabs.io/v1"


_usage_lock = threading.Lock()
_index_lock = threading.Lock()
_blocked = {"until": 0.0, "code": None, "error": None}  # pause requests after a failure that will repeat


FRIENDLY = {
    "quota": "The announcer's voice credits have run out.",
    "auth": "The announcer's voice key isn't working.",
    "limit": "The announcer has reached its speaking limit.",
    "network": "The announcer can't reach the voice service right now.",
    "rate": "The announcer is busy. Trying again shortly.",
    "other": "The announcer is unavailable right now.",
}
# How long to stop asking ElevenLabs after each kind of failure (seconds).
PAUSE = {"quota": 1800, "auth": 1800, "network": 30, "rate": 20}


class TTSError(Exception):
    """An announcer failure. `code` says which kind; `friendly` is safe to show on screen."""

    def __init__(self, message, code="other"):
        super().__init__(message)
        self.code = code

    @property
    def friendly(self):
        return FRIENDLY.get(self.code, FRIENDLY["other"])


def load_env():
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _setting(name, default=None):
    load_env()
    value = os.environ.get(name, default)
    if not value:
        raise TTSError(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


def voices():
    """Configured announcer voices as {name: voice_id}, first one is the default.

    ELEVENLABS_VOICES="Midnight Jazz Host:id1, Late Night:id2"; a lone
    ELEVENLABS_VOICE_ID still works as a single voice.
    """
    load_env()
    out = {}
    for item in os.environ.get("ELEVENLABS_VOICES", "").split(","):
        name, sep, vid = item.partition(":")
        if sep and name.strip() and vid.strip():
            out[name.strip()] = vid.strip()
    if not out:
        out["Announcer"] = _setting("ELEVENLABS_VOICE_ID")
    return out


def _request(method, path, body=None, accept="application/json", want_headers=False):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"xi-api-key": _setting("ELEVENLABS_API_KEY"), "Content-Type": "application/json", "Accept": accept},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            return (data, {k.lower(): v for k, v in resp.headers.items()}) if want_headers else data
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:300]
        low = detail.lower()
        code = ("quota" if "quota_exceeded" in low or "credits" in low
                else "rate" if e.code == 429
                else "auth" if e.code in (401, 403) else "other")
        raise TTSError(f"ElevenLabs returned {e.code}: {detail}", code) from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise TTSError(f"Could not reach ElevenLabs: {e}", "network") from None


def _charge(chars):
    """Count characters sent; refuse past the daily or monthly cap to control cost."""
    day_cap = int(os.environ.get("TTS_DAILY_CHAR_LIMIT", 20000))
    month_cap = int(os.environ.get("TTS_MONTHLY_CHAR_LIMIT", 100000))
    today = date.today()
    day, month = str(today), today.strftime("%Y-%m")
    with _usage_lock:  # several announcements can be requested at once
        try:
            usage = json.loads(USAGE.read_text())
        except (OSError, ValueError):
            usage = {}
        if usage.get("date") != day:
            usage["date"], usage["chars"] = day, 0
        if usage.get("month") != month:
            usage["month"], usage["month_chars"] = month, 0
        usage.setdefault("month_chars", 0)
        if usage["chars"] + chars > day_cap:
            raise TTSError(f"Daily speech limit reached ({day_cap} characters). Raise TTS_DAILY_CHAR_LIMIT in .env if intended.", "limit")
        if usage["month_chars"] + chars > month_cap:
            raise TTSError(f"Monthly speech limit reached ({month_cap} characters). Raise TTS_MONTHLY_CHAR_LIMIT in .env if intended.", "limit")
        usage["chars"] += chars
        usage["month_chars"] += chars
        USAGE.parent.mkdir(parents=True, exist_ok=True)
        tmp = USAGE.with_suffix(".tmp")
        tmp.write_text(json.dumps(usage))
        tmp.replace(USAGE)  # atomic, so a reader never sees a half-written file


def balance():
    """(credits used, credit limit, reset time or None) from ElevenLabs. Needs 'User: read' on the key."""
    sub = json.loads(_request("GET", "/user/subscription"))
    return sub["character_count"], sub["character_limit"], sub.get("next_character_count_reset_unix")


_hinted = False
_balance_cache = {"at": 0.0, "data": None}


def credits_snapshot(max_age=60):
    """The balance in a form the screen can use, remembered for `max_age` seconds so that asking often is cheap."""
    now = time.time()
    if _balance_cache["data"] is not None and now - _balance_cache["at"] < max_age:
        return _balance_cache["data"]
    try:
        used, limit, reset = balance()
        data = {
            "ok": True, "used": used, "limit": limit, "left": max(limit - used, 0),
            "pct": round(100 * max(limit - used, 0) / limit, 1) if limit else 0,
            "reset": time.strftime("%b %d", time.localtime(reset)) if reset else "",
        }
    except TTSError as e:
        data = {"ok": False, "reason": "permission" if e.code == "auth" else e.code}
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        data = {"ok": False, "reason": "unknown"}
    _balance_cache.update(at=now, data=data)
    return data


def _report(text, meta, headers):
    """After a new clip is generated, print what it cost and what is left. Runs off to the side, so it
    never slows an announcement down."""
    global _hinted
    try:
        cost = int(headers.get("character-cost") or len(text))
    except ValueError:
        cost = len(text)
    kind = (meta or {}).get("kind", "clip")
    snap = credits_snapshot(max_age=0)
    if snap["ok"]:
        when = f", resets {snap['reset']}" if snap["reset"] else ""
        left = f"{snap['left']:,} of {snap['limit']:,} credits left{when}"
    else:
        left = "credits left: unknown"
        if snap["reason"] == "permission" and not _hinted:
            _hinted = True
            left += " (add 'User' access to the ElevenLabs key to see it here)"
    try:
        today = json.loads(USAGE.read_text())
        mine = f" | app total today {today.get('chars', 0):,}/{os.environ.get('TTS_DAILY_CHAR_LIMIT', 20000)}"
    except (OSError, ValueError):
        mine = ""
    snippet = text if len(text) <= 48 else text[:45] + "..."
    print(f'[announcer] voiced {kind} "{snippet}" | cost {cost} | {left}{mine}', flush=True)


def show_usage():
    load_env()
    try:
        usage = json.loads(USAGE.read_text())
    except (OSError, ValueError):
        usage = {}
    today = date.today()
    day = usage.get("chars", 0) if usage.get("date") == str(today) else 0
    month = usage.get("month_chars", 0) if usage.get("month") == today.strftime("%Y-%m") else 0
    print(f"Today:      {day:>7} of {os.environ.get('TTS_DAILY_CHAR_LIMIT', 20000)} characters")
    print(f"This month: {month:>7} of {os.environ.get('TTS_MONTHLY_CHAR_LIMIT', 100000)} characters")
    print(f"Saved clips (free to replay): {len(list(CACHE.glob('*.mp3'))) if CACHE.is_dir() else 0}")
    try:  # the real balance at ElevenLabs, if the key is allowed to see it
        used, limit, reset = balance()
        when = time.strftime("%b %d", time.localtime(reset)) if reset else "unknown"
        print(f"ElevenLabs credits: {used:,} of {limit:,} used, resets {when} ({max(limit - used, 0):,} left)")
    except TTSError as e:
        if e.code == "auth":  # speech works with this key, but it may not read account details
            print("ElevenLabs credits: not shown (this key can't read account details; add 'User: read' to the key to see it)")
        else:
            print(f"ElevenLabs credits: could not check ({e.friendly})")
    except (KeyError, TypeError, ValueError):
        print("ElevenLabs credits: could not check")


def _refund(chars):
    """A request that failed did not spend anything, so give the characters back."""
    with _usage_lock:
        try:
            usage = json.loads(USAGE.read_text())
            usage["chars"] = max(usage.get("chars", 0) - chars, 0)
            usage["month_chars"] = max(usage.get("month_chars", 0) - chars, 0)
            tmp = USAGE.with_suffix(".tmp")
            tmp.write_text(json.dumps(usage))
            tmp.replace(USAGE)
        except (OSError, ValueError):
            pass


def load_index():
    try:
        return json.loads(INDEX.read_text())
    except (OSError, ValueError):
        return {}


def save_index(index):
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, indent=0))
    tmp.replace(INDEX)


def record_clip(key, voice_id, model_id, text, meta):
    """Remember what a saved clip is (its kind, style, song) so it can be found later."""
    with _index_lock:
        index = load_index()
        entry = index.get(key, {})
        entry.update({"voice": voice_id, "model": model_id, "text": text, **{k: v for k, v in (meta or {}).items() if v}})
        if index.get(key) != entry:
            index[key] = entry
            save_index(index)


def resolve_voice(voice=None):
    """(name, voice_id) for a voice name; unknown or missing means the default voice."""
    available = voices()
    name = voice if voice in available else next(iter(available))
    return name, available[name]


def blocked():
    """The TTSError to raise while requests are paused, or None."""
    if time.time() < _blocked["until"]:
        err = TTSError(_blocked["error"] or "paused", _blocked["code"] or "other")
        return err
    return None


def _pause(err):
    seconds = PAUSE.get(err.code)
    if seconds:
        first = time.time() >= _blocked["until"]
        _blocked.update(until=time.time() + seconds, code=err.code, error=str(err))
        if first:  # the technical detail goes to the server log, once, not onto the screen
            print(f"[announcer] {err.code}: {err} (pausing voice requests for {seconds // 60 or 1} min)", file=sys.stderr, flush=True)


def speak(text, voice=None, meta=None):
    """Return the path of an MP3 of `text` in the named voice (cached). `meta` says what the
    clip is ({"kind": ..., "category": ..., "url": ...}) so it can be found again later."""
    text = text.strip()
    if not text:
        raise TTSError("Nothing to say.")
    _, voice_id = resolve_voice(voice)
    model_id = _setting("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
    key = hashlib.sha256(f"{voice_id}|{model_id}|{text}".encode()).hexdigest()[:24]
    out = CACHE / f"{key}.mp3"
    if out.is_file():
        if meta:
            record_clip(key, voice_id, model_id, text, meta)
        return out
    pending = blocked()  # known to fail for a while: do not even ask
    if pending:
        raise pending
    _charge(len(text))
    try:
        audio, headers = _request(
            "POST", f"/text-to-speech/{voice_id}?output_format=mp3_44100_128",
            {"text": text, "model_id": model_id}, accept="audio/mpeg", want_headers=True,
        )
    except TTSError as err:
        _refund(len(text))
        _pause(err)
        raise
    CACHE.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    record_clip(key, voice_id, model_id, text, meta)
    threading.Thread(target=_report, args=(text, meta, headers), daemon=True).start()
    return out


def list_voices():
    for v in json.loads(_request("GET", "/voices"))["voices"]:
        print(f"{v['voice_id']}  {v['name']}  ({v.get('category', '')})")


def list_models():
    for m in json.loads(_request("GET", "/models")):
        if m.get("can_do_text_to_speech"):
            print(f"{m['model_id']}  {m['name']}")


if __name__ == "__main__":
    try:
        cmd = sys.argv[1] if len(sys.argv) > 1 else ""
        if cmd == "voices":
            list_voices()
        elif cmd == "models":
            list_models()
        elif cmd == "usage":
            show_usage()
        elif cmd == "say" and len(sys.argv) > 2:
            print(speak(" ".join(sys.argv[2:])))
        else:
            print(__doc__)
    except TTSError as e:
        sys.exit(f"Error: {e}")
