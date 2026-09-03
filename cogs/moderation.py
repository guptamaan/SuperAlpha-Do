"""
cogs/moderation.py — Moderation commands.
Commands: kick, ban, unban, mute, unmute, purge, warn, warnings, clearwarns,
          slowmode, lock, unlock, nickname, softban, massban, voicekick,
          voicemove, deafen, undeafen, strip, addrole, removerole
"""

import asyncio
import datetime
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands

from cogs.checks import perms_or_developer


_warnings: dict[int, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))


class Moderation(commands.Cog, name="moderation"):
    """Server moderation commands (kick, ban, mute, purge, warn …)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title, icon_url=None)
        if description:
            embed.description = description
        return embed

    # ── kick ──────────────────────────────────────────────────────────────────
    @commands.command(name="kick", aliases=["pkill"])
    @perms_or_developer(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided") -> None:
        """Kick a member. Usage: sudo kick <@user> [reason]"""
        await member.kick(reason=f"{ctx.author} — {reason}")
        embed = self._make_embed("👢 Member Kicked", 0xE74C3C)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── ban ───────────────────────────────────────────────────────────────────
    @commands.command(name="ban")
    @perms_or_developer(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided") -> None:
        """Ban a member. Usage: sudo ban <@user> [reason]"""
        await member.ban(reason=f"{ctx.author} — {reason}", delete_message_days=0)
        embed = self._make_embed("🔨 Member Banned", 0xC0392B)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── softban ───────────────────────────────────────────────────────────────
    @commands.command(name="softban")
    @perms_or_developer(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def softban(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided") -> None:
        """Ban then immediately unban (clears messages). Usage: sudo softban <@user> [reason]"""
        await member.ban(reason=f"Softban by {ctx.author} — {reason}", delete_message_days=7)
        await ctx.guild.unban(member, reason="Softban unban")
        embed = self._make_embed("💨 Softban Executed", 0xE67E22)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Messages Purged", value="7 days", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── massban ───────────────────────────────────────────────────────────────
    @commands.command(name="massban")
    @perms_or_developer(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def massban(self, ctx: commands.Context, members: commands.Greedy[discord.Member], *, reason: str = "Mass ban") -> None:
        """Ban multiple members at once. Usage: sudo massban <@user1> <@user2> ... [reason]"""
        if not members:
            embed = self._make_embed("🔨 Mass Ban Error", 0xE74C3C, "❌ No valid members specified")
            await ctx.send(embed=embed)
            return
        banned = []
        for member in members:
            try:
                await member.ban(reason=f"{ctx.author} — {reason}", delete_message_days=0)
                banned.append(str(member))
            except discord.HTTPException:
                pass
        embed = self._make_embed("🔨 Mass Ban Complete", 0xC0392B)
        embed.add_field(name="Banned", value=f"**{len(banned)}** member(s)", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        if banned:
            embed.add_field(name="Users", value=", ".join(banned[:10]), inline=False)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── unban ─────────────────────────────────────────────────────────────────
    @commands.command(name="unban")
    @perms_or_developer(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx: commands.Context, *, user_tag: str) -> None:
        """Unban a user by tag. Usage: sudo unban <user#0000>"""
        banned = [entry async for entry in ctx.guild.bans()]
        for entry in banned:
            if str(entry.user) == user_tag:
                await ctx.guild.unban(entry.user)
                embed = self._make_embed("✅ Member Unbanned", 0x2ECC71)
                embed.add_field(name="User", value=str(entry.user), inline=True)
                embed.set_footer(text=f"By {ctx.author}")
                await ctx.send(embed=embed)
                return
        embed = self._make_embed("❌ Unban Failed", 0xE74C3C, f"User `{user_tag}` not found in ban list")
        await ctx.send(embed=embed)

    # ── mute (timeout) ────────────────────────────────────────────────────────
    @commands.command(name="mute", aliases=["timeout", "vlock"])
    @perms_or_developer(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def mute(self, ctx: commands.Context, member: discord.Member, minutes: int = 10, *, reason: str = "No reason provided") -> None:
        """Timeout a member. Usage: sudo mute <@user> [minutes] [reason]"""
        until = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
        await member.timeout(until, reason=f"{ctx.author} — {reason}")
        embed = self._make_embed("🔇 Member Muted", 0x95A5A6)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Duration", value=f"**{minutes}** minute(s)", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── unmute ────────────────────────────────────────────────────────────────
    @commands.command(name="unmute", aliases=["untimeout"])
    @perms_or_developer(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def unmute(self, ctx: commands.Context, member: discord.Member) -> None:
        """Remove timeout from a member. Usage: sudo unmute <@user>"""
        await member.timeout(None)
        embed = self._make_embed("🔊 Member Unmuted", 0x2ECC71)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── voicekick ─────────────────────────────────────────────────────────────
    @commands.command(name="voicekick", aliases=["vkick"])
    @perms_or_developer(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def voicekick(self, ctx: commands.Context, member: discord.Member) -> None:
        """Kick a member from their voice channel. Usage: sudo voicekick <@user>"""
        if not member.voice or not member.voice.channel:
            embed = self._make_embed("❌ Voicekick Failed", 0xE74C3C, f"{member} is not in a voice channel")
            await ctx.send(embed=embed)
            return
        await member.move_to(None)
        embed = self._make_embed("🔊 Voice Disconnected", 0x3498DB)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── voicemove ─────────────────────────────────────────────────────────────
    @commands.command(name="voicemove", aliases=["vmove"])
    @perms_or_developer(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def voicemove(self, ctx: commands.Context, member: discord.Member, channel: discord.VoiceChannel) -> None:
        """Move a member to a voice channel. Usage: sudo voicemove <@user> <channel>"""
        if not member.voice:
            embed = self._make_embed("❌ Move Failed", 0xE74C3C, f"{member} is not in a voice channel")
            await ctx.send(embed=embed)
            return
        await member.move_to(channel)
        embed = self._make_embed("🔊 Voice Moved", 0x3498DB)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Channel", value=channel.name, inline=True)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── deafen ────────────────────────────────────────────────────────────────
    @commands.command(name="deafen")
    @perms_or_developer(deafen_members=True)
    @commands.bot_has_permissions(deafen_members=True)
    async def deafen(self, ctx: commands.Context, member: discord.Member) -> None:
        """Server-deafen a member. Usage: sudo deafen <@user>"""
        if not member.voice:
            embed = self._make_embed("❌ Deafen Failed", 0xE74C3C, f"{member} is not in a voice channel")
            await ctx.send(embed=embed)
            return
        await member.edit(deafen=True)
        embed = self._make_embed("🔇 Member Deafen", 0x95A5A6)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── undeafen ──────────────────────────────────────────────────────────────
    @commands.command(name="undeafen")
    @perms_or_developer(deafen_members=True)
    @commands.bot_has_permissions(deafen_members=True)
    async def undeafen(self, ctx: commands.Context, member: discord.Member) -> None:
        """Remove server-deafen from a member. Usage: sudo undeafen <@user>"""
        if not member.voice:
            embed = self._make_embed("❌ Undeafen Failed", 0xE74C3C, f"{member} is not in a voice channel")
            await ctx.send(embed=embed)
            return
        await member.edit(deafen=False)
        embed = self._make_embed("🔊 Member Undeafen", 0x2ECC71)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── addrole ───────────────────────────────────────────────────────────────
    @commands.command(name="addrole", aliases=["roleadd"])
    @perms_or_developer(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def addrole(self, ctx: commands.Context, member: discord.Member, *, role: discord.Role) -> None:
        """Add a role to a member. Usage: sudo addrole <@user> <role>"""
        if role >= ctx.guild.me.top_role:
            embed = self._make_embed("❌ Add Role Failed", 0xE74C3C, "Role is above bot's highest role")
            await ctx.send(embed=embed)
            return
        await member.add_roles(role, reason=f"addrole by {ctx.author}")
        embed = self._make_embed("✅ Role Added", 0x2ECC71)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Role", value=role.mention, inline=True)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── removerole ────────────────────────────────────────────────────────────
    @commands.command(name="removerole", aliases=["roledel"])
    @perms_or_developer(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def removerole(self, ctx: commands.Context, member: discord.Member, *, role: discord.Role) -> None:
        """Remove a role from a member. Usage: sudo removerole <@user> <role>"""
        if role >= ctx.guild.me.top_role:
            embed = self._make_embed("❌ Remove Role Failed", 0xE74C3C, "Role is above bot's highest role")
            await ctx.send(embed=embed)
            return
        await member.remove_roles(role, reason=f"removerole by {ctx.author}")
        embed = self._make_embed("✅ Role Removed", 0xE67E22)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Role", value=role.mention, inline=True)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── strip ────────────────────────────────────────────────────────────────
    @commands.command(name="strip")
    @perms_or_developer(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def strip(self, ctx: commands.Context, member: discord.Member) -> None:
        """Remove all removable roles from a member. Usage: sudo strip <@user>"""
        roles_to_remove = [
            r for r in member.roles
            if r != ctx.guild.default_role and r < ctx.guild.me.top_role
        ]
        if not roles_to_remove:
            embed = self._make_embed("❌ Strip Failed", 0xE74C3C, f"No removable roles found for {member}")
            await ctx.send(embed=embed)
            return
        await member.remove_roles(*roles_to_remove, reason=f"strip by {ctx.author}")
        embed = self._make_embed("🧹 Roles Stripped", 0xE67E22)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Removed", value=f"**{len(roles_to_remove)}** role(s)", inline=True)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── purge ─────────────────────────────────────────────────────────────────
    @commands.command(name="purge", aliases=["clear", "rm", "delete"])
    @perms_or_developer(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purge(self, ctx: commands.Context, amount: int) -> None:
        """Delete messages. Usage: sudo purge <amount>"""
        if not 1 <= amount <= 500:
            embed = self._make_embed("❌ Purge Failed", 0xE74C3C, "Amount must be between 1 and 500")
            await ctx.send(embed=embed)
            return
        deleted = await ctx.channel.purge(limit=amount + 1)
        embed = self._make_embed("🗑️ Messages Purged", 0x95A5A6)
        embed.add_field(name="Deleted", value=f"**{len(deleted) - 1}** message(s)", inline=True)
        embed.set_footer(text=f"By {ctx.author}")
        msg = await ctx.send(embed=embed)
        await asyncio.sleep(4)
        await msg.delete()

    # ── warn ──────────────────────────────────────────────────────────────────
    @commands.command(name="warn")
    @perms_or_developer(manage_messages=True)
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided") -> None:
        """Warn a member. Usage: sudo warn <@user> [reason]"""
        _warnings[ctx.guild.id][member.id].append(reason)
        count = len(_warnings[ctx.guild.id][member.id])
        embed = self._make_embed("⚠️ Warning Issued", 0xF39C12)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Warning #", value=f"**{count}**", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)
        try:
            await member.send(
                f"⚠️ You have been warned in **{ctx.guild.name}**.\n"
                f"Reason: {reason}\nTotal warnings: {count}"
            )
        except discord.Forbidden:
            pass

    # ── warnings ──────────────────────────────────────────────────────────────
    @commands.command(name="warnings", aliases=["warns"])
    @perms_or_developer(manage_messages=True)
    async def warnings(self, ctx: commands.Context, member: discord.Member) -> None:
        """List warnings for a member. Usage: sudo warnings <@user>"""
        warns = _warnings[ctx.guild.id][member.id]
        if not warns:
            embed = self._make_embed(f"Warnings for {member}", 0x2ECC71, "✅ No warnings found")
            await ctx.send(embed=embed)
            return
        lines = "\n".join(f"`[{i+1}]` {r}" for i, r in enumerate(warns))
        embed = self._make_embed(f"⚠️ Warnings for {member}", 0xF39C12)
        embed.add_field(name="Total Warnings", value=f"**{len(warns)}**", inline=True)
        embed.add_field(name="Warnings", value=lines, inline=False)
        await ctx.send(embed=embed)

    # ── clearwarns ────────────────────────────────────────────────────────────
    @commands.command(name="clearwarns")
    @perms_or_developer(manage_guild=True)
    async def clearwarns(self, ctx: commands.Context, member: discord.Member) -> None:
        """Clear all warnings for a member. Usage: sudo clearwarns <@user>"""
        _warnings[ctx.guild.id][member.id].clear()
        embed = self._make_embed("✅ Warnings Cleared", 0x2ECC71)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── slowmode ──────────────────────────────────────────────────────────────
    @commands.command(name="slowmode")
    @perms_or_developer(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def slowmode(self, ctx: commands.Context, seconds: int = 0) -> None:
        """Set channel slowmode. Usage: sudo slowmode [seconds]"""
        if not 0 <= seconds <= 21600:
            embed = self._make_embed("❌ Slowmode Failed", 0xE74C3C, "Value must be 0–21600 seconds")
            await ctx.send(embed=embed)
            return
        await ctx.channel.edit(slowmode_delay=seconds)
        embed = self._make_embed("🐌 Slowmode Set", 0x3498DB)
        embed.add_field(name="Channel", value=ctx.channel.mention, inline=True)
        embed.add_field(name="Delay", value=f"**{seconds}** seconds", inline=True)
        if seconds == 0:
            embed.description = "Slowmode **disabled**"
        await ctx.send(embed=embed)

    # ── lock ──────────────────────────────────────────────────────────────────
    @commands.command(name="lock", aliases=["chattr"])
    @perms_or_developer(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lock(self, ctx: commands.Context) -> None:
        """Lock the current channel. Usage: sudo lock"""
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        embed = self._make_embed("🔒 Channel Locked", 0xE74C3C)
        embed.add_field(name="Channel", value=ctx.channel.mention, inline=True)
        embed.description = "@everyone **cannot** send messages"
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── unlock ────────────────────────────────────────────────────────────────
    @commands.command(name="unlock")
    @perms_or_developer(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context) -> None:
        """Unlock the current channel. Usage: sudo unlock"""
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        embed = self._make_embed("🔓 Channel Unlocked", 0x2ECC71)
        embed.add_field(name="Channel", value=ctx.channel.mention, inline=True)
        embed.description = "@everyone **can** send messages"
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── nickname ──────────────────────────────────────────────────────────────
    @commands.command(name="nickname", aliases=["nick", "usermod"])
    @perms_or_developer(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def nickname(self, ctx: commands.Context, member: discord.Member, *, name: str | None = None) -> None:
        """Change or reset a member's nickname. Usage: sudo nickname <@user> [name]"""
        await member.edit(nick=name)
        embed = self._make_embed("📛 Nickname Updated", 0x9B59B6)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="New Nickname", value=name or "*None*", inline=True)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── Slash Commands ────────────────────────────────────────────────────────
    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.describe(member="The member to kick", reason="Reason for kick")
    @app_commands.default_permissions(kick_members=True)
    async def slash_kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
        """Slash command version of kick."""
        await member.kick(reason=f"{interaction.user} — {reason}")
        embed = self._make_embed("👢 Member Kicked", 0xE74C3C)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.describe(member="The member to ban", reason="Reason for ban")
    @app_commands.default_permissions(ban_members=True)
    async def slash_ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
        """Slash command version of ban."""
        await member.ban(reason=f"{interaction.user} — {reason}", delete_message_days=0)
        embed = self._make_embed("🔨 Member Banned", 0xC0392B)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mute", description="Timeout a member")
    @app_commands.describe(member="The member to mute", minutes="Duration in minutes", reason="Reason for mute")
    @app_commands.default_permissions(moderate_members=True)
    async def slash_mute(self, interaction: discord.Interaction, member: discord.Member, minutes: int = 10, reason: str = "No reason provided") -> None:
        """Slash command version of mute."""
        until = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
        await member.timeout(until, reason=f"{interaction.user} — {reason}")
        embed = self._make_embed("🔇 Member Muted", 0x95A5A6)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Duration", value=f"**{minutes}** minute(s)", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unmute", description="Remove timeout from a member")
    @app_commands.describe(member="The member to unmute")
    @app_commands.default_permissions(moderate_members=True)
    async def slash_unmute(self, interaction: discord.Interaction, member: discord.Member) -> None:
        """Slash command version of unmute."""
        await member.timeout(None)
        embed = self._make_embed("🔊 Member Unmuted", 0x2ECC71)
        embed.add_field(name="User", value=member.mention, inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="purge", description="Delete messages in the channel")
    @app_commands.describe(amount="Number of messages to delete (1-500)")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_purge(self, interaction: discord.Interaction, amount: int) -> None:
        """Slash command version of purge."""
        if not 1 <= amount <= 500:
            await interaction.response.send_message("Amount must be between 1 and 500.")
            return
        deleted = await interaction.channel.purge(limit=amount)
        embed = self._make_embed("🗑️ Messages Purged", 0x95A5A6)
        embed.add_field(name="Deleted", value=f"**{len(deleted)}** message(s)", inline=True)
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(4)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass

    @app_commands.command(name="slowmode", description="Set channel slowmode")
    @app_commands.describe(seconds="Slowmode delay in seconds (0 to disable)")
    @app_commands.default_permissions(manage_channels=True)
    async def slash_slowmode(self, interaction: discord.Interaction, seconds: int = 0) -> None:
        """Slash command version of slowmode."""
        if not 0 <= seconds <= 21600:
            await interaction.response.send_message("Value must be 0–21600 seconds.")
            return
        await interaction.channel.edit(slowmode_delay=seconds)
        embed = self._make_embed("🐌 Slowmode Set", 0x3498DB)
        embed.add_field(name="Channel", value=interaction.channel.mention, inline=True)
        embed.add_field(name="Delay", value=f"**{seconds}** seconds", inline=True)
        if seconds == 0:
            embed.description = "Slowmode **disabled**"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="lock", description="Lock the current channel")
    @app_commands.default_permissions(manage_channels=True)
    async def slash_lock(self, interaction: discord.Interaction) -> None:
        """Slash command version of lock."""
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.")
            return
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        embed = self._make_embed("🔒 Channel Locked", 0xE74C3C)
        embed.add_field(name="Channel", value=interaction.channel.mention, inline=True)
        embed.description = "@everyone **cannot** send messages"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unlock", description="Unlock the current channel")
    @app_commands.default_permissions(manage_channels=True)
    async def slash_unlock(self, interaction: discord.Interaction) -> None:
        """Slash command version of unlock."""
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.")
            return
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        embed = self._make_embed("🔓 Channel Unlocked", 0x2ECC71)
        embed.add_field(name="Channel", value=interaction.channel.mention, inline=True)
        embed.description = "@everyone **can** send messages"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="nickname", description="Change a member's nickname")
    @app_commands.describe(member="The member", name="New nickname (leave empty to reset)")
    @app_commands.default_permissions(manage_nicknames=True)
    async def slash_nickname(self, interaction: discord.Interaction, member: discord.Member, name: str | None = None) -> None:
        """Slash command version of nickname."""
        await member.edit(nick=name)
        embed = self._make_embed("📛 Nickname Updated", 0x9B59B6)
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="New Nickname", value=name or "*None*", inline=True)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
