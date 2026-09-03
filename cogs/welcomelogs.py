"""
cogs/welcomelogs.py — Welcome messages and server logging.
"""

import json
import os
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from cogs.checks import perms_or_developer


DATA_DIR = "data/welcomelogs"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
os.makedirs(DATA_DIR, exist_ok=True)


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


def save_config(config: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_guild_config(guild_id: int) -> dict:
    config = load_config()
    return config.get(str(guild_id), {
        "welcome_channel": None,
        "welcome_message": "Welcome {user} to {server}!",
        "welcome_enabled": False,
        "logs_channel": None,
        "logs_enabled": False,
        "log_messages": True,
        "log_joins": True,
        "log_leaves": True,
        "log_roles": True,
        "log_bans": True,
        "log_edits": True,
    })


def save_guild_config(guild_id: int, guild_config: dict) -> None:
    config = load_config()
    config[str(guild_id)] = guild_config
    save_config(config)


class WelcomeLogs(commands.Cog, name="welcomelogs"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title)
        if description:
            embed.description = description
        return embed

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return

        config = get_guild_config(member.guild.id)

        if not config.get("welcome_enabled") or not config.get("welcome_channel"):
            return

        channel = member.guild.get_channel(config["welcome_channel"])
        if not channel:
            return

        message = config.get("welcome_message", "Welcome {user} to {server}!")
        message = message.replace("{user}", member.mention)
        message = message.replace("{user_name}", member.display_name)
        message = message.replace("{server}", member.guild.name)
        message = message.replace("{member_count}", str(member.guild.member_count))

        try:
            embed = discord.Embed(color=0x2ECC71, description=message)
            embed.set_author(name=f"Welcome {member.display_name}!", icon_url=member.display_avatar.url)
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Member Count", value=f"#{member.guild.member_count}", inline=True)
            await channel.send(embed=embed)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot:
            return

        config = get_guild_config(member.guild.id)

        if not config.get("logs_enabled") or not config.get("logs_channel"):
            return
        if not config.get("log_leaves"):
            return

        channel = member.guild.get_channel(config["logs_channel"])
        if not channel:
            return

        try:
            embed = discord.Embed(color=0xE74C3C, timestamp=datetime.now(timezone.utc))
            embed.set_author(name="Member Left", icon_url=member.display_avatar.url)
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
            embed.add_field(name="Joined At", value=member.joined_at.strftime("%Y-%m-%d %H:%M:%S") if member.joined_at else "Unknown", inline=True)
            embed.add_field(name="Member Count", value=f"#{member.guild.member_count}", inline=True)
            await channel.send(embed=embed)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.bot or after.bot:
            return

        config = get_guild_config(before.guild.id)

        if not config.get("logs_enabled") or not config.get("logs_channel"):
            return
        if not config.get("log_roles"):
            return

        if before.roles != after.roles:
            channel = before.guild.get_channel(config["logs_channel"])
            if not channel:
                return

            before_roles = set(before.roles)
            after_roles = set(after.roles)

            added_roles = after_roles - before_roles
            removed_roles = before_roles - after_roles

            for role in added_roles:
                try:
                    embed = discord.Embed(color=0x2ECC71, timestamp=datetime.now(timezone.utc))
                    embed.set_author(name="Role Added", icon_url=after.display_avatar.url)
                    embed.add_field(name="User", value=str(after), inline=False)
                    embed.add_field(name="Role", value=role.mention, inline=True)
                    await channel.send(embed=embed)
                except Exception:
                    pass

            for role in removed_roles:
                try:
                    embed = discord.Embed(color=0xE74C3C, timestamp=datetime.now(timezone.utc))
                    embed.set_author(name="Role Removed", icon_url=after.display_avatar.url)
                    embed.add_field(name="User", value=str(after), inline=False)
                    embed.add_field(name="Role", value=role.mention, inline=True)
                    await channel.send(embed=embed)
                except Exception:
                    pass

        if before.nick != after.nick:
            channel = before.guild.get_channel(config["logs_channel"])
            if not channel:
                return
            try:
                embed = discord.Embed(color=0x3498DB, timestamp=datetime.now(timezone.utc))
                embed.set_author(name="Nickname Changed", icon_url=after.display_avatar.url)
                embed.add_field(name="User", value=str(after), inline=False)
                embed.add_field(name="Before", value=before.nick or before.display_name, inline=True)
                embed.add_field(name="After", value=after.nick or after.display_name, inline=True)
                await channel.send(embed=embed)
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not message.guild:
            return

        config = get_guild_config(message.guild.id)

        if not config.get("logs_enabled") or not config.get("logs_channel"):
            return
        if not config.get("log_messages"):
            return

        channel = message.guild.get_channel(config["logs_channel"])
        if not channel:
            return

        try:
            embed = discord.Embed(color=0xE74C3C, description=message.content[:1024] if message.content else "*No text content*", timestamp=datetime.now(timezone.utc))
            embed.set_author(name="Message Deleted", icon_url=message.author.display_avatar.url)
            embed.add_field(name="Author", value=f"{message.author} ({message.author.id})", inline=False)
            embed.add_field(name="Channel", value=message.channel.mention, inline=True)
            embed.add_field(name="Message ID", value=message.id, inline=True)
            if message.attachments:
                embed.add_field(name="Attachments", value=f"{len(message.attachments)} file(s)", inline=True)
            await channel.send(embed=embed)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.author.bot:
            return
        if not before.guild:
            return
        if before.content == after.content:
            return

        config = get_guild_config(before.guild.id)

        if not config.get("logs_enabled") or not config.get("logs_channel"):
            return
        if not config.get("log_edits"):
            return

        channel = before.guild.get_channel(config["logs_channel"])
        if not channel:
            return

        try:
            embed = discord.Embed(color=0xF39C12, timestamp=datetime.now(timezone.utc))
            embed.set_author(name="Message Edited", icon_url=before.author.display_avatar.url)
            embed.add_field(name="Author", value=f"{before.author} ({before.author.id})", inline=False)
            embed.add_field(name="Channel", value=before.channel.mention, inline=True)
            embed.add_field(name="Jump to", value=f"[Click Here]({after.jump_url})", inline=True)
            embed.add_field(name="Before", value=before.content[:1024] if before.content else "*No text*", inline=False)
            embed.add_field(name="After", value=after.content[:1024] if after.content else "*No text*", inline=False)
            await channel.send(embed=embed)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        config = get_guild_config(guild.id)

        if not config.get("logs_enabled") or not config.get("logs_channel"):
            return
        if not config.get("log_bans"):
            return

        channel = guild.get_channel(config["logs_channel"])
        if not channel:
            return

        try:
            embed = discord.Embed(color=0xE74C3C, timestamp=datetime.now(timezone.utc))
            embed.set_author(name="Member Banned", icon_url=user.display_avatar.url if hasattr(user, 'display_avatar') else None)
            embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
            await channel.send(embed=embed)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        config = get_guild_config(guild.id)

        if not config.get("logs_enabled") or not config.get("logs_channel"):
            return
        if not config.get("log_bans"):
            return

        channel = guild.get_channel(config["logs_channel"])
        if not channel:
            return

        try:
            embed = discord.Embed(color=0x2ECC71, timestamp=datetime.now(timezone.utc))
            embed.set_author(name="Member Unbanned", icon_url=user.display_avatar.url if hasattr(user, 'display_avatar') else None)
            embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
            await channel.send(embed=embed)
        except Exception:
            pass

    @commands.command(name="welcomesetup")
    @perms_or_developer(administrator=True)
    async def welcomesetup(self, ctx: commands.Context, channel: discord.TextChannel = None, *, message: str = None) -> None:
        """Setup welcome message. Usage: sudo welcomesetup #channel Welcome {user}!"""
        if not channel:
            channel = ctx.channel

        config = get_guild_config(ctx.guild.id)
        config["welcome_channel"] = channel.id
        config["welcome_enabled"] = True
        if message:
            config["welcome_message"] = message
        save_guild_config(ctx.guild.id, config)

        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name="✅ Welcome Setup Complete")
        embed.add_field(name="Channel", value=channel.mention, inline=True)
        embed.add_field(name="Message", value=message or config.get("welcome_message"), inline=False)
        embed.add_field(name="Placeholders", value="{user}, {user_name}, {server}, {member_count}", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="welcomedisable")
    @perms_or_developer(administrator=True)
    async def welcomedisable(self, ctx: commands.Context) -> None:
        """Disable welcome messages. Usage: sudo welcomedisable"""
        config = get_guild_config(ctx.guild.id)
        config["welcome_enabled"] = False
        save_guild_config(ctx.guild.id, config)
        await ctx.send(embed=self._make_embed("❌ Welcome Disabled", 0xE74C3C, "Welcome messages have been disabled."))

    @commands.command(name="logsetup")
    @perms_or_developer(administrator=True)
    async def logsetup(self, ctx: commands.Context, channel: discord.TextChannel = None) -> None:
        """Setup logging channel. Usage: sudo logsetup #channel"""
        if not channel:
            await ctx.send(embed=self._make_embed("❌ No Channel", 0xE74C3C, "Please mention a channel: `sudo logsetup #channel`"))
            return

        config = get_guild_config(ctx.guild.id)
        config["logs_channel"] = channel.id
        config["logs_enabled"] = True
        save_guild_config(ctx.guild.id, config)

        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name="✅ Logging Setup Complete")
        embed.description = f"Logs will be sent to {channel.mention}"
        embed.add_field(name="Enabled Events", value="Messages, Joins, Leaves, Roles, Bans, Edits", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="logdisable")
    @perms_or_developer(administrator=True)
    async def logdisable(self, ctx: commands.Context) -> None:
        """Disable logging. Usage: sudo logdisable"""
        config = get_guild_config(ctx.guild.id)
        config["logs_enabled"] = False
        save_guild_config(ctx.guild.id, config)
        await ctx.send(embed=self._make_embed("❌ Logging Disabled", 0xE74C3C, "Logging has been disabled."))

    @commands.command(name="logconfig")
    @perms_or_developer(administrator=True)
    async def logconfig(self, ctx: commands.Context) -> None:
        """View current logging configuration. Usage: sudo logconfig"""
        config = get_guild_config(ctx.guild.id)

        welcome_status = "✅ Enabled" if config.get("welcome_enabled") else "❌ Disabled"
        welcome_channel = ctx.guild.get_channel(config.get("welcome_channel")) if config.get("welcome_channel") else None

        logs_status = "✅ Enabled" if config.get("logs_enabled") else "❌ Disabled"
        logs_channel = ctx.guild.get_channel(config.get("logs_channel")) if config.get("logs_channel") else None

        embed = discord.Embed(color=0x9B59B6)
        embed.set_author(name="⚙️ Configuration")

        embed.add_field(name="📝 Welcome", value=f"Status: {welcome_status}", inline=False)
        if welcome_channel:
            embed.add_field(name="", value=f"Channel: {welcome_channel.mention}", inline=False)

        embed.add_field(name="📋 Logging", value=f"Status: {logs_status}", inline=False)
        if logs_channel:
            embed.add_field(name="", value=f"Channel: {logs_channel.mention}", inline=False)

        await ctx.send(embed=embed)

    @welcomesetup.error
    async def welcomesetup_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission."))

    @logsetup.error
    async def logsetup_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission."))

    @logconfig.error
    async def logconfig_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeLogs(bot))
