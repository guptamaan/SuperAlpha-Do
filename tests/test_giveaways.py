"""Giveaway command and persistence tests."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from discord.ext import commands

import cogs.giveaways as giveaways
from cogs.giveaways import Giveaways, _fmt_duration, _parse_duration

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
)


# ── Pure helpers ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,seconds", [
    ("30s", 30), ("10m", 600), ("2h", 7200), ("1d", 86400), ("1w", 604800),
])
def test_parse_duration_valid(text, seconds):
    assert _parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "abc", "5", "5x", "0s", "31d", "  "])
def test_parse_duration_invalid(text):
    assert _parse_duration(text) is None


def test_fmt_duration():
    assert _fmt_duration(90) == "1m 30s"
    assert _fmt_duration(86400 + 3600) == "1d 1h"
    assert _fmt_duration(0) == "0s"


# ── Command flows ─────────────────────────────────────────────────────────────
@pytest.fixture
def gv_bot(bot):
    return bot


async def _admin_ctx(gv_bot, ctx_channel=None):
    guild = make_guild()
    admin = make_member(USER_IDS["admin"], guild=guild, permissions=make_permissions(administrator=True))
    channel = ctx_channel or make_channel(TEXT_CHANNEL_ID, guild=guild)
    return make_ctx(gv_bot, author=admin, guild=guild, channel=channel)


async def test_giveaway_list_regression_missing_entries_key(gv_bot, monkeypatch):
    """Giveaways created by the bot have no 'entries' key; listing must not crash."""
    cog = Giveaways(gv_bot)
    gw = {
        "guild_id": GUILD_ID,
        "channel_id": TEXT_CHANNEL_ID,
        "message_id": 42,
        "prize": "Nitro",
        "winners": 1,
        "host_id": USER_IDS["admin"],
        "end_ts": time.time() + 600,
    }
    cog._save({"1001:42": gw})

    guild = make_guild()
    member = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(gv_bot, author=member, guild=guild)
    await cog.giveaway.callback(cog, ctx)

    embed = ctx.send.call_args_list[-1].kwargs["embed"]
    assert embed.author.name == "🎉 Active Giveaways"
    assert "0 entries" in embed.description


async def test_giveaway_list_empty(gv_bot):
    cog = Giveaways(gv_bot)
    guild = make_guild()
    member = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(gv_bot, author=member, guild=guild)
    await cog.giveaway.callback(cog, ctx)
    embed = ctx.send.call_args_list[-1].kwargs["embed"]
    assert embed.description == "No active giveaways in this server."


async def test_giveaway_create_persists(gv_bot, monkeypatch):
    cog = Giveaways(gv_bot)
    target = make_channel(3005, guild=make_guild())  # separate channel for parse
    target.send = AsyncMock()
    async def _send(*_a, **_kw):
        msg = MagicMock(id=4242)
        msg.add_reaction = AsyncMock()
        return msg
    target.send.side_effect = _send
    monkeypatch.setattr(commands.TextChannelConverter, "convert", AsyncMock(return_value=target))

    ctx = await _admin_ctx(gv_bot)
    await cog.giveaway.callback(cog, ctx, "create", rest="#target 1h Nitro")

    saved = cog._load()
    assert len(saved) == 1
    record = next(iter(saved.values()))
    assert record["channel_id"] == target.id
    assert record["prize"] == "Nitro"
    assert record["winners"] == 1
    assert record["guild_id"] == GUILD_ID
    target.send.assert_awaited_once()
    assert ctx.send.await_args.kwargs["embed"].author.name == "🎉 Giveaway Started"

    # ends in the future and dials the winner count when provided
    assert target.send.await_args is not None


async def test_giveaway_create_requires_admin(gv_bot):
    cog = Giveaways(gv_bot)
    guild = make_guild()
    member = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(gv_bot, author=member, guild=guild)
    await cog.giveaway.callback(cog, ctx, "create", rest="#target 1h Nitro")
    embed = ctx.send.call_args_list[-1].kwargs["embed"]
    assert embed.author.name == "❌ Permission Denied"


async def test_giveaway_create_rejects_bad_duration(gv_bot, monkeypatch):
    cog = Giveaways(gv_bot)
    target = make_channel(3005, guild=make_guild())
    monkeypatch.setattr(commands.TextChannelConverter, "convert", AsyncMock(return_value=target))
    ctx = await _admin_ctx(gv_bot)
    await cog.giveaway.callback(cog, ctx, "create", rest="#target 5x prize")
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Invalid Duration"


async def test_giveaway_end_removes_record(gv_bot, monkeypatch):
    cog = Giveaways(gv_bot)
    gw = {
        "guild_id": GUILD_ID, "channel_id": TEXT_CHANNEL_ID, "message_id": 42,
        "prize": "Nitro", "winners": 1, "host_id": 1, "end_ts": time.time() + 600,
    }
    cog._save({"1001:42": gw})
    finishing = AsyncMock()
    monkeypatch.setattr(cog, "_finish_giveaway", finishing)

    ctx = await _admin_ctx(gv_bot)
    await cog.giveaway.callback(cog, ctx, "end", rest="42")
    assert "1001:42" not in cog._load()
    finishing.assert_awaited()


async def test_giveaway_cancel_removes_record(gv_bot):
    cog = Giveaways(gv_bot)
    gw = {
        "guild_id": GUILD_ID, "channel_id": TEXT_CHANNEL_ID, "message_id": 42,
        "prize": "Nitro", "winners": 1, "host_id": 1, "end_ts": time.time() + 600,
    }
    cog._save({"1001:42": gw})
    ctx = await _admin_ctx(gv_bot)
    await cog.giveaway.callback(cog, ctx, "cancel", rest="42")
    assert "1001:42" not in cog._load()
    assert ctx.send.await_args.kwargs["embed"].author.name == "🗑️ Cancelled"


async def test_giveaway_reroll_picks_winner_with_entries(gv_bot, monkeypatch):
    cog = Giveaways(gv_bot)
    winner = make_member(USER_IDS["member"], guild=make_guild())
    msg = make_message(embeds=[], author=winner, guild=make_guild())

    async def fake_entries(_message):
        return [winner], USER_IDS["admin"]

    monkeypatch.setattr(cog, "_get_entries", fake_entries)
    ctx = await _admin_ctx(gv_bot)
    ctx.channel.fetch_message = AsyncMock(return_value=msg)
    await cog.giveaway.callback(cog, ctx, "reroll", rest="9999")
    assert "**Reroll!**" in ctx.send.await_args.args[0]


async def test_giveaway_reroll_no_entries(gv_bot):
    cog = Giveaways(gv_bot)
    msg = make_message(embeds=[])
    ctx = await _admin_ctx(gv_bot)
    ctx.channel.fetch_message = AsyncMock(return_value=msg)
    await cog.giveaway.callback(cog, ctx, "reroll", rest="9999")
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ No Entries"


# ── Sweep ─────────────────────────────────────────────────────────────────────
async def test_sweep_finishes_and_removes_expired(gv_bot, monkeypatch):
    cog = Giveaways(gv_bot)
    expired = {
        "guild_id": GUILD_ID, "channel_id": TEXT_CHANNEL_ID, "message_id": 42,
        "prize": "Nitro", "winners": 1, "host_id": 1, "end_ts": time.time() - 1,
    }
    not_expired = dict(expired)
    not_expired["message_id"] = 43
    not_expired["end_ts"] = time.time() + 9999
    not_expired["prize"] = "Future"
    cog._save({"1001:42": expired, "1001:43": not_expired})

    finished = AsyncMock()
    monkeypatch.setattr(cog, "_finish_giveaway", finished)
    monkeypatch.setattr(giveaways, "SWEEP_INTERVAL", 3600)

    task = asyncio.create_task(cog._sweep())
    await asyncio.sleep(0.05)
    task.cancel()

    finished.assert_awaited_once()
    remaining = cog._load()
    assert "1001:42" not in remaining
    assert "1001:43" in remaining


async def test_finish_giveaway_no_channel_is_safe(gv_bot):
    cog = Giveaways(gv_bot)
    gw = {"channel_id": 999999, "message_id": 1, "winners": 1, "prize": "x"}
    await cog._finish_giveaway(gw, {})  # bot.get_channel returns None -> no crash