"""
cogs/linux.py — Arch/Linux-inspired command aliases.

Linux aliases are added to every command but are locked until a server
enables them with `sudo enable linux` (or `disable linux` to turn them off).
The developer/owner can always use them via the perms_or_developer gate.
"""

import json
import pathlib

import discord
from discord.ext import commands

MODE_FILE = pathlib.Path("data/linux_mode.json")
MODE_DIR = MODE_FILE.parent


class LinuxDisabled(commands.CheckFailure):
    """Raised when a Linux alias is used while Linux mode is disabled."""


# ── Persisted per-guild mode ──────────────────────────────────────────────────
def _load_enabled_guilds() -> set[int]:
    if not MODE_FILE.exists():
        return set()
    try:
        with open(MODE_FILE) as f:
            data = json.load(f)
        return {int(g) for g in data.get("guilds", [])}
    except (json.JSONDecodeError, OSError, ValueError):
        return set()


def _save_enabled_guilds(guilds: set[int]) -> None:
    MODE_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODE_FILE, "w") as f:
        json.dump({"guilds": sorted(guilds)}, f, indent=2)


def is_linux_enabled(guild_id: int | None) -> bool:
    if not guild_id:
        return False
    return guild_id in _load_enabled_guilds()


def set_linux_enabled(guild_id: int, enabled: bool) -> None:
    guilds = _load_enabled_guilds()
    if enabled:
        guilds.add(guild_id)
    else:
        guilds.discard(guild_id)
    _save_enabled_guilds(guilds)


# ── Linux alternative aliases per command ────────────────────────────────────
LINUX_ALIASES: dict[str, tuple[str, ...]] = {
    # AFK
    "afk": ("suspend",),
    "afklist": ("who",),
    # AI
    "ai": ("llama", "ollama"),
    "aiclear": ("historyclear",),
    "aihistory": ("history",),
    "aitranslate": ("gettext",),
    "code": ("gcc", "clang"),
    "explain": ("tldr",),
    "imagine": ("blender",),
    "summarize": ("sum",),
    # Fun
    "8ball": ("fortune",),
    "ascii": ("toilet",),
    "choose": ("option",),
    "coinflip": ("toss",),
    "emojify": ("unicode",),
    "fact": ("factoid",),
    "fliptext": ("rot13",),
    "hack": ("hydra",),
    "joke": ("lolcat",),
    "kill": ("xkill",),
    "mock": ("sarcasm",),
    "pat": ("pet",),
    "quote": ("cowsay",),
    "reverse": ("mirror",),
    "roll": ("diceware",),
    "rps": ("janken",),
    "ship": ("pair",),
    "slots": ("jackpot",),
    "trivia": ("quiz",),
    "wouldyourather": ("dilemma",),
    # Games
    "connect4": ("gomoku",),
    "tictactoe": ("nought",),
    "wordbank": ("look",),
    # Info
    "avatar": ("icon",),
    "banner": ("art",),
    "botinfo": ("neofetch",),
    "channelinfo": ("ifconfig",),
    "emojis": ("emoji",),
    "membercount": ("wc",),
    "perms": ("lsattr",),
    "roleinfo": ("group",),
    "roles": ("groups",),
    "serverinfo": ("hostname",),
    "userinfo": ("whoami",),
    # Moderation
    "addrole": ("gpasswd",),
    "ban": ("userdel",),
    "clearwarns": ("vacuum",),
    "deafen": ("soundoff",),
    "kick": ("killall",),
    "lock": ("chmod",),
    "massban": ("bomb",),
    "mute": ("quiet",),
    "nickname": ("rename",),
    "purge": ("truncate",),
    "removerole": ("delgrp",),
    "slowmode": ("tc",),
    "softban": ("kickban",),
    "strip": ("prune",),
    "unban": ("useradd",),
    "undeafen": ("soundon",),
    "unlock": ("flock",),
    "unmute": ("unquiet",),
    "voicekick": ("cut",),
    "voicemove": ("mv",),
    "warn": ("syslog",),
    "warnings": ("dmesg",),
    # Music
    "8d": ("surround",),
    "autoplay": ("daemon",),
    "bassboost": ("bass",),
    "clearqueue": ("cacheclear",),
    "equalizer": ("sox",),
    "favorites": ("bookmarks",),
    "join": ("mount",),
    "leave": ("umount",),
    "loop": ("loopback",),
    "lyrics": ("cat",),
    "nightcore": ("speedup",),
    "nowplaying": ("ps",),
    "pause": ("sleep",),
    "play": ("exec",),
    "playlist": ("mpd",),
    "queue": ("jobs",),
    "radio": ("stream",),
    "refresh": ("flushdns",),
    "remove": ("qdel",),
    "replay": ("restart",),
    "resume": ("fg",),
    "revive": ("respawn",),
    "seek": ("dd",),
    "shuffle": ("shuf",),
    "skip": ("ffwd",),
    "slowed": ("slow",),
    "stop": ("term",),
    "volume": ("amixer",),
    # Music games
    "guessthesong": ("shazam",),
    # Reaction roles
    "reactionrole": ("rr",),
    # Spectrum
    "spectrum": ("showeq",),
    # System
    "invite": ("oauth",),
    "journalctl": ("journal",),
    "latency": ("traceroute",),
    "loadcog": ("insmod",),
    "man": ("archwiki",),
    "ping": ("pong",),
    "reload": ("daemon-reload",),
    "shutdown": ("reboot",),
    "status": ("health",),
    "unloadcog": ("rmmod",),
    "uptime": ("w",),
    # Temp VC
    "createvc": ("mkdir",),
    "vc": ("enter",),
    # Utility
    "announce": ("wall",),
    "base64": ("xxd",),
    "calc": ("qalc",),
    "define": ("grep",),
    "embed": ("markdown",),
    "hash": ("cksum",),
    "poll": ("vote",),
    "publicip": ("wanip",),
    "rand": ("urandom",),
    "remind": ("cron",),
    "say": ("write",),
    "shorten": ("short",),
    "timestamp": ("chrony",),
    "translate": ("locale",),
    "urban": ("slang",),
    "weather": ("forecast",),
    "wiki": ("docs",),
    # Welcome logs
    "logconfig": ("vi",),
    "logdisable": ("logoff",),
    "logsetup": ("rsyslog",),
    "welcomedisable": ("welcomeoff",),
    "welcomesetup": ("motd",),
    # XP
    "bet": ("gamble",),
    "daily": ("payday",),
    "give": ("cp",),
    "leaderboard": ("sort",),
    "rank": ("finger",),
    "work": ("grind",),
    "xpsystem": ("chkconfig",),
}

LINUX_ALIAS_SET: set[str] = {
    alias for aliases in LINUX_ALIASES.values() for alias in aliases
}


def apply_linux_aliases(bot: commands.Bot) -> int:
    """Attach Linux aliases to the given commands.

    Returns the number of aliases successfully attached. Aliases that would
    collide with an existing, unrelated command are skipped.
    """
    count = 0
    for cmd_name, aliases in LINUX_ALIASES.items():
        cmd = bot.all_commands.get(cmd_name)
        if cmd is None:
            continue
        for alias in aliases:
            existing = bot.all_commands.get(alias)
            if existing is not None and existing is not cmd:
                continue
            if alias not in cmd.aliases:
                cmd.aliases.append(alias)
            bot.all_commands[alias] = cmd
            count += 1
    return count


class Linux(commands.Cog, name="linux"):
    """Linux-inspired alternatives for every command (enable with `enable linux`)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_check(self._linux_gate)
        self.bot.linux_disabled_exc = LinuxDisabled

    async def cog_unload(self) -> None:
        self.bot.remove_check(self._linux_gate)

    def _linux_gate(self, ctx: commands.Context) -> bool:
        """Block Linux aliases in servers that have not enabled Linux mode."""
        command = ctx.command
        if command is None:
            return True
        if ctx.invoked_with is None or ctx.invoked_with not in LINUX_ALIAS_SET:
            return True
        if not is_linux_enabled(ctx.guild.id if ctx.guild else None):
            raise LinuxDisabled()
        return True

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title)
        if description:
            embed.description = description
        return embed

    @commands.command(name="enable")
    async def enable(self, ctx: commands.Context, feature: str = "linux") -> None:
        """Enable a feature. Usage: sudo enable linux"""
        if feature.strip().lower() != "linux":
            embed = self._make_embed(
                "❌ Unknown Feature",
                0xE74C3C,
                f"Unknown feature: `{feature}`. Try `sudo enable linux`.",
            )
            await ctx.send(embed=embed)
            return

        if ctx.guild is None:
            embed = self._make_embed(
                "❌ No Server", 0xE74C3C, "Linux mode can only be enabled in a server."
            )
            await ctx.send(embed=embed)
            return

        set_linux_enabled(ctx.guild.id, True)
        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name="🐧 Linux Mode Enabled")
        embed.description = (
            "All Linux-style command alternatives are now active in this server.\n"
            f"Try `{ctx.prefix}neofetch`, `{ctx.prefix}whoami`, `{ctx.prefix}tldr`."
        )
        embed.add_field(
            name="Toggle off",
            value=f"`{ctx.prefix}disable linux`",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(name="disable")
    async def disable(self, ctx: commands.Context, feature: str = "linux") -> None:
        """Disable a feature. Usage: sudo disable linux"""
        if feature.strip().lower() != "linux":
            embed = self._make_embed(
                "❌ Unknown Feature",
                0xE74C3C,
                f"Unknown feature: `{feature}`. Try `sudo disable linux`.",
            )
            await ctx.send(embed=embed)
            return

        if ctx.guild is None:
            embed = self._make_embed(
                "❌ No Server", 0xE74C3C, "Linux mode can only be disabled in a server."
            )
            await ctx.send(embed=embed)
            return

        set_linux_enabled(ctx.guild.id, False)
        embed = discord.Embed(color=0xE74C3C)
        embed.set_author(name="🐧 Linux Mode Disabled")
        embed.description = "Linux-style command alternatives have been deactivated."
        embed.add_field(
            name="Toggle on",
            value=f"`{ctx.prefix}enable linux`",
            inline=False,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Linux(bot))