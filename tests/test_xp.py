"""XP/SP command behavior tests (uses isolated SQLite via db_env)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import cogs.xp as xp
from cogs.xp import XP

from helpers import (
    GUILD_ID,
    TEXT_CHANNEL_ID,
    USER_IDS,
    make_channel,
    make_ctx,
    make_guild,
    make_member,
    make_message,
)


def _cog(bot):
    return XP(bot)


async def test_rank_sends_stats_embed(bot):
    cog = _cog(bot)
    data = xp.load_user(USER_IDS["member"])
    data["xp"] = 150
    data["sp"] = 40
    data["messages"] = 12
    xp.save_user(USER_IDS["member"], data)

    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.rank.callback(cog, ctx)

    embed = ctx.send.await_args.kwargs["embed"]
    names = {f.name for f in embed.fields}
    assert {"Level", "Total XP", "SP Balance", "VC Time"} <= names
    assert "📊 User7004's Stats" == embed.author.name


async def test_daily_claims_once_per_day(bot):
    cog = _cog(bot)
    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=author, guild=guild)

    await cog.daily.callback(cog, ctx)
    after_first = ctx.send.await_args.kwargs["embed"]
    assert after_first.author.name == "💰 Daily Claimed!"
    assert xp.load_user(USER_IDS["member"])["sp"] == 100
    assert xp.load_user(USER_IDS["member"])["streak"] == 1

    ctx.send.reset_mock()
    await cog.daily.callback(cog, ctx)
    embed = ctx.send.await_args.kwargs["embed"]
    assert embed.author.name == "❌ Already Claimed"
    assert xp.load_user(USER_IDS["member"])["sp"] == 100


async def test_daily_streak_bonus(bot):
    cog = _cog(bot)
    uid = USER_IDS["member"]
    data = xp.load_user(uid)
    data["streak"] = 5
    xp.save_user(uid, data)

    guild = make_guild()
    author = make_member(uid, guild=guild)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.daily.callback(cog, ctx)
    embed = ctx.send.await_args.kwargs["embed"]
    by_name = {f.name: f.value for f in embed.fields}
    assert by_name["🔥 Streak"] == "6 days"
    assert xp.load_user(uid)["sp"] == 100 + 50


async def test_give_to_self_rejected(bot):
    cog = _cog(bot)
    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.give.callback(cog, ctx, author, 50)
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Invalid"


async def test_give_to_bot_rejected(bot):
    cog = _cog(bot)
    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild)
    target = make_member(999_999, guild=guild, bot=True)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.give.callback(cog, ctx, target, 50)
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Invalid User"


async def test_give_insufficient_funds(bot):
    cog = _cog(bot)
    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild)
    target = make_member(USER_IDS["admin"], guild=guild)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.give.callback(cog, ctx, target, 50)
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Insufficient SP"


async def test_give_transfers_sp(bot):
    cog = _cog(bot)
    guild = make_guild()
    sender = make_member(USER_IDS["member"], guild=guild)
    receiver = make_member(USER_IDS["admin"], guild=guild)
    data = xp.load_user(sender.id)
    data["sp"] = 100
    xp.save_user(sender.id, data)
    data2 = xp.load_user(receiver.id)
    data2["sp"] = 5
    xp.save_user(receiver.id, data2)

    ctx = make_ctx(bot, author=sender, guild=guild)
    await cog.give.callback(cog, ctx, receiver, 30)
    assert ctx.send.await_args.kwargs["embed"].author.name == "💸 SP Transferred"
    assert xp.load_user(sender.id)["sp"] == 70
    assert xp.load_user(receiver.id)["sp"] == 35


async def test_bet_negative_amount_rejected(bot):
    cog = _cog(bot)
    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.bet.callback(cog, ctx, 0)
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Invalid Amount"


async def test_bet_win_and_loss(bot, monkeypatch):
    cog = _cog(bot)
    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild)
    data = xp.load_user(author.id)
    data["sp"] = 100
    xp.save_user(author.id, data)

    monkeypatch.setattr("cogs.xp.random.random", lambda: 0.1)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.bet.callback(cog, ctx, 40)
    assert ctx.send.await_args.kwargs["embed"].author.name == "🎉 You Won!"
    assert xp.load_user(author.id)["sp"] == 140

    monkeypatch.setattr("cogs.xp.random.random", lambda: 0.9)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.bet.callback(cog, ctx, 40)
    assert ctx.send.await_args.kwargs["embed"].author.name == "😢 You Lost!"
    assert xp.load_user(author.id)["sp"] == 100


async def test_work_grants_sp(bot):
    cog = _cog(bot)
    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.work.callback(cog, ctx)
    assert xp.load_user(author.id)["sp"] >= 50


# ── on_message listener ───────────────────────────────────────────────────────
async def test_on_message_awards_xp(bot):
    cog = _cog(bot)
    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild)
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)
    msg = make_message("hello", author=author, channel=channel, guild=guild)

    await cog.on_message(msg)
    xp.flush_all()
    assert xp.load_user(author.id)["xp"] >= 10
    assert xp.load_user(author.id)["messages"] == 1


async def test_on_message_respects_30s_gate(bot):
    cog = _cog(bot)
    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild)
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)

    await cog.on_message(make_message("hi", author=author, channel=channel, guild=guild))
    await cog.on_message(make_message("again", author=author, channel=channel, guild=guild))
    assert xp.load_user(author.id)["messages"] == 1


async def test_on_message_skipped_when_disabled(bot):
    cog = _cog(bot)
    guild = make_guild()
    xp.set_xp_enabled(guild.id, False)
    author = make_member(USER_IDS["member"], guild=guild)
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)
    msg = make_message("hi", author=author, channel=channel, guild=guild)

    await cog.on_message(msg)
    xp.flush_all()
    assert xp.load_user(author.id)["xp"] == 0


async def test_on_message_bot_ignored(bot):
    cog = _cog(bot)
    guild = make_guild()
    botmember = make_member(999_998, guild=guild, bot=True)
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)
    msg = make_message("hi", author=botmember, channel=channel, guild=guild)

    await cog.on_message(msg)
    xp.flush_all()
    assert xp.load_user(botmember.id)["xp"] == 0


async def test_on_message_level_up_sends_embed(bot):
    cog = _cog(bot)
    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild)
    channel = make_channel(TEXT_CHANNEL_ID, guild=guild)

    data = xp.load_user(author.id)
    data["xp"] = 90  # one message (>=10 XP) pushes to level 2
    xp.save_user(author.id, data)

    channel.send = AsyncMock()
    await cog.on_message(make_message("nudge", author=author, channel=channel, guild=guild))
    assert channel.send.await_args is not None
    embed = channel.send.await_args.kwargs["embed"]
    assert embed.title == "🎉 Level Up!"
    assert xp.load_user(author.id)["level"] == 2