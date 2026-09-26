"""Distro game: metadata coverage, answer variants, spawn/solve logic."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import bot.cogs.distro as distro_mod
from bot.cogs.distro import (
    EXPIRE_TIMEOUT,
    FIRST_HINT_DELAY,
    GUESS_COOLDOWN,
    HINT_PENALTY,
    MIN_SP,
    MIN_XP,
    SECOND_HINT_DELAY,
    TIER_REWARDS,
    Distro,
    _accepted_answers,
    _answer_variants,
    _image_files,
    _metadata_for,
    _normalise_text,
    _primary_name,
    _tier_for,
    get_spawn_channel,
    is_enabled,
    set_enabled,
    set_spawn_channel,
)

from helpers import (
    GUILD_ID,
    TEXT_CHANNEL_ID,
    USER_IDS,
    make_channel,
    make_ctx,
    make_guild,
    make_member,
    make_message,
    make_permissions,
    make_text_channel,
)


# ── Constants ──────────────────────────────────────────────────────────────────
def test_timing_constants():
    assert FIRST_HINT_DELAY == 45
    assert SECOND_HINT_DELAY == 150
    assert EXPIRE_TIMEOUT == 180
    assert GUESS_COOLDOWN == 2.5
    assert HINT_PENALTY == 0.6
    assert MIN_XP == 5
    assert MIN_SP == 1
    assert TIER_REWARDS["easy"] == {"xp": 15, "sp": 3}
    assert TIER_REWARDS["medium"] == {"xp": 25, "sp": 5}
    assert TIER_REWARDS["hard"] == {"xp": 45, "sp": 10}


# ── Metadata coverage ──────────────────────────────────────────────────────────
def test_every_image_has_metadata():
    assert len(_image_files()) == 31
    for img in _image_files():
        meta = _metadata_for(img.stem)
        assert meta, f"{img.stem} missing metadata"
        assert meta["name"]
        assert meta["tier"] in TIER_REWARDS
        assert meta["hints"]


def test_metadata_has_no_orphan_entries():
    images = {_primary_name(img.stem) for img in _image_files()}
    meta = distro_mod._load_metadata()
    orphans = [k for k in meta if k not in images]
    assert orphans == [], f"orphan metadata entries: {orphans}"


# ── Answer variants ────────────────────────────────────────────────────────────
def test_normalise_text():
    assert _normalise_text("  Arch_Linux.png  ") == "arch linux"
    assert _normalise_text("Pop!_OS.") == "pop! os"
    assert _normalise_text(" Debian Linux ") == "debian linux"
    assert _normalise_text("") == ""


def test_primary_name():
    assert _primary_name("arch") == "arch"
    assert _primary_name("Pop_OS") == "pop os"
    assert _primary_name("linux-lite") == "linux lite"


def test_answer_variants_for_arch():
    variants = _answer_variants("arch")
    for expected in ("arch", "arch os", "arch linux", "arch os linux", "archlinux"):
        assert expected in variants


def test_accepted_answers_pulls_aliases():
    accepted = _accepted_answers("pop")
    for expected in ("pop", "pop os", "popos", "pop linux"):
        assert expected in accepted


def test_tier_for_known_and_unknown():
    assert _tier_for("arch") == "easy"
    assert _tier_for("cachy") == "medium"
    assert _tier_for("omarchy") == "hard"
    assert _tier_for("totally-unknown") == "medium"  # DEFAULT_TIER


# ── Feature toggle persistence ─────────────────────────────────────────────────
def test_enabled_roundtrip():
    assert is_enabled(GUILD_ID) is False
    set_enabled(GUILD_ID, True)
    assert is_enabled(GUILD_ID) is True
    set_enabled(GUILD_ID, False)
    assert is_enabled(GUILD_ID) is False


def test_spawn_channel_roundtrip():
    assert get_spawn_channel(GUILD_ID) is None
    set_spawn_channel(GUILD_ID, TEXT_CHANNEL_ID)
    assert get_spawn_channel(GUILD_ID) == TEXT_CHANNEL_ID
    set_spawn_channel(GUILD_ID, None)
    assert get_spawn_channel(GUILD_ID) is None


# ── Spawn / solve ──────────────────────────────────────────────────────────────
def _cog(bot):
    return Distro(bot)


async def test_spawn_no_permission(bot):
    cog = _cog(bot)
    guild = make_guild(permissions_for_me=_none_perms())
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild, permissions_for_me=_none_perms())
    ok, feedback = await cog._spawn(channel)
    assert ok is False
    assert "permission" in feedback


def _none_perms():
    from helpers import make_permissions
    return make_permissions(send_messages=False, attach_files=False)


async def test_spawn_creates_active_round(bot):
    cog = _cog(bot)
    guild = make_guild()
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)

    ok, feedback = await cog._spawn(channel)
    assert ok is True, feedback
    r = cog.active.get(channel.id)
    assert r is not None
    assert r["solved"] is False
    assert r["guild_id"] == guild.id
    assert r["task"] is not None

    channel.send.assert_awaited_once()
    assert r["answer"] in r["variants"]

    # a second spawn while a round is active is rejected
    ok2, feedback2 = await cog._spawn(channel)
    assert ok2 is False
    assert "already spawned" in feedback2

    r["task"].cancel()


async def test_maybe_solve_correct_guess(bot):
    cog = _cog(bot)
    guild = make_guild()
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)
    ok, _ = await cog._spawn(channel)
    assert ok
    r = cog.active[channel.id]

    award = AsyncMock()
    cog._award_win = award
    solver = make_member(USER_IDS["member"], guild=guild)
    msg = make_message(_primary_name(r["answer"]), author=solver, channel=channel, guild=guild)

    await cog._maybe_solve(msg)
    award.assert_awaited_once_with(msg, r)
    assert channel.id not in cog.active


async def test_maybe_solve_wrong_guess_throttles(bot):
    cog = _cog(bot)
    guild = make_guild()
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)
    ok, _ = await cog._spawn(channel)
    assert ok
    r = cog.active[channel.id]

    award = AsyncMock()
    cog._award_win = award
    solver = make_member(USER_IDS["member"], guild=guild)
    wrong = make_message("not-it", author=solver, channel=channel, guild=guild)
    await cog._maybe_solve(wrong)
    await cog._maybe_solve(wrong)  # second guess within cooldown -> ignored
    award.assert_not_awaited()
    assert channel.id in cog.active

    r["task"].cancel()


async def test_award_win_hint_penalty(bot):
    cog = _cog(bot)
    guild = make_guild()
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)
    r = {
        "guild_id": guild.id,
        "answer": "arch",
        "display": "Arch Linux",
        "tier": "medium",
        "reward": TIER_REWARDS["medium"],
        "hints_used": 2,
        "message": make_message(author=make_member(1, guild=guild), channel=channel, guild=guild),
    }
    winner = make_member(USER_IDS["member"], guild=guild)
    msg = make_message("arch", author=winner, channel=channel, guild=guild)

    await cog._award_win(msg, r)

    # 25 * 0.6**2 = 9 XP; 5 * 0.36 = 2 SP
    embed = channel.send.await_args.kwargs["embed"]
    assert "**9 XP**" in embed.description
    assert "**2 SP**" in embed.description
    assert "(medium difficulty, 2 hint used)" in embed.description
    assert "LEVEL UP" not in embed.description


async def test_award_win_floors_at_min(bot):
    cog = _cog(bot)
    guild = make_guild()
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)
    r = {
        "guild_id": guild.id,
        "display": "Arch Linux",
        "tier": "easy",
        "reward": TIER_REWARDS["easy"],
        "hints_used": 5,  # 15*0.6**5 = 1.16 -> floor 5 XP
        "message": make_message(author=make_member(1, guild=guild), channel=channel, guild=guild),
    }
    winner = make_member(USER_IDS["member"], guild=guild)
    msg = make_message("arch", author=winner, channel=channel, guild=guild)

    await cog._award_win(msg, r)
    embed = channel.send.await_args.kwargs["embed"]
    assert "**5 XP**" in embed.description
    assert "**1 SP**" in embed.description


async def test_on_message_ignores_bots_and_dm(bot):
    cog = _cog(bot)
    member = make_member(USER_IDS["member"], guild=make_guild(), bot=True)
    msg = make_message("anything", author=member, guild=None, channel=None)
    await cog.on_message(msg)  # must not raise


# ── Commands ───────────────────────────────────────────────────────────────────
async def test_status_embed(bot):
    cog = _cog(bot)
    guild = make_guild()
    set_enabled(guild.id, True)
    bot.get_channel = MagicMock(return_value=None)
    member = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=member, guild=guild)
    await cog.distro.callback(cog, ctx)
    embed = ctx.send.await_args.kwargs["embed"]
    by_name = {f.name: f.value for f in embed.fields}
    assert embed.author.name == "🐧 Distro Game Status"
    assert by_name["Enabled"] == "Yes"
    assert by_name["Images Available"] == "31"
    assert by_name["Spawn Channel"] == "Random"


async def test_spawn_cmd_disabled_feature(bot):
    cog = _cog(bot)
    guild = make_guild()
    member = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=member, guild=guild)
    await cog.distro.callback(cog, ctx, "spawn", rest=None)
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Feature Disabled"


async def test_end_cmd_permission_denied(bot):
    cog = _cog(bot)
    guild = make_guild()
    member = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=member, guild=guild)
    await cog.distro.callback(cog, ctx, "end", rest=None)
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Permission Denied"


async def test_channel_cmd_pins_channel(bot):
    cog = _cog(bot)
    channel = make_text_channel(4001, name="distros")
    guild = make_guild(channels=[channel])
    ctx = make_ctx(
        bot,
        author=make_member(USER_IDS["admin"], guild=guild, permissions=make_permissions(administrator=True)),
        guild=guild,
    )
    await cog.distro.callback(cog, ctx, "channel", rest="4001")
    assert get_spawn_channel(guild.id) == 4001


async def test_channel_cmd_clear(bot):
    cog = _cog(bot)
    guild = make_guild()
    set_spawn_channel(guild.id, 4001)
    ctx = make_ctx(
        bot,
        author=make_member(USER_IDS["admin"], guild=guild, permissions=make_permissions(administrator=True)),
        guild=guild,
    )
    await cog.distro.callback(cog, ctx, "channel", rest="clear")
    assert get_spawn_channel(guild.id) is None