"""
cogs/steal.py — Steal emojis (or images) and re-host them in your server.
Reply to a message containing a custom emoji or an image, then run
`alpha steal <name>`; the bot creates a new server emoji with that name.

Needs emoji management permission. Emoji slot limits (per-guild, scaled by
boosts) are respected, and the feature is throttled so concurrent steals
don't trip over each other.

Commands: steal
"""

import asyncio
import re

import aiohttp
import discord
from discord.ext import commands

from cogs.checks import perms_or_developer

NAME_MIN = 2
NAME_MAX = 32
_EMOJI_RE = re.compile(r"<(?P<animated>a)?:(?P<name>\w+):(?P<id>\d+)>")


def _sanitise_name(raw: str | None) -> str | None:
    """A Discord emoji name: 2-32 chars of letters/digits/underscore."""
    if not raw:
        return None
    name = re.sub(r"[^\w]", "", raw)[:NAME_MAX].strip("_")
    return name if len(name) >= NAME_MIN else None


class Steal(commands.Cog, name="steal"):
    """Steal emojis and images to add them to your server."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title, icon_url=None)
        if description:
            embed.description = description
        return embed

    def _lock_for(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    # ── Source extraction ─────────────────────────────────────────────────────
    @staticmethod
    def _emoji_from_message(message: discord.Message) -> tuple[int, bool] | None:
        """First custom emoji in a message's content -> (id, is_animated)."""
        hit = _EMOJI_RE.search(message.content or "")
        if not hit:
            return None
        return int(hit.group("id")), bool(hit.group("animated"))

    @staticmethod
    def _image_from_message(message: discord.Message) -> tuple[str, bool] | None:
        """Largest image attachment or first embed image -> (url, is_animated)."""
        picks = [a for a in message.attachments
                 if a.content_type and a.content_type.lower().startswith("image")]
        if picks:
            largest = max(picks, key=lambda a: a.size or 0)
            low = (largest.filename or "").lower()
            animated = low.endswith(".gif") or (largest.content_type or "").lower() == "image/gif"
            return str(largest.url), animated
        for embed in message.embeds:
            for probe in (embed.image, embed.thumbnail):
                if probe.url:
                    return str(probe.url), False
        return None

    async def _fetch(self, url: str) -> bytes:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.read()

    @staticmethod
    def _filtered_name(guild: discord.Guild, base: str) -> str:
        """Pick `base`, `base_2`, `base_3`, ... if the name is already taken."""
        taken = {e.name for e in guild.emojis}
        candidate, i = base, 1
        while candidate in taken:
            i += 1
            suffix = str(i)
            candidate = f"{base[: NAME_MAX - len(suffix) - 1]}_{suffix}"
        return candidate

    # ── Command ───────────────────────────────────────────────────────────────
    @commands.command(name="steal", aliases=["emojisteal", "copysteal"])
    @perms_or_developer(manage_expressions=True)
    async def steal(self, ctx: commands.Context, *, name: str | None = None) -> None:
        """Steal an emoji/image from a message you reply to. Usage: alpha steal <name>"""
        if not ctx.message.reference:
            embed = self._make_embed(
                "❌ Nothing to Steal", 0xE74C3C,
                f"Reply to a message containing an emoji or image, then use "
                f"`{ctx.prefix}steal <name>`.\nExample: reply to a message with a "
                f"custom emoji and type `{ctx.prefix}steal my_new_emoji`.",
            )
            await ctx.send(embed=embed)
            return

        try:
            ref = ctx.message.reference.resolved
            if ref is None:
                ref = await ctx.message.channel.fetch_message(ctx.message.reference.message_id)
        except discord.HTTPException:
            embed = self._make_embed(
                "❌ Cannot Read", 0xE74C3C,
                "I couldn't read the message you replied to.",
            )
            await ctx.send(embed=embed)
            return
        if not isinstance(ref, discord.Message):
            embed = self._make_embed(
                "❌ Nothing to Steal", 0xE74C3C,
                "The message you replied to doesn't contain an emoji or image.",
            )
            await ctx.send(embed=embed)
            return

        name = name.strip() if name else None

        source = self._emoji_from_message(ref)
        default_name = None
        if source:
            emoji_id, animated = source
            if not name:
                hit = _EMOJI_RE.search(ref.content or "")
                default_name = hit.group("name") if hit else None
            url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{'gif' if animated else 'png'}"
        else:
            image = self._image_from_message(ref)
            if not image:
                embed = self._make_embed(
                    "❌ Nothing to Steal", 0xE74C3C,
                    "That message has no custom emoji, image attachment, or embed image to steal.",
                )
                await ctx.send(embed=embed)
                return
            url, animated = image

        emoji_name = _sanitise_name(name or default_name)
        if not emoji_name:
            embed = self._make_embed(
                "❌ Invalid Name", 0xE74C3C,
                f"Emoji names need **{NAME_MIN}-{NAME_MAX}** letters, digits, or underscores. "
                f"You gave: `{name or default_name or '(none)'}`.",
            )
            await ctx.send(embed=embed)
            return

        async with self._lock_for(ctx.guild.id):
            emoji_limit = ctx.guild.emoji_limit
            counts = {"static": 0, "animated": 0}
            for e in ctx.guild.emojis:
                counts["animated" if e.animated else "static"] += 1
            kind = "animated" if animated else "static"
            if counts[kind] >= emoji_limit:
                embed = self._make_embed(
                    "❌ Emoji Slots Full", 0xE74C3C,
                    f"This server has reached its **{emoji_limit}** {kind} emoji slot limit. "
                    "Remove an emoji or boost the server to add more.",
                )
                await ctx.send(embed=embed)
                return

            try:
                raw = await self._fetch(url)
            except (aiohttp.ClientError, UnicodeDecodeError, ValueError):
                embed = self._make_embed(
                    "❌ Download Failed", 0xE74C3C,
                    "I couldn't download that emoji/image. Source may be unavailable.",
                )
                await ctx.send(embed=embed)
                return

            final_name = self._filtered_name(ctx.guild, emoji_name)
            try:
                emoji = await ctx.guild.create_custom_emoji(
                    name=final_name,
                    image=raw,
                    reason=f"Stolen by {ctx.author}",
                )
            except discord.Forbidden:
                embed = self._make_embed(
                    "❌ Permission Denied", 0xE74C3C,
                    "I need the **Manage Expressions** permission to add emojis.",
                )
                await ctx.send(embed=embed)
                return
            except discord.HTTPException as exc:
                embed = self._make_embed(
                    "❌ Emoji Not Added", 0xE74C3C,
                    f"Discord rejected the emoji: `{exc.text or exc}`. "
                    "It may be too large (Discord allows up to 256 KB).",
                )
                await ctx.send(embed=embed)
                return

        shown = f"<{'a' if emoji.animated else ''}:{emoji.name}:{emoji.id}>"
        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name=f"✅ Stolen & Added — :{emoji.name}:")
        embed.add_field(name="Emoji", value=shown, inline=True)
        embed.add_field(name="Name", value=f"`{emoji.name}`", inline=True)
        embed.set_image(url=emoji.url)
        embed.set_footer(text=f"Stolen from {ref.author.display_name} · Added by {ctx.author.display_name}")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Steal(bot))