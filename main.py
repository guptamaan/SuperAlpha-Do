"""
SuperUser Do — A Linux-flavored all-in-one Discord bot.
Prefix: "sudo " or "$ " or "@SuperUser Do " (with a trailing space, e.g. sudo ping)
"""

import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

from cogs.linux import apply_linux_aliases

# ── Bootstrap ──────────────────────────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("SuperUser Do")

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    log.critical("DISCORD_TOKEN not set in .env — aborting.")
    sys.exit(1)

# ── Intents ────────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.voice_states = True
intents.presences = True


# ── Bot ────────────────────────────────────────────────────────────────────────
def get_prefix(bot: commands.Bot, message: discord.Message) -> list[str]:
    base_prefixes = ["sudo ", "Sudo ", "SUDO ", "$ "]
    content = message.content.lower()
    for p in base_prefixes:
        if content.startswith(p.lower()):
            return [p, f"<@{bot.user.id}> ", f"<@!{bot.user.id}> "]
    return [f"<@{bot.user.id}> ", f"<@!{bot.user.id}> "]


SUPER_USERS = {1224391248580972584}

bot = commands.Bot(
    command_prefix=get_prefix,
    intents=intents,
    help_command=None,
    case_insensitive=True,
    owner_ids=SUPER_USERS,
)

# ── Cog loader ─────────────────────────────────────────────────────────────────
COGS = [
    "cogs.system",
    "cogs.moderation",
    "cogs.info",
    "cogs.fun",
    "cogs.music",
    "cogs.musicgames",
    "cogs.utility",
    "cogs.games",
    "cogs.ai",
    "cogs.xp",
    "cogs.tempvc",
    "cogs.afk",
    "cogs.welcomelogs",
    "cogs.reaction_roles",
    "cogs.clan_system",
    "cogs.spectrum",
    "cogs.journal",
    "cogs.linux",
]


async def load_cogs() -> None:
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            log.info("Loaded cog: %s", cog)
        except Exception as exc:
            log.error("Failed to load cog %s: %s", cog, exc)


# ── Events ─────────────────────────────────────────────────────────────────────
BANNED_GUILDS = {1523771297090507005, 1446772086231138375}
BANNED_USERS: set[int] = set()


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    if message.author.id in BANNED_USERS:
        return

    await bot.process_commands(message)


@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    if guild.id in BANNED_GUILDS:
        log.info("Joined banned guild: %s (ID: %s) — leaving...", guild.name, guild.id)
        try:
            await guild.leave()
            log.info("Successfully left banned guild: %s", guild.name)
        except Exception as e:
            log.error("Failed to leave guild %s: %s", guild.name, e)


@bot.event
async def on_ready() -> None:
    for guild_id in BANNED_GUILDS:
        try:
            guild = await bot.fetch_guild(guild_id)
            log.info(
                "Found banned guild: %s (ID: %s) — leaving...", guild.name, guild.id
            )
            await guild.leave()
            log.info("Successfully left banned guild: %s", guild.name)
        except discord.NotFound:
            log.info("Guild %s not found (not in it)", guild_id)
        except Exception as e:
            log.error("Failed to leave guild %s: %s", guild_id, e)
            try:
                await bot.http.leave_guild(guild_id)
                log.info("Left banned guild via HTTP: %s", guild_id)
            except Exception as e2:
                log.error("HTTP leave also failed: %s", e2)

    activity = discord.Activity(
        type=discord.ActivityType.watching,
        name="ZoundZ Nation on YouTube",
    )
    await bot.change_presence(status=discord.Status.idle, activity=activity)
    await bot.tree.sync()
    log.info("Synced slash commands")
    log.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    log.info("Guilds: %d", len(bot.guilds))

    guilds_file = "guilds.txt"
    current_guilds = {guild.id: guild.name for guild in bot.guilds}

    with open(guilds_file, "w") as f:
        for guild_id, guild_name in sorted(
            current_guilds.items(), key=lambda x: x[1].lower()
        ):
            f.write(f"{guild_id} | {guild_name}\n")
    log.info("Saved %d guilds to %s", len(current_guilds), guilds_file)

    if os.path.exists(guilds_file):
        with open(guilds_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(" | ", 1)
                if len(parts) == 2:
                    guild_id_str, guild_name = parts
                    try:
                        guild_id = int(guild_id_str)
                        if guild_id not in current_guilds:
                            log.warning(
                                "Not in guild: %s (ID: %s)", guild_name, guild_id
                            )
                    except ValueError:
                        pass


@bot.event
async def on_command(ctx: commands.Context) -> None:
    user = ctx.author
    cmd = ctx.command.qualified_name if ctx.command else ctx.invoked_with
    guild = ctx.guild
    channel = ctx.channel
    guild_name = guild.name if guild else "DM"
    log.info(
        "CMD USED: %s by %s (%s) in %s (#%s)",
        cmd,
        user,
        user.id,
        guild_name,
        channel,
    )


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    prefix = str(getattr(ctx, "prefix", "sudo")).strip() or "sudo"
    embed_color = 0xE74C3C

    async def send_error(description: str, *, usage: str | None = None) -> None:
        try:
            embed = discord.Embed(
                title="⚠️ Command Error", description=description, color=embed_color
            )
            if usage:
                embed.add_field(name="Usage", value=usage, inline=False)
            embed.set_footer(text=f"Prefix: {prefix}")
            await ctx.send(embed=embed)
        except discord.HTTPException:
            pass

    if isinstance(error, commands.CommandNotFound):
        cmd = ctx.invoked_with
        await send_error(
            f"Unknown command: `{cmd}`.\nTry `{prefix} man` to see available commands."
        )
    elif isinstance(error, commands.MissingRequiredArgument):
        await send_error(
            f"Missing operand: `{error.param.name}`.",
            usage=f"{prefix} {ctx.command.qualified_name} {ctx.command.signature}",
        )
    elif isinstance(error, commands.MissingPermissions):
        perms = ", ".join(error.missing_permissions)
        await send_error(
            f"Permission denied. You need: {perms}",
        )
    elif isinstance(error, commands.BotMissingPermissions):
        perms = ", ".join(error.missing_permissions)
        await send_error(
            f"Bot permission denied. Bot needs: {perms}",
        )
    elif isinstance(error, commands.MemberNotFound):
        await send_error(f"User not found: `{error.argument}`.")
    elif isinstance(error, commands.BadArgument):
        await send_error(f"Bad argument: `{error}`.")
    elif isinstance(error, commands.CommandOnCooldown):
        await send_error(
            f"⏰ Slow down! `{prefix}{ctx.command.qualified_name}` is still on "
            f"cooldown. Try again in **{error.retry_after:.1f}s**.",
        )
    elif type(error).__name__ == "LinuxDisabled":
        await send_error(
            f"Linux mode is disabled in this server. Enable it with "
            f"`{prefix}enable linux`.",
        )
    elif isinstance(error, commands.CheckFailure):
        await send_error("Access denied.")
    elif isinstance(error, discord.HTTPException):
        pass
    else:
        log.exception("Unhandled error in command '%s':", ctx.command, exc_info=error)
        await send_error(f"Unexpected error: `{error}`.")


# ── Entry point ────────────────────────────────────────────────────────────────
async def main() -> None:
    async with bot:
        await load_cogs()
        attached = apply_linux_aliases(bot)
        log.info("Attached %d Linux aliases.", attached)
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
