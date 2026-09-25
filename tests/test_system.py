"""System commands: constants, ping, latency, invite, reload, shutdown."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from discord.ext import commands

from cogs.system import INVITE_URL, OWNER_HANDLE, SUPPORT_SERVER, System

from helpers import USER_IDS, make_ctx, make_guild, make_member


def test_info_constants():
    assert INVITE_URL.startswith("https://discord.com/oauth2/authorize?client_id=")
    assert SUPPORT_SERVER.startswith("https://discord.gg/")
    assert OWNER_HANDLE.startswith("@")
    assert OWNER_HANDLE == "@r4ve_x"


def test_ws_ms_zero_with_no_latency(bot):
    cog = System(bot)
    bot.ws.latency = 0.0
    assert cog._ws_ms() == 0
    bot.ws.latency = 0.35
    assert cog._ws_ms() == 350


async def test_ping_edits_message(bot):
    cog = System(bot)
    sent = MagicMock()
    sent.edit = AsyncMock()
    ctx = make_ctx(bot)
    ctx.send = AsyncMock(return_value=sent)
    await cog.ping.callback(cog, ctx)

    assert "Pinging" in ctx.send.call_args_list[0].args[0]
    sent.edit.assert_awaited_once()
    content = sent.edit.await_args.kwargs["content"]
    assert "ws=0 ms" in content
    assert "rtt=" in content


async def test_latency_quality(bot):
    cog = System(bot)
    bot.ws.latency = 0.05
    ctx = make_ctx(bot)
    await cog.latency.callback(cog, ctx)
    assert "excellent" in ctx.send.await_args.args[0]

    bot.ws.latency = 1.0
    ctx2 = make_ctx(bot)
    await cog.latency.callback(cog, ctx2)
    assert "poor" in ctx2.send.await_args.args[0]


async def test_uptime_formats(bot):
    cog = System(bot)
    ctx = make_ctx(bot)
    await cog.uptime.callback(cog, ctx)
    assert " up " in ctx.send.await_args.args[0]


async def test_invite_embed_has_urls(bot):
    cog = System(bot)
    ctx = make_ctx(bot)
    await cog.invite.callback(cog, ctx)
    embed = ctx.send.await_args.kwargs["embed"]
    assert INVITE_URL in embed.description
    by_name = {f.name: f.value for f in embed.fields}
    assert "⚠️ Registration required" in by_name
    assert OWNER_HANDLE in by_name["⚠️ Registration required"]


async def test_reload_owner_only(bot):
    cog = System(bot)
    bot.reload_extension = AsyncMock()

    guild = make_guild()
    member = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=member, guild=guild)
    with pytest.raises(commands.NotOwner):
        await cog.reload.can_run(ctx)

    owner = make_member(USER_IDS["owner"], guild=guild)
    ctx_owner = make_ctx(bot, author=owner, guild=guild)
    await cog.reload.can_run(ctx_owner)
    await cog.reload.callback(cog, ctx_owner, "utility")
    assert "reloaded successfully" in ctx_owner.send.await_args.args[0]


async def test_shutdown_owner_only(bot):
    cog = System(bot)
    bot.close = AsyncMock()
    guild = make_guild()

    member = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=member, guild=guild)
    with pytest.raises(commands.NotOwner):
        await cog.shutdown.can_run(ctx)
    bot.close.assert_not_awaited()

    owner = make_member(USER_IDS["owner"], guild=guild)
    ctx_owner = make_ctx(bot, author=owner, guild=guild)
    await cog.shutdown.can_run(ctx_owner)
    await cog.shutdown.callback(cog, ctx_owner)
    assert "shutdown now" in ctx_owner.send.await_args.args[0]
    bot.close.assert_awaited_once()


async def test_unloadcog_protects_system(bot):
    cog = System(bot)
    ctx = make_ctx(bot)
    bot.unload_extension = AsyncMock()
    await cog.unloadcog.callback(cog, ctx, "system")
    assert "cannot unload system cog" in ctx.send.await_args.args[0]
    bot.unload_extension.assert_not_awaited()