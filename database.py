"""
Database management for Telegram Video/Audio Downloader Bot.
Uses SQLite for persistent storage of users, downloads, and stats.
"""

import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "bot_database.db"


def get_connection():
    """Returns a SQLite connection with dict-like row access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes the database tables."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                username TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                download_count INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                url TEXT,
                title TEXT,
                media_type TEXT,
                filesize_mb REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Default setting for real-time admin notifications
        cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('notify_admin', '1')
        """)
        conn.commit()


def add_or_update_user(user_id: int, first_name: str, last_name: str, username: str):
    """Registers or updates a user's activity."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (user_id, first_name, last_name, username, joined_at, last_active)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                username = excluded.username,
                last_active = CURRENT_TIMESTAMP
        """, (user_id, first_name or "", last_name or "", username or ""))
        conn.commit()


def log_download(user_id: int, url: str, title: str, media_type: str, filesize_mb: float):
    """Logs a successful download and increments the user's counter."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO downloads (user_id, url, title, media_type, filesize_mb, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (user_id, url, title, media_type, round(filesize_mb, 2)))

        cursor.execute("""
            UPDATE users SET download_count = download_count + 1, last_active = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (user_id,))
        conn.commit()


def get_stats() -> dict:
    """Returns aggregated bot statistics."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) AS total FROM users")
        total_users = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM downloads")
        total_downloads = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM downloads WHERE media_type = 'video'")
        video_downloads = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM downloads WHERE media_type = 'audio'")
        audio_downloads = cursor.fetchone()["total"]

        cursor.execute("SELECT COALESCE(SUM(filesize_mb), 0) AS total_mb FROM downloads")
        total_mb = cursor.fetchone()["total_mb"]

        # Today's stats
        today_date = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("SELECT COUNT(*) AS total FROM downloads WHERE DATE(created_at) = DATE(?)", (today_date,))
        today_downloads = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM users WHERE DATE(joined_at) = DATE(?)", (today_date,))
        today_new_users = cursor.fetchone()["total"]

        return {
            "total_users": total_users,
            "total_downloads": total_downloads,
            "video_downloads": video_downloads,
            "audio_downloads": audio_downloads,
            "total_mb": total_mb,
            "today_downloads": today_downloads,
            "today_new_users": today_new_users,
        }


def get_recent_downloads(limit: int = 8) -> list:
    """Returns recent download entries with user info."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT d.id, d.title, d.media_type, d.filesize_mb, d.created_at, d.url,
                   u.user_id, u.first_name, u.username
            FROM downloads d
            LEFT JOIN users u ON d.user_id = u.user_id
            ORDER BY d.id DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def get_recent_users(limit: int = 8) -> list:
    """Returns recent users list."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id, first_name, username, download_count, joined_at, last_active
            FROM users
            ORDER BY last_active DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def get_setting(key: str, default: str = "") -> str:
    """Fetches setting value by key."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    """Sets a configuration setting."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        conn.commit()
