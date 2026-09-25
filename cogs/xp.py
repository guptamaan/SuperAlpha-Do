"""
cogs/xp.py — XP and ranking system with SP currency.
Awards XP/SP for: chatting, VC time, using bot commands.
"""

import asyncio
import json
import os
import sqlite3
import time
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from cogs.checks import perms_or_developer


DATA_DIR = "data/xp"
CONFIG_FILE = "data/xp/config.json"
DATABASE_FILE = "data/xp.db"
os.makedirs(DATA_DIR, exist_ok=True)

_user_cache: dict[int, dict] = {}
_dirty_users: set[int] = set()
_SAVE_INTERVAL = 120
_config_cache: dict | None = None
_config_cache_loaded = 0.0
_CONFIG_CACHE_TTL = 10

_db_conn: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        os.makedirs("data", exist_ok=True)
        _db_conn = sqlite3.connect(DATABASE_FILE, check_same_thread=False)
        _db_conn.row_factory = sqlite3.Row
        _db_conn.execute("PRAGMA journal_mode=WAL")
    return _db_conn


def init_db() -> None:
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS xp_users (
            user_id        INTEGER PRIMARY KEY,
            xp             INTEGER NOT NULL DEFAULT 0,
            level          INTEGER NOT NULL DEFAULT 1,
            sp             INTEGER NOT NULL DEFAULT 0,
            messages       INTEGER NOT NULL DEFAULT 0,
            vc_time        INTEGER NOT NULL DEFAULT 0,
            commands_used  INTEGER NOT NULL DEFAULT 0,
            last_message   REAL    NOT NULL DEFAULT 0,
            vc_start       REAL    NOT NULL DEFAULT 0,
            daily_claimed  TEXT,
            streak         INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    _migrate_legacy_json()


def _default_user() -> dict:
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


def _migrate_legacy_json() -> None:
    """One-time import of old per-user JSON files into SQLite."""
    count = get_db().execute("SELECT COUNT(*) AS n FROM xp_users").fetchone()["n"]
    if count:
        return
    if not os.path.isdir(DATA_DIR):
        return
    for filename in os.listdir(DATA_DIR):
        if not filename.endswith(".json"):
            continue
        try:
            user_id = int(filename[:-5])
        except ValueError:
            continue
        try:
            with open(os.path.join(DATA_DIR, filename)) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        merged = _default_user()
        merged.update({k: v for k, v in data.items() if k in merged})
        _upsert_user(user_id, merged)


def _row_to_user(row: sqlite3.Row) -> dict:
    return {
        "xp": int(row["xp"] or 0),
        "level": int(row["level"] or 1),
        "sp": int(row["sp"] or 0),
        "messages": int(row["messages"] or 0),
        "vc_time": int(row["vc_time"] or 0),
        "commands_used": int(row["commands_used"] or 0),
        "last_message": float(row["last_message"] or 0),
        "vc_start": float(row["vc_start"] or 0),
        "daily_claimed": row["daily_claimed"],
        "streak": int(row["streak"] or 0),
    }


def _load_user_from_disk(user_id: int) -> dict:
    row = get_db().execute(
        "SELECT * FROM xp_users WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row is not None:
        return _row_to_user(row)
    return _default_user()


def load_user(user_id: int) -> dict:
    if user_id not in _user_cache:
        _user_cache[user_id] = _load_user_from_disk(user_id)
    return _user_cache[user_id]


def save_user(user_id: int, data: dict) -> None:
    _user_cache[user_id] = data
    _dirty_users.add(user_id)


def _upsert_user(user_id: int, data: dict) -> None:
    merged = _default_user()
    merged.update(data)
    conn = get_db()
    conn.execute(
        """
        INSERT INTO xp_users (user_id, xp, level, sp, messages, vc_time,
                              commands_used, last_message, vc_start, daily_claimed, streak)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            xp=excluded.xp, level=excluded.level, sp=excluded.sp,
            messages=excluded.messages, vc_time=excluded.vc_time,
            commands_used=excluded.commands_used, last_message=excluded.last_message,
            vc_start=excluded.vc_start, daily_claimed=excluded.daily_claimed,
            streak=excluded.streak
        """,
        (
            user_id,
            int(merged["xp"] or 0),
            int(merged["level"] or 1),
            int(merged["sp"] or 0),
            int(merged["messages"] or 0),
            int(merged["vc_time"] or 0),
            int(merged["commands_used"] or 0),
            float(merged["last_message"] or 0),
            float(merged["vc_start"] or 0),
            merged["daily_claimed"],
            int(merged["streak"] or 0),
        ),
    )
    conn.commit()


def _flush_user(user_id: int) -> None:
    if user_id not in _dirty_users:
        return
    data = _user_cache.get(user_id)
    if data is None:
        _dirty_users.discard(user_id)
        return
    _upsert_user(user_id, data)
    _dirty_users.discard(user_id)


def flush_all() -> None:
    for uid in list(_dirty_users):
        _flush_user(uid)


_TOP_COLUMNS = {"xp": "xp", "sp": "sp", "messages": "messages", "vc": "vc_time"}


def top_users(key: str, limit: int = 10) -> list[tuple[int, dict]]:
    """Top `limit` users ranked by a stat key, as [(user_id, data), ...]."""
    column = _TOP_COLUMNS.get(key, "xp")
    rows = get_db().execute(
        f"SELECT * FROM xp_users ORDER BY {column} DESC, user_id ASC LIMIT ?",
        (limit,),
    ).fetchall()
    return [(int(r["user_id"]), _row_to_user(r)) for r in rows]


init_db()


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


def get_level_channel(guild_id: int) -> int | None:
    config = load_config()
    data = config.get(str(guild_id))
    if data:
        return data.get("level_channel")
    return None


def set_level_channel(guild_id: int, channel_id: int | None) -> None:
    config = load_config()
    if str(guild_id) not in config:
        config[str(guild_id)] = {"enabled": True}
    config[str(guild_id)]["level_channel"] = channel_id
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
