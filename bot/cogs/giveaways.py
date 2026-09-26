"""
cogs/giveaways.py — Giveaway system.
Create reaction-entry giveaways that auto-end on a timer or via command.
Active giveaways are persisted so they survive restarts.
Commands: giveaway, giveaway create, giveaway end, giveaway reroll, giveaway cancel, giveaway list
"""

import asyncio
import json
import os
import random
import re
import time

import discord
from discord.ext import commands

from bot.cogs.checks import perms_or_developer

DATA_DIR = "data/giveaways"
DATA_FILE = os.path.join(DATA_DIR, "giveaways.json")
MAX_DURATION = 30 * 86400  # 30 days
SWEEP_INTERVAL = 10
ENTRY_EMOJI = "🎉"

_TIME_RE = re.compile(r"^(\d+)([smhdw])$")
_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _load_json(path: str) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _parse_duration(text: str) -> int | None:
    """Parse a duration like 30s, 10m, 2h, 1d, 1w. Returns seconds or None."""
    match = _TIME_RE.match(text.strip().lower())
    if not match:
        return None
    amount = int(match.group(1))
    seconds = amount * _MULTIPLIERS[match.group(2)]
    if seconds <= 0 or seconds > MAX_DURATION:
        return None
    return seconds


def _fmt_duration(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


class Giveaways(commands.Cog, name="giveaways"):
    """Reaction-entry giveaways."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._sweep_task: asyncio.Task | None = None

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title, icon_url=None)
        if description:
            embed.description = description
        return embed

    def _load(self) -> dict:
        return _load_json(DATA_FILE)

    def _save(self, data: dict) -> None:
        _save_json(DATA_FILE, data)

    async def cog_load(self) -> None:
        self._sweep_task = asyncio.create_task(self._sweep())

    async def cog_unload(self) -> None:
        if self._sweep_task:
            self._sweep_task.cancel()

    async def _sweep(self) -> None:
        """End any giveaways whose timer has expired."""
        while True:
            try:
                data = self._load()
                now = time.time()
                for key, gw in list(data.items()):
                    if now >= gw["end_ts"]:
                        await self._finish_giveaway(gw, data)
                        data.pop(key, None)
                if data:
                    self._save(data)
            except Exception:
                import traceback
                traceback.print_exc()
            await asyncio.sleep(SWEEP_INTERVAL)

    @commands.command(name="giveaway")
    async def giveaway(self, ctx: commands.Context, action: str = None, *, rest: str = None) -> None:
        """Run giveaways. Usage: alpha giveaway [create|end|reroll|cancel|list]"""
        if not action:
            data = self._load()
            active = [gw for gw in data.values() if gw.get("guild_id") == ctx.guild.id]
            if not active:
                embed = self._make_embed("🎉 Giveaways", 0x9B59B6, "No active giveaways in this server.")
                await ctx.send(embed=embed)
                return
            embed = discord.Embed(color=0x9B59B6)
            embed.set_author(name="🎉 Active Giveaways")
            lines = []
            for gw in active:
                remaining = int(gw["end_ts"] - time.time())
                lines.append(
                    f"• **{gw['prize']}** — {len(gw.get('entries') or [])} entries · ends in {_fmt_duration(max(remaining, 0))} · "
                    f"[link](https://discord.com/channels/{gw['guild_id']}/{gw['channel_id']}/{gw['message_id']})"
                )
            embed.description = "\n".join(lines)
            await ctx.send(embed=embed)
            return

        action = action.lower()

        if action in ["create", "new", "start"]:
            await self._create(ctx, rest)
        elif action in ["end", "finish", "close"]:
            await self._end(ctx, rest)
        elif action in ["reroll"]:
            await self._reroll(ctx, rest)
        elif action in ["cancel", "delete"]:
            await self._cancel(ctx, rest)
        elif action in ["list", "active"]:
            await self.giveaway(ctx)
        else:
            embed = self._make_embed(
                "❌ Invalid Action", 0xE74C3C,
                "Usage: `alpha giveaway create #channel <time> [winners] <prize>`\n"
                "`alpha giveaway end <message-id>` · `alpha giveaway reroll <message-id>`\n"
                "`alpha giveaway cancel <message-id>` · `alpha giveaway list`",
            )
            await ctx.send(embed=embed)

    async def _create(self, ctx: commands.Context, rest: str | None) -> None:
        if not ctx.author.guild_permissions.administrator and not await self.bot.is_owner(ctx.author):
            embed = self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission.")
            await ctx.send(embed=embed)
            return

        if not rest:
            embed = self._make_embed("❌ Missing Args", 0xE74C3C, "Usage: `alpha giveaway create #channel <time> [winners] <prize>`")
            await ctx.send(embed=embed)
            return

        parts = rest.split()
        channel = None
        try:
            channel = await commands.TextChannelConverter().convert(ctx, parts[0])
        except Exception:
            channel = None
        if channel is None:
            embed = self._make_embed("❌ Invalid Channel", 0xE74C3C, "First argument must be a channel: `#channel`")
            await ctx.send(embed=embed)
            return

        seconds = None
        winners = 1
        prize_start = 2
        if len(parts) > 1:
            seconds = _parse_duration(parts[1])
        if seconds is None:
            embed = self._make_embed("❌ Invalid Duration", 0xE74C3C, "Time format: `30s`, `10m`, `2h`, `1d`, `1w` (max 30d)")
            await ctx.send(embed=embed)
            return

        if len(parts) > 2 and parts[2].isdigit():
            winners = max(1, int(parts[2]))
            prize_start = 3

        prize = " ".join(parts[prize_start:]).strip()
        if not prize:
            embed = self._make_embed("❌ No Prize", 0xE74C3C, "Provide a prize name after the duration.")
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(color=0xF1C40F)
        embed.set_author(name="🎉 GIVEAWAY")
        embed.description = prize
        embed.add_field(name="Winners", value=str(winners), inline=True)
        embed.add_field(name="Ends", value=f"<t:{int(time.time() + seconds)}:R>", inline=True)
        embed.add_field(name="Hosted by", value=ctx.author.mention, inline=True)
        embed.set_footer(text="React with 🎉 to enter!")
        msg = await channel.send(embed=embed)
        await msg.add_reaction(ENTRY_EMOJI)

        key = f"{ctx.guild.id}:{msg.id}"
        data = self._load()
        data[key] = {
            "guild_id": ctx.guild.id,
            "channel_id": channel.id,
            "message_id": msg.id,
            "prize": prize,
            "winners": winners,
            "host_id": ctx.author.id,
            "end_ts": time.time() + seconds,
        }
        self._save(data)

        confirm = self._make_embed(
            "🎉 Giveaway Started", 0x2ECC71,
            f"**{prize}** — {winners} winner(s), ends {_fmt_duration(seconds)} in {channel.mention}.",
        )
        await ctx.send(embed=confirm)

    async def _end(self, ctx: commands.Context, rest: str | None) -> None:
        if not ctx.author.guild_permissions.administrator and not await self.bot.is_owner(ctx.author):
            embed = self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission.")
            await ctx.send(embed=embed)
            return
        gw = await self._find_by_message_id(ctx, rest)
        if not gw:
            return
        data = self._load()
        key = f"{ctx.guild.id}:{gw['message_id']}"
        await self._finish_giveaway(gw, data)
        data.pop(key, None)
        self._save(data)

    async def _reroll(self, ctx: commands.Context, rest: str | None) -> None:
        if not ctx.author.guild_permissions.administrator and not await self.bot.is_owner(ctx.author):
            embed = self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission.")
            await ctx.send(embed=embed)
            return

        if not rest:
            embed = self._make_embed("❌ Missing Message ID", 0xE74C3C, "Usage: `alpha giveaway reroll <message-id>`")
            await ctx.send(embed=embed)
            return
        try:
            msg_id = int(rest.strip().split()[0])
        except ValueError:
            embed = self._make_embed("❌ Invalid ID", 0xE74C3C, "That's not a valid message ID.")
            await ctx.send(embed=embed)
            return
        channel = ctx.channel
        try:
            msg = await channel.fetch_message(msg_id)
        except Exception:
            embed = self._make_embed("❌ Not Found", 0xE74C3C, "Couldn't find that giveaway message in this channel.")
            await ctx.send(embed=embed)
            return

        entries, host_id = await self._get_entries(msg)
        if not entries:
            embed = self._make_embed("❌ No Entries", 0xE74C3C, "Nobody entered — nothing to reroll.")
            await ctx.send(embed=embed)
            return

        prize = str(msg.embeds[0].description) if msg.embeds else "Prize"
        winner = random.choice(entries)
        await ctx.send(
            f"🎉 **Reroll!** New winner of **{prize}**: {winner.mention}!"
        )

    async def _cancel(self, ctx: commands.Context, rest: str | None) -> None:
        if not ctx.author.guild_permissions.administrator and not await self.bot.is_owner(ctx.author):
            embed = self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission.")
            await ctx.send(embed=embed)
            return
        gw = await self._find_by_message_id(ctx, rest)
        if not gw:
            return
        data = self._load()
        data.pop(f"{ctx.guild.id}:{gw['message_id']}", None)
        self._save(data)
        try:
            channel = self.bot.get_channel(gw["channel_id"])
            msg = await channel.fetch_message(gw["message_id"])
            embed = self._make_embed("❌ Giveaway Cancelled", 0xE74C3C, "This giveaway was cancelled by a moderator.")
            await msg.edit(embed=embed)
        except Exception:
            pass
        confirm = self._make_embed("🗑️ Cancelled", 0x95A5A6, f"Cancelled giveaway **{gw['prize']}**.")
        await ctx.send(embed=confirm)

    async def _find_by_message_id(self, ctx: commands.Context, rest: str | None):
        if not rest:
            embed = self._make_embed("❌ Missing Message ID", 0xE74C3C, "Usage: `alpha giveaway end <message-id>`")
            await ctx.send(embed=embed)
            return None
        try:
            msg_id = int(rest.strip().split()[0])
        except ValueError:
            embed = self._make_embed("❌ Invalid ID", 0xE74C3C, "That's not a valid message ID.")
            await ctx.send(embed=embed)
            return None
        data = self._load()
        gw = data.get(f"{ctx.guild.id}:{msg_id}")
        if not gw:
            embed = self._make_embed("❌ Not Found", 0xE74C3C, "No active giveaway with that message ID.")
            await ctx.send(embed=embed)
            return None
        return gw

    async def _get_entries(self, message: discord.Message) -> tuple[list[discord.Member], int]:
        """Return (eligible entrants, host_id) for a giveaway message."""
        host_id = 0
        if message.embeds:
            for field in message.embeds[0].fields:
                if field.name == "Hosted by" and field.value.startswith("<@"):
                    try:
                        host_id = int(field.value[2:-1])
                    except ValueError:
                        host_id = 0
        members: dict[int, discord.Member] = {}
        for reaction in message.reactions:
            if str(reaction.emoji) != ENTRY_EMOJI:
                continue
            async for user in reaction.users():
                if user.bot or user.id == host_id:
                    continue
                if isinstance(user, discord.Member) and user not in members.values():
                    members[user.id] = user
        return list(members.values()), host_id

    async def _finish_giveaway(self, gw: dict, data: dict) -> None:
        """Announce winners for a giveaway and update its embed."""
        channel = self.bot.get_channel(gw["channel_id"])
        if not channel:
            return
        try:
            msg = await channel.fetch_message(gw["message_id"])
        except Exception:
            return

        entries, _ = await self._get_entries(msg)
        winners = random.sample(entries, min(gw["winners"], len(entries))) if entries else []

        if winners:
            names = ", ".join(w.mention for w in winners)
            result = f"🥳 **Winners:** {names}\nCongratulations on winning **{gw['prize']}**!"
        else:
            result = "😔 No valid entries — giveaway cancelled."

        embed = msg.embeds[0] if msg.embeds else discord.Embed(color=0xF1C40F)
        embed.color = 0x2ECC71
        embed.description = f"**{gw['prize']}**\n\n{result}"
        embed.set_footer(text="Giveaway ended")
        await msg.edit(embed=embed)
        await channel.send(result, allowed_mentions=discord.AllowedMentions(users=True))

        try:
            for w in winners:
                await w.send(f"🎉 You won **{gw['prize']}** in **{channel.guild.name}**!")
        except Exception:
            pass

    @giveaway.error
    async def giveaway_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingPermissions):
            embed = self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission.")
            await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Giveaways(bot))