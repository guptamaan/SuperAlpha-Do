"""
cogs/spam.py — Spam chain game.
In a configured channel, members take turns sending a single word/emoji.
The same person may not send twice in a row; anyone who sends the target
twice consecutively or sends anything else breaks (resets) the streak and
gets a wilted-rose shaming message.
Data stored in data/spam.db.
Commands: spam, spam channel, spam word, spam start, spam stop, spam reset
"""

import json
import os
import sqlite3

import discord
from discord.ext import commands

DATA_DIR = "data/spam"
CONFIG_FILE = os.path.join(DATA_DIR, "spam.json")
DATABASE_FILE = "data/spam.db"

WILTED_ROSE = "🥀"
ROSE = "🌹"
BROKEN_HEART = "💔"

_db_conn: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        os.makedirs("data", exist_ok=True)
        _db_conn = sqlite3.connect(DATABASE_FILE, check_same_thread=False)
        _db_conn.row_factory = sqlite3.Row
        _db_conn.execute("PRAGMA journal_mode=WAL")
    return _db_conn


def _init_db() -> None:
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spam_config (
            guild_id        INTEGER PRIMARY KEY,
            channel_id      INTEGER,
            word            TEXT,
            enabled         INTEGER NOT NULL DEFAULT 0,
            streak          INTEGER NOT NULL DEFAULT 0,
            best_streak     INTEGER NOT NULL DEFAULT 0,
            last_author_id  INTEGER,
            score_msg_id    INTEGER
        )
    """)
    conn.commit()
    _migrate_legacy_json()


def _load_json(path: str) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _migrate_legacy_json() -> None:
    """One-time import of the old single spam.json into SQLite."""
    count = get_db().execute("SELECT COUNT(*) AS n FROM spam_config").fetchone()["n"]
    if count or not os.path.exists(CONFIG_FILE):
        return
    data = _load_json(CONFIG_FILE)
    for guild_str, stored in data.items():
        try:
            guild_id = int(guild_str)
        except ValueError:
            continue
        if not isinstance(stored, dict):
            continue
        config = _default_config()
        config.update(stored)
        _write_config(guild_id, config)


def _default_config() -> dict:
    return {
        "channel_id": None,
        "word": None,
        "enabled": False,
        "streak": 0,
        "best_streak": 0,
        "last_author_id": None,
        "score_msg_id": None,
    }


def _row_to_config(row: sqlite3.Row) -> dict:
    return {
        "channel_id": row["channel_id"],
        "word": row["word"],
        "enabled": bool(row["enabled"]),
        "streak": row["streak"] or 0,
        "best_streak": row["best_streak"] or 0,
        "last_author_id": row["last_author_id"],
        "score_msg_id": row["score_msg_id"],
    }


def get_config(guild_id: int) -> dict:
    row = get_db().execute(
        "SELECT * FROM spam_config WHERE guild_id = ?", (guild_id,)
    ).fetchone()
    if row is None:
        return _default_config()
    return _row_to_config(row)


def _write_config(guild_id: int, config: dict) -> None:
    conn = get_db()
    conn.execute(
        """
        INSERT INTO spam_config (guild_id, channel_id, word, enabled, streak,
                                 best_streak, last_author_id, score_msg_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            channel_id=excluded.channel_id, word=excluded.word,
            enabled=excluded.enabled, streak=excluded.streak,
            best_streak=excluded.best_streak,
            last_author_id=excluded.last_author_id, score_msg_id=excluded.score_msg_id
        """,
        (
            guild_id,
            config.get("channel_id"),
            config.get("word"),
            int(bool(config.get("enabled"))),
            config.get("streak", 0),
            config.get("best_streak", 0),
            config.get("last_author_id"),
            config.get("score_msg_id"),
        ),
    )
    conn.commit()


def set_config(guild_id: int, config: dict) -> None:
    merged = _default_config()
    merged.update(config)
    _write_config(guild_id, merged)


_init_db()


def _normalise(text: str) -> str:
    return text.strip().lower()


class SpamGame(commands.Cog, name="spam"):
    """The spam chain game."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title, icon_url=None)
        if description:
            embed.description = description
        return embed

    async def _admin_ok(self, ctx: commands.Context) -> bool:
        if ctx.author.guild_permissions.administrator or ctx.author.id == ctx.guild.owner_id:
            return True
        if self.bot.owner_id and ctx.author.id == self.bot.owner_id:
            return True
        embed = self._make_embed(
            "❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission."
        )
        await ctx.send(embed=embed)
        return False

    # ── Commands ──────────────────────────────────────────────────────────────
    @commands.command(name="spam")
    async def spam(self, ctx: commands.Context, action: str = None, *, rest: str = None) -> None:
        """Spam chain game where everyone spams the same word/emoji, one person at a time.

USAGE: alpha spam [subcommand]

SUBCOMMANDS
    status    Show the game state, current streak, and best streak.
    channel   Pick the channel the game runs in.  e.g. alpha spam channel #spam
    word      Choose the exact word/emoji everyone must send.
              e.g. alpha spam word lol  or  alpha spam word 😂
    start     Begin a fresh chain (needs a channel and a word set first).
    stop      Pause the game, keeping the best streak on record.
    reset     Reset the streak and best streak back to zero.

RULES
    In the game channel, everyone takes turns sending the SAME single word
    or emoji — one message per person. A valid send adds 1 to the streak.
    You cannot send twice in a row; another person must send before you can
    send again. Sending the target twice in a row, or sending anything else,
    breaks the chain and resets the streak with a 🥀 message.

EXAMPLES
    alpha spam channel #spam
    alpha spam word lol
    alpha spam start
    alpha spam
        """
        cfg = get_config(ctx.guild.id)

        if not action:
            await self._status(ctx, cfg)
            return

        action = action.lower()

        if action in ["status", "stats", "info", "show"]:
            await self._status(ctx, cfg)
        elif action in ["channel", "chan", "setchannel"]:
            if not await self._admin_ok(ctx):
                return
            await self._set_channel(ctx, cfg, rest)
        elif action in ["word", "target", "setword"]:
            if not await self._admin_ok(ctx):
                return
            await self._set_word(ctx, cfg, rest)
        elif action in ["start", "on", "enable"]:
            if not await self._admin_ok(ctx):
                return
            await self._start(ctx, cfg)
        elif action in ["stop", "off", "disable"]:
            if not await self._admin_ok(ctx):
                return
            await self._stop(ctx, cfg)
        elif action in ["reset", "clear"]:
            if not await self._admin_ok(ctx):
                return
            await self._reset(ctx, cfg)
        else:
            embed = self._make_embed(
                "❌ Invalid Action", 0xE74C3C,
                "Usage: `alpha spam` (status) · `alpha spam channel #channel`\n"
                "`alpha spam word <word/emoji>` · `alpha spam start | stop | reset`",
            )
            await ctx.send(embed=embed)

    async def _status(self, ctx: commands.Context, cfg: dict) -> None:
        target = cfg.get("word") or "not set"
        channel = self.bot.get_channel(cfg.get("channel_id") or 0)
        channel_str = channel.mention if channel else "not set"
        enabled = "✅ Running" if cfg.get("enabled") else "❌ Stopped"

        embed = discord.Embed(color=0x9B59B6)
        embed.set_author(name="🥀 Spam Chain Status")
        embed.add_field(name="Status", value=enabled, inline=True)
        embed.add_field(name="Channel", value=channel_str, inline=True)
        embed.add_field(name="Target", value=f"`{target}`", inline=True)
        embed.add_field(name="Current Streak", value=str(cfg.get("streak", 0)), inline=True)
        embed.add_field(name="Best Streak", value=str(cfg.get("best_streak", 0)), inline=True)

        if not cfg.get("enabled"):
            embed.set_footer(
                text=f"Setup: `{ctx.prefix}spam channel #channel` then `{ctx.prefix}spam word <target>` and `{ctx.prefix}spam start` "
            )
        await ctx.send(embed=embed)

    async def _set_channel(self, ctx: commands.Context, cfg: dict, rest: str | None) -> None:
        if not rest:
            embed = self._make_embed("❌ Missing Channel", 0xE74C3C, "Usage: `alpha spam channel #channel`")
            await ctx.send(embed=embed)
            return
        try:
            channel = await commands.TextChannelConverter().convert(ctx, rest.split()[0])
        except Exception:
            embed = self._make_embed("❌ Invalid Channel", 0xE74C3C, "First argument must be a channel: `#channel`")
            await ctx.send(embed=embed)
            return
        cfg["channel_id"] = channel.id
        set_config(ctx.guild.id, cfg)
        embed = self._make_embed("✅ Channel Set", 0x2ECC71, f"The spam chain now runs in {channel.mention}.")
        await ctx.send(embed=embed)

    async def _set_word(self, ctx: commands.Context, cfg: dict, rest: str | None) -> None:
        if not rest:
            embed = self._make_embed("❌ Missing Target", 0xE74C3C, "Usage: `alpha spam word <word or emoji>`")
            await ctx.send(embed=embed)
            return
        target = rest.strip()
        if len(target) > 64:
            embed = self._make_embed("❌ Too Long", 0xE74C3C, "Keep the target under 64 characters.")
            await ctx.send(embed=embed)
            return
        cfg["word"] = target
        set_config(ctx.guild.id, cfg)
        embed = self._make_embed("✅ Target Set", 0x2ECC71, f"Everyone must send **`{target}`** to keep the chain going.")
        await ctx.send(embed=embed)

    async def _start(self, ctx: commands.Context, cfg: dict) -> None:
        if not cfg.get("channel_id"):
            embed = self._make_embed("❌ No Channel", 0xE74C3C, "Set a channel first: `alpha spam channel #channel`")
            await ctx.send(embed=embed)
            return
        if not cfg.get("word"):
            embed = self._make_embed("❌ No Target", 0xE74C3C, "Set a target first: `alpha spam word <word or emoji>`")
            await ctx.send(embed=embed)
            return
        cfg["enabled"] = True
        cfg["streak"] = 0
        cfg["last_author_id"] = None
        set_config(ctx.guild.id, cfg)

        channel = self.bot.get_channel(cfg["channel_id"])
        score = self._scoreboard_embed(cfg)
        msg = await channel.send(embed=score)
        cfg["score_msg_id"] = msg.id
        set_config(ctx.guild.id, cfg)

        embed = self._make_embed(
            "🥀 Spam Chain Started", 0x2ECC71,
            f"Take turns sending **`{cfg['word']}`** in {channel.mention}. One each, in order —"
            f" send it twice in a row or something else and the chain dies.",
        )
        await ctx.send(embed=embed)

    async def _stop(self, ctx: commands.Context, cfg: dict) -> None:
        cfg["enabled"] = False
        set_config(ctx.guild.id, cfg)
        embed = self._make_embed(
            "🛑 Spam Chain Stopped", 0xE74C3C,
            f"Best streak this run: **{cfg.get('best_streak', 0)}**. "
            f"Restart with `{ctx.prefix}spam start`.",
        )
        await ctx.send(embed=embed)

    async def _reset(self, ctx: commands.Context, cfg: dict) -> None:
        cfg["streak"] = 0
        cfg["best_streak"] = 0
        cfg["last_author_id"] = None
        set_config(ctx.guild.id, cfg)
        embed = self._make_embed("🧹 Draft Clear", 0x95A5A6, "The streak has been reset to zero.")
        await ctx.send(embed=embed)

    # ── Scoreboard ────────────────────────────────────────────────────────────
    def _scoreboard_embed(self, cfg: dict) -> discord.Embed:
        embed = discord.Embed(color=0x9B59B6)
        embed.set_author(name="🥀 Spam Chain")
        if cfg.get("last_author_id"):
            last = f"<@{cfg['last_author_id']}>"
        else:
            last = "no one yet"
        embed.description = (
            f"**Streak: {cfg.get('streak', 0)}**\n"
            f"Target: `{cfg.get('word')}`\n"
            f"Best: {cfg.get('best_streak', 0)}\n"
            f"Last spammed by: {last}"
        )
        return embed

    async def _update_scoreboard(self, cfg: dict, channel: discord.TextChannel) -> None:
        msg_id = cfg.get("score_msg_id")
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=self._scoreboard_embed(cfg))
                return
            except Exception:
                pass
        try:
            msg = await channel.send(embed=self._scoreboard_embed(cfg))
            cfg["score_msg_id"] = msg.id
        except Exception:
            pass

    # ── Listener ──────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        try:
            await self._handle_message(message)
        except Exception:
            import traceback
            traceback.print_exc()

    async def _handle_message(self, message: discord.Message) -> None:
        cfg = get_config(message.guild.id)
        if not cfg.get("enabled"):
            return
        if message.channel.id != cfg.get("channel_id"):
            return

        content = message.content.strip()
        if not content:
            return
        lowered = content.lower()
        if lowered.startswith(("alpha ", "sudo ")):
            return

        target = _normalise(cfg.get("word") or "")
        if not target:
            return
        is_target = lowered == target
        last_author = cfg.get("last_author_id")

        if is_target:
            if last_author == message.author.id:
                await self._break_streak(message, cfg, reason="twice")
                return
            cfg["streak"] = cfg.get("streak", 0) + 1
            cfg["last_author_id"] = message.author.id
            if cfg["streak"] > cfg.get("best_streak", 0):
                cfg["best_streak"] = cfg["streak"]
            set_config(message.guild.id, cfg)
            await self._update_scoreboard(cfg, message.channel)
            return

        if cfg.get("streak", 0) >= 1:
            await self._break_streak(message, cfg, reason="other")

    async def _break_streak(self, message: discord.Message, cfg: dict, reason: str) -> None:
        broke_at = cfg.get("streak", 0)
        cfg["streak"] = 0
        cfg["last_author_id"] = None
        set_config(message.guild.id, cfg)
        await self._update_scoreboard(cfg, message.channel)

        embed = discord.Embed(color=0xE74C3C)
        embed.set_author(name=f"{WILTED_ROSE} Spam Chain Broken...")
        if reason == "twice":
            embed.description = (
                f"{ROSE} **{message.author.mention}** was too greedy and sent "
                f"**`{cfg.get('word')}`** twice in a row! {WILTED_ROSE}"
            )
        else:
            embed.description = (
                f"{ROSE} **{message.author.mention}** ruined the chain by sending "
                f"something else! {WILTED_ROSE} {BROKEN_HEART}"
            )
        embed.add_field(name="Streak ended at", value=str(broke_at), inline=True)
        embed.add_field(name="Best streak", value=str(cfg.get("best_streak", 0)), inline=True)
        embed.set_footer(text=f"Send **`{cfg.get('word')}`** to start a new chain. {ROSE}")
        if broke_at >= 1:
            embed.description += f"\n\n**The streak ended at {broke_at}!**"
        await message.channel.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SpamGame(bot))