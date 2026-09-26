"""System commands: constants, ping, latency, invite, reload, shutdown."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from discord.ext import commands

from bot.cogs.system import INVITE_URL, OWNER_HANDLE, SUPPORT_SERVER, System

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


ISSUE_PAYLOAD = {
    "number": 42,
    "title": "Fix the thing",
    "state": "open",
    "body": "The thing is broken.",
    "user": {"login": "tester"},
    "labels": [{"name": "bug"}, {"name": "good first issue"}],
    "comments": 3,
    "created_at": "2026-01-02T03:04:05Z",
    "html_url": "https://github.com/guptamaan/SuperAlpha-Do/issues/42",
}

PR_PAYLOAD = {
    **ISSUE_PAYLOAD,
    "merged": False,
    "merged_at": None,
    "mergeable": True,
    "commits": 5,
    "additions": 120,
    "deletions": 30,
    "changed_files": 4,
    "base": {"ref": "main"},
    "head": {"ref": "feature/x"},
    "html_url": "https://github.com/guptamaan/SuperAlpha-Do/pull/42",
}


async def test_issue_shows_embed(bot, monkeypatch):
    cog = System(bot)
    monkeypatch.setattr("bot.cogs.system._gh_issue", AsyncMock(return_value=ISSUE_PAYLOAD))
    ctx = make_ctx(bot)
    await cog.issue.callback(cog, ctx, 42)
    embed = ctx.send.await_args.kwargs["embed"]
    assert "42" in embed.title and "Fix the thing" in embed.title
    by_name = {f.name: f.value for f in embed.fields}
    assert by_name["State"] == "Open"
    assert "`bug`" in by_name["Labels"]
    assert by_name["Comments"] == "3"
    assert embed.url == ISSUE_PAYLOAD["html_url"]


async def test_pr_shows_merge_info(bot, monkeypatch):
    cog = System(bot)
    monkeypatch.setattr("bot.cogs.system._gh_pr", AsyncMock(return_value=PR_PAYLOAD))
    ctx = make_ctx(bot)
    await cog.pr.callback(cog, ctx, 42)
    embed = ctx.send.await_args.kwargs["embed"]
    assert "🟢 open" in embed.title
    by_name = {f.name: f.value for f in embed.fields}
    assert by_name["Base → Head"] == "`main` → `feature/x`"
    assert "+120 −30" in by_name["Merge"]


async def test_issue_missing_payload(bot, monkeypatch):
    cog = System(bot)
    monkeypatch.setattr("bot.cogs.system._gh_issue", AsyncMock(return_value=None))
    ctx = make_ctx(bot)
    await cog.issue.callback(cog, ctx, 9999)
    assert "Resource not found or GitHub unreachable" in ctx.send.await_args.args[0]