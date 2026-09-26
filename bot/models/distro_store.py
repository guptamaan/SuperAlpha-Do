"""File-backed persistence for the distro game.

Owns the ``distro/names.json`` metadata pointer, the per-guild enabled list /
spawn-channel pin (``data/distro/enabled.json``), and round stats
(``data/distro/stats.json``). Game rules and answer-matching logic live in
``bot.services.distro_game``; the command/event surface in ``bot.cogs.distro``.
"""

from __future__ import annotations

import json
import pathlib

DISTRO_DIR = pathlib.Path("distro")
ENABLED_FILE = pathlib.Path("data/distro/enabled.json")
STATS_FILE = pathlib.Path("data/distro/stats.json")
METADATA_FILE = DISTRO_DIR / "names.json"


def _load_json(path: pathlib.Path) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── Feature toggle ─────────────────────────────────────────────────────────────
def is_enabled(guild_id: int | None) -> bool:
    if not guild_id:
        return False
    return guild_id in {int(g) for g in _load_json(ENABLED_FILE).get("guilds", [])}


def set_enabled(guild_id: int, enabled: bool) -> None:
    data = _load_json(ENABLED_FILE)
    guilds = {int(g) for g in data.get("guilds", [])}
    if enabled:
        guilds.add(guild_id)
    else:
        guilds.discard(guild_id)
    data["guilds"] = sorted(guilds)
    _save_json(ENABLED_FILE, data)


# ── Dedicated spawn channel ───────────────────────────────────────────────────
def get_spawn_channel(guild_id: int | None) -> int | None:
    """The configured text channel for auto-spawns in a guild, if any."""
    if not guild_id:
        return None
    channels = _load_json(ENABLED_FILE).get("channels", {})
    raw = channels.get(str(guild_id))
    return int(raw) if raw is not None else None


def set_spawn_channel(guild_id: int, channel_id: int | None) -> None:
    """Pin (or clear) the dedicated spawn channel for a guild."""
    data = _load_json(ENABLED_FILE)
    channels = {str(k): v for k, v in data.get("channels", {}).items()}
    if channel_id is None:
        channels.pop(str(guild_id), None)
    else:
        channels[str(guild_id)] = channel_id
    data["channels"] = channels
    _save_json(ENABLED_FILE, data)


# ── Stats ─────────────────────────────────────────────────────────────────────
def _guild_stats(guild_id: int) -> dict:
    data = _load_json(STATS_FILE)
    return data.setdefault(str(guild_id), {"spawns": 0, "solved": 0, "users": {}})


def _save_guild_stats(guild_id: int, stats: dict) -> None:
    data = _load_json(STATS_FILE)
    data[str(guild_id)] = stats
    _save_json(STATS_FILE, data)


# ── Distro metadata (tiers + hints) ───────────────────────────────────────────
def _load_metadata() -> dict:
    """names.json: { "filename-stem": {"name", "tier", "hints", "aliases"} }."""
    return _load_json(METADATA_FILE)