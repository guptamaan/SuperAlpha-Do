"""
SuperUser Do — A Linux-flavored all-in-one Discord bot.
Prefix: "alpha " or "Alpha " (with a trailing space, e.g. alpha ping),
plus the bot mention and slash (/) commands.
"""

import asyncio
import difflib
import logging
import os
import re
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

from bot.cogs.linux import apply_linux_aliases
from bot.config.settings import BANNED_GUILDS, BANNED_USERS
from bot.core.bot import make_bot

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

# ── Bot ────────────────────────────────────────────────────────────────────────
bot = make_bot()

# ── Cog loader ─────────────────────────────────────────────────────────────────
COGS = [
    "bot.cogs.system",
    "bot.cogs.moderation",
    "bot.cogs.info",
    "bot.cogs.fun",
    "bot.cogs.music",
    "bot.cogs.musicgames",
    "bot.cogs.utility",
    "bot.cogs.games",
    "bot.cogs.ai",
    "bot.cogs.xp",
    "bot.cogs.tempvc",
    "bot.cogs.afk",
    "bot.cogs.welcomelogs",
    "bot.cogs.reaction_roles",
    "bot.cogs.clan_system",
    "bot.cogs.spectrum",
    "bot.cogs.journal",
    "bot.cogs.linux",
    "bot.cogs.automod",
    "bot.cogs.giveaways",
    "bot.cogs.shop",
    "bot.cogs.spam",
    "bot.cogs.distro",
    "bot.cogs.steal",
    "bot.cogs.suggestions",
]


async def load_cogs() -> None:
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            log.info("Loaded cog: %s", cog)
        except Exception as exc:
            log.error("Failed to load cog %s: %s", cog, exc)


# ── Events ─────────────────────────────────────────────────────────────────────

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
        type=discord.ActivityType.playing,
        name="Fixing my own bugs",
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
    prefix = str(getattr(ctx, "prefix", "alpha")).strip() or "alpha"
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
        await _handle_not_found(ctx, ctx.invoked_with or "")
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


# ── Unknown-command handling: bash suggestions + history re-runs ──────────────
async def _handle_not_found(ctx: commands.Context, invoked: str) -> None:
    if invoked.startswith("!") and len(invoked) > 1:
        from bot.cogs.journal import _hist_line, _hist_prefix, _run_as

        bang = re.fullmatch(r"!([\w-]+)", invoked)
        if bang:
            word = bang.group(1)
            entry = _hist_line(ctx.author.id, int(word)) if word.isdigit() else _hist_prefix(ctx.author.id, word)
            if entry is None:
                prefix = str(getattr(ctx, "prefix", "alpha")).strip() or "alpha"
                await ctx.send(
                    embed=discord.Embed(
                        title="⚠️ Command Error",
                        description=f"bash: `{invoked}`: event not found",
                        color=0xE74C3C,
                    ).set_footer(text=f"Prefix: {prefix}")
                )
                return
            await _run_as(ctx, entry["content"])
            return
    await _suggest_command(ctx, invoked)


def _suggestion_names(bot: commands.Bot) -> list[str]:
    names = {cmd.name for cmd in bot.walk_commands()}
    for cmd in bot.walk_commands():
        names.update(cmd.aliases)
    try:
        from bot.cogs.linux import LINUX_ALIASES

        for group in LINUX_ALIASES.values():
            names.update(group)
    except Exception:
        pass
    return sorted(names)


def _closest_names(invoked: str, names: list[str], top: int = 3) -> list[str]:
    compared = invoked.lower()
    scored = []
    for name in names:
        other = name.lower()
        if other == compared:
            continue
        ratio = difflib.SequenceMatcher(None, compared, other).ratio()
        if other.startswith(compared) or compared.startswith(other):
            ratio += 0.15
        if compared in other or other in compared:
            ratio += 0.25
        if ratio >= 0.55:
            scored.append((ratio, name))
    scored.sort(reverse=True)
    return [name for _, name in scored[:top]]


async def _suggest_command(ctx: commands.Context, invoked: str) -> None:
    """Prompt `Did you mean …? (y/n/hint)` for a typo'd command, like bash."""
    prefix = str(getattr(ctx, "prefix", "alpha")).strip() or "alpha"
    names = _suggestion_names(ctx.bot)
    candidates = _closest_names(invoked, names)
    if not candidates:
        try:
            await ctx.send(
                embed=discord.Embed(
                    title="⚠️ Command Error",
                    description=(
                        f"bash: `{invoked}`: command not found\n"
                        f"Try `{prefix} man` to see available commands."
                    ),
                    color=0xE74C3C,
                ).set_footer(text=f"Prefix: {prefix}")
            )
        except discord.HTTPException:
            pass
        return

    async def edit(msg: discord.Message, content: str) -> None:
        try:
            await msg.edit(content=content)
        except discord.HTTPException:
            pass

    from bot.cogs.journal import _run_as

    prompt = f"Did you mean: `{candidates[0]}`?  (y / n / hint)"
    body_lines = [
        f"$ {prefix} {invoked}",
        f"bash: {invoked}: command not found",
        prompt,
    ]
    body = "```bash\n" + "\n".join(body_lines) + "\n```"

    def make_check(allow_numbers: bool = False):
        choices = {"y", "yes", "n", "no", "hint", "cancel"}
        if allow_numbers:
            choices.update({"1", "2", "3"})
        return lambda m: (
            m.author.id == ctx.author.id
            and m.channel.id == ctx.channel.id
            and m.content.strip().lower() in choices
        )

    def target_key(choice: str) -> str | None:
        if choice in ("y", "yes"):
            return candidates[0]
        if choice in ("1", "2", "3"):
            idx = int(choice) - 1
            return candidates[idx] if idx < len(candidates) else None
        return None

    async def wait_answer(check, timeout: float = 30.0):
        try:
            return await ctx.bot.wait_for("message", check=check, timeout=timeout)
        except asyncio.TimeoutError:
            return None

    try:
        msg = await ctx.send(body)
    except discord.HTTPException:
        return

    answer = await wait_answer(make_check())
    if answer is None:
        await edit(msg, body + "* ignored — nothing run *")
        return
    choice = answer.content.strip().lower()
    if choice in ("n", "no", "cancel"):
        await edit(msg, body + "* aborted *")
        return
    if choice == "hint":
        hint_lines = [
            f"$ {prefix} {invoked}",
            f"bash: {invoked}: command not found",
            "Did you mean one of:",
        ]
        for i, name in enumerate(candidates, 1):
            hint_lines.append(f"  {i}. {name}")
        hint_lines.append("(reply 1-3, y / n / cancel)")
        hint_body = "```bash\n" + "\n".join(hint_lines) + "\n```"
        await edit(msg, hint_body)
        answer = await wait_answer(make_check(allow_numbers=True), timeout=30.0)
        if answer is None:
            await edit(msg, hint_body + "* ignored — nothing run *")
            return
        choice = answer.content.strip().lower()
        if choice in ("n", "no", "cancel"):
            await edit(msg, hint_body + "* aborted *")
            return
    target = target_key(choice)
    if target is None:
        return
    await edit(msg, body + f"\nRunning `{prefix} {target}`…")
    await _run_as(ctx, f"{ctx.prefix}{target}")


# ── Entry point ────────────────────────────────────────────────────────────────
async def main() -> None:
    async with bot:
        await load_cogs()
        attached = apply_linux_aliases(bot)
        log.info("Attached %d Linux aliases.", attached)
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
