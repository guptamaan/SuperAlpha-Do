"""Permission and authorization tests.

Covers the shared ``perms_or_developer`` gate plus the inline permission
checks used by shop, giveaways, spam, distro, tempvc, and the Linux toggles.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands

import bot.cogs.checks as checks
import bot.cogs.linux as linux_cog
import bot.cogs.steal as steal_cog
import bot.cogs.system as system_cog
import bot.cogs.tempvc as tempvc_cog
import bot.cogs.xp as xp_cog
from bot.cogs.shop import Shop
from discord.ext.commands import CommandError

from helpers import (
    USER_IDS,
    make_channel,
    make_ctx,
    make_guild,
    make_member,
    make_permissions,
    make_role,
)

from conftest import register_cog


# ── perms_or_developer gate on a synthetic command ────────────────────────────
class _Gated(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="gated")
    @checks.perms_or_developer(administrator=True)
    async def gated(self, ctx):
        await ctx.send("ok")


async def test_perm_admin_allowed(bot):
    register_cog(_Gated(bot))
    cmd = bot.get_command("gated")
    guild = make_guild()
    author = make_member(USER_IDS["admin"], guild=guild, permissions=make_permissions(administrator=True))
    ctx = make_ctx(bot, author=author, guild=guild, command=cmd)
    assert await cmd.can_run(ctx) is True


async def test_perm_plain_member_denied(bot):
    register_cog(_Gated(bot))
    cmd = bot.get_command("gated")
    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild, permissions=make_permissions())
    ctx = make_ctx(bot, author=author, guild=guild, command=cmd)
    with pytest.raises(commands.CheckAnyFailure):
        await cmd.can_run(ctx)


async def test_perm_bot_owner_allowed_without_perms(bot):
    register_cog(_Gated(bot))
    cmd = bot.get_command("gated")
    guild = make_guild()
    author = make_member(USER_IDS["owner"], guild=guild, permissions=make_permissions())
    ctx = make_ctx(bot, author=author, guild=guild, command=cmd)
    assert await cmd.can_run(ctx) is True


async def test_checks_composition_is_check_any():
    """perms_or_developer must be bot-owner OR guild-permission based."""
    gate = checks.perms_or_developer(administrator=True)

    async def stub(ctx):
        return None

    wrapped = gate(stub)
    assert len(wrapped.__commands_checks__) >= 1


# ── XP admin commands ─────────────────────────────────────────────────────────
@pytest.fixture
def xp_bot(bot):
    register_cog(xp_cog.XP(bot))
    return bot


async def test_xp_xpsystem_admin(xp_bot):
    cmd = xp_bot.get_command("xpsystem")
    guild = make_guild()
    author = make_member(USER_IDS["admin"], guild=guild, permissions=make_permissions(administrator=True))
    ctx = make_ctx(xp_bot, author=author, guild=guild, command=cmd)
    assert await cmd.can_run(ctx) is True


async def test_xp_xpsystem_denied_for_member(xp_bot):
    cmd = xp_bot.get_command("xpsystem")
    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(xp_bot, author=author, guild=guild, command=cmd)
    with pytest.raises(commands.CheckAnyFailure):
        await cmd.can_run(ctx)


async def test_xp_addxp_owner_only(xp_bot):
    cmd = xp_bot.get_command("addxp")
    guild = make_guild()
    owner = make_member(USER_IDS["owner"], guild=guild, permissions=make_permissions(administrator=True))
    admin = make_member(USER_IDS["admin"], guild=guild, permissions=make_permissions(administrator=True))
    assert await cmd.can_run(make_ctx(xp_bot, author=owner, guild=guild, command=cmd)) is True
    with pytest.raises(commands.NotOwner):
        await cmd.can_run(make_ctx(xp_bot, author=admin, guild=guild, command=cmd))


# ── Linux enable / disable now require administrator ──────────────────────────
@pytest.fixture
def linux_bot(bot):
    register_cog(linux_cog.Linux(bot))
    return bot


@pytest.mark.parametrize("cmd_name", ["enable", "disable"])
async def test_linux_toggle_admins_only(linux_bot, cmd_name):
    cmd = linux_bot.get_command(cmd_name)
    guild = make_guild()
    admin = make_member(USER_IDS["admin"], guild=guild, permissions=make_permissions(administrator=True))
    member = make_member(USER_IDS["member"], guild=guild)
    assert await cmd.can_run(make_ctx(linux_bot, author=admin, guild=guild, command=cmd)) is True
    with pytest.raises(commands.CheckAnyFailure):
        await cmd.can_run(make_ctx(linux_bot, author=member, guild=guild, command=cmd))


# ── Steal requires manage_expressions ─────────────────────────────────────────
@pytest.fixture
def steal_bot(bot):
    register_cog(steal_cog.Steal(bot))
    return bot


async def test_steal_permission(steal_bot):
    cmd = steal_bot.get_command("steal")
    guild = make_guild()
    with_mod = make_member(
        USER_IDS["member"], guild=guild,
        permissions=make_permissions(manage_expressions=True),
    )
    without = make_member(USER_IDS["admin"], guild=guild, permissions=make_permissions(administrator=True))
    assert await cmd.can_run(make_ctx(steal_bot, author=with_mod, guild=guild, command=cmd)) is True
    with pytest.raises(commands.CheckAnyFailure):
        await cmd.can_run(make_ctx(steal_bot, author=without, guild=guild, command=cmd))


# ── System owner-only command ─────────────────────────────────────────────────
async def test_system_reload_owner_only(bot):
    register_cog(system_cog.System(bot))
    cmd = bot.get_command("reload")
    guild = make_guild()
    member = make_member(USER_IDS["member"], guild=guild)
    owner = make_member(USER_IDS["owner"], guild=guild)
    assert await cmd.can_run(make_ctx(bot, author=owner, guild=guild, command=cmd)) is True
    with pytest.raises(commands.NotOwner):
        await cmd.can_run(make_ctx(bot, author=member, guild=guild, command=cmd))


# ── Shop admin gating (inline check) ──────────────────────────────────────────
async def test_shop_add_requires_admin(bot):
    cog = Shop(bot)
    guild = make_guild()
    member = make_member(USER_IDS["member"], guild=guild)
    admin = make_member(USER_IDS["admin"], guild=guild, permissions=make_permissions(administrator=True))
    ctx_member, ctx_admin = make_ctx(bot, author=member, guild=guild), make_ctx(bot, author=admin, guild=guild)

    await cog._add(ctx_member, "50 cool hat")
    embed = ctx_member.send.call_args_list[-1].kwargs["embed"]
    assert embed.author.name == "❌ Permission Denied"

    await cog._add(ctx_admin, "50 cool hat")
    embed = ctx_admin.send.call_args_list[-1].kwargs["embed"]
    assert embed.author.name == "✅ Item Added"


# ── Spam admin gating (inline check) ──────────────────────────────────────────
async def test_spam_admin_ok_paths(bot):
    cog = __import__("bot.cogs.spam", fromlist=["SpamGame"]).SpamGame(bot)
    guild = make_guild()
    admin = make_member(USER_IDS["admin"], guild=guild, permissions=make_permissions(administrator=True))
    member = make_member(USER_IDS["member"], guild=guild)
    guild_owner = make_member(USER_IDS["guild_owner"], guild=guild, permissions=make_permissions())
    bot_owner = make_member(USER_IDS["owner"], guild=guild, permissions=make_permissions())

    assert await cog._admin_ok(make_ctx(bot, author=admin, guild=guild)) is True
    assert await cog._admin_ok(make_ctx(bot, author=guild_owner, guild=guild)) is True
    assert await cog._admin_ok(make_ctx(bot, author=bot_owner, guild=guild)) is True

    ctx = make_ctx(bot, author=member, guild=guild)
    assert await cog._admin_ok(ctx) is False
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Permission Denied"


# ── TempVC ownership model ────────────────────────────────────────────────────
async def test_tempvc_owner_can_manage(bot):
    cog = tempvc_cog.TempVCManager(bot)
    guild = make_guild()
    voice = make_channel(3001, guild=guild, name="temp")
    cog._vcs[voice.id] = tempvc_cog.TempVC(voice.id, USER_IDS["member"], "temp")
    author = make_member(USER_IDS["member"], guild=guild, voice_channel=voice)
    ctx = make_ctx(bot, author=author, guild=guild, channel=voice)
    await cog.vc.callback(cog, ctx, "name", value="cool name")
    voice.edit.assert_awaited_once()
    assert ctx.send.await_args.kwargs["embed"].author.name == "✏️ Renamed"


async def test_tempvc_non_owner_denied(bot):
    cog = tempvc_cog.TempVCManager(bot)
    guild = make_guild()
    voice = make_channel(3001, guild=guild, name="temp")
    cog._vcs[voice.id] = tempvc_cog.TempVC(voice.id, USER_IDS["admin"], "temp")
    author = make_member(USER_IDS["member"], guild=guild, voice_channel=voice)
    ctx = make_ctx(bot, author=author, guild=guild, channel=voice)
    await cog.vc.callback(cog, ctx, "name", value="hijack")
    assert voice.edit.await_count == 0
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Not Owner"


async def test_tempvc_vanilla_channel_management_denied(bot):
    """Regression: actions on a non-temp channel must be rejected, not allowed."""
    cog = tempvc_cog.TempVCManager(bot)
    guild = make_guild()
    voice = make_channel(3001, guild=guild, name="team-general")
    author = make_member(USER_IDS["member"], guild=guild, voice_channel=voice)
    for action, value in [
        ("name", "renamed"),
        ("limit", "5"),
        ("lock", None),
        ("kick", "<@7004>"),
        ("ban", "<@7004>"),
        ("unban", "<@7004>"),
    ]:
        fresh = make_ctx(bot, author=author, guild=guild, channel=voice)
        await cog.vc.callback(cog, fresh, action, value=value)
        assert fresh.send.await_args.kwargs["embed"].author.name == "❌ Not a Temp VC", action
        assert voice.edit.await_count == 0 and voice.set_permissions.await_count == 0, action


async def test_tempvc_claim_still_works_for_vanilla_channel(bot):
    cog = tempvc_cog.TempVCManager(bot)
    guild = make_guild()
    voice = make_channel(3001, guild=guild, name="lonely")
    voice.members = [make_member(USER_IDS["member"], guild=guild, voice_channel=voice)]
    author = voice.members[0]
    ctx = make_ctx(bot, author=author, guild=guild, channel=voice)
    await cog.vc.callback(cog, ctx, "claim", value=None)
    assert ctx.send.await_args.kwargs["embed"].author.name == "✅ Claimed"
    assert voice.id in cog._vcs
    assert cog._vcs[voice.id].owner_id == author.id