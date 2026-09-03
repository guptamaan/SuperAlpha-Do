"""
cogs/spectrum.py — Audio spectrum visualization for music playback.
"""

import asyncio
import random
import threading
import time
from collections import deque

import discord
from discord.ext import commands


class SpectrumVisualizer:
    BARS = 7
    CHARS = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]

    def __init__(self) -> None:
        self.is_active: bool = False
        self.guild_id: int = 0
        self.bot = None
        self.task = None
        self._stop_event = threading.Event()
        self._audio_levels = deque([0.1] * 10, maxlen=10)

    def update_level(self, level: float) -> None:
        self._audio_levels.append(level)

    def get_spectrum(self) -> str:
        if not self._audio_levels:
            return "▁" * self.BARS
        
        avg_level = sum(self._audio_levels) / len(self._audio_levels)
        bars = []
        for i in range(self.BARS):
            offset = (i - self.BARS // 2) / (self.BARS // 2)
            variance = random.uniform(0.7, 1.3)
            bar_level = max(0, min(1, avg_level + offset * 0.3)) * variance
            bar_height = int(bar_level * (len(self.CHARS) - 1))
            bars.append(self.CHARS[bar_height])
        return "".join(bars)

    async def start(self, bot: commands.Bot, guild_id: int) -> None:
        self.is_active = True
        self.guild_id = guild_id
        self.bot = bot
        self._stop_event.clear()
        self.task = asyncio.create_task(self._update_loop())

    async def stop(self) -> None:
        self.is_active = False
        self._stop_event.set()
        if self.task:
            try:
                self.task.cancel()
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
        await self._clear_status()

    async def _clear_status(self) -> None:
        guild = self.bot.get_guild(self.guild_id)
        if guild and guild.voice_client:
            try:
                await guild.voice_client.channel.edit(status=None)
            except Exception:
                pass

    async def _update_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                guild = self.bot.get_guild(self.guild_id)
                if guild and guild.voice_client and guild.voice_client.is_playing():
                    spectrum = self.get_spectrum()
                    try:
                        await guild.voice_client.channel.edit(status=f"🎵 {spectrum}")
                    except Exception:
                        pass
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            except Exception:
                pass


class Spectrum(commands.Cog, name="spectrum"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._visualizers: dict[int, SpectrumVisualizer] = {}
        self._spectrum_enabled: dict[int, bool] = {}

    def _get_visualizer(self, guild_id: int) -> SpectrumVisualizer:
        if guild_id not in self._visualizers:
            self._visualizers[guild_id] = SpectrumVisualizer()
        return self._visualizers[guild_id]

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
            viz = self._get_visualizer(after.channel.guild.id)
            if viz.is_active and after.channel.guild.voice_client:
                if after.channel.guild.voice_client.is_playing():
                    await viz.start(self.bot, after.channel.guild.id)

        if before.channel and not after.channel:
            if not before.channel.members or all(m.bot for m in before.channel.members):
                viz = self._get_visualizer(before.channel.guild.id)
                if viz.is_active:
                    await viz.stop()

    @commands.command(name="spectrum", aliases=["spec", "vis", "visualizer"])
    async def spectrum(self, ctx: commands.Context, action: str = None) -> None:
        """Toggle audio spectrum visualization. Usage: sudo spectrum [on|off]"""
        if not ctx.voice_client:
            embed = self._make_embed("❌ Not in VC", 0xE74C3C, "Bot is not in a voice channel")
            await ctx.send(embed=embed)
            return

        guild_id = ctx.guild.id
        viz = self._get_visualizer(guild_id)

        if not action:
            status = "**enabled**" if self._spectrum_enabled.get(guild_id, False) else "**disabled**"
            embed = discord.Embed(color=0x9B59B6)
            embed.set_author(name="🎨 Spectrum Visualizer")
            embed.description = f"Spectrum is currently {status}"
            embed.add_field(name="Bars", value="".join(SpectrumVisualizer.CHARS), inline=False)
            embed.add_field(name="Commands", value="`sudo spectrum on` - Enable\n`sudo spectrum off` - Disable", inline=False)
            await ctx.send(embed=embed)
            return

        action = action.lower()

        if action in ["on", "enable", "true", "1", "yes", "start"]:
            if not ctx.voice_client.is_playing():
                embed = self._make_embed("❌ Not Playing", 0xE74C3C, "Start playing music first")
                await ctx.send(embed=embed)
                return

            self._spectrum_enabled[guild_id] = True
            await viz.start(self.bot, guild_id)
            
            embed = discord.Embed(color=0x2ECC71)
            embed.set_author(name="🎨 Spectrum Enabled")
            embed.description = "Visual spectrum is now showing in the voice channel status"
            embed.add_field(name="Preview", value=f"Example: 🎵 {viz.get_spectrum()}", inline=False)
            await ctx.send(embed=embed)

        elif action in ["off", "disable", "false", "0", "no", "stop"]:
            self._spectrum_enabled[guild_id] = False
            await viz.stop()

            embed = discord.Embed(color=0xE74C3C)
            embed.set_author(name="🎨 Spectrum Disabled")
            embed.description = "Visual spectrum has been hidden"
            await ctx.send(embed=embed)

        else:
            embed = self._make_embed("❌ Invalid", 0xE74C3C, "Usage: `sudo spectrum [on|off]`")
            await ctx.send(embed=embed)

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title)
        if description:
            embed.description = description
        return embed

    async def cog_unload(self) -> None:
        for viz in self._visualizers.values():
            if viz.is_active:
                await viz.stop()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Spectrum(bot))
