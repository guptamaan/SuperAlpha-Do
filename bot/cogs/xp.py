"""
cogs/xp.py — XP and ranking system with SP currency.
Awards XP/SP for: chatting, VC time, using bot commands.

Persistence lives in ``bot.models.xp_store``; level math in
``bot.services.leveling``. This file re-exports those symbols so existing
imports (``from bot.cogs.xp import award_game_xp``) keep working.
"""

import asyncio
import random
import time
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.checks import perms_or_developer
from bot.models.xp_store import (
    CONFIG_FILE,
    DATA_DIR,
    DATABASE_FILE,
    _config_cache,
    _config_cache_loaded,
    _db_conn,
    _load_user_from_disk,
    _row_to_user,
    _SAVE_INTERVAL,
    _dirty_users,
    _default_user,
    _flush_user,
    _migrate_legacy_json,
    _upsert_user,
    _user_cache,
    flush_all,
    get_db,
    get_level_channel,
    init_db,
    is_xp_enabled,
    load_config,
    load_user,
    save_config,
    save_user,
    set_level_channel,
    set_xp_enabled,
    top_users,
)
from bot.services.leveling import (
    award_game_xp,
    cumulative_xp,
    get_level_progress,
    level_from_xp,
    xp_for_level,
)

__all__ = [
    "CONFIG_FILE",
    "DATA_DIR",
    "DATABASE_FILE",
    "XP",
    "award_game_xp",
    "cumulative_xp",
    "flush_all",
    "get_db",
    "get_level_channel",
    "get_level_progress",
    "init_db",
    "is_xp_enabled",
    "level_from_xp",
    "load_config",
    "load_user",
    "save_config",
    "save_user",
    "set_level_channel",
    "set_xp_enabled",
    "top_users",
    "xp_for_level",
]


class XP(commands.Cog, name="xp"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._vc_tasks: dict[int, asyncio.Task] = {}
        self._flush_task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def cog_unload(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
        flush_all()

    async def _periodic_flush(self) -> None:
        while True:
            await asyncio.sleep(_SAVE_INTERVAL)
            flush_all()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not message.guild:
            return
        if not is_xp_enabled(message.guild.id):
            return

        user_id = message.author.id
        data = load_user(user_id)

        now = time.time()
        if now - data["last_message"] < 30:
            return

        data["messages"] += 1
        data["last_message"] = now

        xp_gain = random.randint(10, 25)
        sp_gain = random.randint(1, 3)

        data["xp"] += xp_gain
        data["sp"] += sp_gain

        old_level = data["level"]
        data["level"] = level_from_xp(data["xp"])

        save_user(user_id, data)

        if data["level"] > old_level:
            try:
                embed = discord.Embed(
                    color=0xF1C40F,
                    title="🎉 Level Up!",
                    description=f"**{message.author.mention}** reached **Level {data['level']}**!"
                )
                embed.add_field(name="XP", value=f"{xp_gain} xp earned", inline=True)
                embed.add_field(name="SP", value=f"{sp_gain} sp earned", inline=True)
                channel = None
                level_channel_id = get_level_channel(message.guild.id)
                if level_channel_id:
                    channel = message.guild.get_channel(level_channel_id)
                await (channel or message.channel).send(embed=embed)
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return
        if not is_xp_enabled(member.guild.id):
            return

        user_id = member.id
        data = load_user(user_id)

        if after.channel and not before.channel:
            data["vc_start"] = time.time()

        elif before.channel and not after.channel:
            if data["vc_start"] > 0:
                elapsed = time.time() - data["vc_start"]
                minutes = int(elapsed / 60)

                if minutes >= 1:
                    xp_gain = minutes * 5
                    sp_gain = minutes // 3
                    data["xp"] += xp_gain
                    data["sp"] += sp_gain
                    data["vc_time"] += int(elapsed)
                    data["level"] = level_from_xp(data["xp"])
                    save_user(user_id, data)

                data["vc_start"] = 0
                save_user(user_id, data)

    async def _award_command_xp(self, user_id: int) -> None:
        data = load_user(user_id)
        xp_gain = random.randint(5, 15)
        sp_gain = random.randint(1, 2)
        data["xp"] += xp_gain
        data["sp"] += sp_gain
        data["commands_used"] += 1
        data["level"] = level_from_xp(data["xp"])
        save_user(user_id, data)

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context) -> None:
        if ctx.author.bot:
            return
        if ctx.guild and not is_xp_enabled(ctx.guild.id):
            return
        await self._award_command_xp(ctx.author.id)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.user.bot:
            return
        if interaction.guild and not is_xp_enabled(interaction.guild.id):
            return
        await self._award_command_xp(interaction.user.id)

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title)
        if description:
            embed.description = description
        return embed

    @commands.command(name="rank", aliases=["profile", "stats"])
    async def rank(self, ctx: commands.Context, *, member: discord.Member = None) -> None:
        """View your rank and stats. Usage: sudo rank [user]"""
        member = member or ctx.author
        data = load_user(member.id)
        xp_in_level, xp_needed, level = get_level_progress(data["xp"])

        vc_time_min = data["vc_time"] // 60
        hours = vc_time_min // 60
        mins = vc_time_min % 60

        embed = discord.Embed(color=0x9B59B6)
        embed.set_author(name=f"📊 {member.display_name}'s Stats")
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="Level", value=f"**{level}**", inline=True)
        embed.add_field(name="Total XP", value=f"**{data['xp']:,}**", inline=True)
        embed.add_field(name="SP Balance", value=f"**{data['sp']:,}**", inline=True)

        embed.add_field(name="Progress", value=f"`{'█' * int(xp_in_level / xp_needed * 10)}{'░' * (10 - int(xp_in_level / xp_needed * 10))}`", inline=False)
        embed.add_field(name="XP in Level", value=f"{xp_in_level} / {xp_needed}", inline=True)
        embed.add_field(name="Messages", value=f"{data['messages']:,}", inline=True)

        embed.add_field(name="VC Time", value=f"{hours}h {mins}m", inline=True)
        embed.add_field(name="Commands Used", value=f"{data['commands_used']:,}", inline=True)

        await ctx.send(embed=embed)

    @commands.command(name="leaderboard", aliases=["lb", "top"])
    async def leaderboard(self, ctx: commands.Context, type: str = "xp") -> None:
        """View the leaderboard. Usage: sudo leaderboard [xp|sp|messages|vc]"""
        type_key = type.lower()
        if type_key == "sp":
            title = "💰 SP Leaderboard"
            field_name = "SP"
        elif type_key == "messages":
            title = "💬 Messages Leaderboard"
            field_name = "Messages"
        elif type_key == "vc":
            title = "🎤 VC Time Leaderboard"
            field_name = "VC Time"
        else:
            type_key = "xp"
            title = "⭐ XP Leaderboard"
            field_name = "XP"

        top = top_users(type_key, 10)

        embed = discord.Embed(color=0xF1C40F)
        embed.set_author(name=title)

        if not top:
            embed.description = "No data yet!"
            await ctx.send(embed=embed)
            return

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, (user_id, data) in enumerate(top):
            user = self.bot.get_user(user_id)
            if user:
                name = user.display_name[:15]
                if type.lower() == "vc":
                    mins = data["vc_time"] // 60
                    val = f"{mins // 60}h {mins % 60}m"
                elif type.lower() == "messages":
                    val = f"{data['messages']:,}"
                elif type.lower() == "sp":
                    val = f"{data['sp']:,}"
                else:
                    val = f"{data['xp']:,}"

                medal = medals[i] if i < 3 else f"`{i+1}.`"
                lines.append(f"{medal} **{name}** — {data['level']} lvl — {val} {field_name}")

        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Showing top {len(top)} | Use 'sudo lb sp/messages/vc' for different rankings")
        await ctx.send(embed=embed)

    @commands.command(name="daily", aliases=["claim"])
    async def daily(self, ctx: commands.Context) -> None:
        """Claim your daily SP reward. Usage: sudo daily"""
        user_id = ctx.author.id
        data = load_user(user_id)

        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        if data["daily_claimed"] == today:
            next_claim = datetime.strptime(data["daily_claimed"], "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            remaining = next_claim - now
            hours = int(remaining.total_seconds() / 3600)
            minutes = int((remaining.total_seconds() % 3600) / 60)
            embed = self._make_embed("❌ Already Claimed", 0xE74C3C, f"Come back in **{hours}h {minutes}m**")
            await ctx.send(embed=embed)
            return

        base_reward = 100
        streak_bonus = data["streak"] * 10
        total_reward = base_reward + streak_bonus

        data["sp"] += total_reward
        data["daily_claimed"] = today
        data["streak"] += 1

        save_user(user_id, data)

        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name="💰 Daily Claimed!")
        embed.description = f"**+{total_reward} SP**"
        embed.add_field(name="Base", value=f"{base_reward} SP", inline=True)
        embed.add_field(name="Streak Bonus", value=f"+{streak_bonus} SP", inline=True)
        embed.add_field(name="🔥 Streak", value=f"{data['streak']} days", inline=True)
        embed.add_field(name="Total SP", value=f"**{data['sp']:,}**", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="give", aliases=["pay", "transfer"])
    async def give(self, ctx: commands.Context, member: discord.Member, amount: int) -> None:
        """Give SP to another user. Usage: sudo give @user <amount>"""
        if member.bot:
            embed = self._make_embed("❌ Invalid User", 0xE74C3C, "Cannot give SP to bots")
            await ctx.send(embed=embed)
            return

        if member.id == ctx.author.id:
            embed = self._make_embed("❌ Invalid", 0xE74C3C, "Cannot give SP to yourself")
            await ctx.send(embed=embed)
            return

        if amount <= 0:
            embed = self._make_embed("❌ Invalid Amount", 0xE74C3C, "Amount must be positive")
            await ctx.send(embed=embed)
            return

        sender_data = load_user(ctx.author.id)
        if sender_data["sp"] < amount:
            embed = self._make_embed("❌ Insufficient SP", 0xE74C3C, f"You only have **{sender_data['sp']:,} SP**")
            await ctx.send(embed=embed)
            return

        sender_data["sp"] -= amount
        save_user(ctx.author.id, sender_data)

        receiver_data = load_user(member.id)
        receiver_data["sp"] += amount
        save_user(member.id, receiver_data)

        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name="💸 SP Transferred")
        embed.description = f"**{ctx.author.mention}** sent **{amount:,} SP** to **{member.mention}**"
        await ctx.send(embed=embed)

    @commands.command(name="bet")
    async def bet(self, ctx: commands.Context, amount: int) -> None:
        """Bet SP for a chance to double it. Usage: sudo bet <amount>"""
        if amount <= 0:
            embed = self._make_embed("❌ Invalid Amount", 0xE74C3C, "Amount must be positive")
            await ctx.send(embed=embed)
            return

        user_data = load_user(ctx.author.id)
        if user_data["sp"] < amount:
            embed = self._make_embed("❌ Insufficient SP", 0xE74C3C, f"You only have **{user_data['sp']:,} SP**")
            await ctx.send(embed=embed)
            return

        win = random.random() < 0.5

        if win:
            user_data["sp"] += amount
            embed = discord.Embed(color=0x2ECC71)
            embed.set_author(name="🎉 You Won!")
            embed.description = f"You doubled your **{amount:,} SP** to **{user_data['sp']:,} SP**!"
        else:
            user_data["sp"] -= amount
            embed = discord.Embed(color=0xE74C3C)
            embed.set_author(name="😢 You Lost!")
            embed.description = f"You lost **{amount:,} SP**. Now at **{user_data['sp']:,} SP**"

        save_user(ctx.author.id, user_data)
        await ctx.send(embed=embed)

    @commands.command(name="work")
    @commands.cooldown(1, 3600, commands.BucketType.user)
    async def work(self, ctx: commands.Context) -> None:
        """Work to earn SP (1 hour cooldown). Usage: sudo work"""
        user_data = load_user(ctx.author.id)
        reward = random.randint(50, 200)
        user_data["sp"] += reward
        save_user(ctx.author.id, user_data)

        embed = discord.Embed(color=0x3498DB)
        embed.set_author(name="💼 Work Complete!")
        embed.description = f"You earned **{reward:,} SP**!\nTotal: **{user_data['sp']:,} SP**"
        await ctx.send(embed=embed)

    @app_commands.command(name="rank", description="View your rank and stats")
    @app_commands.describe(member="User to check (optional)")
    async def slash_rank(self, interaction: discord.Interaction, member: discord.Member = None) -> None:
        await interaction.response.defer()
        member = member or interaction.user
        data = load_user(member.id)
        xp_in_level, xp_needed, level = get_level_progress(data["xp"])

        embed = discord.Embed(color=0x9B59B6)
        embed.set_author(name=f"📊 {member.display_name}'s Stats")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Level", value=f"**{level}**", inline=True)
        embed.add_field(name="Total XP", value=f"**{data['xp']:,}**", inline=True)
        embed.add_field(name="SP Balance", value=f"**{data['sp']:,}**", inline=True)
        embed.add_field(name="Progress", value=f"`{'█' * int(xp_in_level / xp_needed * 10)}{'░' * (10 - int(xp_in_level / xp_needed * 10))}`", inline=False)
        embed.add_field(name="XP in Level", value=f"{xp_in_level} / {xp_needed}", inline=True)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="leaderboard", description="View the server leaderboard")
    @app_commands.describe(type="Type of leaderboard (xp, sp, messages, vc)")
    @app_commands.choices(type=[
        app_commands.Choice(name="XP", value="xp"),
        app_commands.Choice(name="SP", value="sp"),
        app_commands.Choice(name="Messages", value="messages"),
        app_commands.Choice(name="VC Time", value="vc"),
    ])
    async def slash_leaderboard(self, interaction: discord.Interaction, type: str = "xp") -> None:
        await interaction.response.defer()
        if type == "sp":
            title = "💰 SP Leaderboard"
            field_name = "SP"
        elif type == "messages":
            title = "💬 Messages Leaderboard"
            field_name = "Messages"
        elif type == "vc":
            title = "🎤 VC Time Leaderboard"
            field_name = "VC Time"
        else:
            type = "xp"
            title = "⭐ XP Leaderboard"
            field_name = "XP"

        top = top_users(type, 10)
        embed = discord.Embed(color=0xF1C40F)
        embed.set_author(name=title)

        if not top:
            embed.description = "No data yet!"
            await interaction.followup.send(embed=embed)
            return

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, (user_id, data) in enumerate(top):
            user = self.bot.get_user(user_id)
            if user:
                name = user.display_name[:15]
                if type == "vc":
                    mins = data["vc_time"] // 60
                    val = f"{mins // 60}h {mins % 60}m"
                elif type == "messages":
                    val = f"{data['messages']:,}"
                elif type == "sp":
                    val = f"{data['sp']:,}"
                else:
                    val = f"{data['xp']:,}"
                medal = medals[i] if i < 3 else f"`{i+1}.`"
                lines.append(f"{medal} **{name}** — {data['level']} lvl — {val} {field_name}")

        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    @commands.command(name="levelchannel", aliases=["lvlchannel", "levelupchannel"])
    @perms_or_developer(administrator=True)
    async def levelchannel(self, ctx: commands.Context, action: str = None, channel: discord.TextChannel = None) -> None:
        """Set the channel for level-up messages. Usage: sudo levelchannel [set #channel|off|status]"""
        if not action:
            current = get_level_channel(ctx.guild.id)
            if current:
                ch = ctx.guild.get_channel(current)
                desc = f"Level-up messages are sent to **{ch.mention if ch else f'<#{current}>'}**."
            else:
                desc = "Level-up messages are sent where the user last chatted. Set a channel with `sudo levelchannel set #channel`."
            embed = discord.Embed(color=0x9B59B6)
            embed.set_author(name="📣 Level-Up Channel")
            embed.description = desc
            await ctx.send(embed=embed)
            return

        action = action.lower()

        if action in ["set", "channel"]:
            if channel is None:
                embed = self._make_embed("❌ Missing Channel", 0xE74C3C, "Usage: `sudo levelchannel set #channel`")
                await ctx.send(embed=embed)
                return
            set_level_channel(ctx.guild.id, channel.id)
            embed = discord.Embed(color=0x2ECC71)
            embed.set_author(name="✅ Level-Up Channel Set")
            embed.description = f"Level-up messages will now be sent to **{channel.mention}**."
            await ctx.send(embed=embed)

        elif action in ["off", "disable", "none", "clear", "reset"]:
            set_level_channel(ctx.guild.id, None)
            embed = discord.Embed(color=0x95A5A6)
            embed.set_author(name="🔕 Level-Up Channel Cleared")
            embed.description = "Level-up messages will be sent where the user last chatted."
            await ctx.send(embed=embed)

        else:
            embed = self._make_embed("❌ Invalid Action", 0xE74C3C, "Usage: `sudo levelchannel set #channel | off | status`")
            await ctx.send(embed=embed)

    @levelchannel.error
    async def levelchannel_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingPermissions):
            embed = self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission to use this command.")
            await ctx.send(embed=embed)

    @commands.command(name="xpsystem")
    @perms_or_developer(administrator=True)
    async def xpsystem(self, ctx: commands.Context, action: str = None) -> None:
        """Enable/disable XP system. Usage: sudo xpsystem [enable|disable|status]"""
        if not action:
            enabled = is_xp_enabled(ctx.guild.id)
            status = "✅ Enabled" if enabled else "❌ Disabled"
            embed = discord.Embed(color=0x9B59B6)
            embed.set_author(name="📊 XP System Status")
            embed.description = f"XP/Level system is currently **{status}**"
            await ctx.send(embed=embed)
            return

        action = action.lower()

        if action in ["enable", "on", "true", "1", "yes"]:
            set_xp_enabled(ctx.guild.id, True)
            embed = discord.Embed(color=0x2ECC71)
            embed.set_author(name="✅ XP System Enabled")
            embed.description = "XP/Level system has been **enabled** for this server."
            await ctx.send(embed=embed)

        elif action in ["disable", "off", "false", "0", "no"]:
            set_xp_enabled(ctx.guild.id, False)
            embed = discord.Embed(color=0xE74C3C)
            embed.set_author(name="❌ XP System Disabled")
            embed.description = "XP/Level system has been **disabled** for this server."
            await ctx.send(embed=embed)

        else:
            embed = self._make_embed("❌ Invalid Action", 0xE74C3C, "Usage: `sudo xpsystem [enable|disable|status]`")
            await ctx.send(embed=embed)

    @xpsystem.error
    async def xpsystem_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingPermissions):
            embed = self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission to use this command.")
            await ctx.send(embed=embed)

    @commands.command(name="addxp", aliases=["givexp", "grantxp"], hidden=True)
    @commands.is_owner()
    async def addxp(self, ctx: commands.Context, member: discord.Member, amount: int) -> None:
        """[Owner] Add or remove XP for a user. Usage: sudo addxp <user> <amount>"""
        if amount == 0:
            embed = self._make_embed("❌ Invalid Amount", 0xE74C3C, "Amount must not be zero")
            await ctx.send(embed=embed)
            return

        old_xp = load_user(member.id)["xp"]
        new_level = award_game_xp(member.id, amount)
        new_xp = old_xp + amount

        embed = discord.Embed(color=0x2ECC71 if amount > 0 else 0xE74C3C)
        embed.set_author(name="✅ XP Updated" if amount > 0 else "❌ XP Removed")
        embed.description = (
            f"**{member.mention}** — **{old_xp:,} → {new_xp:,} XP** (`{amount:+d}`) · **Level {new_level}**"
        )
        await ctx.send(embed=embed)

    @addxp.error
    async def addxp_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.NotOwner):
            embed = self._make_embed("❌ Access Denied", 0xE74C3C, "Only the bot owner / super user can use this command.")
            await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(XP(bot))