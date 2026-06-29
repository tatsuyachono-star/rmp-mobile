# -*- coding: utf-8 -*-
"""
RMP Mobile (Cloud) - YouTube Music Player for Smartphones
Render にデプロイ用。音源ファイルはスマホ側で保管（IndexedDB）。
サーバーはメタデータ DB のみ保持。
"""
import os
import re
import io
import sys
import json
import time
import uuid
import sqlite3
import logging
import threading
import tempfile
import traceback
import urllib.request
import subprocess
from pathlib import Path

from flask import Flask, request, jsonify, send_file, send_from_directory, abort
from flask_cors import CORS
import yt_dlp

# ===== 設定 =====
PORT = int(os.environ.get("PORT", 5000))
DATABASE_URL = os.environ.get("DATABASE_URL")  # Render PostgreSQL（将来対応）
TEMP_DIR = tempfile.gettempdir()
DATA_DIR = os.path.join(tempfile.gettempdir(), "rmp_cloud")
DB_PATH = os.path.join(DATA_DIR, "rmp.db")

os.makedirs(DATA_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== ffmpeg は不使用（メモリ節約） =====

# ===== データベース =====
_db_lock = threading.Lock()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with db() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS songs (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                artist     TEXT,
                duration   REAL,
                favorite   INTEGER NOT NULL DEFAULT 0,
                source_url TEXT,
                added_at   REAL
            );
            CREATE TABLE IF NOT EXISTS playlists (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS playlist_songs (
                playlist_id INTEGER NOT NULL,
                song_id     TEXT NOT NULL,
                position    INTEGER NOT NULL,
                PRIMARY KEY (playlist_id, song_id),
                FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
                FOREIGN KEY (song_id)     REFERENCES songs(id)     ON DELETE CASCADE
            );
        """)

def song_to_dict(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "artist": row["artist"] or "",
        "duration": row["duration"] or 0,
        "favorite": bool(row["favorite"]),
        "sourceUrl": row["source_url"] or "",
        "addedAt": row["added_at"] or 0,
    }

# ===== 曲取得・ダウンロード =====
def download_and_encode(url):
    """YouTube URL から音声をダウンロード・エンコードし、Blob(bytes)とメタデータを返す。
    メモリ効率化：ffmpeg をスキップ、直接音声ファイルを返す。
    プレイリスト対応：?list= を削除して単一曲のみダウンロード。
    """
    try:
        # プレイリストパラメータを削除（YouTube 認証エラー対策）
        url = re.sub(r'[?&]list=[^&]*', '', url).rstrip('?&')
        logger.info(f"Downloading: {url}")
        resolve_opts = {
            "quiet": False,
            "no_warnings": False,
            "socket_timeout": 60,
            "skip_unavailable_fragments": True,
            "extractor_args": {"youtube": {"lang": ["en", "ja"]}},
            "youtube_include_dash_manifest": False,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
            },
        }
        with yt_dlp.YoutubeDL(resolve_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        entries = info.get("entries")
        items = list(entries) if entries else [info]
        items = [e for e in items if e]

        results = []
        for entry in items:
            try:
                if not entry.get("formats") and entry.get("id"):
                    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl2:
                        entry = ydl2.extract_info(
                            entry.get("webpage_url") or ("https://www.youtube.com/watch?v=" + entry["id"]),
                            download=False,
                        )

                # 一時ディレクトリ
                tmp_dir = tempfile.mkdtemp()

                # ffmpeg なし - ダウンロードのみ
                # プレイリストを無視（YouTube 認証エラー対策）
                ydl_opts = {
                    "format": "bestaudio/best",
                    "outtmpl": os.path.join(tmp_dir, "%(id)s.%(ext)s"),
                    "quiet": True,
                    "no_warnings": True,
                    "noprogress": True,
                    "socket_timeout": 30,
                    "noplaylist": True,
                    "http_headers": {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                        "Accept": "*/*",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([entry.get("webpage_url") or ("https://www.youtube.com/watch?v=" + entry["id"])])

                # ダウンロードされたファイルを探す
                audio_file = None
                for fn in os.listdir(tmp_dir):
                    if fn.startswith(entry['id']):
                        audio_file = os.path.join(tmp_dir, fn)
                        break

                if not audio_file:
                    raise RuntimeError("Audio file not found after download")

                # ファイルを読んで Blob として返す
                with open(audio_file, "rb") as f:
                    audio_blob = f.read()

                # 不要なファイルを削除
                try:
                    for fn in os.listdir(tmp_dir):
                        os.remove(os.path.join(tmp_dir, fn))
                    os.rmdir(tmp_dir)
                except Exception:
                    pass

                # メタデータ
                vid = entry.get("id")
                title = entry.get("title") or vid
                artist = entry.get("artist") or entry.get("uploader") or ""
                duration = entry.get("duration") or 0
                webpage = entry.get("webpage_url") or ("https://www.youtube.com/watch?v=" + vid)

                results.append({
                    "id": vid,
                    "title": title,
                    "artist": artist,
                    "duration": duration,
                    "sourceUrl": webpage,
                    "audioBlob": audio_blob,
                })

            except Exception as e:
                logger.error(f"Failed to process entry: {e}")
                continue

        return results

    except Exception as e:
        logger.error(f"Download error: {e}\n{traceback.format_exc()}")
        raise

# ===== Static Files =====
@app.route("/")
def index():
    try:
        return send_file(os.path.join(os.path.dirname(__file__), "index.html"))
    except Exception as e:
        return {"error": str(e)}, 500

# ===== API =====
@app.get("/api/health")
def api_health():
    return jsonify({"ok": True, "version": "2026.06.29"})

@app.post("/api/import-file")
def api_import_file():
    """ローカルオーディオファイルをアップロード - メモリ最適化版."""
    files = request.files.getlist("files")
    files = [f for f in files if f and f.filename]
    if not files:
        return jsonify({"error": "No files selected"}), 400

    results = []
    for f in files:
        try:
            vid = "f" + uuid.uuid4().hex[:15]
            title = os.path.splitext(f.filename)[0]

            # ファイルをそのまま返す（Base64エンコードはスキップしてメモリ節約）
            # クライアント側で Blob として処理
            file_data = f.read()

            import base64
            audio_base64 = base64.b64encode(file_data).decode('utf-8')

            results.append({
                "id": vid,
                "title": title,
                "artist": "",
                "duration": 0.0,
                "sourceUrl": "",
                "audioBase64": audio_base64,
            })

            # DB に保存
            with _db_lock, db() as c:
                c.execute(
                    """INSERT INTO songs (id, title, artist, duration, source_url, added_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (vid, title, "", 0.0, "", time.time())
                )
        except Exception as e:
            logger.error(f"File upload error: {e}\n{traceback.format_exc()}")
            results.append({"error": str(e)})

    return jsonify({"songs": results})

@app.post("/api/import")
def api_import():
    """YouTube URL から曲をダウンロード・エンコードし、音声Blob + メタデータを返す。
    スマホ側で IndexedDB に保存。
    """
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"error": "URL is empty"}), 400

    if not re.match(r"^https?://", url):
        url = "ytsearch1:" + url

    try:
        results = download_and_encode(url)

        # DB に曲情報を保存
        with _db_lock, db() as c:
            for r in results:
                c.execute(
                    """INSERT OR REPLACE INTO songs
                       (id, title, artist, duration, source_url, added_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (r["id"], r["title"], r["artist"], r["duration"], r["sourceUrl"], time.time())
                )

        # スマホに返す（Blob は Base64 エンコード）
        response_data = []
        for r in results:
            import base64
            response_data.append({
                "id": r["id"],
                "title": r["title"],
                "artist": r["artist"],
                "duration": r["duration"],
                "sourceUrl": r["sourceUrl"],
                "audioBase64": base64.b64encode(r["audioBlob"]).decode("utf-8"),
            })

        return jsonify({"songs": response_data})

    except Exception as e:
        logger.error(f"Import error: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)[:200]}), 500

@app.get("/api/songs")
def api_songs():
    """DB から曲メタデータを取得。"""
    with db() as c:
        rows = c.execute("SELECT * FROM songs ORDER BY added_at DESC").fetchall()
    return jsonify([song_to_dict(r) for r in rows])

@app.post("/api/songs/<vid>/favorite")
def api_favorite(vid):
    data = request.get_json(force=True, silent=True) or {}
    fav = 1 if data.get("favorite") else 0
    with _db_lock, db() as c:
        c.execute("UPDATE songs SET favorite=? WHERE id=?", (fav, vid))
    return jsonify({"ok": True})

@app.delete("/api/songs/<vid>")
def api_delete_song(vid):
    with _db_lock, db() as c:
        c.execute("DELETE FROM songs WHERE id=?", (vid,))
    return jsonify({"ok": True})

@app.put("/api/songs/<vid>/meta")
def api_edit_meta(vid):
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()
    artist = (data.get("artist") or "").strip()
    if not title:
        return jsonify({"error": "Title is empty"}), 400
    with _db_lock, db() as c:
        c.execute("UPDATE songs SET title=?, artist=? WHERE id=?", (title, artist, vid))
    return jsonify({"ok": True})

# プレイリスト
@app.get("/api/playlists")
def api_playlists():
    with db() as c:
        rows = c.execute(
            """SELECT p.id, p.name, p.created_at,
                      (SELECT COUNT(*) FROM playlist_songs ps WHERE ps.playlist_id=p.id) AS cnt
               FROM playlists p ORDER BY p.created_at DESC"""
        ).fetchall()
    return jsonify([
        {"id": r["id"], "name": r["name"], "count": r["cnt"], "createdAt": r["created_at"]}
        for r in rows
    ])

@app.post("/api/playlists")
def api_create_playlist():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is empty"}), 400
    with _db_lock, db() as c:
        cur = c.execute("INSERT INTO playlists(name, created_at) VALUES(?, ?)", (name, time.time()))
        pid = cur.lastrowid
    return jsonify({"id": pid, "name": name, "count": 0})

@app.put("/api/playlists/<int:pid>")
def api_rename_playlist(pid):
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is empty"}), 400
    with _db_lock, db() as c:
        c.execute("UPDATE playlists SET name=? WHERE id=?", (name, pid))
    return jsonify({"ok": True})

@app.delete("/api/playlists/<int:pid>")
def api_delete_playlist(pid):
    with _db_lock, db() as c:
        c.execute("DELETE FROM playlists WHERE id=?", (pid,))
    return jsonify({"ok": True})

@app.get("/api/playlists/<int:pid>")
def api_playlist_detail(pid):
    with db() as c:
        p = c.execute("SELECT * FROM playlists WHERE id=?", (pid,)).fetchone()
        if not p:
            return jsonify({"error": "not found"}), 404
        rows = c.execute(
            """SELECT s.* FROM playlist_songs ps
               JOIN songs s ON s.id = ps.song_id
               WHERE ps.playlist_id=? ORDER BY ps.position""",
            (pid,),
        ).fetchall()
    return jsonify({
        "id": p["id"], "name": p["name"],
        "songs": [song_to_dict(r) for r in rows],
    })

@app.post("/api/playlists/<int:pid>/songs")
def api_playlist_add(pid):
    data = request.get_json(force=True, silent=True) or {}
    song_ids = data.get("songIds") or ([data["songId"]] if data.get("songId") else [])
    with _db_lock, db() as c:
        maxpos = c.execute(
            "SELECT COALESCE(MAX(position), -1) m FROM playlist_songs WHERE playlist_id=?", (pid,)
        ).fetchone()["m"]
        pos = maxpos + 1
        for sid in song_ids:
            c.execute(
                "INSERT OR IGNORE INTO playlist_songs(playlist_id, song_id, position) VALUES(?, ?, ?)",
                (pid, sid, pos),
            )
            pos += 1
    return jsonify({"ok": True})

@app.delete("/api/playlists/<int:pid>/songs/<sid>")
def api_playlist_remove(pid, sid):
    with _db_lock, db() as c:
        c.execute("DELETE FROM playlist_songs WHERE playlist_id=? AND song_id=?", (pid, sid))
    return jsonify({"ok": True})

@app.put("/api/playlists/<int:pid>/order")
def api_playlist_reorder(pid):
    data = request.get_json(force=True, silent=True) or {}
    order = data.get("songIds") or []
    with _db_lock, db() as c:
        for pos, sid in enumerate(order):
            c.execute(
                "UPDATE playlist_songs SET position=? WHERE playlist_id=? AND song_id=?",
                (pos, pid, sid),
            )
    return jsonify({"ok": True})

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=PORT, threaded=True, debug=False, use_reloader=False)
