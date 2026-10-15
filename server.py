#!/usr/bin/env python3
"""Local server for the jazz app: static pages, the MP3 library, and a tiny
event relay so a phone can control the player. Standard library only."""
import json
import mimetypes
import os
import queue
import re
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import announcer
import tracks
import tts

ROOT = Path(__file__).parent.resolve()
PUBLIC = ROOT / "public"
MUSIC = Path(os.environ.get("MUSIC_DIR", ROOT / "music")).resolve()
PORT = int(os.environ.get("PORT", 3000))
AUDIO_EXT = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav"}

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


def read_title(file):
    """Embedded song title (ID3v2 TIT2, then ID3v1), or None."""
    try:
        with open(file, "rb") as f:
            head = f.read(10)
            if head[:3] == b"ID3":
                major = head[3]
                size = int.from_bytes(head[6:10], "big")
                size = ((size >> 24) & 0x7F) << 21 | ((size >> 16) & 0x7F) << 14 | ((size >> 8) & 0x7F) << 7 | (size & 0x7F)
                tag = f.read(size)
                pos = 0
                while pos + 10 <= len(tag) and tag[pos] != 0:
                    fid, fsize = tag[pos:pos + 4], int.from_bytes(tag[pos + 4:pos + 8], "big")
                    if major == 4:
                        fsize = ((fsize >> 24) & 0x7F) << 21 | ((fsize >> 16) & 0x7F) << 14 | ((fsize >> 8) & 0x7F) << 7 | (fsize & 0x7F)
                    if fid == b"TIT2":
                        title = _decode_text(tag[pos + 10:pos + 10 + fsize])
                        if title:
                            return title
                    pos += 10 + fsize
            f.seek(-128, 2)
            v1 = f.read(128)
            if v1[:3] == b"TAG":
                return v1[3:33].split(b"\x00")[0].decode("latin-1").strip() or None
    except (OSError, ValueError):
        pass
    return None


def track_info(folder, f, details):
    """One song: title from tracks.csv, else embedded tag, else cleaned filename."""
    name_title, take = tracks.split_name(f.stem)
    row = details.get((folder.name, f.name), {})
    title = row.get("title") or (read_title(f) if f.suffix.lower() == ".mp3" else None) or name_title
    return {
        "title": title,
        "group": f"{folder.name}/{title.lower()}",  # takes of one song share a group
        "take": int(row.get("take") or take),
        "tempo": row.get("tempo", ""),
        "bpm": row.get("bpm", ""),
        "mood": row.get("mood", ""),
        "instruments": row.get("instruments", ""),
        "notes": row.get("notes", ""),
        "url": f"/music/{folder.name}/{f.name}".replace(" ", "%20"),
    }


def scan_library():
    categories = []
    details = tracks.load()
    if MUSIC.is_dir():
        for folder in sorted(p for p in MUSIC.iterdir() if p.is_dir()):
            tracks_ = [
                track_info(folder, f, details)
                for f in sorted(folder.iterdir())
                if f.suffix.lower() in AUDIO_EXT
            ]
            if tracks_:
                categories.append(
                    {
                        "id": folder.name,
                        "label": folder.name.replace("-", " ").replace("_", " "),
                        "tracks": tracks_,
                    }
                )
    return categories


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
        path = unquote(urlparse(self.path).path)
        if path == "/api/library":
            return self.send_json({"categories": scan_library()})
        if path == "/events":
            return self.serve_events()
        if path.startswith("/music/"):
            return self.serve_file(safe_join(MUSIC, path[len("/music/"):]), audio_only=True)
        if path == "/":
            path = "/index.html"
        elif path == "/remote":
            path = "/remote.html"
        self.serve_file(safe_join(PUBLIC, path.lstrip("/")))

    def do_POST(self):
        route = urlparse(self.path).path
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
        text = announcer.build_text(body, scan_library())
        if not text:
            return self.send_json({"error": "unknown announcement"}, 400)
        try:
            audio = tts.speak(text).read_bytes()
        except tts.TTSError as e:
            return self.send_json({"error": str(e)}, 503)
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio)))
        self.send_header("Cache-Control", "no-store")
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
    server = QuietServer(("0.0.0.0", PORT), Handler)
    print(f"Player (open on this Mac, cast this tab): http://localhost:{PORT}")
    print(f"Phone remote (same Wi-Fi):               http://{lan_ip()}:{PORT}/remote")
    print(f"Music folder: {MUSIC}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
