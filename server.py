#!/usr/bin/env python3
"""Local server for the jazz app: static pages, the MP3 library, and a tiny
event relay so a phone can control the player. Standard library only."""
import json
import mimetypes
import os
import queue
import re
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import announcer
import fallback
import tracks
import tts

ROOT = Path(__file__).parent.resolve()
PUBLIC = ROOT / "public"
MUSIC = Path(os.environ.get("MUSIC_DIR", ROOT / "music")).resolve()
IMAGES = Path(os.environ.get("IMAGES_DIR", ROOT / "images")).resolve()
PORT = int(os.environ.get("PORT", 8080))  # 3000 was unreachable from the phone on this network
AUDIO_EXT = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}

listeners = []
listeners_lock = threading.Lock()


def broadcast(message):
    data = json.dumps(message)
    with listeners_lock:
        for q in listeners:
            q.put(data)


def _decode_text(raw):
    enc = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}.get(raw[0] if raw else 0, "latin-1")
    return raw[1:].decode(enc, errors="ignore").strip("\x00 ﻿").split("\x00")[0].strip()


_tags = {}  # (path, mtime) -> what the file says about itself; read once


def read_tags(file):
    """What an MP3 says about itself: title, artist, album, and whether it looks AI-made or a real recording.
    'ai' = made by Mureka (an ffmpeg 'Lavf' encoder tag plus an embedded cover); 'real' = it names an artist and
    has no such marks; anything else is 'unknown' (the announcer then says only the title)."""
    try:
        key = (str(file), file.stat().st_mtime)
    except OSError:
        return {}
    if key in _tags:
        return _tags[key]
    got = {"title": "", "artist": "", "album": ""}
    encoder, has_cover = "", False
    try:
        with open(file, "rb") as f:
            head = f.read(10)
            if head[:3] == b"ID3" and head[3] in (3, 4):
                tag = f.read(_synchsafe(head[6:10]))
                pos = 0
                while pos + 10 <= len(tag) and tag[pos] != 0:
                    fid, raw = tag[pos:pos + 4], tag[pos + 4:pos + 8]
                    size = _synchsafe(raw) if head[3] == 4 else int.from_bytes(raw, "big")
                    body = tag[pos + 10:pos + 10 + size]
                    if fid == b"TIT2":
                        got["title"] = _decode_text(body)
                    elif fid == b"TPE1":
                        got["artist"] = _decode_text(body)
                    elif fid == b"TALB":
                        got["album"] = _decode_text(body)
                    elif fid == b"TSSE":
                        encoder = _decode_text(body)
                    elif fid == b"APIC":
                        has_cover = True
                    pos += 10 + size
            if not got["title"]:  # an old-style ID3v1 tag at the end of the file
                f.seek(-128, 2)
                v1 = f.read(128)
                if v1[:3] == b"TAG":
                    got["title"] = v1[3:33].split(b"\x00")[0].decode("latin-1").strip()
    except (OSError, ValueError, IndexError):
        pass
    mureka = encoder.startswith("Lavf") and has_cover
    got["origin"] = "ai" if mureka else "real" if got["artist"] else "unknown"
    _tags[key] = got
    return got


_covers = {}  # (path, mtime) -> (mime, bytes) or None; a few MB for a whole library


def _synchsafe(raw):
    return ((raw[0] & 0x7F) << 21) | ((raw[1] & 0x7F) << 14) | ((raw[2] & 0x7F) << 7) | (raw[3] & 0x7F)


def read_cover(file):
    """The cover picture embedded in an MP3 (ID3v2 APIC frame): (mime, bytes) or None."""
    try:
        key = (str(file), file.stat().st_mtime)
    except OSError:
        return None
    if key in _covers:
        return _covers[key]
    found = None
    try:
        with open(file, "rb") as f:
            head = f.read(10)
            if head[:3] == b"ID3" and head[3] in (3, 4):
                tag = f.read(_synchsafe(head[6:10]))
                pos = 0
                while pos + 10 <= len(tag) and tag[pos] != 0:
                    fid, raw = tag[pos:pos + 4], tag[pos + 4:pos + 8]
                    size = _synchsafe(raw) if head[3] == 4 else int.from_bytes(raw, "big")
                    if fid == b"APIC":
                        body = tag[pos + 10:pos + 10 + size]
                        enc = body[0]
                        i = body.index(b"\x00", 1) + 2  # end of mime, then the picture-type byte
                        if enc in (1, 2):  # UTF-16 description ends with an aligned double null
                            while i + 1 < len(body) and body[i:i + 2] != b"\x00\x00":
                                i += 2
                            i += 2
                        else:
                            i = body.index(b"\x00", i) + 1
                        data = body[i:]
                        mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg" if data[:2] == b"\xff\xd8" else None
                        if mime and len(data) > 100:
                            found = (mime, data)
                        break
                    pos += 10 + size
    except (OSError, ValueError, IndexError):
        found = None
    _covers[key] = found
    return found


THUMBS = ROOT / "cache" / "thumbs"
STYLE_PICTURES = ("style.jpeg", "style.jpg", "style.png", "style.webp")


def style_picture(folder):
    """The picture that represents a style: style.jpeg (or .jpg/.png/.webp) in its folder."""
    return next((folder / n for n in STYLE_PICTURES if (folder / n).is_file()), None)


def make_thumb(src):
    """A small copy of a style picture (made once, kept in cache/thumbs). Falls back to the
    original if the macOS image tool (sips) is not available."""
    st = src.stat()
    name = tracks.style_id(src.parent).replace("/", "__")  # 'Champagne_Ballroom__Easy_Foxtrot'
    out = THUMBS / f"{name}-{int(st.st_mtime)}-{st.st_size}.jpg"
    if out.is_file():
        return out
    tmp = out.with_suffix(".tmp.jpg")
    try:
        THUMBS.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["sips", "-Z", "480", "-s", "format", "jpeg", "-s", "formatOptions", "80", str(src), "--out", str(tmp)],
            capture_output=True, timeout=30, check=True,
        )
        tmp.replace(out)
        for old in THUMBS.glob(f"{name}-*.jpg"):  # drop thumbnails of earlier versions
            if old != out:
                old.unlink(missing_ok=True)
        return out
    except (OSError, subprocess.SubprocessError):
        tmp.unlink(missing_ok=True)
        return src


def warm_thumbs():
    """Make every style's thumbnail at startup, so the first screen never waits for one, and
    drop thumbnails of styles that no longer exist (e.g. after a folder moved)."""
    keep = set()
    for _, folder in tracks.style_folders():
        pic = style_picture(folder)
        if pic:
            keep.add(make_thumb(pic))
    if THUMBS.is_dir():
        for old in THUMBS.glob("*.jpg"):
            if old not in keep:
                old.unlink(missing_ok=True)


DEFAULT_COLLECTION = "Midnight Jazz Room"  # the label for styles that sit directly in music/
MAIN_COLLECTION = os.environ.get("MAIN_COLLECTION", "Jazz")  # the collection offered first (if it has songs)


def track_info(folder, f, details):
    """One song: title from tracks.csv, else embedded tag, else cleaned filename."""
    sid = tracks.style_id(folder)
    name_title, take = tracks.split_name(f.stem)
    row = details.get((sid, f.name), {})
    tags_ = read_tags(f) if f.suffix.lower() == ".mp3" else {}
    title = row.get("title") or tags_.get("title") or name_title
    return {
        "title": title,
        "artist": tags_.get("artist", ""),   # from the file's own tags, never guessed
        "album": tags_.get("album", ""),
        "origin": tags_.get("origin", "unknown"),  # 'ai', 'real' or 'unknown'

        "group": f"{sid}/{title.lower()}",  # takes of one song share a group
        "take": int(row.get("take") or take),
        "tempo": row.get("tempo", ""),
        "bpm": row.get("bpm", ""),
        "mood": row.get("mood", ""),
        "instruments": row.get("instruments", ""),
        "notes": row.get("notes", ""),
        "url": f"/music/{sid}/{f.name}".replace(" ", "%20"),
        "cover": f"/cover/{quote(sid)}/{quote(f.name)}" if f.suffix.lower() == ".mp3" and read_cover(f) else "",
    }


def pretty(name):
    return name.replace("-", " ").replace("_", " ")


def scan_library():
    """Every style that has songs, each tagged with the collection it belongs to."""
    categories = []
    details = tracks.load()
    for collection, folder in tracks.style_folders():
        tracks_ = [track_info(folder, f, details) for f in sorted(folder.iterdir()) if f.suffix.lower() in AUDIO_EXT]
        if tracks_:
            sid = tracks.style_id(folder)
            categories.append({
                "id": sid,
                "label": pretty(folder.name),
                "collection": collection,
                "thumb": f"/thumb/{quote(sid)}" if style_picture(folder) else "",
                "tracks": tracks_,
            })
    return categories


def collections_of(categories):
    """The collections that have songs: the main one (MAIN_COLLECTION) first, then the rest A to Z."""
    names = sorted({c["collection"] for c in categories})
    names.sort(key=lambda n: (n != MAIN_COLLECTION, n != "", n))
    return [{"id": n, "label": pretty(n) if n else DEFAULT_COLLECTION} for n in names]


def scan_images():
    """Pictures for the background. images/*.jpg is the general pool; images/<style>/*.jpg
    is used only while that style plays."""
    def urls(folder, prefix):
        return [f"{prefix}{quote(f.name)}" for f in sorted(folder.iterdir())
                if f.is_file() and f.suffix.lower() in IMAGE_EXT and not f.name.startswith(".")]
    result = {"all": [], "byStyle": {}}
    if IMAGES.is_dir():
        result["all"] = urls(IMAGES, "/images/")
        for folder in sorted(p for p in IMAGES.iterdir() if p.is_dir()):
            found = urls(folder, f"/images/{quote(folder.name)}/")
            if found:
                result["byStyle"][folder.name] = found
    return result


def safe_join(base, rel):
    target = (base / rel).resolve()
    return target if base == target or base in target.parents else None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # urlsplit, not urlparse: urlparse treats ";" in a file name as the start of path parameters and drops it
        path = unquote(urlsplit(self.path).path)
        if path == "/api/library":
            categories = scan_library()
            return self.send_json({"categories": categories, "collections": collections_of(categories)})
        if path == "/api/voices":
            try:
                return self.send_json({"voices": list(tts.voices())})
            except tts.TTSError:
                return self.send_json({"voices": []})
        if path == "/api/schedule":
            try:
                return self.send_json(json.loads((ROOT / "schedule.json").read_text()))
            except (OSError, ValueError):
                return self.send_json({"slots": []})  # no schedule: Auto plays everything
        if path == "/api/credits":
            return self.send_json(tts.credits_snapshot())
        if path == "/api/images":
            return self.send_json(scan_images())
        if path == "/events":
            return self.serve_events()
        if path.startswith("/thumb/"):
            folder = safe_join(MUSIC, path[len("/thumb/"):])
            ok = folder and folder.is_dir() and 1 <= len(folder.relative_to(MUSIC).parts) <= 2
            pic = ok and style_picture(folder)
            if not pic:
                return self.send_json({"error": "not found"}, 404)
            return self.serve_file(make_thumb(pic))
        if path.startswith("/cover/"):
            file = safe_join(MUSIC, path[len("/cover/"):])
            cover = file and file.suffix.lower() == ".mp3" and file.is_file() and read_cover(file)
            if not cover:
                return self.send_json({"error": "not found"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", cover[0])
            self.send_header("Content-Length", str(len(cover[1])))
            self.send_header("Cache-Control", "max-age=86400")
            self.end_headers()
            self.wfile.write(cover[1])
            return
        if path.startswith("/images/"):
            file = safe_join(IMAGES, path[len("/images/"):])
            if not file or file.suffix.lower() not in IMAGE_EXT:
                return self.send_json({"error": "not found"}, 404)
            return self.serve_file(file)
        if path.startswith("/music/"):
            return self.serve_file(safe_join(MUSIC, path[len("/music/"):]), audio_only=True)
        if path == "/":
            path = "/index.html"
        elif path == "/remote":
            path = "/remote.html"
        self.serve_file(safe_join(PUBLIC, path.lstrip("/")))

    def do_POST(self):
        route = urlsplit(self.path).path
        if route not in ("/api/send", "/api/announce"):
            return self.send_json({"error": "not found"}, 404)
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self.send_json({"error": "bad json"}, 400)
        if route == "/api/send":
            broadcast(body)
            return self.send_json({"ok": True})
        categories = scan_library()
        text = announcer.build_text(body, categories)
        if not text:
            return self.send_json({"error": "unknown announcement"}, 400)
        meta = {"kind": body.get("kind"), "category": body.get("category"), "url": body.get("url")}
        if body.get("kind") == "hour":
            meta["hour"] = str(body.get("hour"))  # as text, so hour 0 (midnight) is not dropped as "empty"
        used = None
        try:
            clip = tts.speak(text, body.get("voice"), meta)
        except tts.TTSError as e:
            # The voice is unavailable (credits, network, key). Play a saved clip that is still true
            # for this moment; if there is none, the player skips the announcement and the music goes on.
            clip = fallback.pick(body.get("kind"), body, body.get("voice"), categories)
            if not clip:
                return self.send_json({"error": e.friendly, "code": e.code}, 503)
            used = e.code
        audio = clip.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio)))
        self.send_header("Cache-Control", "no-store")
        if used:
            self.send_header("X-Announcer-Fallback", used)
        self.end_headers()
        self.wfile.write(audio)

    def serve_events(self):
        q = queue.Queue()
        with listeners_lock:
            listeners.append(q)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                try:
                    self.wfile.write(f"data: {q.get(timeout=15)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with listeners_lock:
                listeners.remove(q)

    def serve_file(self, file, audio_only=False):
        if not file or not file.is_file():
            return self.send_json({"error": "not found"}, 404)
        if audio_only and file.suffix.lower() not in AUDIO_EXT:
            return self.send_json({"error": "not found"}, 404)
        ctype = AUDIO_EXT.get(file.suffix.lower()) or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        size = file.stat().st_size
        start, end, status = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = max(size - int(m.group(2)), 0)
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with open(file, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # Phones, tabs and cast sessions drop connections all the time; that is not an error.
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def label_clips():
    """Work out what any unlabelled saved clips say, so they can stand in later (quietly, in the background)."""
    try:
        categories = scan_library()
        fallback.relabel_moved(categories)  # a style folder that moved keeps its clips' labels
        fallback.reindex(categories)
    except Exception as e:  # voices not configured yet, etc.: not worth stopping for
        print(f"[announcer] could not label saved clips: {e}", file=sys.stderr, flush=True)


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "localhost"
    finally:
        s.close()


if __name__ == "__main__":
    threading.Thread(target=warm_thumbs, daemon=True).start()
    threading.Thread(target=label_clips, daemon=True).start()
    server = QuietServer(("0.0.0.0", PORT), Handler)
    print(f"Player (open on this Mac, cast this tab): http://localhost:{PORT}")
    print(f"Phone remote (same Wi-Fi):               http://{lan_ip()}:{PORT}/remote")
    print(f"Music folder: {MUSIC}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
