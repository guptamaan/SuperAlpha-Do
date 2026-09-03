"""
cogs/info.py — Informational commands.
Commands: userinfo, serverinfo, avatar, roleinfo, channelinfo, botinfo,
          membercount, roles, emojis, banner, perms, ping
"""

import datetime

import discord
from discord import app_commands
from discord.ext import commands


def _fmt_dt(dt: datetime.datetime | None) -> str:
    if dt is None:
        return "N/A"
    return dt.strftime("%Y-%m-%d %H:%M UTC")


class Info(commands.Cog, name="info"):
    """Informational lookup commands (userinfo, serverinfo, avatar …)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.start_time = datetime.datetime.now(datetime.timezone.utc)

    def _make_embed(self, title: str, color: int) -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title, icon_url=None)
        return embed

    # ── userinfo ──────────────────────────────────────────────────────────────
    @commands.command(name="userinfo", aliases=["whois", "ui", "id"])
    async def userinfo(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        """Get detailed info about a user. Usage: sudo userinfo [@user]"""
        member = member or ctx.author
        roles = [r.mention for r in member.roles if r != ctx.guild.default_role]

        status_emojis = {
            discord.Status.online:    "🟢 Online",
            discord.Status.idle:      "🟡 Idle",
            discord.Status.dnd:       "🔴 Do Not Disturb",
            discord.Status.offline:   "⚫ Offline",
        }
        status = status_emojis.get(member.status, "⚫ Offline")
        activity = member.activity
        if activity:
            activity_type = str(activity.type).split('.')[-1].title()
            activity_name = activity.name or getattr(activity, "state", None)
            if activity_name:
                status = f"{status} • **{activity_type}**: {activity_name}"

        color = member.color if member.color != discord.Color.default() else 0x7289DA
        embed = discord.Embed(color=color)
        embed.set_author(name=f"👤 {member}", icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="📛 Username", value=str(member), inline=True)
        embed.add_field(name="🆔 ID", value=str(member.id), inline=True)
        embed.add_field(name="👋 Nickname", value=member.nick or "None", inline=True)
        embed.add_field(name="📊 Status", value=status, inline=True)
        embed.add_field(name="🤖 Bot", value="Yes" if member.bot else "No", inline=True)
        embed.add_field(name="💎 Boosting", value="Yes" if member.premium_since else "No", inline=True)
        embed.add_field(name="📅 Account Created", value=_fmt_dt(member.created_at), inline=True)
        embed.add_field(name="📥 Joined Server", value=_fmt_dt(member.joined_at), inline=True)

        roles_text = ", ".join(roles[:15]) if roles else "None"
        embed.add_field(name=f"🎭 Roles [{len(roles)}]", value=roles_text, inline=False)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    # ── serverinfo ────────────────────────────────────────────────────────────
    @commands.command(name="serverinfo", aliases=["guildinfo", "server", "si", "df"])
    async def serverinfo(self, ctx: commands.Context) -> None:
        """Get information about the current server. Usage: sudo serverinfo"""
        g = ctx.guild
        text_ch  = len(g.text_channels)
        voice_ch = len(g.voice_channels)
        cats     = len(g.categories)

        embed = discord.Embed(color=0x3498DB)
        embed.set_author(name=f"🖥️ {g.name}", icon_url=g.icon.url if g.icon else None)
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)

        embed.add_field(name="👑 Owner", value=str(g.owner), inline=True)
        embed.add_field(name="🆔 ID", value=str(g.id), inline=True)
        embed.add_field(name="🌐 Locale", value=str(g.preferred_locale), inline=True)
        embed.add_field(name="👥 Members", value=str(g.member_count), inline=True)
        embed.add_field(name="💬 Text Channels", value=str(text_ch), inline=True)
        embed.add_field(name="🔊 Voice Channels", value=str(voice_ch), inline=True)
        embed.add_field(name="📁 Categories", value=str(cats), inline=True)
        embed.add_field(name="🎭 Roles", value=str(len(g.roles)), inline=True)
        embed.add_field(name="😀 Emojis", value=str(len(g.emojis)), inline=True)
        embed.add_field(name="🚀 Boost Level", value=str(g.premium_tier), inline=True)
        embed.add_field(name="✨ Boosts", value=str(g.premium_subscription_count), inline=True)
        embed.add_field(name="🔒 Verification", value=str(g.verification_level).title(), inline=True)
        embed.add_field(name="📅 Created", value=_fmt_dt(g.created_at), inline=False)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    # ── avatar ────────────────────────────────────────────────────────────────
    @commands.command(name="avatar", aliases=["pfp", "av"])
    async def avatar(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        """View a user's profile picture. Usage: sudo avatar [@user]"""
        member = member or ctx.author
        embed = discord.Embed(color=0xE74C3C)
        embed.set_author(name=f"🖼️ {member.display_name}'s Avatar", icon_url=member.display_avatar.url)
        embed.set_image(url=member.display_avatar.url)
        links = (
            f"[PNG]({member.display_avatar.replace(format='png').url})  "
            f"[JPG]({member.display_avatar.replace(format='jpg').url})  "
            f"[WEBP]({member.display_avatar.replace(format='webp').url})"
        )
        embed.add_field(name="📥 Download", value=links, inline=False)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    # ── banner ────────────────────────────────────────────────────────────────
    @commands.command(name="banner")
    async def banner(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        """View a user's profile banner. Usage: sudo banner [@user]"""
        member = member or ctx.author
        fetched = await self.bot.fetch_user(member.id)
        if not fetched.banner:
            embed = self._make_embed("🎨 No Banner", 0x95A5A6)
            embed.description = f"{member} has no banner set"
            await ctx.send(embed=embed)
            return
        embed = discord.Embed(color=fetched.accent_color or 0x7289DA)
        embed.set_author(name=f"🎨 {member.display_name}'s Banner", icon_url=member.display_avatar.url)
        embed.set_image(url=fetched.banner.url)
        await ctx.send(embed=embed)

    # ── roleinfo ──────────────────────────────────────────────────────────────
    @commands.command(name="roleinfo", aliases=["role", "ri"])
    async def roleinfo(self, ctx: commands.Context, *, role: discord.Role) -> None:
        """Get info about a role. Usage: sudo roleinfo <role mention>"""
        perms = [p.replace("_", " ").title() for p, v in role.permissions if v]
        embed = discord.Embed(color=role.color)
        embed.set_author(name=f"🔑 {role.name}", icon_url=None)
        embed.add_field(name="🆔 ID", value=str(role.id), inline=True)
        embed.add_field(name="🎨 Color", value=str(role.color), inline=True)
        embed.add_field(name="👥 Mentionable", value="Yes" if role.mentionable else "No", inline=True)
        embed.add_field(name="📌 Hoisted", value="Yes" if role.hoist else "No", inline=True)
        embed.add_field(name="👤 Members", value=str(len(role.members)), inline=True)
        embed.add_field(name="🔢 Position", value=str(role.position), inline=True)
        embed.add_field(name="📅 Created", value=_fmt_dt(role.created_at), inline=True)
        embed.add_field(name="🤖 Managed", value="Yes" if role.managed else "No", inline=True)
        perms_text = ", ".join(perms[:15]) or "None"
        embed.add_field(name="🔐 Permissions", value=perms_text, inline=False)
        await ctx.send(embed=embed)

    # ── channelinfo ───────────────────────────────────────────────────────────
    @commands.command(name="channelinfo", aliases=["chan", "ci"])
    async def channelinfo(self, ctx: commands.Context, channel: discord.TextChannel | None = None) -> None:
        """Get info about a text channel. Usage: sudo channelinfo [#channel]"""
        channel = channel or ctx.channel
        embed = discord.Embed(color=0x9B59B6)
        embed.set_author(name=f"📁 #{channel.name}", icon_url=None)
        embed.description = channel.topic or "No topic set."
        embed.add_field(name="🆔 ID", value=str(channel.id), inline=True)
        embed.add_field(name="📂 Category", value=str(channel.category), inline=True)
        embed.add_field(name="🔞 NSFW", value="Yes" if channel.nsfw else "No", inline=True)
        embed.add_field(name="🐌 Slowmode", value=f"{channel.slowmode_delay}s", inline=True)
        embed.add_field(name="🔢 Position", value=str(channel.position), inline=True)
        embed.add_field(name="📅 Created", value=_fmt_dt(channel.created_at), inline=True)
        await ctx.send(embed=embed)

    # ── membercount ───────────────────────────────────────────────────────────
    @commands.command(name="membercount", aliases=["mc"])
    async def membercount(self, ctx: commands.Context) -> None:
        """See member statistics for the server. Usage: sudo membercount"""
        g = ctx.guild
        humans = sum(1 for m in g.members if not m.bot)
        bots   = sum(1 for m in g.members if m.bot)
        online = sum(1 for m in g.members if m.status != discord.Status.offline)
        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name=f"👥 Member Count — {g.name}", icon_url=None)
        embed.add_field(name="👤 Total", value=str(g.member_count), inline=True)
        embed.add_field(name="🧑 Humans", value=str(humans), inline=True)
        embed.add_field(name="🤖 Bots", value=str(bots), inline=True)
        embed.add_field(name="🟢 Online", value=str(online), inline=True)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    # ── roles ─────────────────────────────────────────────────────────────────
    @commands.command(name="roles")
    async def roles(self, ctx: commands.Context) -> None:
        """List all roles in the server. Usage: sudo roles"""
        role_list = [r.mention for r in reversed(ctx.guild.roles) if r != ctx.guild.default_role]
        chunks = [role_list[i:i+20] for i in range(0, len(role_list), 20)]
        for i, chunk in enumerate(chunks[:3]):
            embed = discord.Embed(
                title=f"🔑 Roles ({len(ctx.guild.roles)-1} total)" + (f" — page {i+1}" if len(chunks) > 1 else ""),
                description=", ".join(chunk),
                color=0xF39C12,
            )
            await ctx.send(embed=embed)

    # ── emojis ────────────────────────────────────────────────────────────────
    @commands.command(name="emojis")
    async def emojis(self, ctx: commands.Context) -> None:
        """View all custom emojis in the server. Usage: sudo emojis"""
        emojis = ctx.guild.emojis
        if not emojis:
            embed = self._make_embed("😀 No Emojis", 0x95A5A6)
            embed.description = "No custom emojis in this server"
            await ctx.send(embed=embed)
            return
        static   = [str(e) for e in emojis if not e.animated]
        animated = [str(e) for e in emojis if e.animated]
        embed = discord.Embed(title=f"😀 Emojis — {ctx.guild.name}", color=0xF1C40F)
        if static:
            embed.add_field(name=f"Static ({len(static)})", value=" ".join(static[:30]) or "None", inline=False)
        if animated:
            embed.add_field(name=f"Animated ({len(animated)})", value=" ".join(animated[:30]) or "None", inline=False)
        await ctx.send(embed=embed)

    # ── perms ─────────────────────────────────────────────────────────────────
    @commands.command(name="perms", aliases=["permissions"])
    async def perms(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        """View a user's server permissions. Usage: sudo perms [@user]"""
        member = member or ctx.author
        granted = [p.replace("_", " ").title() for p, v in member.guild_permissions if v]
        denied  = [p.replace("_", " ").title() for p, v in member.guild_permissions if not v]
        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name=f"🔐 Permissions — {member.display_name}", icon_url=member.display_avatar.url)
        embed.add_field(name="✅ Granted", value=", ".join(granted) or "None", inline=False)
        embed.add_field(name="❌ Denied", value=", ".join(denied[:20]) or "None", inline=False)
        await ctx.send(embed=embed)

    # ── botinfo ───────────────────────────────────────────────────────────────
    @commands.command(name="botinfo", aliases=["about", "info"])
    async def botinfo(self, ctx: commands.Context) -> None:
        """Learn about the bot and its stats. Usage: sudo botinfo"""
        import platform
        import psutil
        import os

        uptime = datetime.datetime.now(datetime.timezone.utc) - self.start_time
        days, seconds = divmod(int(uptime.total_seconds()), 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"

        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        total_channels = sum(len(g.channels) for g in self.bot.guilds)
        voice_connections = len([vc for vc in self.bot.voice_clients])

        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024
        cpu_percent = process.cpu_percent(interval=0.1)

        embed = discord.Embed(
            title="🤖 SuperUser Do",
            description="A Linux-flavored all-in-one Discord bot built with power and simplicity in mind.",
            color=0xF39C12,
        )
        embed.set_author(name="SuperUser Do", icon_url=self.bot.user.display_avatar.url if self.bot.user else None)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url if self.bot.user else None)

        embed.add_field(name="📚 Library", value=f"discord.py {discord.__version__}", inline=True)
        embed.add_field(name="🐍 Python", value=platform.python_version(), inline=True)

        embed.add_field(name="🏠 Servers", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="👥 Users", value=str(total_members), inline=True)
        embed.add_field(name="📁 Channels", value=str(total_channels), inline=True)
        embed.add_field(name="🔊 Voice", value=str(voice_connections), inline=True)

        embed.add_field(name="⚡ Uptime", value=uptime_str, inline=True)
        embed.add_field(name="💾 Memory", value=f"{memory_mb:.1f} MB", inline=True)
        embed.add_field(name="🖥️ CPU", value=f"{cpu_percent:.1f}%", inline=True)

        embed.add_field(name="📝 Commands", value=str(len(self.bot.commands)), inline=True)
        embed.add_field(name="⚙️ Modules", value=str(len(self.bot.cogs)), inline=True)

        embed.add_field(name="🔗 Links", value="[Invite Bot](#) | [Support Server](#)", inline=False)
        embed.set_footer(text="sudo man | Sudo <command> for help")
        await ctx.send(embed=embed)

    # ── Slash Commands ────────────────────────────────────────────────────────
    @app_commands.command(name="userinfo", description="Get detailed info about a user")
    @app_commands.describe(member="The user to look up (optional)")
    async def slash_userinfo(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        """Slash command version of userinfo."""
        member = member or interaction.user
        if isinstance(member, discord.User) and not isinstance(member, discord.Member):
            member = interaction.guild.get_member(member.id) if interaction.guild else member
        if not isinstance(member, discord.Member):
            member = interaction.guild.get_member(interaction.user.id) if interaction.guild else interaction.user

        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.")
            return

        roles = [r.mention for r in member.roles if r != interaction.guild.default_role]
        status_emojis = {
            discord.Status.online: "🟢 Online",
            discord.Status.idle: "🟡 Idle",
            discord.Status.dnd: "🔴 Do Not Disturb",
            discord.Status.offline: "⚫ Offline",
        }
        status = status_emojis.get(member.status, "⚫ Offline")

        color = member.color if member.color != discord.Color.default() else 0x7289DA
        embed = discord.Embed(color=color)
        embed.set_author(name=f"👤 {member}", icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="📛 Username", value=str(member), inline=True)
        embed.add_field(name="🆔 ID", value=str(member.id), inline=True)
        embed.add_field(name="👋 Nickname", value=member.nick or "None", inline=True)
        embed.add_field(name="📊 Status", value=status, inline=True)
        embed.add_field(name="🤖 Bot", value="Yes" if member.bot else "No", inline=True)
        embed.add_field(name="💎 Boosting", value="Yes" if member.premium_since else "No", inline=True)
        roles_text = ", ".join(roles[:15]) if roles else "None"
        embed.add_field(name=f"🎭 Roles [{len(roles)}]", value=roles_text, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="Get information about the current server")
    async def slash_serverinfo(self, interaction: discord.Interaction) -> None:
        """Slash command version of serverinfo."""
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.")
            return

        g = interaction.guild
        text_ch = len(g.text_channels)
        voice_ch = len(g.voice_channels)

        embed = discord.Embed(color=0x3498DB)
        embed.set_author(name=f"🖥️ {g.name}", icon_url=g.icon.url if g.icon else None)
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="👑 Owner", value=str(g.owner), inline=True)
        embed.add_field(name="🆔 ID", value=str(g.id), inline=True)
        embed.add_field(name="🌐 Locale", value=str(g.preferred_locale), inline=True)
        embed.add_field(name="👥 Members", value=str(g.member_count), inline=True)
        embed.add_field(name="💬 Text Channels", value=str(text_ch), inline=True)
        embed.add_field(name="🔊 Voice Channels", value=str(voice_ch), inline=True)
        embed.add_field(name="🎭 Roles", value=str(len(g.roles)), inline=True)
        embed.add_field(name="😀 Emojis", value=str(len(g.emojis)), inline=True)
        embed.add_field(name="🚀 Boost Level", value=str(g.premium_tier), inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="View a user's profile picture")
    @app_commands.describe(member="The user to get avatar for (optional)")
    async def slash_avatar(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        """Slash command version of avatar."""
        member = member or interaction.user
        if isinstance(member, discord.User) and not isinstance(member, discord.Member):
            member = interaction.guild.get_member(member.id) if interaction.guild else member
        if not isinstance(member, discord.Member):
            member = interaction.guild.get_member(interaction.user.id) if interaction.guild else interaction.user

        embed = discord.Embed(color=0xE74C3C)
        embed.set_author(name=f"🖼️ {member.display_name}'s Avatar", icon_url=member.display_avatar.url)
        embed.set_image(url=member.display_avatar.url)
        links = (
            f"[PNG]({member.display_avatar.replace(format='png').url})  "
            f"[JPG]({member.display_avatar.replace(format='jpg').url})  "
            f"[WEBP]({member.display_avatar.replace(format='webp').url})"
        )
        embed.add_field(name="📥 Download", value=links, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="botinfo", description="Learn about the bot and its stats")
    async def slash_botinfo(self, interaction: discord.Interaction) -> None:
        """Slash command version of botinfo."""
        import platform
        import psutil
        import os

        uptime = datetime.datetime.now(datetime.timezone.utc) - self.start_time
        days, seconds = divmod(int(uptime.total_seconds()), 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"

        total_members = sum(g.member_count or 0 for g in self.bot.guilds)

        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024
        cpu_percent = process.cpu_percent(interval=0.1)

        embed = discord.Embed(
            title="🤖 SuperUser Do",
            description="A Linux-flavored all-in-one Discord bot.",
            color=0xF39C12,
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url if self.bot.user else None)
        embed.add_field(name="📚 Library", value=f"discord.py {discord.__version__}", inline=True)
        embed.add_field(name="🐍 Python", value=platform.python_version(), inline=True)
        embed.add_field(name="🏠 Servers", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="👥 Users", value=str(total_members), inline=True)
        embed.add_field(name="⚡ Uptime", value=uptime_str, inline=True)
        embed.add_field(name="💾 Memory", value=f"{memory_mb:.1f} MB", inline=True)
        embed.add_field(name="🖥️ CPU", value=f"{cpu_percent:.1f}%", inline=True)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Info(bot))
