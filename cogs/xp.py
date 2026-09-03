"""
cogs/xp.py — XP and ranking system with SP currency.
Awards XP/SP for: chatting, VC time, using bot commands.
"""

import asyncio
import json
import os
import time
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from cogs.checks import perms_or_developer


DATA_DIR = "data/xp"
CONFIG_FILE = "data/xp/config.json"
os.makedirs(DATA_DIR, exist_ok=True)

_user_cache: dict[int, dict] = {}
_dirty_users: set[int] = set()
_SAVE_INTERVAL = 120
_config_cache: dict | None = None
_config_cache_loaded = 0.0
_CONFIG_CACHE_TTL = 10


def get_user_file(user_id: int) -> str:
    return os.path.join(DATA_DIR, f"{user_id}.json")


def _load_user_from_disk(user_id: int) -> dict:
    path = get_user_file(user_id)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {
        "xp": 0,
        "level": 1,
        "sp": 0,
        "messages": 0,
        "vc_time": 0,
        "commands_used": 0,
        "last_message": 0,
        "vc_start": 0,
        "daily_claimed": None,
        "streak": 0,
    }


def load_user(user_id: int) -> dict:
    if user_id not in _user_cache:
        _user_cache[user_id] = _load_user_from_disk(user_id)
    return _user_cache[user_id]


def save_user(user_id: int, data: dict) -> None:
    _user_cache[user_id] = data
    _dirty_users.add(user_id)


def _flush_user(user_id: int) -> None:
    if user_id not in _dirty_users:
        return
    data = _user_cache.get(user_id)
    if data is None:
        return
    path = get_user_file(user_id)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    _dirty_users.discard(user_id)


def flush_all() -> None:
    for uid in list(_dirty_users):
        _flush_user(uid)


def load_config() -> dict:
    global _config_cache, _config_cache_loaded
    now = time.time()
    if _config_cache is None or (now - _config_cache_loaded) > _CONFIG_CACHE_TTL:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                _config_cache = json.load(f)
        else:
            _config_cache = {}
        _config_cache_loaded = now
    return _config_cache


def save_config(config: dict) -> None:
    global _config_cache, _config_cache_loaded
    _config_cache = config
    _config_cache_loaded = time.time()
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def is_xp_enabled(guild_id: int) -> bool:
    config = load_config()
    if str(guild_id) in config:
        return config[str(guild_id)].get("enabled", True)
    return True


def set_xp_enabled(guild_id: int, enabled: bool) -> None:
    config = load_config()
    if str(guild_id) not in config:
        config[str(guild_id)] = {"enabled": True}
    config[str(guild_id)]["enabled"] = enabled
    save_config(config)


_cumulative_xp_cache: dict[int, int] = {}


def xp_for_level(level: int) -> int:
    return 100 * level * level


def cumulative_xp(level: int) -> int:
    if level not in _cumulative_xp_cache:
        _cumulative_xp_cache[level] = sum(xp_for_level(l) for l in range(1, level))
    return _cumulative_xp_cache[level]


def level_from_xp(total_xp: int) -> int:
    level = 1
    while total_xp >= xp_for_level(level):
        total_xp -= xp_for_level(level)
        level += 1
        if level > 1000:
            break
    return level


def get_level_progress(total_xp: int) -> tuple[int, int, int]:
    level = level_from_xp(total_xp)
    current_level_xp = cumulative_xp(level)
    xp_in_level = total_xp - current_level_xp
    xp_needed = xp_for_level(level)
    return xp_in_level, xp_needed, level


def award_game_xp(user_id: int, xp: int, sp: int = 0) -> int:
    """Award XP/SP earned from games. Returns the level after the award."""
    data = load_user(user_id)
    data["xp"] += xp
    data["sp"] += sp
    data["level"] = level_from_xp(data["xp"])
    save_user(user_id, data)
    return data["level"]


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
                    title=f"🎉 Level Up!",
                    description=f"**{message.author.mention}** reached **Level {data['level']}**!"
                )
                embed.add_field(name="XP", value=f"{xp_gain} xp earned", inline=True)
                embed.add_field(name="SP", value=f"{sp_gain} sp earned", inline=True)
                await message.channel.send(embed=embed)
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
            key_fn = lambda d: d["sp"]
        elif type_key == "messages":
            title = "💬 Messages Leaderboard"
            field_name = "Messages"
            key_fn = lambda d: d["messages"]
        elif type_key == "vc":
            title = "🎤 VC Time Leaderboard"
            field_name = "VC Time"
            key_fn = lambda d: d["vc_time"]
        else:
            type_key = "xp"
            title = "⭐ XP Leaderboard"
            field_name = "XP"
            key_fn = lambda d: d["xp"]

        top = []
        for filename in os.listdir(DATA_DIR):
            if not filename.endswith(".json"):
                continue
            try:
                user_id = int(filename.replace(".json", ""))
                data = load_user(user_id)
                top.append((user_id, data))
            except Exception:
                continue

        top.sort(key=lambda x: key_fn(x[1]), reverse=True)
        top = top[:10]

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
            key_fn = lambda d: d["sp"]
        elif type == "messages":
            title = "💬 Messages Leaderboard"
            field_name = "Messages"
            key_fn = lambda d: d["messages"]
        elif type == "vc":
            title = "🎤 VC Time Leaderboard"
            field_name = "VC Time"
            key_fn = lambda d: d["vc_time"]
        else:
            type = "xp"
            title = "⭐ XP Leaderboard"
            field_name = "XP"
            key_fn = lambda d: d["xp"]

        top = []
        for filename in os.listdir(DATA_DIR):
            if not filename.endswith(".json"):
                continue
            try:
                user_id = int(filename.replace(".json", ""))
                data = load_user(user_id)
                top.append((user_id, data))
            except Exception:
                continue

        top.sort(key=lambda x: key_fn(x[1]), reverse=True)
        top = top[:10]
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(XP(bot))
