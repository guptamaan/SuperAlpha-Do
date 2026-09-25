"""SQLite + JSON persistence tests.

The ``db_env`` autouse fixture redirects every storage path to a throwaway
tmp dir, so these tests exercise the real SQL schema, upserts, and migration
paths without touching the repo's live ``data/`` files.
"""

from __future__ import annotations

import json
import os

import bot.cogs.spam as spam
import bot.cogs.xp as xp

from helpers import GUILD_ID


# ── XP (SQLite xp_users) ──────────────────────────────────────────────────────
def test_load_user_returns_defaults_for_unknown():
    xp._user_cache.clear()
    user = xp.load_user(999_001)
    assert user["xp"] == 0
    assert user["level"] == 1
    assert user["sp"] == 0
    assert user["messages"] == 0
    assert user["daily_claimed"] is None


def test_save_and_flush_persist_to_sqlite():
    xp._user_cache.clear()
    xp._dirty_users.clear()

    data = xp.load_user(999_002)
    data["xp"] = 500
    data["sp"] = 30
    data["messages"] = 7
    xp.save_user(999_002, data)
    xp.flush_all()

    # Cold reload: drop cached connection and in-memory cache.
    xp._db_conn = None
    xp._user_cache.clear()
    reloaded = xp.load_user(999_002)
    assert reloaded["xp"] == 500
    assert reloaded["sp"] == 30
    assert reloaded["messages"] == 7


def test_flush_noop_when_not_dirty():
    xp._user_cache.clear()
    xp._dirty_users.clear()
    xp.flush_all()  # must not raise
    xp._db_conn = None


def test_award_game_xp_adds_sp_and_relevels():
    xp._user_cache.clear()
    level = xp.award_game_xp(999_003, xp.xp_for_level(2), sp=5)
    assert level == 2
    assert xp.load_user(999_003)["sp"] == 5


def test_top_users_orders_by_key():
    xp._user_cache.clear()
    for uid, amount, sp in [(1, 100, 30), (2, 300, 10), (3, 50, 20)]:
        data = xp._default_user()
        data["xp"] = amount
        data["sp"] = sp
        xp._upsert_user(uid, data)
    top = xp.top_users("xp", 10)
    assert [uid for uid, _ in top] == [2, 1, 3]
    assert top[0][1]["xp"] == 300
    top_sp = xp.top_users("sp", 10)
    assert [uid for uid, _ in top_sp] == [1, 3, 2]


def test_legacy_json_migration_imported_once(tmp_path):
    legacy_dir = str(tmp_path / "xp")
    os.makedirs(legacy_dir, exist_ok=True)
    with open(os.path.join(legacy_dir, "424242.json"), "w") as f:
        json.dump({"xp": 123, "sp": 9, "messages": 4}, f)

    xp._db_conn = None
    xp.init_db()

    xp._user_cache.clear()
    migrated = xp.load_user(424242)
    assert migrated["xp"] == 123
    assert migrated["sp"] == 9
    assert migrated["messages"] == 4

    # Second run must not re-import (table already populated).
    xp._db_conn = None
    xp.init_db()
    assert xp._load_user_from_disk(424242)["xp"] == 123


# ── XP config (JSON) ──────────────────────────────────────────────────────────
def test_xp_config_roundtrip():
    xp._config_cache = None
    xp._config_cache_loaded = 0.0
    assert xp.is_xp_enabled(GUILD_ID) is True  # unknown guild defaults to enabled

    xp.set_xp_enabled(GUILD_ID, False)
    assert xp.is_xp_enabled(GUILD_ID) is False

    xp.set_level_channel(GUILD_ID, 555)
    assert xp.get_level_channel(GUILD_ID) == 555

    xp.set_xp_enabled(GUILD_ID, True)
    assert xp.is_xp_enabled(GUILD_ID) is True


# ── Level math ────────────────────────────────────────────────────────────────
def test_level_math():
    assert xp.xp_for_level(1) == 100
    assert xp.xp_for_level(2) == 400
    assert xp.cumulative_xp(3) == 100 + 400
    assert xp.level_from_xp(0) == 1
    assert xp.level_from_xp(99) == 1
    assert xp.level_from_xp(100) == 2
    assert xp.level_from_xp(500) == 3  # 100 + 400 consumed, level 3 begins at 500
    assert xp.level_from_xp(501) == 3
    progress = xp.get_level_progress(150)
    assert progress == (50, 400, 2)


# ── Spam (SQLite spam_config) ─────────────────────────────────────────────────
def test_spam_default_config():
    cfg = spam.get_config(123_001)
    assert cfg == spam._default_config()


def test_spam_config_roundtrip():
    spam.set_config(123_002, {
        "channel_id": 77,
        "word": "lol",
        "enabled": True,
        "streak": 7,
        "best_streak": 9,
        "last_author_id": 44,
    })
    spam._db_conn = None  # cold reload from disk
    cfg = spam.get_config(123_002)
    assert cfg["channel_id"] == 77
    assert cfg["word"] == "lol"
    assert cfg["enabled"] is True
    assert cfg["streak"] == 7
    assert cfg["best_streak"] == 9
    assert cfg["last_author_id"] == 44


def test_spam_config_upsert_merges_defaults():
    chunk = spam.get_config(123_003)
    chunk["enabled"] = True
    chunk["streak"] = 3
    spam.set_config(123_003, chunk)
    spam._db_conn = None
    cfg = spam.get_config(123_003)
    assert cfg["enabled"] is True
    assert cfg["streak"] == 3
    assert cfg["best_streak"] == 0


def test_spam_legacy_json_migration(tmp_path):
    os.makedirs(str(tmp_path / "spam"), exist_ok=True)
    with open(str(tmp_path / "spam" / "spam.json"), "w") as f:
        json.dump({"987654": {"channel_id": 5, "word": "spam", "enabled": True, "best_streak": 11}}, f)

    spam._db_conn = None
    spam._init_db()

    cfg = spam.get_config(987654)
    assert cfg["channel_id"] == 5
    assert cfg["word"] == "spam"
    assert cfg["enabled"] is True
    assert cfg["best_streak"] == 11


# ── Spam helpers ──────────────────────────────────────────────────────────────
def test_spam_normalise():
    assert spam._normalise("  HeLLO  ") == "hello"
    assert spam._normalise("😂") == "😂"