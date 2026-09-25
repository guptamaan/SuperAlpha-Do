"""SQLite/JSON persistence for the XP & SP profile system.

Owns user rows, the in-memory write-behind cache, and per-guild XP settings.
Pure persistence — level math lives in ``bot.services.leveling`` and the
command surface in ``bot.cogs.xp``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time

DATA_DIR = "data/xp"
CONFIG_FILE = "data/xp/config.json"
DATABASE_FILE = "data/xp.db"
os.makedirs(DATA_DIR, exist_ok=True)

_user_cache: dict[int, dict] = {}
_dirty_users: set[int] = set()
_SAVE_INTERVAL = 120
_config_cache: dict | None = None
_config_cache_loaded = 0.0
_CONFIG_CACHE_TTL = 10

_db_conn: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        os.makedirs("data", exist_ok=True)
        _db_conn = sqlite3.connect(DATABASE_FILE, check_same_thread=False)
        _db_conn.row_factory = sqlite3.Row
        _db_conn.execute("PRAGMA journal_mode=WAL")
    return _db_conn


def init_db() -> None:
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS xp_users (
            user_id        INTEGER PRIMARY KEY,
            xp             INTEGER NOT NULL DEFAULT 0,
            level          INTEGER NOT NULL DEFAULT 1,
            sp             INTEGER NOT NULL DEFAULT 0,
            messages       INTEGER NOT NULL DEFAULT 0,
            vc_time        INTEGER NOT NULL DEFAULT 0,
            commands_used  INTEGER NOT NULL DEFAULT 0,
            last_message   REAL    NOT NULL DEFAULT 0,
            vc_start       REAL    NOT NULL DEFAULT 0,
            daily_claimed  TEXT,
            streak         INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    _migrate_legacy_json()


def _default_user() -> dict:
    return {
        "xp": 0,
        "level": 1,
        "sp": 0,
        "messages": 0,
        "vc_time": 0,
        "commands_used": 0,
        "last_message": 0,
        "vc_start": 0,
        "daily_claimed": None,
        "streak": 0,
    }


def _migrate_legacy_json() -> None:
    """One-time import of old per-user JSON files into SQLite."""
    count = get_db().execute("SELECT COUNT(*) AS n FROM xp_users").fetchone()["n"]
    if count:
        return
    if not os.path.isdir(DATA_DIR):
        return
    for filename in os.listdir(DATA_DIR):
        if not filename.endswith(".json"):
            continue
        try:
            user_id = int(filename[:-5])
        except ValueError:
            continue
        try:
            with open(os.path.join(DATA_DIR, filename)) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        merged = _default_user()
        merged.update({k: v for k, v in data.items() if k in merged})
        _upsert_user(user_id, merged)


def _row_to_user(row: sqlite3.Row) -> dict:
    return {
        "xp": int(row["xp"] or 0),
        "level": int(row["level"] or 1),
        "sp": int(row["sp"] or 0),
        "messages": int(row["messages"] or 0),
        "vc_time": int(row["vc_time"] or 0),
        "commands_used": int(row["commands_used"] or 0),
        "last_message": float(row["last_message"] or 0),
        "vc_start": float(row["vc_start"] or 0),
        "daily_claimed": row["daily_claimed"],
        "streak": int(row["streak"] or 0),
    }


def _load_user_from_disk(user_id: int) -> dict:
    row = get_db().execute(
        "SELECT * FROM xp_users WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row is not None:
        return _row_to_user(row)
    return _default_user()


def load_user(user_id: int) -> dict:
    if user_id not in _user_cache:
        _user_cache[user_id] = _load_user_from_disk(user_id)
    return _user_cache[user_id]


def save_user(user_id: int, data: dict) -> None:
    _user_cache[user_id] = data
    _dirty_users.add(user_id)


def _upsert_user(user_id: int, data: dict) -> None:
    merged = _default_user()
    merged.update(data)
    conn = get_db()
    conn.execute(
        """
        INSERT INTO xp_users (user_id, xp, level, sp, messages, vc_time,
                              commands_used, last_message, vc_start, daily_claimed, streak)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            xp=excluded.xp, level=excluded.level, sp=excluded.sp,
            messages=excluded.messages, vc_time=excluded.vc_time,
            commands_used=excluded.commands_used, last_message=excluded.last_message,
            vc_start=excluded.vc_start, daily_claimed=excluded.daily_claimed,
            streak=excluded.streak
        """,
        (
            user_id,
            int(merged["xp"] or 0),
            int(merged["level"] or 1),
            int(merged["sp"] or 0),
            int(merged["messages"] or 0),
            int(merged["vc_time"] or 0),
            int(merged["commands_used"] or 0),
            float(merged["last_message"] or 0),
            float(merged["vc_start"] or 0),
            merged["daily_claimed"],
            int(merged["streak"] or 0),
        ),
    )
    conn.commit()


def _flush_user(user_id: int) -> None:
    if user_id not in _dirty_users:
        return
    data = _user_cache.get(user_id)
    if data is None:
        _dirty_users.discard(user_id)
        return
    _upsert_user(user_id, data)
    _dirty_users.discard(user_id)


def flush_all() -> None:
    for uid in list(_dirty_users):
        _flush_user(uid)


_TOP_COLUMNS = {"xp": "xp", "sp": "sp", "messages": "messages", "vc": "vc_time"}


def top_users(key: str, limit: int = 10) -> list[tuple[int, dict]]:
    """Top `limit` users ranked by a stat key, as [(user_id, data), ...]."""
    column = _TOP_COLUMNS.get(key, "xp")
    rows = get_db().execute(
        f"SELECT * FROM xp_users ORDER BY {column} DESC, user_id ASC LIMIT ?",
        (limit,),
    ).fetchall()
    return [(int(r["user_id"]), _row_to_user(r)) for r in rows]


init_db()


def load_config() -> dict:
    global _config_cache, _config_cache_loaded
    now = time.time()
    if _config_cache is None or (now - _config_cache_loaded) > _CONFIG_CACHE_TTL:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                _config_cache = json.load(f)
        else:
            _config_cache = {}
        _config_cache_loaded = now
    return _config_cache


def save_config(config: dict) -> None:
    global _config_cache, _config_cache_loaded
    _config_cache = config
    _config_cache_loaded = time.time()
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def is_xp_enabled(guild_id: int) -> bool:
    config = load_config()
    if str(guild_id) in config:
        return config[str(guild_id)].get("enabled", True)
    return True


def set_xp_enabled(guild_id: int, enabled: bool) -> None:
    config = load_config()
    if str(guild_id) not in config:
        config[str(guild_id)] = {"enabled": True}
    config[str(guild_id)]["enabled"] = enabled
    save_config(config)


def get_level_channel(guild_id: int) -> int | None:
    config = load_config()
    data = config.get(str(guild_id))
    if data:
        return data.get("level_channel")
    return None


def set_level_channel(guild_id: int, channel_id: int | None) -> None:
    config = load_config()
    if str(guild_id) not in config:
        config[str(guild_id)] = {"enabled": True}
    config[str(guild_id)]["level_channel"] = channel_id
    save_config(config)