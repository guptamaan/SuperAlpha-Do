"""
cogs/distro.py — Guess-the-Linux-distro game.
The bot picks a random image from the distro/ folder and posts it with a
"guess the distro" prompt. The first person to name the distro correctly
wins XP and SP; the image message is then deleted.

Persistence lives in ``bot.models.distro_store``; game rules (tiers, hints,
answer matching) in ``bot.services.distro_game``. This module re-exports those
symbols so existing imports (``from bot.cogs.distro import _tier_for``) work.
"""

import asyncio
import random
import time

import discord
from discord.ext import commands

from bot.models.distro_store import (
    DISTRO_DIR,
    ENABLED_FILE,
    METADATA_FILE,
    STATS_FILE,
    _guild_stats,
    _load_json,
    _load_metadata,
    _save_guild_stats,
    _save_json,
    get_spawn_channel,
    is_enabled,
    set_enabled,
    set_spawn_channel,
)
from bot.models.xp_store import load_user
from bot.services.distro_game import (
    EXPIRE_TIMEOUT,
    FIRST_HINT_DELAY,
    GUESS_COOLDOWN,
    HINT_PENALTY,
    IMAGE_EXTENSIONS,
    MANAGED_FILES,
    MIN_SP,
    MIN_XP,
    SECOND_HINT_DELAY,
    TIER_COLORS,
    TIER_REWARDS,
    _AUTO_SPAWN_MAX,
    _AUTO_SPAWN_MIN,
    _accepted_answers,
    _answer_variants,
    _image_files,
    _metadata_for,
    _normalise_text,
    _primary_name,
    _tier_for,
)
from bot.services.leveling import award_game_xp

DEFAULT_TIER = "medium"

__all__ = [
    "DISTRO_DIR",
    "ENABLED_FILE",
    "EXPIRE_TIMEOUT",
    "FIRST_HINT_DELAY",
    "GUESS_COOLDOWN",
    "HINT_PENALTY",
    "METADATA_FILE",
    "MIN_SP",
    "MIN_XP",
    "SECOND_HINT_DELAY",
    "STATS_FILE",
    "TIER_REWARDS",
    "Distro",
    "_accepted_answers",
    "_answer_variants",
    "_image_files",
    "_load_metadata",
    "_metadata_for",
    "_normalise_text",
    "_primary_name",
    "_tier_for",
    "get_spawn_channel",
    "is_enabled",
    "set_enabled",
    "set_spawn_channel",
]


class Distro(commands.Cog, name="distro"):
    """Guess-the-Linux-distro image game."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.active: dict[int, dict] = {}
        self._last_guess: dict[int, float] = {}
        self._timer: asyncio.Task | None = None

    @staticmethod
    def _round_active(active: dict[int, dict], channel_id: int) -> bool:
        r = active.get(channel_id)
        return r is not None and not r["solved"]

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title, icon_url=None)
        if description:
            embed.description = description
        return embed

    async def cog_load(self) -> None:
        self._timer = asyncio.create_task(self._auto_spawn_loop())

    async def cog_unload(self) -> None:
        if self._timer:
            self._timer.cancel()

    # ── Auto spawner ─────────────────────────────────────────────────────────
    async def _auto_spawn_loop(self) -> None:
        while True:
            await asyncio.sleep(random.randint(_AUTO_SPAWN_MIN, _AUTO_SPAWN_MAX))
            try:
                await self._auto_spawn_once()
            except Exception:
                import traceback
                traceback.print_exc()

    async def _auto_spawn_once(self) -> None:
        guild_ids = [int(g) for g in _load_json(ENABLED_FILE).get("guilds", [])]
        random.shuffle(guild_ids)
        for guild_id in guild_ids:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue

            def eligible(ch: discord.TextChannel) -> bool:
                return (
                    self.active.get(ch.id) is None
                    and not ch.is_nsfw()
                    and ch.permissions_for(guild.me).send_messages
                    and ch.permissions_for(guild.me).attach_files
                )

            host = None
            pinned = self.bot.get_channel(get_spawn_channel(guild_id))
            if isinstance(pinned, discord.TextChannel) and pinned.guild is guild and eligible(pinned):
                host = pinned
            if host is None:
                candidates = [c for c in guild.text_channels if eligible(c)]
                if candidates:
                    host = random.choice(candidates)
            if host is None:
                continue
            await self._spawn(host)
            return

    # ── Round lifecycle ──────────────────────────────────────────────────────
    async def _spawn(self, channel: discord.TextChannel, poster_id: int | None = None) -> tuple[bool, str]:
        if self.active.get(channel.id):
            return False, "A distro is already spawned in this channel. Guess it first!"

        images = _image_files()
        if not images:
            return False, f"No images found in `{DISTRO_DIR}/`. Drop a Linux distro image there first (named e.g. `arch.png`)."

        if not (channel.permissions_for(channel.guild.me).send_messages
                and channel.permissions_for(channel.guild.me).attach_files):
            return False, "I need permission to send messages and attach files here."

        image_path = random.choice(images)
        base = _primary_name(image_path.stem)
        tier = _tier_for(image_path.stem)
        data = _metadata_for(image_path.stem)
        display = data.get("name") or base.title() or image_path.stem
        hints = [str(h) for h in (data.get("hints") or [])][:2]
        variants = _accepted_answers(image_path.stem)

        # Reserve the slot before any await so concurrent spawns can't double-post.
        self.active[channel.id] = {"solved": True, "message": None}

        try:
            file = discord.File(str(image_path))
            msg = await channel.send("What distro is this? First correct answer wins XP.", file=file)
        except discord.Forbidden:
            self.active.pop(channel.id, None)
            return False, "I don't have permission to send files in this channel."
        except discord.HTTPException:
            self.active.pop(channel.id, None)
            return False, "I couldn't send the image. It may be too large for Discord."

        try:
            stats = _guild_stats(channel.guild.id)
            stats["spawns"] += 1
            _save_guild_stats(channel.guild.id, stats)
        except Exception:
            self.active.pop(channel.id, None)
            return False, "I couldn't record the round. Please try again."

        self.active[channel.id] = {
            "channel_id": channel.id,
            "guild_id": channel.guild.id,
            "answer": base,
            "display": display,
            "tier": tier,
            "variants": variants,
            "hints": hints,
            "hints_used": 0,
            "reward": TIER_REWARDS[tier],
            "message": msg,
            "solved": False,
            "task": None,
        }
        self.active[channel.id]["task"] = asyncio.create_task(self._run_timeline(channel.id))
        return True, ""

    async def _run_timeline(self, channel_id: int) -> None:
        """Drives the round lifecycle: hint at 45s, hint at 150s, expire at 180s."""
        await asyncio.sleep(FIRST_HINT_DELAY)
        if not self._round_active(self.active, channel_id):
            return
        await self._send_hint(channel_id, 0)

        await asyncio.sleep(SECOND_HINT_DELAY - FIRST_HINT_DELAY)
        if not self._round_active(self.active, channel_id):
            return
        await self._send_hint(channel_id, 1)

        await asyncio.sleep(EXPIRE_TIMEOUT - SECOND_HINT_DELAY)
        if not self._round_active(self.active, channel_id):
            return
        await self._expire_round(channel_id)

    async def _send_hint(self, channel_id: int, index: int) -> None:
        r = self.active.get(channel_id)
        if not r or r["solved"]:
            return
        hints = r.get("hints") or []
        if index >= len(hints):
            return
        await asyncio.sleep(0.05)
        if not self._round_active(self.active, channel_id):
            return
        r["hints_used"] = r.get("hints_used", 0) + 1
        hint = hints[index]
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        try:
            embed = self._make_embed(
                "💡 Hint", 0x3498DB, f"**{index + 1}.** {hint}"
            )
            embed.set_footer(text="Hints reduce the XP reward. Reply in chat to guess.")
            await channel.send(embed=embed)
        except Exception:
            r["hints_used"] -= 1

    async def _expire_round(self, channel_id: int) -> None:
        r = self.active.get(channel_id)
        if not r or r["solved"]:
            return
        r["solved"] = True
        self.active.pop(channel_id, None)
        try:
            await r["message"].delete()
        except Exception:
            pass
        try:
            channel = self.bot.get_channel(channel_id)
            if channel:
                embed = self._make_embed(
                    "⌛ Round Expired", 0x95A5A6,
                    f"Nobody guessed it in time. The answer was **{r['display']}** "
                    f"({r['tier']} difficulty).",
                )
                await channel.send(embed=embed)
        except Exception:
            pass

    # ── Solving ──────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        try:
            await self._maybe_solve(message)
        except Exception:
            import traceback
            traceback.print_exc()

    async def _maybe_solve(self, message: discord.Message) -> None:
        r = self.active.get(message.channel.id)
        if not r or r["solved"]:
            return
        guess = _normalise_text(message.content)
        if not guess:
            return
        if guess in r["variants"]:
            self._prune_guess_tracker()
            r["solved"] = True
            self.active.pop(message.channel.id, None)
            if r.get("task"):
                r["task"].cancel()
            await self._award_win(message, r)
            return
        # Wrong guess: throttle per user so nobody can brute-force a list.
        now = time.monotonic()
        last = self._last_guess.get(message.author.id)
        if last is not None and now - last < GUESS_COOLDOWN:
            return
        self._last_guess[message.author.id] = now

    def _prune_guess_tracker(self) -> None:
        cutoff = time.monotonic() - EXPIRE_TIMEOUT * 2
        for uid in [uid for uid, t in self._last_guess.items() if t < cutoff]:
            del self._last_guess[uid]

    async def _award_win(self, message: discord.Message, r: dict) -> None:
        winner = message.author
        stats = _guild_stats(r["guild_id"])
        stats["solved"] += 1
        stats["users"][str(winner.id)] = stats["users"].get(str(winner.id), 0) + 1
        _save_guild_stats(r["guild_id"], stats)

        hints_used = r.get("hints_used", 0)
        reward = r.get("reward") or TIER_REWARDS[DEFAULT_TIER]
        factor = HINT_PENALTY ** hints_used
        xp = max(MIN_XP, round(reward["xp"] * factor))
        sp = max(MIN_SP, round(reward["sp"] * factor))

        prev_level = int(load_user(winner.id).get("level", 1) or 1)
        new_level = award_game_xp(winner.id, xp, sp)

        try:
            await r["message"].delete()
        except Exception:
            pass

        embed_title = "✅ Correct! Distro Identified"
        color = TIER_COLORS.get(r["tier"], 0x2ECC71)
        description = (
            f"{winner.mention} identified **{r['display']}** "
            f"({r['tier']} difficulty" + (f", {hints_used} hint{'s' if hints_used != 1 else ''} used" if hints_used else "") + ") "
            f"and earned **{xp} XP** and **{sp} SP**."
        )
        if new_level > prev_level:
            description += f"\n**LEVEL UP!** {winner.mention} is now **level {new_level}**."
        embed = self._make_embed(embed_title, color, description)
        embed.set_footer(text=f"Solved by {winner.display_name} · Next round coming soon.")
        await message.channel.send(embed=embed)

    # ── Commands ─────────────────────────────────────────────────────────────
    @commands.command(name="distro", aliases=["distroguess"])
    async def distro(self, ctx: commands.Context, action: str = None, *, rest: str = None) -> None:
        """Distro guessing game. Usage: alpha distro [spawn|end|stats]"""
        if not action:
            await self._status(ctx)
            return

        action = action.lower()

        if action in ["spawn", "start", "generate"]:
            await self._spawn_cmd(ctx)
        elif action in ["end", "stop", "finish"]:
            await self._end_cmd(ctx)
        elif action in ["stats", "score", "top"]:
            await self._stats_cmd(ctx)
        elif action in ["channel", "chan", "host"]:
            await self._channel_cmd(ctx, rest)
        else:
            embed = self._make_embed(
                "❌ Invalid Action", 0xE74C3C,
                "Usage: `alpha distro` (status) · `alpha distro spawn`\n"
                "`alpha distro end` · `alpha distro stats` · `alpha distro channel [channel|clear]`",
            )
            await ctx.send(embed=embed)

    async def _status(self, ctx: commands.Context) -> None:
        guild = ctx.guild
        enabled = is_enabled(guild.id)
        round_active = self.active.get(ctx.channel.id) is not None
        images = len(_image_files())
        stats = _guild_stats(guild.id)
        pinned = self.bot.get_channel(get_spawn_channel(guild.id))

        embed = discord.Embed(color=0x9B59B6)
        embed.set_author(name="🐧 Distro Game Status")
        embed.add_field(name="Enabled", value="Yes" if enabled else "No", inline=True)
        embed.add_field(name="Round Here", value="Active" if round_active else "None", inline=True)
        embed.add_field(name="Images Available", value=str(images), inline=True)
        embed.add_field(
            name="Spawn Channel",
            value=pinned.mention if isinstance(pinned, discord.TextChannel) else "Random",
            inline=True,
        )
        embed.add_field(name="Rounds Spawned", value=str(stats.get("spawns", 0)), inline=True)
        embed.add_field(name="Rounds Solved", value=str(stats.get("solved", 0)), inline=True)
        if not enabled:
            embed.set_footer(text=f"Enable with `{ctx.prefix}enable distro`")
        else:
            embed.set_footer(text=f"Spawn a round with `{ctx.prefix}distro spawn`")
        await ctx.send(embed=embed)

    async def _spawn_cmd(self, ctx: commands.Context) -> None:
        if not is_enabled(ctx.guild.id):
            embed = self._make_embed(
                "❌ Feature Disabled", 0xE74C3C,
                f"The distro game is not enabled here. An admin can enable it with `{ctx.prefix}enable distro`.",
            )
            await ctx.send(embed=embed)
            return
        ok, feedback = await self._spawn(ctx.channel, poster_id=ctx.author.id)
        if not ok:
            await ctx.send(embed=self._make_embed("❌ Cannot Spawn", 0xE74C3C, feedback))

    async def _end_cmd(self, ctx: commands.Context) -> None:
        if not (ctx.author.guild_permissions.administrator or ctx.author.id == ctx.guild.owner_id):
            embed = self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission.")
            await ctx.send(embed=embed)
            return
        r = self.active.get(ctx.channel.id)
        if not r:
            embed = self._make_embed("❌ No Round", 0xE74C3C, "There is no active distro round in this channel.")
            await ctx.send(embed=embed)
            return
        r["solved"] = True
        self.active.pop(ctx.channel.id, None)
        if r.get("task"):
            r["task"].cancel()
        try:
            await r["message"].delete()
        except Exception:
            pass
        embed = self._make_embed("🛑 Round Ended", 0x95A5A6, "The distro round was ended by a moderator.")
        await ctx.send(embed=embed)

    async def _channel_cmd(self, ctx: commands.Context, rest: str | None) -> None:
        if not (ctx.author.guild_permissions.administrator or ctx.author.id == ctx.guild.owner_id):
            embed = self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission.")
            await ctx.send(embed=embed)
            return

        if rest is None:
            pinned = self.bot.get_channel(get_spawn_channel(ctx.guild.id))
            value = pinned.mention if isinstance(pinned, discord.TextChannel) else "Any random channel"
            embed = self._make_embed(
                "📌 Distro Spawn Channel", 0x9B59B6,
                f"Auto-spawns currently go to: **{value}**.",
            )
            embed.set_footer(text=f"`{ctx.prefix}distro channel #channel` to pin · `distro channel clear` to randomise")
            await ctx.send(embed=embed)
            return

        rest = rest.strip()
        if rest.lower() in ("clear", "none", "off", "reset", "remove"):
            set_spawn_channel(ctx.guild.id, None)
            embed = self._make_embed(
                "📌 Distro Spawn Channel", 0x95A5A6,
                "Auto-spawns will now go to a **random** eligible channel.",
            )
            await ctx.send(embed=embed)
            return

        target = None
        if rest.startswith("<#") and rest.endswith(">"):
            try:
                target = ctx.guild.get_channel(int(rest[2:-1]))
            except ValueError:
                target = None
        elif rest.isdigit():
            target = ctx.guild.get_channel(int(rest))
        if target is None:
            target = discord.utils.get(ctx.guild.text_channels, name=rest.lstrip("#"))

        if not isinstance(target, discord.TextChannel):
            embed = self._make_embed(
                "❌ Cannot Pin", 0xE74C3C,
                f"I couldn't find a text channel matching `{rest}`.\nUsage: `{ctx.prefix}distro channel #channel` or `distro channel clear`.",
            )
            await ctx.send(embed=embed)
            return
        if target.is_nsfw():
            embed = self._make_embed("❌ Cannot Pin", 0xE74C3C, "NSFW channels can't host distro rounds.")
            await ctx.send(embed=embed)
            return

        set_spawn_channel(ctx.guild.id, target.id)
        embed = self._make_embed(
            "📌 Distro Spawn Channel", 0x2ECC71,
            f"Auto-spawned rounds will now appear in {target.mention}.",
        )
        await ctx.send(embed=embed)

    async def _stats_cmd(self, ctx: commands.Context) -> None:
        stats = _guild_stats(ctx.guild.id)
        embed = discord.Embed(color=0x9B59B6)
        embed.set_author(name="🐧 Distro Game Stats")
        embed.add_field(name="Rounds Spawned", value=str(stats.get("spawns", 0)), inline=True)
        embed.add_field(name="Rounds Solved", value=str(stats.get("solved", 0)), inline=True)
        users = stats.get("users", {})
        if users:
            lines = sorted(users.items(), key=lambda kv: kv[1], reverse=True)[:10]
            embed.add_field(
                name="Top Guesser(s)",
                value="\n".join(f"<@{uid}> · {count}" for uid, count in lines),
                inline=False,
            )
        else:
            embed.add_field(name="Top Guesser(s)", value="No solves yet.", inline=False)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Distro(bot))