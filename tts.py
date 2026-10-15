#!/usr/bin/env python3
"""ElevenLabs text-to-speech for the announcer. Standard library only.

  python3 tts.py voices            list your voices (find the Midnight Jazz Host voice_id)
  python3 tts.py models            list models available to your account (find the model_id)
  python3 tts.py say "Good evening."   generate speech, print the saved file path
  python3 tts.py usage             characters used today and this month

Settings come from .env (see .env.example). The API key never leaves this server.
"""
import hashlib
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
CACHE = ROOT / "cache" / "announcements"
USAGE = ROOT / "cache" / "usage.json"
API = "https://api.elevenlabs.io/v1"


_usage_lock = threading.Lock()


class TTSError(Exception):
    pass


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


def _request(method, path, body=None, accept="application/json"):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"xi-api-key": _setting("ELEVENLABS_API_KEY"), "Content-Type": "application/json", "Accept": accept},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:300]
        raise TTSError(f"ElevenLabs returned {e.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise TTSError(f"Could not reach ElevenLabs: {e}") from None


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
            raise TTSError(f"Daily speech limit reached ({day_cap} characters). Raise TTS_DAILY_CHAR_LIMIT in .env if intended.")
        if usage["month_chars"] + chars > month_cap:
            raise TTSError(f"Monthly speech limit reached ({month_cap} characters). Raise TTS_MONTHLY_CHAR_LIMIT in .env if intended.")
        usage["chars"] += chars
        usage["month_chars"] += chars
        USAGE.parent.mkdir(parents=True, exist_ok=True)
        tmp = USAGE.with_suffix(".tmp")
        tmp.write_text(json.dumps(usage))
        tmp.replace(USAGE)  # atomic, so a reader never sees a half-written file


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


def speak(text):
    """Return the path of an MP3 of `text` in the announcer voice (cached)."""
    text = text.strip()
    if not text:
        raise TTSError("Nothing to say.")
    voice_id = _setting("ELEVENLABS_VOICE_ID")
    model_id = _setting("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
    key = hashlib.sha256(f"{voice_id}|{model_id}|{text}".encode()).hexdigest()[:24]
    out = CACHE / f"{key}.mp3"
    if out.is_file():
        return out
    _charge(len(text))
    audio = _request(
        "POST", f"/text-to-speech/{voice_id}?output_format=mp3_44100_128",
        {"text": text, "model_id": model_id}, accept="audio/mpeg",
    )
    CACHE.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
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
