"""
cogs/musicgames.py — Voice channel game: Guess the Song.

The bot joins your VC, plays the first few seconds of a random track, and
players race to name the song in the text channel. The first correct answer
wins and earns XP.

Commands: guessthesong (guesssong, songquiz, gts)
"""

import asyncio
import difflib
import random
import re
import time
import unicodedata

import discord
from discord.ext import commands

from cogs.music import build_filter_string, get_ffmpeg_opts
from cogs.xp import award_game_xp, is_xp_enabled

PREVIEW_SECONDS = 8
GUESS_WINDOW = 30
WINNER_XP = 40
WINNER_SP = 15

SEARCH_POOL = [
    "top hits 2024", "pop songs of all time", "rock classics",
    "hip hop hits 2000s", "indie hits", "electronic dance hits",
    "soul and funk classics", "iconic 80s songs", "90s alt rock",
    "chart toppers 2010s", "viral tiktok songs", "best kpop songs",
    "latin pop hits", "country hits", "jazz standards",
]


class MusicGames(commands.Cog, name="musicgames"):
    """Voice channel games. Commands: guessthesong"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._active: dict[int, dict] = {}

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title, icon_url=None)
        if description:
            embed.description = description
        return embed

    def _music(self):
        return self.bot.get_cog("music")

    @staticmethod
    def _normalize(text: str) -> str:
        text = unicodedata.normalize("NFKD", text)
        text = text.encode("ascii", "ignore").decode("ascii")
        text = text.lower()
        text = re.sub(r"\([^)]*\)", "", text)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return text.strip()

    @staticmethod
    def _is_match(guess: str, title: str) -> bool:
        guess = MusicGames._normalize(guess)
        title = MusicGames._normalize(title)
        if not guess or not title:
            return False
        if len(guess) < 3:
            return False
        if guess == title:
            return True
        if guess in title or title in guess:
            return True
        guess_tokens = [t for t in guess.split() if len(t) >= 3]
        if not guess_tokens:
            return False
        return all(t in title for t in guess_tokens)

    @staticmethod
    def _similarity(guess: str, title: str) -> float:
        return difflib.SequenceMatcher(
            None,
            MusicGames._normalize(guess),
            MusicGames._normalize(title),
        ).ratio()

    @staticmethod
    def _is_command_like(content: str) -> bool:
        if content.startswith(("sudo ", "$ ")):
            return True
        if re.match(r"^<@!?&?\d+>\s", content):
            return True
        return False

    @commands.command(name="guessthesong", aliases=["guesssong", "songquiz", "gts"])
    @commands.cooldown(1, 60, commands.BucketType.channel)
    async def guess_the_song(self, ctx: commands.Context, *, hint: str = "") -> None:
        """Play Guess the Song in your VC. First correct answer wins XP. Usage: sudo guessthesong [hint]"""
        guild_id = ctx.guild.id
        if guild_id in self._active:
            embed = self._make_embed(
                "❌ Game Running", 0xE74C3C,
                "A song-guessing game is already running in this server.",
            )
            await ctx.send(embed=embed)
            return

        if not ctx.author.voice or not ctx.author.voice.channel:
            embed = self._make_embed(
                "❌ Not in VC", 0xE74C3C, "You must be in a voice channel to play."
            )
            await ctx.send(embed=embed)
            return

        vc_channel = ctx.author.voice.channel
        players = [m for m in vc_channel.members if not m.bot]
        if len(players) < 2:
            embed = self._make_embed(
                "❌ Not Enough Players", 0xE74C3C,
                "Guess the Song needs at least **2** players in the voice channel.",
            )
            await ctx.send(embed=embed)
            return

        music = self._music()
        if music is None:
            embed = self._make_embed(
                "❌ Music Unavailable", 0xE74C3C, "The music module is not loaded."
            )
            await ctx.send(embed=embed)
            return

        if not ctx.voice_client:
            try:
                await vc_channel.connect()
            except Exception as e:
                embed = self._make_embed(
                    "❌ Connection Failed", 0xE74C3C, f"Could not join voice channel: {e}"
                )
                await ctx.send(embed=embed)
                return

        music_player = music._get_player(guild_id)
        vc = ctx.voice_client
        saved_current = music_player.current
        saved_paused = bool(vc and vc.is_paused())
        was_playing = bool(vc and (vc.is_playing() or saved_paused))

        music_player.game_active = True
        self._active[guild_id] = {"vc_channel": vc_channel, "text_channel": ctx.channel}

        try:
            if was_playing and vc:
                vc.stop()

            query = hint.strip() or random.choice(SEARCH_POOL)

            embed = self._make_embed(
                "🎵 Guess the Song", 0x1DB954,
                f"Searching a track from **{query}** ...\nI'll play the first "
                f"**{PREVIEW_SECONDS} seconds**. First to name the song in chat "
                f"wins **{WINNER_XP} XP**!",
            )
            await ctx.send(embed=embed)

            music._last_fetch_error = None
            track = await music._fetch_track(query, ctx.author)
            if track is None:
                embed = self._make_embed(
                    "❌ Fetch Failed", 0xE74C3C,
                    getattr(music, "_last_fetch_error", None)
                    or f"Could not find a track for **'{query}'**.",
                )
                await ctx.send(embed=embed)
                return

            title = getattr(track, "title", "Unknown")

            start_embed = self._make_embed(
                "🔊 Playing Preview", 0x1DB954,
                f"**[{title}]({track.url})** — first {PREVIEW_SECONDS}s.\n"
                "Type the song name in this chat to guess!",
            )
            try:
                preview = discord.FFmpegPCMAudio(
                    track.stream_url,
                    before_options=(
                        "-reconnect 1 -reconnect_streamed 1 "
                        "-reconnect_delay_max 5 -thread_queue_size 8192"
                    ),
                    options=f"-vn -t {PREVIEW_SECONDS} -bufsize 384k -maxrate 256k",
                )
                vc.play(preview, after=lambda e: None)
            except Exception as e:
                embed = self._make_embed(
                    "❌ Playback Failed", 0xE74C3C, f"Could not play the preview: {e}"
                )
                await ctx.send(embed=embed)
                return

            start_msg = await ctx.send(embed=start_embed)

            deadline = time.monotonic() + PREVIEW_SECONDS + GUESS_WINDOW
            preview_ends_at = time.monotonic() + PREVIEW_SECONDS
            announced_end = False
            winner = None
            close_warned: set[int] = set()

            while (
                time.monotonic() < deadline
                and winner is None
                and ctx.guild.voice_client is not None
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break

                def check(
                    m: discord.Message,
                    text_id=ctx.channel.id,
                    vc_id=vc_channel.id,
                ) -> bool:
                    if m.author.bot:
                        return False
                    if m.channel.id != text_id:
                        return False
                    if m.author.voice is None or m.author.voice.channel.id != vc_id:
                        return False
                    if MusicGames._is_command_like(m.content):
                        return False
                    return bool(MusicGames._normalize(m.content))

                try:
                    msg = await self.bot.wait_for("message", timeout=remaining, check=check)
                except asyncio.TimeoutError:
                    break
                except Exception:
                    break

                if not announced_end and time.monotonic() >= preview_ends_at:
                    announced_end = True
                    try:
                        await ctx.send(
                            embed=self._make_embed(
                                "🎧 Preview Over", 0xF39C12,
                                "Type the song name now to submit your guess!",
                            )
                        )
                    except Exception:
                        pass

                if self._is_match(msg.content, title):
                    winner = msg.author
                    break

                if (
                    time.monotonic() < preview_ends_at
                    and msg.author.id not in close_warned
                    and self._similarity(msg.content, title) >= 0.8
                ):
                    close_warned.add(msg.author.id)
                    try:
                        await ctx.send(embed=self._make_embed(
                            "🙊 So Close!", 0xF39C12,
                            f"{msg.author.mention} that was really close!",
                        ))
                    except Exception:
                        pass

            if vc and vc.is_playing():
                try:
                    vc.stop()
                except Exception:
                    pass

            try:
                await start_msg.delete()
            except Exception:
                pass

            if winner is not None:
                level = None
                rewarded = False
                if is_xp_enabled(guild_id):
                    level = award_game_xp(winner.id, WINNER_XP, WINNER_SP)
                    rewarded = True

                final = self._make_embed("🏆 Correct!", 0x2ECC71)
                final.description = (
                    f"**{winner.mention}** guessed it first!\n"
                    f"🎵 The song was **[{title}]({track.url})** — {track.fmt_duration()}."
                )
                if rewarded:
                    final.add_field(
                        name="Earned",
                        value=f"**{WINNER_XP} XP** + **{WINNER_SP} SP**",
                        inline=True,
                    )
                    if level is not None:
                        final.add_field(name="Level", value=f"**{level}**", inline=True)
                await ctx.send(embed=final)
            else:
                final = self._make_embed(
                    "⏰ Time's Up!", 0x95A5A6,
                    f"No one guessed it! The song was **[{title}]({track.url})** — "
                    f"{track.fmt_duration()}.",
                )
                await ctx.send(embed=final)

        finally:
            self._active.pop(guild_id, None)

            player = music._get_player(guild_id)
            player.game_active = False

            try:
                vc = ctx.guild.voice_client
                if saved_current and was_playing and vc:
                    if vc.is_playing():
                        vc.stop()
                    await asyncio.sleep(0.3)
                    filter_str = build_filter_string(player)
                    source = discord.PCMVolumeTransformer(
                        discord.FFmpegPCMAudio(
                            saved_current.stream_url, **get_ffmpeg_opts(filter_str)
                        ),
                        volume=player.volume,
                    )

                    def resume_after(error: Exception | None) -> None:
                        if error:
                            print(f"Resume playback error: {error}")
                        try:
                            asyncio.run_coroutine_threadsafe(
                                music._play_next(guild_id), self.bot.loop
                            )
                        except Exception:
                            pass

                    player.current = saved_current
                    player._start_time = (
                        asyncio.get_event_loop().time()
                        if asyncio.get_event_loop().is_running() else 0
                    )
                    vc.play(source, after=resume_after)
                    await music._update_presence(saved_current, ctx.guild)
                    await music._maybe_start_spectrum(guild_id, ctx.guild)
                    await ctx.send(embed=self._make_embed(
                        "▶️ Resumed", 0x3498DB,
                        "Resumed your music queue after the game.",
                    ))
                elif not saved_current and vc:
                    try:
                        await music._update_presence(None, ctx.guild)
                    except Exception:
                        pass
            except Exception:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicGames(bot))