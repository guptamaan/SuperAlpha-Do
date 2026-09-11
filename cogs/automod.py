"""
cogs/automod.py — Auto-moderation.
Word filter, link whitelist, mass-mention detection, and a strike system.
Per-guild config stored in data/automod/config.json; strikes in data/automod/strikes.json.
Commands: automod, automod word, automod allow, automod mentions, automod action, automod alert
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

from cogs.checks import perms_or_developer

CONFIG_DIR = "data/automod"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
STRIKES_FILE = os.path.join(CONFIG_DIR, "strikes.json")

os.makedirs(CONFIG_DIR, exist_ok=True)

DEFAULT_WORDS = [
    "kys", "kill yourself", "finish yourself",
]
PHISH_WORDS = ["nitro", ".gift", "discord-nitro", "steamcommunity.com/glitch", "free nitro"]
DEFAULT_MAX_MENTIONS = 6
DEFAULT_MAX_LINKS = 3
STRIKE_TIMEOUT = 86400  # seconds before strikes decay
ESCALATION_LIMIT = 3
MUTE_MINUTES = 30

_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def _load_json(path: str) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_guild_config(guild_id: int) -> dict:
    config = _load_json(CONFIG_FILE)
    data = config.get(str(guild_id)) or {
        "enabled": False,
        "words": list(DEFAULT_WORDS),
        "link_whitelist": [],
        "max_mentions": DEFAULT_MAX_MENTIONS,
        "max_links": DEFAULT_MAX_LINKS,
        "action": "warn",
        "alert_channel": None,
    }
    return data


def set_guild_config(guild_id: int, data: dict) -> None:
    config = _load_json(CONFIG_FILE)
    config[str(guild_id)] = data
    _save_json(CONFIG_FILE, config)


def get_strikes(guild_id: int) -> dict:
    strikes = _load_json(STRIKES_FILE)
    return strikes.get(str(guild_id)) or {}


def set_strikes(guild_id: int, data: dict) -> None:
    strikes = _load_json(STRIKES_FILE)
    strikes[str(guild_id)] = data
    _save_json(STRIKES_FILE, strikes)


def _domain(url: str) -> str:
    match = re.match(r"https?://(?:www\.)?([^/?#]+)", url, re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).lower()


class AutoMod(commands.Cog, name="automod"):
    """Automatic moderation (word filter, links, mentions)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title, icon_url=None)
        if description:
            embed.description = description
        return embed

    def _alert_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        config = get_guild_config(guild.id)
        channel_id = config.get("alert_channel")
        if channel_id:
            return guild.get_channel(channel_id)
        return None

    async def _log_violation(
        self, guild: discord.Guild, offender: discord.Member, reason: str, action: str
    ) -> None:
        channel = self._alert_channel(guild)
        if not channel:
            return
        embed = discord.Embed(color=0xE74C3C, timestamp=datetime.now(timezone.utc))
        embed.set_author(name="🚨 Auto-Mod Violation")
        embed.add_field(name="User", value=offender.mention, inline=True)
        embed.add_field(name="Action", value=action, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"ID: {offender.id}")
        try:
            await channel.send(embed=embed)
        except Exception:
            pass

    async def _take_action(self, message: discord.Message, reason: str) -> None:
        """Apply the configured action and count the strike."""
        guild = message.guild
        config = get_guild_config(guild.id)
        member = message.author
        action = config.get("action", "warn")

        now = time.time()
        strikes = get_strikes(guild.id)
        user_strikes = strikes.get(str(member.id)) or {"count": 0, "last": 0}
        if now - user_strikes.get("last", 0) > STRIKE_TIMEOUT:
            user_strikes["count"] = 0
        user_strikes["count"] += 1
        user_strikes["last"] = now
        strikes[str(member.id)] = user_strikes
        set_strikes(guild.id, strikes)

        escalate = user_strikes["count"] >= ESCALATION_LIMIT
        taken = action

        if escalate:
            try:
                until = discord.utils.utcnow() + timedelta(minutes=MUTE_MINUTES)
                await member.timeout(until, reason=f"Auto-mod: {reason}")
                taken = f"timeout {MUTE_MINUTES}m (escalated, {user_strikes['count']} strikes)"
            except Exception:
                taken = f"{action} (could not escalate)"

        if taken == "delete" and not escalate:
            try:
                await message.delete()
            except Exception:
                pass

        if taken == "warn" and not escalate:
            try:
                await member.send(
                    embed=self._make_embed(
                        "⚠️ Auto-Mod Warning",
                        0xF39C12,
                        f"Your message in **{guild.name}** was flagged: {reason}\n"
                        f"You have **{user_strikes['count']}** strike(s). "
                        f"After {ESCALATION_LIMIT} strikes you will be timed out.",
                    )
                )
            except Exception:
                pass

        await self._log_violation(guild, member, reason, taken)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        config = get_guild_config(message.guild.id)
        if not config.get("enabled", False):
            return

        content = message.content
        lowered = content.lower()

        for word in config.get("words", []):
            if word and re.search(rf"\b{re.escape(word)}\b", lowered):
                await self._take_action(message, f"Banned word: `{word}`")
                return

        for phish in PHISH_WORDS:
            if phish in lowered:
                await self._take_action(message, "Suspected phishing link")
                return

        urls = _URL_RE.findall(content)
        if urls:
            whitelist = [d.lower() for d in config.get("link_whitelist", [])]
            if whitelist and not any(_domain(u) in whitelist for u in urls):
                await self._take_action(message, "Link not in the allowed whitelist")
                return
            if len(urls) > config.get("max_links", DEFAULT_MAX_LINKS):
                await self._take_action(message, f"Too many links ({len(urls)})")
                return

        mention_count = len(message.mentions) + len(message.role_mentions)
        if "@everyone" in content or "@here" in content:
            mention_count += 100
        if mention_count > config.get("max_mentions", DEFAULT_MAX_MENTIONS):
            await self._take_action(
                message, f"Mass mention ({mention_count} mentions)"
            )

    @commands.command(name="automod")
    @perms_or_developer(administrator=True)
    async def automod(self, ctx: commands.Context, action: str = None, *, arg: str = None) -> None:
        """Configure auto-moderation. Usage: alpha automod [enable|disable|status|word|allow|mentions|action|alert]"""
        if not action:
            await self._automod_status(ctx)
            return

        action = action.lower()

        if action in ["enable", "on", "true", "1", "yes"]:
            config = get_guild_config(ctx.guild.id)
            config["enabled"] = True
            set_guild_config(ctx.guild.id, config)
            embed = self._make_embed("✅ Auto-Mod Enabled", 0x2ECC71, "Auto-moderation is now active.")
            await ctx.send(embed=embed)

        elif action in ["disable", "off", "false", "0", "no"]:
            config = get_guild_config(ctx.guild.id)
            config["enabled"] = False
            set_guild_config(ctx.guild.id, config)
            embed = self._make_embed("❌ Auto-Mod Disabled", 0xE74C3C, "Auto-moderation is off.")
            await ctx.send(embed=embed)

        elif action in ["status", "info", "show"]:
            await self._automod_status(ctx)

        elif action in ["word", "words", "block"]:
            await self._edit_list(
                ctx, "words", arg, ["add", "remove", "list", "clear"],
            )

        elif action in ["allow", "whitelist", "allowlist", "link"]:
            await self._edit_list(
                ctx, "link_whitelist", arg, ["add", "remove", "list", "clear"],
            )

        elif action in ["mentions", "mention", "maxmentions"]:
            if arg and arg.isdigit():
                config = get_guild_config(ctx.guild.id)
                config["max_mentions"] = int(arg)
                set_guild_config(ctx.guild.id, config)
                embed = self._make_embed("✅ Max Mentions", 0x2ECC71, f"Max mentions set to **{arg}**.")
                await ctx.send(embed=embed)
            else:
                embed = self._make_embed("❌ Invalid", 0xE74C3C, "Usage: `alpha automod mentions <number>`")
                await ctx.send(embed=embed)

        elif action in ["action", "strikeaction"]:
            valid = {"warn", "delete", "mute"}
            if arg and arg.lower() in valid:
                config = get_guild_config(ctx.guild.id)
                config["action"] = arg.lower()
                set_guild_config(ctx.guild.id, config)
                embed = self._make_embed("✅ Action Set", 0x2ECC71, f"Strike action set to **{arg.lower()}**.")
                await ctx.send(embed=embed)
            else:
                embed = self._make_embed("❌ Invalid", 0xE74C3C, "Valid actions: `warn`, `delete`, `mute`.")
                await ctx.send(embed=embed)

        elif action in ["alert", "log", "channel"]:
            await self._set_alert(ctx, arg)

        else:
            embed = self._make_embed(
                "❌ Invalid Action", 0xE74C3C,
                "Usage: `alpha automod [enable|disable|status]`\n"
                "`alpha automod word add|remove|list`\n"
                "`alpha automod allow add|remove|list`\n"
                "`alpha automod mentions <n>` · `alpha automod action <warn|delete|mute>` · `alpha automod alert <#channel|off>`",
            )
            await ctx.send(embed=embed)

    async def _automod_status(self, ctx: commands.Context) -> None:
        config = get_guild_config(ctx.guild.id)
        enabled = "✅ Enabled" if config.get("enabled") else "❌ Disabled"
        words = config.get("words", [])
        whitelist = config.get("link_whitelist", [])
        alert = config.get("alert_channel")
        alert_str = f"<#{alert}>" if alert else "None"

        embed = discord.Embed(color=0x9B59B6)
        embed.set_author(name="🛡️ Auto-Mod Status")
        if config.get("enabled"):
            embed.set_footer(text=f"Disable with `{ctx.prefix}disable automod`")
        else:
            embed.set_footer(text=f"Enable with `{ctx.prefix}enable automod`")
        embed.add_field(name="Status", value=enabled, inline=True)
        embed.add_field(name="Action", value=config.get("action", "warn"), inline=True)
        embed.add_field(name="Max Mentions", value=str(config.get("max_mentions", DEFAULT_MAX_MENTIONS)), inline=True)
        embed.add_field(name="Alert Channel", value=alert_str, inline=True)
        embed.add_field(
            name=f"Blocked Words ({len(words)})",
            value=", ".join(f"`{w}`" for w in words[:20]) or "None",
            inline=False,
        )
        embed.add_field(
            name=f"Allowed Links ({len(whitelist)})",
            value=", ".join(f"`{d}`" for d in whitelist[:20]) or "None",
            inline=False,
        )
        await ctx.send(embed=embed)

    async def _edit_list(self, ctx: commands.Context, key: str, arg: str, verbs: list[str]) -> None:
        config = get_guild_config(ctx.guild.id)
        values = config.setdefault(key, [])
        label = "word" if key == "words" else "domain"

        if not arg:
            lines = ", ".join(f"`{v}`" for v in values[:20]) or "None"
            embed = discord.Embed(color=0x9B59B6)
            embed.set_author(name=f"🛡️ {label.title()} List")
            embed.description = lines
            await ctx.send(embed=embed)
            return

        parts = arg.split(maxsplit=1)
        verb, rest = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")

        if verb in ["add", "a", "block", "allow"]:
            if not rest:
                embed = self._make_embed("❌ Missing Value", 0xE74C3C, f"Usage: `alpha automod {label} add <{label}>`")
                await ctx.send(embed=embed)
                return
            value = rest.strip().lower()
            if value in values:
                embed = self._make_embed("❌ Already Added", 0xE74C3C, f"`{value}` is already on the list.")
            else:
                values.append(value)
                set_guild_config(ctx.guild.id, config)
                embed = self._make_embed("✅ Added", 0x2ECC71, f"Added `{value}` to the {label} list.")
            await ctx.send(embed=embed)

        elif verb in ["remove", "r", "rm", "unblock"]:
            if not rest:
                embed = self._make_embed("❌ Missing Value", 0xE74C3C, f"Usage: `alpha automod {label} remove <{label}>`")
                await ctx.send(embed=embed)
                return
            value = rest.strip().lower()
            if value in values:
                values.remove(value)
                set_guild_config(ctx.guild.id, config)
                embed = self._make_embed("🗑️ Removed", 0xE74C3C, f"Removed `{value}` from the {label} list.")
            else:
                embed = self._make_embed("❌ Not Found", 0xE74C3C, f"`{value}` is not on the list.")
            await ctx.send(embed=embed)

        elif verb in ["clear", "c"]:
            config[key] = []
            set_guild_config(ctx.guild.id, config)
            embed = self._make_embed("🧹 Cleared", 0x95A5A6, f"Cleared the {label} list.")
            await ctx.send(embed=embed)

        else:
            embed = self._make_embed(
                "❌ Invalid Verb", 0xE74C3C,
                f"Usage: `alpha automod {label} add|remove|clear <{label}>`",
            )
            await ctx.send(embed=embed)

    async def _set_alert(self, ctx: commands.Context, arg: str) -> None:
        config = get_guild_config(ctx.guild.id)
        if arg and arg.lower() in ["off", "none", "clear", "0"]:
            config["alert_channel"] = None
            set_guild_config(ctx.guild.id, config)
            embed = self._make_embed("🔕 Alerts Off", 0x95A5A6, "Violation alerts are disabled.")
            await ctx.send(embed=embed)
            return
        if arg and arg.startswith("<#") and arg.endswith(">"):
            try:
                channel_id = int(arg[2:-1])
            except ValueError:
                channel_id = None
            channel = ctx.guild.get_channel(channel_id) if channel_id else None
            if channel:
                config["alert_channel"] = channel.id
                set_guild_config(ctx.guild.id, config)
                embed = self._make_embed("✅ Alert Channel", 0x2ECC71, f"Violations will be logged to {channel.mention}.")
                await ctx.send(embed=embed)
                return
        embed = self._make_embed("❌ Invalid Channel", 0xE74C3C, "Usage: `alpha automod alert <#channel|off>`")
        await ctx.send(embed=embed)

    @automod.error
    async def automod_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingPermissions):
            embed = self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission.")
            await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoMod(bot))