"""
cogs/reaction_roles.py — Reaction role system.
"""

import asyncio
import json
import os
import sqlite3
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from cogs.checks import perms_or_developer


DATABASE_FILE = "data/reaction_roles.db"

_db_conn: sqlite3.Connection | None = None


def get_db():
    global _db_conn
    if _db_conn is None:
        _db_conn = sqlite3.connect(DATABASE_FILE, check_same_thread=False)
        _db_conn.row_factory = sqlite3.Row
        _db_conn.execute("PRAGMA journal_mode=WAL")
    return _db_conn


def init_db():
    os.makedirs("data", exist_ok=True)
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reaction_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            emoji TEXT NOT NULL,
            role_id INTEGER NOT NULL,
            UNIQUE(guild_id, message_id, emoji)
        )
    """)
    conn.commit()


class ReactionRoles(commands.Cog, name="reactionroles"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        init_db()

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title)
        if description:
            embed.description = description
        return embed

    async def _get_or_fetch_message(self, channel: discord.TextChannel, message_id: int):
        try:
            return await channel.fetch_message(message_id)
        except discord.NotFound:
            return None

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.member and payload.member.bot:
            return

        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT role_id FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (payload.guild_id, payload.message_id, str(payload.emoji))
        )
        row = c.fetchone()

        if row:
            guild = self.bot.get_guild(payload.guild_id)
            if not guild:
                return
            role = guild.get_role(row["role_id"])
            if role:
                member = guild.get_member(payload.user_id)
                if member:
                    try:
                        await member.add_roles(role)
                    except Exception:
                        pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT role_id FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (payload.guild_id, payload.message_id, str(payload.emoji))
        )
        row = c.fetchone()

        if row:
            guild = self.bot.get_guild(payload.guild_id)
            if not guild:
                return
            role = guild.get_role(row["role_id"])
            if role:
                member = guild.get_member(payload.user_id)
                if member:
                    try:
                        await member.remove_roles(role)
                    except Exception:
                        pass

    @commands.command(name="reactionrole")
    @perms_or_developer(administrator=True)
    async def reactionrole(self, ctx: commands.Context, action: str = None) -> None:
        """Manage reaction roles. Usage: sudo reactionrole [create|delete|list]"""
        if not action:
            embed = discord.Embed(color=0x9B59B6)
            embed.set_author(name="📋 Reaction Roles")
            embed.description = "Available commands:"
            embed.add_field(name="`sudo reactionrole create`", value="Create a new reaction role", inline=False)
            embed.add_field(name="`sudo reactionrole delete`", value="Delete a reaction role", inline=False)
            embed.add_field(name="`sudo reactionrole list`", value="List all reaction roles", inline=False)
            await ctx.send(embed=embed)
            return

        action = action.lower()

        if action == "create":
            msg = await ctx.send(embed=self._make_embed("📝 Creating Reaction Role", 0x3498DB,
                "Step 1: Mention the **channel** where the message is (or will be).\n"
                "Example: `#general`"))
            
            try:
                channel_msg = await self.bot.wait_for("message", check=lambda m: m.author == ctx.author and m.channel == ctx.channel, timeout=60)
                channel_id = channel_msg.content.strip().replace("<#", "").replace(">", "")
                channel = ctx.guild.get_channel(int(channel_id))
                if not channel:
                    await msg.edit(embed=self._make_embed("❌ Invalid Channel", 0xE74C3C, "Channel not found."))
                    return
            except asyncio.TimeoutError:
                await msg.edit(embed=self._make_embed("❌ Timeout", 0xE74C3C, "Operation cancelled."))
                return

            await msg.edit(embed=self._make_embed("📝 Step 2", 0x3498DB,
                "Send the **message ID** or the **message link**.\n"
                "For new message, type `new`"))
            
            try:
                msg_content = await self.bot.wait_for("message", check=lambda m: m.author == ctx.author and m.channel == ctx.channel, timeout=60)
                msg_input = msg_content.content.strip()

                if msg_input == "new":
                    await msg.edit(embed=self._make_embed("📝 Step 3", 0x3498DB, "Send the **message content** to post."))
                    try:
                        msg_text = await self.bot.wait_for("message", check=lambda m: m.author == ctx.author and m.channel == ctx.channel, timeout=60)
                        sent_msg = await channel.send(msg_text.content)
                        message_id = sent_msg.id
                    except asyncio.TimeoutError:
                        await msg.edit(embed=self._make_embed("❌ Timeout", 0xE74C3C, "Operation cancelled."))
                        return
                elif "discord.com/channels/" in msg_input:
                    parts = msg_input.split("/")
                    message_id = int(parts[-1])
                else:
                    message_id = int(msg_input)
            except (asyncio.TimeoutError, ValueError):
                await msg.edit(embed=self._make_embed("❌ Invalid Input", 0xE74C3C, "Invalid message ID."))
                return

            await msg.edit(embed=self._make_embed("📝 Step 4", 0x3498DB, "Send the **emoji** to use."))
            
            try:
                reaction_msg = await self.bot.wait_for("message", check=lambda m: m.author == ctx.author and m.channel == ctx.channel, timeout=60)
                emoji = reaction_msg.content.strip()
            except asyncio.TimeoutError:
                await msg.edit(embed=self._make_embed("❌ Timeout", 0xE74C3C, "Operation cancelled."))
                return

            await msg.edit(embed=self._make_embed("📝 Step 5", 0x3498DB, "Mention the **role** to assign.\nExample: `@Member`"))
            
            try:
                role_msg = await self.bot.wait_for("message", check=lambda m: m.author == ctx.author and m.channel == ctx.channel, timeout=60)
                role_id = role_msg.content.strip().replace("<@&", "").replace(">", "")
                role = ctx.guild.get_role(int(role_id))
                if not role:
                    await msg.edit(embed=self._make_embed("❌ Invalid Role", 0xE74C3C, "Role not found."))
                    return
            except asyncio.TimeoutError:
                await msg.edit(embed=self._make_embed("❌ Timeout", 0xE74C3C, "Operation cancelled."))
                return

            conn = get_db()
            c = conn.cursor()
            c.execute(
                "INSERT OR REPLACE INTO reaction_roles (guild_id, channel_id, message_id, emoji, role_id) VALUES (?, ?, ?, ?, ?)",
                (ctx.guild.id, channel.id, message_id, emoji, role.id)
            )
            conn.commit()


            target_msg = await self._get_or_fetch_message(channel, message_id)
            if target_msg:
                try:
                    await target_msg.add_reaction(emoji)
                except Exception:
                    pass

            embed = discord.Embed(color=0x2ECC71)
            embed.set_author(name="✅ Reaction Role Created")
            embed.add_field(name="Channel", value=channel.mention, inline=True)
            embed.add_field(name="Message ID", value=message_id, inline=True)
            embed.add_field(name="Emoji", value=emoji, inline=True)
            embed.add_field(name="Role", value=role.mention, inline=True)
            await msg.edit(embed=embed)

        elif action == "delete":
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT * FROM reaction_roles WHERE guild_id = ?", (ctx.guild.id,))
            roles = c.fetchall()


            if not roles:
                await ctx.send(embed=self._make_embed("❌ No Reaction Roles", 0xE74C3C, "No reaction roles configured."))
                return

            msg = await ctx.send(embed=self._make_embed("🗑️ Delete Reaction Role", 0xE74C3C,
                "Send the **message ID** of the reaction role to delete."))
            
            try:
                del_msg = await self.bot.wait_for("message", check=lambda m: m.author == ctx.author and m.channel == ctx.channel, timeout=60)
                message_id = int(del_msg.content.strip())
            except (asyncio.TimeoutError, ValueError):
                await msg.edit(embed=self._make_embed("❌ Invalid Input", 0xE74C3C, "Invalid message ID."))
                return

            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ?", (ctx.guild.id, message_id))
            deleted = c.rowcount
            conn.commit()


            if deleted > 0:
                await msg.edit(embed=self._make_embed("✅ Deleted", 0x2ECC71, f"Reaction role for message {message_id} deleted."))
            else:
                await msg.edit(embed=self._make_embed("❌ Not Found", 0xE74C3C, "Reaction role not found."))

        elif action == "list":
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT * FROM reaction_roles WHERE guild_id = ?", (ctx.guild.id,))
            roles = c.fetchall()


            if not roles:
                await ctx.send(embed=self._make_embed("📋 Reaction Roles", 0x95A5A6, "No reaction roles configured."))
                return

            embed = discord.Embed(color=0x9B59B6)
            embed.set_author(name="📋 Reaction Roles")

            for r in roles:
                channel = self.bot.get_channel(r["channel_id"])
                role = ctx.guild.get_role(r["role_id"])
                embed.add_field(
                    name=f"Message: {r['message_id']}",
                    value=f"Channel: {channel.mention if channel else r['channel_id']}\n"
                          f"Emoji: {r['emoji']}\n"
                          f"Role: {role.mention if role else r['role_id']}",
                    inline=False
                )

            await ctx.send(embed=embed)

        else:
            await ctx.send(embed=self._make_embed("❌ Invalid Action", 0xE74C3C, "Use: create, delete, list"))

    @reactionrole.error
    async def reactionrole_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission."))

    @app_commands.command(name="reactionrole", description="Manage reaction roles")
    @app_commands.describe(action="Action to perform")
    @app_commands.choices(action=[
        app_commands.Choice(name="Create", value="create"),
        app_commands.Choice(name="Delete", value="delete"),
        app_commands.Choice(name="List", value="list"),
    ])
    async def slash_reactionrole(self, interaction: discord.Interaction, action: str) -> None:
        await interaction.response.send_message("Use prefix command `sudo reactionrole` for interactive setup.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReactionRoles(bot))
