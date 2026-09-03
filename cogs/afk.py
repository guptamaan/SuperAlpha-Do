"""
cogs/afk.py — AFK system.
Sets users as AFK with reason, notifies when pinged, welcomes back.
"""

import asyncio
import json
import os
import time

import discord
from discord import app_commands
from discord.ext import commands


DATA_DIR = "data/afk"
os.makedirs(DATA_DIR, exist_ok=True)

_afk_cache: dict | None = None
_afk_dirty = False


def get_afk_file() -> str:
    return os.path.join(DATA_DIR, "afk.json")


def _load_afk_from_disk() -> dict:
    path = get_afk_file()
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


def load_afk() -> dict:
    global _afk_cache
    if _afk_cache is None:
        _afk_cache = _load_afk_from_disk()
    return _afk_cache


def save_afk(data: dict) -> None:
    global _afk_cache, _afk_dirty
    _afk_cache = data
    _afk_dirty = True


def flush_afk() -> None:
    global _afk_dirty
    if not _afk_dirty or _afk_cache is None:
        return
    path = get_afk_file()
    with open(path, "w") as f:
        json.dump(_afk_cache, f, indent=2)
    _afk_dirty = False


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"


class AFK(commands.Cog, name="afk"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._ignored_messages: set[int] = set()
        self._flush_task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def cog_unload(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
        flush_afk()

    async def _periodic_flush(self) -> None:
        while True:
            await asyncio.sleep(120)
            flush_afk()

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title)
        if description:
            embed.description = description
        return embed

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not message.guild:
            return

        if message.id in self._ignored_messages:
            self._ignored_messages.discard(message.id)
            return

        afk_data = load_afk()
        user_id = str(message.author.id)

        if user_id in afk_data:
            afk_info = afk_data[user_id]
            start_time = afk_info.get("timestamp", time.time())
            duration = time.time() - start_time

            del afk_data[user_id]
            save_afk(afk_data)

            try:
                await message.author.edit(nick=afk_info.get("original_nick", message.author.display_name))
            except Exception:
                pass

            embed = discord.Embed(color=0x2ECC71)
            embed.set_author(name="👋 Welcome Back!")
            embed.description = f"**{message.author.display_name}**, you were AFK for **{format_duration(duration)}**"
            if afk_info.get("reason"):
                embed.add_field(name="AFK Reason", value=afk_info["reason"], inline=True)
            await message.channel.send(embed=embed)

        mentions = message.mentions
        if mentions:
            afk_data = load_afk()
            notified = []

            for mention in mentions:
                mention_id = str(mention.id)
                if mention_id in afk_data and mention_id not in notified:
                    afk_info = afk_data[mention_id]
                    start_time = afk_info.get("timestamp", time.time())
                    duration = time.time() - start_time
                    reason = afk_info.get("reason", "No reason")

                    embed = discord.Embed(color=0xF39C12)
                    embed.set_author(name="📴 AFK Notice")
                    embed.description = f"**{mention.display_name}** is AFK"
                    embed.add_field(name="Reason", value=reason, inline=True)
                    embed.add_field(name="Duration", value=format_duration(duration), inline=True)

                    try:
                        await message.channel.send(
                            content=f"📴 **{mention.display_name}** is AFK — *{reason}*",
                            embed=embed
                        )
                    except discord.HTTPException:
                        await message.channel.send(f"📴 **{mention.display_name}** is AFK — *{reason}*")
                    notified.append(mention_id)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return

        if after.channel and not before.channel:
            afk_data = load_afk()
            user_id = str(member.id)

            if user_id in afk_data:
                afk_info = afk_data[user_id]
                start_time = afk_info.get("timestamp", time.time())
                duration = time.time() - start_time

                del afk_data[user_id]
                save_afk(afk_data)

                try:
                    await member.edit(nick=afk_info.get("original_nick", member.display_name))
                except Exception:
                    pass

                dm_channel = member.dm_channel
                if not dm_channel:
                    dm_channel = await member.create_dm()

                embed = discord.Embed(color=0x2ECC71)
                embed.set_author(name="👋 Welcome Back!")
                embed.description = f"You were AFK for **{format_duration(duration)}**"
                if afk_info.get("reason"):
                    embed.add_field(name="AFK Reason", value=afk_info["reason"], inline=True)

                try:
                    await dm_channel.send(embed=embed)
                except Exception:
                    pass

    @commands.command(name="afk")
    async def afk(self, ctx: commands.Context, *, reason: str = "AFK") -> None:
        """Set yourself as AFK. Usage: sudo afk [reason]"""
        afk_data = load_afk()
        user_id = str(ctx.author.id)

        if user_id in afk_data:
            embed = self._make_embed("❌ Already AFK", 0xE74C3C, "You are already marked as AFK")
            await ctx.send(embed=embed)
            return

        original_nick = ctx.author.display_name

        afk_data[user_id] = {
            "name": ctx.author.display_name,
            "original_nick": original_nick,
            "reason": reason,
            "timestamp": time.time(),
        }
        save_afk(afk_data)

        self._ignored_messages.add(ctx.message.id)

        try:
            await ctx.author.edit(nick=f"[AFK] {ctx.author.display_name}")
        except Exception:
            pass

        embed = discord.Embed(color=0xF39C12)
        embed.set_author(name="📴 AFK Set")
        embed.description = f"**{ctx.author.display_name}** is now AFK"
        embed.add_field(name="Reason", value=reason, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="afklist", aliases=["whosafk"])
    async def afklist(self, ctx: commands.Context) -> None:
        """List all AFK users. Usage: sudo afklist"""
        afk_data = load_afk()

        if not afk_data:
            embed = self._make_embed("📴 AFK List", 0x95A5A6, "No one is AFK right now")
            await ctx.send(embed=embed)
            return

        lines = []
        now = time.time()
        for user_id, info in afk_data.items():
            duration = format_duration(now - info.get("timestamp", now))
            reason = info.get("reason", "AFK")
            lines.append(f"• **{info.get('name', 'Unknown')}** — *{reason}* ({duration} ago)")

        embed = discord.Embed(color=0xF39C12)
        embed.set_author(name=f"📴 AFK List ({len(afk_data)} users)")
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @app_commands.command(name="afk", description="Set yourself as AFK")
    @app_commands.describe(reason="Why are you AFK?")
    async def slash_afk(self, interaction: discord.Interaction, reason: str = "AFK") -> None:
        afk_data = load_afk()
        user_id = str(interaction.user.id)

        if user_id in afk_data:
            await interaction.response.send_message(
                embed=self._make_embed("❌ Already AFK", 0xE74C3C, "You are already marked as AFK"),
                ephemeral=True
            )
            return

        original_nick = interaction.user.display_name

        afk_data[user_id] = {
            "name": interaction.user.display_name,
            "original_nick": original_nick,
            "reason": reason,
            "timestamp": time.time(),
        }
        save_afk(afk_data)

        try:
            await interaction.user.edit(nick=f"[AFK] {interaction.user.display_name}")
        except Exception:
            pass

        embed = discord.Embed(color=0xF39C12)
        embed.set_author(name="📴 AFK Set")
        embed.description = f"**{interaction.user.display_name}** is now AFK"
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AFK(bot))
