"""
cogs/clan_system.py — Clan game system with wars and competitive features.
"""

import asyncio
import json
import os
import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


DATABASE_FILE = "data/clans.db"

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
        CREATE TABLE IF NOT EXISTS clans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            guild_id INTEGER NOT NULL,
            leader_id INTEGER NOT NULL,
            xp INTEGER DEFAULT 0,
            coins INTEGER DEFAULT 100,
            level INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            description TEXT DEFAULT '',
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            last_attack TEXT,
            UNIQUE(guild_id, name)
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clan_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clan_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TEXT NOT NULL,
            UNIQUE(clan_id, user_id)
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clan_wars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attacker_id INTEGER NOT NULL,
            defender_id INTEGER NOT NULL,
            attack_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            attacker_score INTEGER DEFAULT 0,
            defender_score INTEGER DEFAULT 0,
            winner_id INTEGER,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clan_war_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attacker_name TEXT NOT NULL,
            defender_name TEXT NOT NULL,
            attack_type TEXT NOT NULL,
            winner TEXT,
            attacker_score INTEGER,
            defender_score INTEGER,
            timestamp TEXT NOT NULL
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_missions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clan_id INTEGER NOT NULL,
            mission_type TEXT NOT NULL,
            target INTEGER DEFAULT 10,
            progress INTEGER DEFAULT 0,
            claimed INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            UNIQUE(clan_id, mission_type)
        )
    """)
    
    conn.commit()


def xp_for_level(level: int) -> int:
    return 100 * level * level


def clan_level_from_xp(total_xp: int) -> int:
    level = 1
    while total_xp >= xp_for_level(level):
        total_xp -= xp_for_level(level)
        level += 1
    return level


class ClanSystem(commands.Cog, name="clans"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        init_db()

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title)
        if description:
            embed.description = description
        return embed

    def get_user_clan(self, user_id: int, guild_id: int) -> Optional[dict]:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT c.* FROM clans c
            JOIN clan_members cm ON c.id = cm.clan_id
            WHERE cm.user_id = ? AND c.guild_id = ?
        """, (user_id, guild_id))
        row = c.fetchone()
        return dict(row) if row else None

    def get_clan_by_name(self, name: str, guild_id: int) -> Optional[dict]:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM clans WHERE LOWER(name) = LOWER(?) AND guild_id = ?", (name, guild_id))
        row = c.fetchone()
        return dict(row) if row else None

    def get_clan_members(self, clan_id: int) -> list:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT user_id FROM clan_members WHERE clan_id = ?", (clan_id,))
        rows = c.fetchall()
        return [r["user_id"] for r in rows]

    @commands.group(name="clan")
    async def clan(self, ctx: commands.Context) -> None:
        """Clan system commands."""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(color=0x9B59B6)
            embed.set_author(name="⚔️ Clan System")
            embed.description = "Available commands:"
            embed.add_field(name="`sudo clan create <name>`", value="Create a clan", inline=False)
            embed.add_field(name="`sudo clan join <name>`", value="Join a clan", inline=False)
            embed.add_field(name="`sudo clan leave`", value="Leave your clan", inline=False)
            embed.add_field(name="`sudo clan info [name]`", value="View clan info", inline=False)
            embed.add_field(name="`sudo clan leaderboard`", value="Top clans", inline=False)
            embed.add_field(name="`sudo clan challenge <clan>`", value="Challenge a clan", inline=False)
            embed.add_field(name="`sudo clan attack <type>`", value="Attack (raid/ambush/siege)", inline=False)
            embed.add_field(name="`sudo clan mission`", value="Daily clan mission", inline=False)
            embed.add_field(name="`sudo clan treasury`", value="View clan treasury", inline=False)
            await ctx.send(embed=embed)

    @clan.command(name="create")
    async def clan_create(self, ctx: commands.Context, *, name: str) -> None:
        """Create a new clan."""
        if len(name) < 3 or len(name) > 20:
            await ctx.send(embed=self._make_embed("❌ Invalid Name", 0xE74C3C, "Clan name must be 3-20 characters."))
            return

        if self.get_user_clan(ctx.author.id, ctx.guild.id):
            await ctx.send(embed=self._make_embed("❌ Already in Clan", 0xE74C3C, "You are already in a clan. Leave first."))
            return

        if self.get_clan_by_name(name, ctx.guild.id):
            await ctx.send(embed=self._make_embed("❌ Name Taken", 0xE74C3C, "A clan with that name already exists."))
            return

        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO clans (name, guild_id, leader_id, created_at) VALUES (?, ?, ?, ?)",
            (name, ctx.guild.id, ctx.author.id, datetime.now(timezone.utc).isoformat())
        )
        clan_id = c.lastrowid
        c.execute(
            "INSERT INTO clan_members (clan_id, user_id, joined_at) VALUES (?, ?, ?)",
            (clan_id, ctx.author.id, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()


        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name="⚔️ Clan Created!")
        embed.description = f"**{name}** has been created!"
        embed.add_field(name="Leader", value=ctx.author.mention, inline=True)
        await ctx.send(embed=embed)

    @clan.command(name="join")
    async def clan_join(self, ctx: commands.Context, *, name: str) -> None:
        """Join a clan."""
        if self.get_user_clan(ctx.author.id, ctx.guild.id):
            await ctx.send(embed=self._make_embed("❌ Already in Clan", 0xE74C3C, "You are already in a clan. Leave first."))
            return

        clan = self.get_clan_by_name(name, ctx.guild.id)
        if not clan:
            await ctx.send(embed=self._make_embed("❌ Not Found", 0xE74C3C, f"Clan **{name}** not found."))
            return

        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO clan_members (clan_id, user_id, joined_at) VALUES (?, ?, ?)",
            (clan["id"], ctx.author.id, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()


        await ctx.send(embed=self._make_embed("✅ Joined!", 0x2ECC71, f"You joined **{clan['name']}**!"))

    @clan.command(name="leave")
    async def clan_leave(self, ctx: commands.Context) -> None:
        """Leave your clan."""
        clan = self.get_user_clan(ctx.author.id, ctx.guild.id)
        if not clan:
            await ctx.send(embed=self._make_embed("❌ No Clan", 0xE74C3C, "You are not in a clan."))
            return

        if clan["leader_id"] == ctx.author.id:
            members = self.get_clan_members(clan["id"])
            if len(members) > 1:
                await ctx.send(embed=self._make_embed("❌ Cannot Leave", 0xE74C3C, "Transfer leadership first or disband the clan."))
                return
            else:
                conn = get_db()
                c = conn.cursor()
                c.execute("DELETE FROM clan_members WHERE clan_id = ?", (clan["id"],))
                c.execute("DELETE FROM clans WHERE id = ?", (clan["id"],))
                conn.commit()
        
                await ctx.send(embed=self._make_embed("🏠 Clan Disbanded", 0x95A5A6, f"**{clan['name']}** has been disbanded."))
                return

        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM clan_members WHERE clan_id = ? AND user_id = ?", (clan["id"], ctx.author.id))
        conn.commit()


        await ctx.send(embed=self._make_embed("🏠 Left", 0x3498DB, f"You left **{clan['name']}**."))

    @clan.command(name="info")
    async def clan_info(self, ctx: commands.Context, *, name: str = None) -> None:
        """View clan information."""
        if name:
            clan = self.get_clan_by_name(name, ctx.guild.id)
        else:
            clan = self.get_user_clan(ctx.author.id, ctx.guild.id)

        if not clan:
            await ctx.send(embed=self._make_embed("❌ Not Found", 0xE74C3C, "Clan not found or you are not in one."))
            return

        members = self.get_clan_members(clan["id"])
        leader = self.bot.get_user(clan["leader_id"])

        embed = discord.Embed(color=0x9B59B6)
        embed.set_author(name=f"⚔️ {clan['name']}")
        embed.add_field(name="Level", value=str(clan["level"]), inline=True)
        embed.add_field(name="XP", value=f"{clan['xp']:,}", inline=True)
        embed.add_field(name="Coins", value=f"{clan['coins']:,}", inline=True)
        embed.add_field(name="Leader", value=leader.mention if leader else f"<@{clan['leader_id']}>", inline=True)
        embed.add_field(name="Members", value=str(len(members)), inline=True)
        embed.add_field(name="W/L", value=f"{clan['wins']}W / {clan['losses']}L", inline=True)
        if clan["description"]:
            embed.add_field(name="Description", value=clan["description"], inline=False)

        await ctx.send(embed=embed)

    @clan.command(name="leaderboard")
    async def clan_leaderboard(self, ctx: commands.Context) -> None:
        """View clan leaderboard."""
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM clans WHERE guild_id = ? ORDER BY xp DESC LIMIT 10", (ctx.guild.id,))
        clans = c.fetchall()


        if not clans:
            await ctx.send(embed=self._make_embed("📋 Leaderboard", 0x95A5A6, "No clans yet!"))
            return

        embed = discord.Embed(color=0xF1C40F)
        embed.set_author(name="⚔️ Clan Leaderboard")

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, clan in enumerate(clans):
            medal = medals[i] if i < 3 else f"`{i+1}.`"
            lines.append(f"{medal} **{clan['name']}** — Lvl {clan['level']} — {clan['xp']:,} XP")

        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @clan.command(name="challenge")
    async def clan_challenge(self, ctx: commands.Context, *, name: str) -> None:
        """Challenge another clan to war."""
        my_clan = self.get_user_clan(ctx.author.id, ctx.guild.id)
        if not my_clan:
            await ctx.send(embed=self._make_embed("❌ No Clan", 0xE74C3C, "You are not in a clan."))
            return

        if my_clan["leader_id"] != ctx.author.id:
            await ctx.send(embed=self._make_embed("❌ Not Leader", 0xE74C3C, "Only the clan leader can challenge."))
            return

        enemy_clan = self.get_clan_by_name(name, ctx.guild.id)
        if not enemy_clan:
            await ctx.send(embed=self._make_embed("❌ Not Found", 0xE74C3C, f"Clan **{name}** not found."))
            return

        if enemy_clan["id"] == my_clan["id"]:
            await ctx.send(embed=self._make_embed("❌ Invalid", 0xE74C3C, "You cannot challenge your own clan."))
            return

        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM clan_wars 
            WHERE ((attacker_id = ? OR defender_id = ?) OR (attacker_id = ? OR defender_id = ?))
            AND status = 'pending'
        """, (my_clan["id"], my_clan["id"], enemy_clan["id"], enemy_clan["id"]))
        existing = c.fetchone()


        if existing:
            await ctx.send(embed=self._make_embed("❌ War Pending", 0xE74C3C, "A war is already pending between these clans!"))
            return

        conn = get_db()
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO clan_wars (attacker_id, defender_id, attack_type, status, created_at)
            VALUES (?, ?, 'raid', 'pending', ?)
            """,
            (my_clan["id"], enemy_clan["id"], datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

        await ctx.send(embed=discord.Embed(color=0xF39C12, description=f"⚔️ **{my_clan['name']}** has challenged **{enemy_clan['name']}**!\n\nLeaders use `sudo clan accept` to start the war."))

    @clan.command(name="accept")
    async def clan_accept(self, ctx: commands.Context) -> None:
        """Accept a clan war challenge."""
        my_clan = self.get_user_clan(ctx.author.id, ctx.guild.id)
        if not my_clan:
            await ctx.send(embed=self._make_embed("❌ No Clan", 0xE74C3C, "You are not in a clan."))
            return

        if my_clan["leader_id"] != ctx.author.id:
            await ctx.send(embed=self._make_embed("❌ Not Leader", 0xE74C3C, "Only the clan leader can accept."))
            return

        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM clan_wars WHERE defender_id = ? AND status = 'pending'
            ORDER BY id DESC LIMIT 1
        """, (my_clan["id"],))
        war = c.fetchone()


        if not war:
            await ctx.send(embed=self._make_embed("❌ No Challenge", 0xE74C3C, "No pending war challenges for your clan."))
            return

        c.execute("UPDATE clan_wars SET status = 'active' WHERE id = ?", (war["id"],))
        conn.commit()

        await ctx.send(embed=discord.Embed(color=0x2ECC71, description="⚔️ War accepted! Use `sudo clan attack <raid|ambush|siege>` to attack!"))

    @clan.command(name="attack")
    async def clan_attack(self, ctx: commands.Context, attack_type: str) -> None:
        """Launch an attack on a clan. Types: raid, ambush, siege"""
        my_clan = self.get_user_clan(ctx.author.id, ctx.guild.id)
        if not my_clan:
            await ctx.send(embed=self._make_embed("❌ No Clan", 0xE74C3C, "You are not in a clan."))
            return

        if my_clan["leader_id"] != ctx.author.id:
            await ctx.send(embed=self._make_embed("❌ Not Leader", 0xE74C3C, "Only the clan leader can attack."))
            return

        attack_type = attack_type.lower()
        if attack_type not in ["raid", "ambush", "siege"]:
            await ctx.send(embed=self._make_embed("❌ Invalid Type", 0xE74C3C, "Attack types: `raid`, `ambush`, `siege`"))
            return

        now = datetime.now(timezone.utc)
        if my_clan["last_attack"]:
            last = datetime.fromisoformat(my_clan["last_attack"])
            if (now - last) < timedelta(hours=1):
                remaining = timedelta(hours=1) - (now - last)
                await ctx.send(embed=self._make_embed("⏳ Cooldown", 0xE74C3C, f"Attack cooldown: {int(remaining.total_seconds()//60)} minutes remaining."))
                return

        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM clan_wars WHERE (attacker_id = ? OR defender_id = ?) AND status = 'active'
            ORDER BY id DESC LIMIT 1
        """, (my_clan["id"], my_clan["id"]))
        active_war = c.fetchone()


        if not active_war:
            await ctx.send(embed=self._make_embed("❌ No Active War", 0xE74C3C, "Start a war with `sudo clan challenge <clan>` first."))
            return

        success = random.random()
        
        if attack_type == "raid":
            success_threshold = 0.6
            xp_reward = 50
            coin_reward = 100
        elif attack_type == "ambush":
            success_threshold = 0.45
            xp_reward = 80
            coin_reward = 150
        else:
            success_threshold = 0.35
            xp_reward = 120
            coin_reward = 250

        if success < success_threshold * 0.5:
            outcome = "critical_win"
            xp_gained = xp_reward * 2
            coins_gained = coin_reward * 2
            my_clan["wins"] = my_clan.get("wins", 0) + 1
        elif success < success_threshold:
            outcome = "win"
            xp_gained = xp_reward
            coins_gained = coin_reward
            my_clan["wins"] = my_clan.get("wins", 0) + 1
        elif success < 0.8:
            outcome = "draw"
            xp_gained = 10
            coins_gained = 20
        else:
            outcome = "loss"
            xp_gained = -20
            coins_gained = -50
            my_clan["losses"] = my_clan.get("losses", 0) + 1

        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE clans SET xp = xp + ?, coins = coins + ?, last_attack = ?, wins = ?, losses = ? WHERE id = ?",
                  (xp_gained, coins_gained, now.isoformat(), my_clan["wins"], my_clan["losses"], my_clan["id"]))
        
        if xp_gained > 0:
            new_level = clan_level_from_xp(my_clan["xp"] + xp_gained)
            if new_level > my_clan["level"]:
                c.execute("UPDATE clans SET level = ? WHERE id = ?", (new_level, my_clan["id"]))

        conn.commit()


        outcomes = {
            "critical_win": ("🏆 Critical Victory!", 0x2ECC71),
            "win": ("⚔️ Victory!", 0x2ECC71),
            "draw": ("⚖️ Draw!", 0xF39C12),
            "loss": ("💀 Defeat!", 0xE74C3C),
        }

        title, color = outcomes[outcome]

        embed = discord.Embed(color=color)
        embed.set_author(name=title)
        embed.description = f"**{attack_type.capitalize()}** attack by **{my_clan['name']}**"
        embed.add_field(name="XP", value=f"{'+' if xp_gained > 0 else ''}{xp_gained}", inline=True)
        embed.add_field(name="Coins", value=f"{'+' if coins_gained > 0 else ''}{coins_gained}", inline=True)
        embed.add_field(name="Next Attack", value="1 hour cooldown", inline=True)

        await ctx.send(embed=embed)

    @clan.command(name="mission")
    async def clan_mission(self, ctx: commands.Context) -> None:
        """View daily clan mission."""
        my_clan = self.get_user_clan(ctx.author.id, ctx.guild.id)
        if not my_clan:
            await ctx.send(embed=self._make_embed("❌ No Clan", 0xE74C3C, "You are not in a clan."))
            return

        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM daily_missions WHERE clan_id = ? AND claimed = 0 AND expires_at > ?
        """, (my_clan["id"], datetime.now(timezone.utc).isoformat()))
        mission = c.fetchone()


        if not mission:
            mission_types = ["messages", "voice_minutes", "invites", "reactions"]
            m_type = random.choice(mission_types)
            target = random.randint(10, 50)
            
            conn = get_db()
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO daily_missions (clan_id, mission_type, target, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
            """, (my_clan["id"], m_type, target, datetime.now(timezone.utc).isoformat(), 
                  (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()))
            conn.commit()
    

            embed = discord.Embed(color=0x9B59B6)
            embed.set_author(name="📜 New Daily Mission!")
            embed.add_field(name="Task", value=f"Send **{target}** {m_type.replace('_', ' ')}", inline=False)
            embed.add_field(name="Reward", value="100 XP + 50 Coins", inline=True)
            embed.add_field(name="Expires", value="24 hours", inline=True)
        else:
            progress = mission["progress"]
            target = mission["target"]
            embed = discord.Embed(color=0xF1C40F)
            embed.set_author(name="📜 Daily Mission")
            embed.add_field(name="Task", value=f"{mission['mission_type'].replace('_', ' ').title()}: {progress}/{target}", inline=False)
            embed.add_field(name="Reward", value="100 XP + 50 Coins", inline=True)
            embed.add_field(name="Progress", value=f"`{'█' * int(progress/target*10)}{'░' * (10-int(progress/target*10))}`", inline=False)

        await ctx.send(embed=embed)

    @clan.command(name="treasury")
    async def clan_treasury(self, ctx: commands.Context) -> None:
        """View clan treasury."""
        my_clan = self.get_user_clan(ctx.author.id, ctx.guild.id)
        if not my_clan:
            await ctx.send(embed=self._make_embed("❌ No Clan", 0xE74C3C, "You are not in a clan."))
            return

        members = self.get_clan_members(my_clan["id"])

        embed = discord.Embed(color=0xF1C40F)
        embed.set_author(name=f"💰 {my_clan['name']} Treasury")
        embed.add_field(name="Total Coins", value=f"**{my_clan['coins']:,}**", inline=True)
        embed.add_field(name="Per Member", value=f"~{my_clan['coins']//max(len(members),1)}", inline=True)
        embed.add_field(name="Level", value=str(my_clan["level"]), inline=True)
        embed.add_field(name="XP Progress", value=f"{my_clan['xp']:,} / {xp_for_level(my_clan['level']+1):,}", inline=True)

        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ClanSystem(bot))
