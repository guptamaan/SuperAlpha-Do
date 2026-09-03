"""
cogs/system.py — System-level bot management commands.
Commands: ping, uptime, man, reload, shutdown, status, htop, loadcog, unloadcog,
          prefix, invite, latency
"""

import asyncio
import glob
import math
import os
import time
import platform

import discord
from discord import app_commands
from discord.ext import commands

import cogs.journal as _journal

START_TIME = time.time()

INVITE_URL = "https://discord.com/oauth2/authorize?client_id=1472581750810083339"
OWNER_HANDLE = "@r4ve_x"


# ── Host health helpers (read /proc, htop-style) ──────────────────────────────
def _proc_read(path: str) -> str:
    try:
        with open(f"/proc/{path}") as f:
            return f.read()
    except OSError:
        return ""


def _bar(pct: float, width: int = 10) -> str:
    filled = max(0, min(width, round(pct / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def _cpu_usage() -> str:
    def sample() -> tuple[int, int] | None:
        stat = _proc_read("stat")
        if not stat:
            return None
        parts = stat.split("\n")[0].split()[1:]
        try:
            total = sum(int(p) for p in parts)
            idle = int(parts[3]) + int(parts[4])
        except (ValueError, IndexError):
            return None
        return total, idle

    try:
        a = sample()
        time.sleep(0.25)
        b = sample()
        if not a or not b:
            return "n/a"
        d_total = max(b[0] - a[0], 1)
        d_idle = b[1] - a[1]
        return f"{max(0, 100 * (d_total - d_idle) / d_total):.0f}%"
    except Exception:
        return "n/a"


def _mem_info() -> tuple[int, int, float] | None:
    info = _proc_read("meminfo")
    mem_total = mem_avail = 0
    for ln in info.splitlines():
        if ln.startswith("MemTotal:"):
            mem_total = int(ln.split()[1]) * 1024
        elif ln.startswith("MemAvailable:"):
            mem_avail = int(ln.split()[1]) * 1024
    if not mem_total:
        return None
    used = mem_total - mem_avail
    return mem_total, used, 100 * used / mem_total


def _load_avg() -> str:
    load = _proc_read("loadavg").split()
    if len(load) < 3:
        return "n/a"
    return "  ".join(load[:3])


def _format_age(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02d}:{mins:02d}:{secs:02d}"
    return f"{hours:02d}:{mins:02d}:{secs:02d}"


def _bot_age() -> str:
    """Process start time derived from /proc, falling back to module import."""
    stat = _proc_read("self/stat")
    uptime = _proc_read("uptime")
    try:
        boot_ticks = int(stat.split()[21])
        hz = os.sysconf("SC_CLK_TCK")
        age = float(uptime.split()[0]) - boot_ticks / hz
        return _format_age(int(age))
    except (IndexError, ValueError, OSError):
        return _format_age(int(time.time() - START_TIME))


def _task_count() -> int | None:
    try:
        return sum(1 for _ in glob.iglob("/proc/[0-9]*"))
    except OSError:
        return None


class System(commands.Cog, name="system"):
    """Core system commands (ping, uptime, man, reload, shutdown)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._htop_refresh = 3.0
        self._htop_refreshes = 10

    # ── ping ──────────────────────────────────────────────────────────────────
    @commands.command(name="ping", aliases=["uname"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def ping(self, ctx: commands.Context) -> None:
        """Check bot latency. Usage: sudo ping"""
        import time as _t
        before = _t.monotonic()
        msg = await ctx.send("```bash\n$ sudo ping discord.com\nPinging…\n```")
        rtt = round((_t.monotonic() - before) * 1000)
        ws  = round(self.bot.latency * 1000)
        await msg.edit(content=(
            f"```bash\n$ sudo ping discord.com\n"
            f"PING discord.com: 64 bytes\n"
            f"icmp_seq=1  ws={ws} ms  rtt={rtt} ms\n```"
        ))

    # ── latency ───────────────────────────────────────────────────────────────
    @commands.command(name="latency", aliases=["lag", "netstat"])
    async def latency(self, ctx: commands.Context) -> None:
        """Show WebSocket latency. Usage: sudo latency"""
        ws = round(self.bot.latency * 1000)
        bar_filled = min(int(ws / 10), 20)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        quality = "excellent" if ws < 80 else "good" if ws < 150 else "poor"
        await ctx.send(
            f"```bash\n$ sudo latency\n"
            f"WebSocket: {ws} ms  [{bar}]  {quality}\n```"
        )

    # ── uptime ────────────────────────────────────────────────────────────────
    @commands.command(name="uptime", aliases=["up"])
    async def uptime(self, ctx: commands.Context) -> None:
        """Show how long the bot has been running. Usage: sudo uptime"""
        elapsed = int(time.time() - START_TIME)
        days, rem = divmod(elapsed, 86400)
        hours, rem = divmod(rem, 3600)
        mins, secs = divmod(rem, 60)
        uptime_str = f"{days}d {hours:02d}:{mins:02d}:{secs:02d}"
        await ctx.send(
            f"```bash\n$ uptime\n"
            f" up {uptime_str},  1 user,  load average: 0.01, 0.01, 0.00\n```"
        )

    # ── man ───────────────────────────────────────────────────────────────────
    @commands.command(name="man", aliases=["help", "--help", "-h", "ls"])
    async def man(self, ctx: commands.Context, *, command_name: str | None = None) -> None:
        """Show the manual page for a command or list all commands. Usage: sudo man [command]"""
        if command_name:
            cmd = self.bot.get_command(command_name)
            if cmd is None:
                await ctx.send(f"```bash\nNo manual entry for {command_name}\n```")
                return
            embed = discord.Embed(
                title=f"MAN PAGE — sudo {cmd.qualified_name}",
                description=cmd.help or "No description available.",
                color=0x2ECC71,
            )
            embed.add_field(
                name="SYNOPSIS",
                value=f"`sudo {cmd.qualified_name} {cmd.signature}`",
                inline=False,
            )
            if cmd.aliases:
                alias_str = ", ".join(f"`{a}`" for a in cmd.aliases)
                embed.add_field(
                    name="ALIASES",
                    value=alias_str,
                    inline=False,
                )
            await ctx.send(embed=embed)
            return

        # Full command listing grouped by cog
        embed = discord.Embed(
            title="📖  sudo man  —  Command Manual",
            description="Prefix: `sudo <command>` or `Sudo <command>`\nUse `sudo man <command>` / `Sudo man <command>` for detailed info.\nMany commands have Linux/Arch aliases (e.g., `sudo ls` shows all commands).",
            color=0x3498DB,
        )
        for cog_name, cog in sorted(self.bot.cogs.items()):
            cmds = [c for c in cog.get_commands() if not c.hidden]
            if cmds:
                value = "  ".join(f"`{c.name}`" for c in cmds)
                embed.add_field(name=f"[{cog_name.upper()}]", value=value, inline=False)
        embed.set_footer(text="sudo man <command> / Sudo man <command> for detailed usage")
        await ctx.send(embed=embed)

    # ── status ────────────────────────────────────────────────────────────────
    @commands.command(name="status", aliases=["sysinfo"])
    async def status(self, ctx: commands.Context) -> None:
        """Display bot system status. Usage: sudo status"""
        guilds  = len(self.bot.guilds)
        users   = sum(g.member_count or 0 for g in self.bot.guilds)
        latency = round(self.bot.latency * 1000)
        elapsed = int(time.time() - START_TIME)
        days, rem = divmod(elapsed, 86400)
        hours, rem = divmod(rem, 3600)
        mins, secs = divmod(rem, 60)
        cogs_loaded = len(self.bot.cogs)
        cmds_total  = len(self.bot.commands)

        embed = discord.Embed(title="⚙️  System Status — SuperUser Do", color=0x1ABC9C)
        embed.add_field(name="🏓 Latency",    value=f"{latency} ms",                              inline=True)
        embed.add_field(name="🖥️  Guilds",    value=str(guilds),                                  inline=True)
        embed.add_field(name="👥 Users",      value=str(users),                                   inline=True)
        embed.add_field(name="⏱️  Uptime",    value=f"{days}d {hours:02d}:{mins:02d}:{secs:02d}", inline=True)
        embed.add_field(name="🔌 Cogs",       value=str(cogs_loaded),                             inline=True)
        embed.add_field(name="⌨️  Commands",  value=str(cmds_total),                              inline=True)
        embed.add_field(name="🐍 Python",     value=platform.python_version(),                    inline=True)
        embed.add_field(name="📦 discord.py", value=discord.__version__,                          inline=True)
        embed.add_field(name="🖥️  OS",        value=platform.system(),                            inline=True)
        embed.set_footer(text=f"Bot: {self.bot.user}")
        await ctx.send(embed=embed)

    # ── htop ──────────────────────────────────────────────────────────────────
    @commands.command(name="htop")
    @commands.cooldown(1, 45, commands.BucketType.channel)
    async def htop(self, ctx: commands.Context) -> None:
        """Live terminal-style health dashboard. Usage: sudo htop"""
        desc = "```bash\n" + self._htop_block(ctx) + "\n```"
        embed = discord.Embed(title="🖥️  htop — live dashboard", description=desc, color=0x1ABC9C)
        embed.set_footer(text="Live refresh · react ⏹ to stop")
        msg = await ctx.send(embed=embed)

        try:
            await msg.add_reaction("⏹")
        except discord.HTTPException:
            pass

        stop = asyncio.Event()

        async def watcher() -> None:
            def check(reaction: discord.Reaction, user) -> bool:
                return (
                    str(reaction.emoji) == "⏹"
                    and reaction.message.id == msg.id
                    and user.id == ctx.author.id
                )
            while not stop.is_set():
                try:
                    await self.bot.wait_for("reaction_add", check=check, timeout=5)
                    stop.set()
                except asyncio.TimeoutError:
                    continue

        async def refresher() -> None:
            for _ in range(self._htop_refreshes):
                if stop.is_set():
                    return
                await asyncio.sleep(self._htop_refresh)
                if stop.is_set():
                    return
                try:
                    desc = "```bash\n" + self._htop_block(ctx) + "\n```"
                    embed = discord.Embed(
                        title="🖥️  htop — live dashboard",
                        description=desc,
                        color=0x1ABC9C,
                    )
                    embed.set_footer(text="Live refresh · react ⏹ to stop")
                    await msg.edit(embed=embed)
                except discord.HTTPException:
                    return
            stop.set()

        await asyncio.gather(refresher(), watcher())
        try:
            await msg.clear_reaction("⏹")
        except discord.HTTPException:
            pass

    def _htop_block(self, ctx: commands.Context) -> str:
        core_count = os.cpu_count() or 1
        tasks = _task_count()
        cpu = _cpu_usage()
        cpu_pct = float(cpu.strip("%")) if cpu.endswith("%") else 0.0
        mem = _mem_info()

        bot_name = _journal._clean(getattr(self.bot.user, "name", None) or "sudo")[:14]
        lines = ["$ sudo htop"]
        lines.append(
            f"{bot_name:<22} up {_bot_age():<16} "
            f"Tasks: {tasks if tasks is not None else 'n/a'}"
        )
        lines.append(f"load avg: {_load_avg()}  ({core_count} core{'s' if core_count != 1 else ''})")
        lines.append(f"CPU {_bar(cpu_pct)} {cpu}")
        if mem:
            total_g, used_g = mem[0] / 2**30, mem[1] / 2**30
            lines.append(f"MEM {_bar(mem[2])} {used_g:.1f}G / {total_g:.1f}G ({mem[2]:.0f}%)")
        else:
            lines.append("MEM n/a")

        lines.append("─" * 44)
        guild = ctx.guild
        if guild:
            members = list(guild.members)
            online = sum(1 for m in members if m.status is not discord.Status.offline)
            bots = sum(1 for m in members if m.bot)
            voice_users = sum(len(ch.members) for ch in guild.voice_channels)
            voice_ch = sum(1 for ch in guild.voice_channels if ch.members)
            lines.append(f"GUILD {_journal._clean(guild.name)[:26]} — {guild.member_count:,} members")
            lines.append(
                f"      online {online:,} · bots {bots:,} · voice {voice_users} "
                f"({voice_ch} ch) · text {len(guild.text_channels)} · "
                f"vc {len(guild.voice_channels)} · boost Lv{guild.premium_tier}"
            )
        else:
            lines.append("GUILD — (direct message)")

        today = time.strftime("%Y-%m-%d")
        try:
            cmds_today = sum(
                1
                for e in _journal._load_journal()
                if time.strftime("%Y-%m-%d", time.localtime(e.get("ts") or 0)) == today
            )
        except Exception:
            cmds_today = 0
        latency = self.bot.latency
        if not math.isfinite(latency):
            latency = 0.0
        lines.append(
            f"BOT   {round(latency * 1000)}ms · {len(self.bot.guilds)} guilds · "
            f"{cmds_today} cmds today · py {platform.python_version()}"
        )

        lines.append("─" * 44)
        lines.append(f"{'':<14} {'':<3} {'':<10} PROCESSES")
        proc = self._htop_process_rows()
        if proc:
            lines.extend(proc)
        else:
            lines.append("(nothing running)")

        return "\n".join(line[:104] for line in lines)

    def _htop_process_rows(self) -> list[str]:
        rows: list[str] = []

        def row(left: str, state: str, cmd: str, args: str) -> str:
            return f"{left:<14} {state:<3} {cmd:<10} {args[:40]}"

        music = self.bot.get_cog("music")
        if music:
            for gid, player in list(getattr(music, "_players", {}).items()):
                if len(rows) >= 4:
                    break
                guild = self.bot.get_guild(gid)
                gname = _journal._clean(guild.name)[:14] if guild else "?"
                vc = guild.voice_client if guild else None
                if vc and vc.is_paused():
                    state = "⏸"
                elif vc and vc.is_playing():
                    state = "▶"
                else:
                    state = "□"
                track = player.current
                if track is None and player.queue:
                    track = player.queue[0]
                title = _journal._clean(getattr(track, "title", None) or "—")[:30]
                rows.append(row(gname, state, "play", title))

        mg = self.bot.get_cog("musicgames")
        if mg:
            for gid in getattr(mg, "_active", {}) or {}:
                if len(rows) >= 4:
                    break
                guild = self.bot.get_guild(gid)
                gname = _journal._clean(guild.name)[:14] if guild else "?"
                rows.append(row(gname, "▶", "game", "guess-the-song"))

        limit = 4 - len(rows)
        if limit > 0:
            for e in list(_journal._load_journal())[-limit:]:
                rows.append(row(
                    e.get("uid", "?"),
                    "·",
                    str(e.get("cmd", "?"))[:10],
                    _journal._format_args(e),
                ))
        return rows

    # ── invite ────────────────────────────────────────────────────────────────
    @commands.command(name="invite")
    async def invite(self, ctx: commands.Context) -> None:
        """Generate bot invite link. Usage: sudo invite"""
        embed = discord.Embed(
            title="🐧 Add SuperUser Do to your server",
            description=(
                f"🔗 [Click to invite SuperUser Do]({INVITE_URL})\n"
                "```bash\n$ sudo invite\nInvite URL generated.\n```"
            ),
            color=0x2ECC71,
        )
        embed.add_field(
            name="⚠️ Registration required",
            value=(
                "You **must** register the bot in the DMs of "
                f"{OWNER_HANDLE} and invite them to your server/guild. "
                "Servers that skip registration will be **removed from the "
                "guild in the next update**."
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    # ── reload ────────────────────────────────────────────────────────────────
    @commands.command(name="reload", hidden=True)
    @commands.is_owner()
    async def reload(self, ctx: commands.Context, cog: str) -> None:
        """[Owner] Reload a cog. Usage: sudo reload <cog>"""
        ext = f"cogs.{cog}"
        try:
            await self.bot.reload_extension(ext)
            await ctx.send(f"```bash\n$ sudo reload {cog}\nModule '{ext}' reloaded successfully.\n```")
        except Exception as exc:
            await ctx.send(f"```bash\nsudo: reload: {exc}\n```")

    # ── loadcog ───────────────────────────────────────────────────────────────
    @commands.command(name="loadcog", hidden=True)
    @commands.is_owner()
    async def loadcog(self, ctx: commands.Context, cog: str) -> None:
        """[Owner] Load a cog. Usage: sudo loadcog <cog>"""
        ext = f"cogs.{cog}"
        try:
            await self.bot.load_extension(ext)
            await ctx.send(f"```bash\n$ sudo loadcog {cog}\nModule '{ext}' loaded.\n```")
        except Exception as exc:
            await ctx.send(f"```bash\nsudo: loadcog: {exc}\n```")

    # ── unloadcog ─────────────────────────────────────────────────────────────
    @commands.command(name="unloadcog", hidden=True)
    @commands.is_owner()
    async def unloadcog(self, ctx: commands.Context, cog: str) -> None:
        """[Owner] Unload a cog. Usage: sudo unloadcog <cog>"""
        if cog == "system":
            await ctx.send("```bash\nsudo: unloadcog: cannot unload system cog\n```")
            return
        ext = f"cogs.{cog}"
        try:
            await self.bot.unload_extension(ext)
            await ctx.send(f"```bash\n$ sudo unloadcog {cog}\nModule '{ext}' unloaded.\n```")
        except Exception as exc:
            await ctx.send(f"```bash\nsudo: unloadcog: {exc}\n```")

    # ── shutdown ──────────────────────────────────────────────────────────────
    @commands.command(name="shutdown", aliases=["halt", "poweroff"], hidden=True)
    async def shutdown(self, ctx: commands.Context) -> None:
        """Gracefully shut down the bot. Usage: sudo shutdown"""
        if ctx.author.id != 1224391248580972584:
            await ctx.send("```bash\nsudo: shutdown: Access denied\n```")
            return
        await ctx.send(
            "```bash\n$ sudo shutdown now\n"
            "Broadcast message: The system is going down NOW!\n```"
        )
        await self.bot.close()

    # ── Slash Commands ────────────────────────────────────────────────────────
    @app_commands.command(name="ping", description="Check bot latency")
    @app_commands.describe()
    async def slash_ping(self, interaction: discord.Interaction) -> None:
        """Slash command version of ping."""
        import time as _t
        before = _t.monotonic()
        await interaction.response.send_message("```bash\n$ sudo ping discord.com\nPinging…\n```")
        rtt = round((_t.monotonic() - before) * 1000)
        ws = round(self.bot.latency * 1000)
        await interaction.edit_original_response(content=(
            f"```bash\n$ sudo ping discord.com\n"
            f"PING discord.com: 64 bytes\n"
            f"icmp_seq=1  ws={ws} ms  rtt={rtt} ms\n```"
        ))

    @app_commands.command(name="uptime", description="Show how long the bot has been running")
    async def slash_uptime(self, interaction: discord.Interaction) -> None:
        """Slash command version of uptime."""
        elapsed = int(time.time() - START_TIME)
        days, rem = divmod(elapsed, 86400)
        hours, rem = divmod(rem, 3600)
        mins, secs = divmod(rem, 60)
        uptime_str = f"{days}d {hours:02d}:{mins:02d}:{secs:02d}"
        await interaction.response.send_message(
            f"```bash\n$ uptime\n"
            f" up {uptime_str},  1 user,  load average: 0.01, 0.01, 0.00\n```"
        )

    @app_commands.command(name="status", description="Display bot system status")
    async def slash_status(self, interaction: discord.Interaction) -> None:
        """Slash command version of status."""
        guilds = len(self.bot.guilds)
        users = sum(g.member_count or 0 for g in self.bot.guilds)
        latency = round(self.bot.latency * 1000)
        elapsed = int(time.time() - START_TIME)
        days, rem = divmod(elapsed, 86400)
        hours, rem = divmod(rem, 3600)
        mins, secs = divmod(rem, 60)
        cogs_loaded = len(self.bot.cogs)
        cmds_total = len(self.bot.commands)

        embed = discord.Embed(title="⚙️  System Status — SuperUser Do", color=0x1ABC9C)
        embed.add_field(name="🏓 Latency", value=f"{latency} ms", inline=True)
        embed.add_field(name="🖥️  Guilds", value=str(guilds), inline=True)
        embed.add_field(name="👥 Users", value=str(users), inline=True)
        embed.add_field(name="⏱️  Uptime", value=f"{days}d {hours:02d}:{mins:02d}:{secs:02d}", inline=True)
        embed.add_field(name="🔌 Cogs", value=str(cogs_loaded), inline=True)
        embed.add_field(name="⌨️  Commands", value=str(cmds_total), inline=True)
        embed.add_field(name="🐍 Python", value=platform.python_version(), inline=True)
        embed.add_field(name="📦 discord.py", value=discord.__version__, inline=True)
        embed.add_field(name="🖥️  OS", value=platform.system(), inline=True)
        embed.set_footer(text=f"Bot: {self.bot.user}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="invite", description="Generate bot invite link")
    async def slash_invite(self, interaction: discord.Interaction) -> None:
        """Slash command version of invite."""
        embed = discord.Embed(
            title="🐧 Add SuperUser Do to your server",
            description=(
                f"🔗 [Click to invite SuperUser Do]({INVITE_URL})\n"
                "```bash\n$ sudo invite\nInvite URL generated.\n```"
            ),
            color=0x2ECC71,
        )
        embed.add_field(
            name="⚠️ Registration required",
            value=(
                "You **must** register the bot in the DMs of "
                f"{OWNER_HANDLE} and invite them to your server/guild. "
                "Servers that skip registration will be **removed from the "
                "guild in the next update**."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(System(bot))
