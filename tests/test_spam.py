"""Spam chain game: config storage, streak logic, and command flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import bot.cogs.spam as spam
from bot.cogs.spam import SpamGame

from helpers import (
    TEXT_CHANNEL_ID,
    USER_IDS,
    make_channel,
    make_ctx,
    make_guild,
    make_member,
    make_message,
    make_permissions,
)


def _base_config(**overrides):
    cfg = {
        "channel_id": None,
        "word": None,
        "enabled": False,
        "streak": 0,
        "best_streak": 0,
        "last_author_id": None,
        "score_msg_id": None,
    }
    cfg.update(overrides)
    return cfg


async def _configured_game(bot, guild, channel_id=TEXT_CHANNEL_ID, word="lol"):
    spam.set_config(guild.id, _base_config(
        enabled=True, channel_id=channel_id, word=word,
    ))
    return SpamGame(bot)


def test_normalise():
    assert spam._normalise("  LOOl!!  ") == "lool!!"
    assert spam._normalise("HEHE") == "hehe"


# ── _handle_message ───────────────────────────────────────────────────────────
async def test_correct_word_increments_streak(bot):
    cog = await _configured_game(bot, guild := make_guild())
    author = make_member(USER_IDS["member"], guild=guild)
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)

    await cog._handle_message(make_message("lol", author=author, channel=channel, guild=guild))
    cfg = spam.get_config(guild.id)
    assert cfg["streak"] == 1
    assert cfg["best_streak"] == 1
    assert cfg["last_author_id"] == USER_IDS["member"]


async def test_wrong_word_breaks_streak(bot):
    guild = make_guild()
    cog = await _configured_game(bot, guild)
    author = make_member(USER_IDS["member"], guild=guild)
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)

    await cog._handle_message(make_message("lol", author=author, channel=channel, guild=guild))
    second = make_member(USER_IDS["admin"], guild=guild)
    await cog._handle_message(make_message("lol", author=second, channel=channel, guild=guild))
    bad = make_message("nottheword", author=author, channel=channel, guild=guild)
    await cog._handle_message(bad)

    cfg = spam.get_config(guild.id)
    assert cfg["streak"] == 0
    assert cfg["best_streak"] == 2
    embed = bad.channel.send.call_args_list[-1].kwargs["embed"]
    assert "ruined the chain" in embed.description
    assert embed.author.name == "🥀 Spam Chain Broken..."


async def test_same_author_twice_breaks(bot):
    guild = make_guild()
    cog = await _configured_game(bot, guild)
    author = make_member(USER_IDS["member"], guild=guild)
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)

    await cog._handle_message(make_message("lol", author=author, channel=channel, guild=guild))
    second = make_message("lol", author=author, channel=channel, guild=guild)
    await cog._handle_message(second)

    cfg = spam.get_config(guild.id)
    assert cfg["streak"] == 0
    assert "too greedy" in second.channel.send.call_args_list[-1].kwargs["embed"].description


async def test_message_outside_channel_ignored(bot):
    guild = make_guild()
    cog = await _configured_game(bot, guild)
    author = make_member(USER_IDS["member"], guild=guild)
    channel = make_channel(9090, guild=guild)

    await cog._handle_message(make_message("lol", author=author, channel=channel, guild=guild))
    assert spam.get_config(guild.id)["streak"] == 0


async def test_disabled_game_ignored(bot):
    guild = make_guild()
    spam.set_config(guild.id, _base_config(enabled=False))
    cog = SpamGame(bot)
    author = make_member(USER_IDS["member"], guild=guild)
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)

    await cog._handle_message(make_message("lol", author=author, channel=channel, guild=guild))
    assert spam.get_config(guild.id)["streak"] == 0


# ── Commands ──────────────────────────────────────────────────────────────────
async def _admin_ctx(bot, guild):
    admin = make_member(USER_IDS["admin"], guild=guild, permissions=make_permissions(administrator=True))
    return make_ctx(bot, author=admin, guild=guild)


async def test_start_missing_channel_and_word(bot):
    cog = SpamGame(bot)
    guild = make_guild()
    ctx = await _admin_ctx(bot, guild)
    await cog.spam.callback(cog, ctx, "start", rest=None)
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ No Channel"

    spam.set_config(guild.id, _base_config(channel_id=TEXT_CHANNEL_ID))
    ctx = await _admin_ctx(bot, guild)
    await cog.spam.callback(cog, ctx, "start", rest=None)
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ No Target"


async def test_start_configured_creates_scoreboard(bot):
    cog = SpamGame(bot)
    guild = make_guild()
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)
    spam.set_config(guild.id, _base_config(channel_id=channel.id, word="lol"))

    cog.bot.get_channel = MagicMock(return_value=channel)
    channel.send = AsyncMock(return_value=MagicMock(id=55))

    ctx = await _admin_ctx(bot, guild)
    await cog.spam.callback(cog, ctx, "start", rest=None)
    cfg = spam.get_config(guild.id)
    assert cfg["enabled"] is True
    assert cfg["score_msg_id"] == 55
    channel.send.assert_awaited_once()
    assert ctx.send.await_args.kwargs["embed"].author.name == "🥀 Spam Chain Started"


async def test_status_shows_fields(bot):
    cog = SpamGame(bot)
    guild = make_guild()
    spam.set_config(guild.id, _base_config(streak=5, best_streak=10))
    member = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=member, guild=guild)
    await cog.spam.callback(cog, ctx)
    embed = ctx.send.await_args.kwargs["embed"]
    by_name = {f.name: f.value for f in embed.fields}
    assert by_name["Status"] == "❌ Stopped"
    assert by_name["Current Streak"] == "5"
    assert by_name["Best Streak"] == "10"


async def test_set_word_and_channel_admin_only(bot):
    cog = SpamGame(bot)
    guild = make_guild()
    member = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=member, guild=guild)
    await cog.spam.callback(cog, ctx, "word", rest="lol")
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Permission Denied"


async def test_set_word_persists(bot):
    cog = SpamGame(bot)
    guild = make_guild()
    ctx = await _admin_ctx(bot, guild)
    await cog.spam.callback(cog, ctx, "word", rest="  lol  ")
    cfg = spam.get_config(guild.id)
    assert cfg["word"] == "lol"
    assert ctx.send.await_args.kwargs["embed"].author.name == "✅ Target Set"


async def test_set_channel_invalid(bot):
    cog = SpamGame(bot)
    guild = make_guild()
    ctx = await _admin_ctx(bot, guild)
    ctx.guild.get_channel = MagicMock(return_value=None)
    await cog.spam.callback(cog, ctx, "channel", rest="#missing")
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Invalid Channel"


async def test_set_channel_persists(bot, monkeypatch):
    cog = SpamGame(bot)
    guild = make_guild()
    target = make_channel(4001, guild=guild)
    from discord.ext import commands as _commands
    monkeypatch.setattr(_commands.TextChannelConverter, "convert", AsyncMock(return_value=target))

    ctx = await _admin_ctx(bot, guild)
    await cog.spam.callback(cog, ctx, "channel", rest="#4001")
    cfg = spam.get_config(guild.id)
    assert cfg["channel_id"] == target.id
    assert ctx.send.await_args.kwargs["embed"].author.name == "✅ Channel Set"


async def test_stop_disables_game(bot):
    cog = SpamGame(bot)
    guild = make_guild()
    spam.set_config(guild.id, _base_config(enabled=True))
    ctx = await _admin_ctx(bot, guild)
    await cog.spam.callback(cog, ctx, "stop", rest=None)
    assert spam.get_config(guild.id)["enabled"] is False
    assert ctx.send.await_args.kwargs["embed"].author.name == "🛑 Spam Chain Stopped"


async def test_reset_clears_streak(bot):
    cog = SpamGame(bot)
    guild = make_guild()
    spam.set_config(guild.id, _base_config(enabled=True, streak=5, best_streak=9))
    ctx = await _admin_ctx(bot, guild)
    await cog.spam.callback(cog, ctx, "reset", rest=None)
    cfg = spam.get_config(guild.id)
    assert cfg["streak"] == 0
    assert cfg["best_streak"] == 0


async def test_invalid_action(bot):
    cog = SpamGame(bot)
    guild = make_guild()
    member = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=member, guild=guild)
    await cog.spam.callback(cog, ctx, "bogus", rest=None)
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Invalid Action"