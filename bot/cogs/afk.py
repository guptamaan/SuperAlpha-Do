"""
cogs/afk.py — AFK system.
Sets users as AFK with reason, notifies when pinged, welcomes back.
"""

import asyncio
import os
import time

import discord
from discord import app_commands
from discord.ext import commands



async def load_afk(bot: commands.Bot) -> dict:
    """Load all AFK users from PostgreSQL into an in-memory dictionary."""
    rows = await bot.db.fetch("SELECT user_id, name, reason, timestamp FROM afk.users;")

    afk_dict = {}
    for row in rows:
        user_id = str(row["user_id"])
        afk_dict[user_id] = {
            "name": row["name"],
            "reason": row["reason"],
            "timestamp": row["timestamp"],
        }

    return afk_dict


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"

    mins, secs = divmod(seconds, 60)
    if mins < 60:
        return f"{mins}m {secs}s"

    hours, mins = divmod(mins, 60)
    if hours < 24:
        return f"{hours}h {mins}m"

    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


class AFK(commands.Cog, name="afk"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._ignored_messages: set[int] = set()
        self.afk_cache: dict[str, dict] = {}


    async def setup_schema(self) -> None:
        """Create afk schema and users table inside PostgreSQL."""
        await self.bot.db.execute("CREATE SCHEMA IF NOT EXISTS afk;")
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS afk.users (
                user_id   TEXT PRIMARY KEY,
                name      TEXT,
                reason    TEXT,
                timestamp DOUBLE PRECISION
            );
            """
        )

    async def cog_load(self) -> None:
        """Initialize schema and populate the in-memory cache on cog startup."""
        await self.setup_schema()
        self.afk_cache = await load_afk(self.bot)

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title)
        if description:
            embed.description = description
        return embed

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return


        ctx = await self.bot.get_context(message)
        
        if ctx.valid and ctx.command and ctx.command.qualified_name == "afk":
            return

        user_id = str(message.author.id)

        # Check if message author was AFK -> Remove AFK status
        if user_id in self.afk_cache:
            afk_info = self.afk_cache.pop(user_id)
            
            await self.bot.db.execute("DELETE FROM afk.users WHERE user_id = $1;", user_id)

            start_time = afk_info.get("timestamp", time.time())
            duration = time.time() - start_time

            embed = discord.Embed(color=0x2ECC71)
            embed.set_author(name="👋 Welcome Back!")
            embed.description = f"**{message.author.display_name}**, you were AFK for **{format_duration(duration)}**"
            if afk_info.get("reason"):
                embed.add_field(name="AFK Reason", value=afk_info["reason"], inline=True)
            await message.channel.send(embed=embed)

        # check if any mentioned users are AFK -> Send notice
        if message.mentions:
            notified = []

            for mention in message.mentions:
                mention_id = str(mention.id)
                if mention_id in self.afk_cache and mention_id not in notified:
                    afk_info = self.afk_cache[mention_id]
                    start_time = afk_info.get("timestamp", time.time())
                    duration = time.time() - start_time
                    reason = afk_info.get("reason", "AFK")

                    embed = discord.Embed(color=0xF39C12)
                    embed.set_author(name="📴 AFK Notice")
                    embed.description = f"**{mention.display_name}** is AFK"
                    embed.add_field(name="Reason", value=reason, inline=True)
                    embed.add_field(name="Duration", value=format_duration(duration), inline=True)

                    try:
                        await message.channel.send(
                            content=f"📴 **{mention.display_name}** is AFK — *{reason}*",
                            embed=embed,
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

        # Trigger welcome back if user joins a voice channel while AFK
        if after.channel and not before.channel:
            user_id = str(member.id)

            if user_id in self.afk_cache:
                afk_info = self.afk_cache.pop(user_id)
                await self.bot.db.execute("DELETE FROM afk.users WHERE user_id = $1;", user_id)

                start_time = afk_info.get("timestamp", time.time())
                duration = time.time() - start_time

                dm_channel = member.dm_channel or await member.create_dm()

                embed = discord.Embed(color=0x2ECC71)
                embed.set_author(name="👋 Welcome Back!")
                embed.description = f"You were AFK for **{format_duration(duration)}**"
                if afk_info.get("reason"):
                    embed.add_field(name="AFK Reason", value=afk_info["reason"], inline=True)

                try:
                    await dm_channel.send(embed=embed)
                except discord.HTTPException:
                    pass

    @commands.command(name="afk")
    async def afk(self, ctx: commands.Context, *, reason: str = "AFK") -> None:
        """Set yourself as AFK. Usage: alpha afk [reason]"""
        user_id = str(ctx.author.id)

        if user_id in self.afk_cache:
            embed = self._make_embed("❌ Already AFK", 0xE74C3C, "You are already marked as AFK")
            await ctx.send(embed=embed)
            return

        now = time.time()
    
        self.afk_cache[user_id] = {
            "name": ctx.author.display_name,
            "reason": reason,
            "timestamp": now,
        }


        await self.bot.db.execute(
            """
            INSERT INTO afk.users (
                user_id, 
                name, 
                reason, 
                timestamp
            )
    
            VALUES ($1, $2, $3, $4)
            
            ON CONFLICT (user_id) DO UPDATE 
            SET name = EXCLUDED.name, reason = EXCLUDED.reason, timestamp = EXCLUDED.timestamp;
            """,
            user_id,
            ctx.author.display_name,
            reason,
            now 
    )


        embed = discord.Embed(color=0xF39C12)
        embed.set_author(name="📴 AFK Set")
        embed.description = f"**{ctx.author.display_name}** is now AFK"
        embed.add_field(name="Reason", value=reason, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="afklist", aliases=["whosafk"])
    async def afklist(self, ctx: commands.Context) -> None:
        """List all AFK users. Usage: alpha afklist"""
        if not self.afk_cache:
            embed = self._make_embed("📴 AFK List", 0x95A5A6, "No one is AFK right now")
            await ctx.send(embed=embed)
            return

        lines = []
        now = time.time()
        for user_id, info in self.afk_cache.items():
            duration = format_duration(now - info.get("timestamp", now))
            reason = info.get("reason", "AFK")
            lines.append(f"• **{info.get('name', 'Unknown')}** — *{reason}* ({duration} ago)")

        embed = discord.Embed(color=0xF39C12)
        embed.set_author(name=f"📴 AFK List ({len(self.afk_cache)} user{'s' if len(self.afk_cache) != 1 else ''})")
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    
    @app_commands.command(name="afk", description="Set yourself as AFK")
    @app_commands.describe(reason="Why are you AFK?")
    async def slash_afk(self, interaction: discord.Interaction, reason: str = "AFK") -> None:
        user_id = str(interaction.user.id)

        if user_id in self.afk_cache:
            await interaction.response.send_message(
                embed=self._make_embed("❌ Already AFK", 0xE74C3C, "You are already marked as AFK"),
                ephemeral=True,
            )
            return

        now = time.time()

        self.afk_cache[user_id] = {
            "name": interaction.user.display_name,
            "reason": reason,
            "timestamp": now,
        }


        await self.bot.db.execute(
            """
            INSERT INTO afk.users (
                user_id, 
                name, 
                reason, 
                timestamp
            )
            
            VALUES ($1, $2, $3, $4)
            
            ON CONFLICT (user_id) DO UPDATE 
            SET name = EXCLUDED.name, reason = EXCLUDED.reason, timestamp = EXCLUDED.timestamp;
            """,
            user_id,
            interaction.user.display_name,
            reason,
            now
        )

        embed = discord.Embed(color=0xF39C12)
        embed.set_author(name="📴 AFK Set")
        embed.description = f"**{interaction.user.display_name}** is now AFK"
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AFK(bot))
