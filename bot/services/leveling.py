"""Level-up math and cross-game XP awarding (reusable by any cog)."""

from __future__ import annotations

from bot.models.xp_store import load_user, save_user

_cumulative_xp_cache: dict[int, int] = {}


def xp_for_level(level: int) -> int:
    return 100 * level * level


def cumulative_xp(level: int) -> int:
    if level not in _cumulative_xp_cache:
        _cumulative_xp_cache[level] = sum(xp_for_level(l) for l in range(1, level))
    return _cumulative_xp_cache[level]


def level_from_xp(total_xp: int) -> int:
    level = 1
    while total_xp >= xp_for_level(level):
        total_xp -= xp_for_level(level)
        level += 1
        if level > 1000:
            break
    return level


def get_level_progress(total_xp: int) -> tuple[int, int, int]:
    level = level_from_xp(total_xp)
    current_level_xp = cumulative_xp(level)
    xp_in_level = total_xp - current_level_xp
    xp_needed = xp_for_level(level)
    return xp_in_level, xp_needed, level


def award_game_xp(user_id: int, xp: int, sp: int = 0) -> int:
    """Award XP/SP earned from games. Returns the level after the award."""
    data = load_user(user_id)
    data["xp"] += xp
    data["sp"] += sp
    data["level"] = level_from_xp(data["xp"])
    save_user(user_id, data)
    return data["level"]