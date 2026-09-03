"""
cogs/music.py — Music commands (yt-dlp + FFmpeg, no lavalink needed).
Commands: join, leave, play, pause, resume, stop, skip, queue, revive,
          nowplaying, volume, shuffle, loop, remove, clear, radio

Requirements (all pip-installable except FFmpeg):
    pip install discord.py yt-dlp PyNaCl

FFmpeg must be installed on the system:
    - On Wispbyte: Add to startup command or install via apt
    - e.g., apt install ffmpeg OR use a container with FFmpeg
"""

import asyncio
import functools
import math
import os
import random
from collections import deque

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from cogs.checks import perms_or_developer

EMOJI_MUSIC_PLAY = "<a:musicplay:1485243787084042270>"
EMOJI_MUSIC_PAUSE = "<a:musicpause:1485244346386350111>"
EMOJI_MUSIC_NEXT = "<a:musicnext:1485244699605471312>"
EMOJI_MUSIC_STOP = "⏹️"
EMOJI_MUSIC_SHUFFLE = "<a:musicshuffle:1485245854548885626>"
EMOJI_MUSIC_LOOP = "<a:musicloop:1485246094505017515>"
EMOJI_MUSIC_VOL = "<a:musicvol:1485246400940867695>"
EMOJI_MUSIC_QUEUE = "<a:musicqueue:1485246769318072431>"

BASE_YTDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "noplaylist": True,
    "extract_flat": False,
    "socket_timeout": 20,
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    },
    "js_runtimes": {"node": {"cmd": ["node"]}},
}


def get_ytdl_opts() -> dict:
    opts = BASE_YTDL_OPTS.copy()
    cookies_file = "cookies.txt"
    if os.path.exists(cookies_file):
        if os.path.getsize(cookies_file) > 0:
            opts["cookiefile"] = cookies_file
        else:
            print("Warning: cookies.txt exists but is empty")
    return opts


def get_ffmpeg_opts(filter_str: str = "") -> dict:
    before = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -thread_queue_size 8192"
    options = "-vn -bufsize 384k -maxrate 256k"
    if filter_str:
        options += f' -af "{filter_str}"'
    return {
        "before_options": before,
        "options": options,
    }


class Track:
    __slots__ = ("title", "url", "stream_url", "duration", "requester")

    def __init__(self, data: dict, requester: discord.Member) -> None:
        self.title: str = data.get("title", "Unknown")
        self.url: str = data.get("webpage_url", data.get("url", ""))
        self.stream_url: str = data.get("url", "")
        self.duration: int = data.get("duration", 0)
        self.requester: discord.Member = requester

    def fmt_duration(self) -> str:
        m, s = divmod(self.duration, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class GuildPlayer:
    def __init__(self, guild_id: int) -> None:
        self.guild_id: int = guild_id
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.last_track: Track | None = None
        self.volume: float = 1.0
        self.loop: bool = False
        self.autoplay: bool = False
        self.bassboost: bool = False
        self.nightcore: bool = False
        self.eight_d: bool = False
        self.slowed: bool = False
        self.equalizer: str = "flat"
        self.skip_event: asyncio.Event = asyncio.Event()
        self.original_nick: str | None = None
        self.text_channel: discord.TextChannel | None = None
        self.skip_votes: set[int] = set()
        self.vote_msg_id: int | None = None
        self._start_time: float = 0
        self._paused_time: float = 0
        self.game_active: bool = False


def build_filter_string(player: GuildPlayer) -> str:
    filters = []
    if player.bassboost:
        filters.append("bass=g=15")
    if player.nightcore:
        filters.append("asetrate=48000*1.25,aresample=48000")
    if player.eight_d:
        filters.append("aecho=0.8:0.9:50:0.5,aecho=0.8:0.9:70:0.4,apulsator=hz=0.3,stereowiden=1.5")
    if player.slowed:
        filters.append("asetrate=44100*0.75,aresample=44100,aecho=0.8:0.88:60:0.4")
    eq = player.equalizer.lower()
    if eq != "flat" and eq:
        eq_presets = {
            "bass": "equalizer=f=100:width_type=o:width=2:g=15",
            "treble": "equalizer=f=3000:width_type=o:width=2:g=10",
            "pop": "equalizer=f=500:width_type=o:width=2:g=6,equalizer=f=3000:width_type=o:width=2:g=6",
            "rock": "equalizer=f=100:width_type=o:width=2:g=8,equalizer=f=5000:width_type=o:width=2:g=8",
            "jazz": "equalizer=f=200:width_type=o:width=2:g=5,equalizer=f=4000:width_type=o:width=2:g=5",
            "classical": "equalizer=f=300:width_type=o:width=2:g=5,equalizer=f=2000:width_type=o:width=2:g=5",
            "electronic": "equalizer=f=100:width_type=o:width=2:g=12,equalizer=f=5000:width_type=o:width=2:g=8",
        }
        if eq in eq_presets:
            filters.append(eq_presets[eq])
    return ",".join(filters) if filters else ""


class Music(commands.Cog, name="music"):
    """Music playback commands (YouTube via yt-dlp)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._players: dict[int, GuildPlayer] = {}
        self._last_fetch_error: str | None = None

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Auto-leave when everyone leaves the voice channel."""
        if member.bot:
            return
        try:
            if before.channel and before.channel.guild:
                guild = before.channel.guild
                voice_client = guild.voice_client
                player = self._get_player(guild.id)
                player.skip_votes.discard(member.id)
                if voice_client and voice_client.channel == before.channel:
                    if (
                        len(voice_client.channel.members) == 1
                        and voice_client.channel.members[0].bot
                    ):
                        player.last_track = player.current
                        player.queue.clear()
                        player.current = None
                        player.skip_votes.clear()
                        self._reset_player_settings(player)
                        try:
                            await self._update_presence(None, guild)
                            await voice_client.disconnect()
                        except Exception:
                            pass
        except Exception:
            pass

    async def _update_presence(self, track: Track | None, guild: discord.Guild) -> None:
        """Update the voice channel status to show the current track."""
        try:
            voice_client = guild.voice_client
            if voice_client:
                if track:
                    await voice_client.channel.edit(
                        status=f"<a:dance:1484553189964644352> Listening: {track.title[:100]}"
                    )
                else:
                    await voice_client.channel.edit(status=None)
        except Exception:
            pass

    def _build_now_playing_embed(
        self, track: Track, player: GuildPlayer
    ) -> discord.Embed:
        """Build the now playing embed for a track."""
        embed = discord.Embed(color=0x1DB954)
        embed.set_author(name="Now Playing", icon_url=None)
        embed.description = (
            f"[{track.title}]({track.url})" if track.url else track.title
        )
        embed.add_field(name="Duration", value=track.fmt_duration(), inline=True)
        embed.add_field(name="Requested by", value=track.requester.mention, inline=True)
        embed.add_field(
            name=f"{EMOJI_MUSIC_LOOP} Loop",
            value="ON" if player.loop else "OFF",
            inline=True,
        )
        embed.add_field(
            name=f"{EMOJI_MUSIC_VOL} Volume",
            value=f"{int(player.volume * 100)}%",
            inline=True,
        )
        return embed

    def _make_embed(
        self, title: str, color: int, description: str = ""
    ) -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(
            name=title,
            icon_url=None,
        )
        if description:
            embed.description = description
        return embed

    def _get_player(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self._players:
            self._players[guild_id] = GuildPlayer(guild_id)
        return self._players[guild_id]

    def _is_spotify_url(self, url: str) -> bool:
        return "spotify.com" in url.lower()

    def _is_apple_url(self, url: str) -> bool:
        url_lower = url.lower()
        return "music.apple.com" in url_lower or "itunes.apple.com" in url_lower

    def _is_soundcloud_url(self, url: str) -> bool:
        return "soundcloud.com" in url.lower()

    def _is_playable_url(self, url: str) -> bool:
        supported = [
            "youtube.com", "youtu.be", "youtube.com/watch",
            "soundcloud.com", "spotify.com", "music.apple.com",
            "itunes.apple.com", "bandcamp.com", "twitch.tv",
        ]
        return any(s in url.lower() for s in supported)

    def _get_youtube_search_query(self, query: str) -> str:
        return f"ytsearch1:{query}"

    def _classify_ytdl_error(self, error: Exception) -> str:
        """Turn a yt-dlp exception into a human-friendly message."""
        msg = str(error)
        low = msg.lower()
        if any(k in low for k in (
            "cookies", "cookie not found", "sign in to confirm", "logged out",
            "logged_out", "must provide login", "use cookies",
        )):
            return (
                "**YouTube cookie expired or bot-check triggered.**\n"
                "Refresh `cookies.txt`, restart the bot, or update yt-dlp "
                "with `pip install -U yt-dlp`."
            )
        if any(k in low for k in (
            "video unavailable", "unavailable", "has been removed",
            "private video", "age-restricted", "age restriction",
        )):
            return "That video is unavailable (removed, private, age-restricted, or region-locked)."
        if any(k in low for k in ("429", "too many requests", "request has been blocked", "rate limit", "repeated request")):
            return "YouTube is rate-limiting the bot. Wait a minute and try again."
        if "not a valid url" in low or "unsupported url" in low:
            return (
                "That doesn't look like a link I can play. Try a YouTube, "
                "SoundCloud, Bandcamp, Spotify, or Apple Music link, or a search term."
            )
        return f"Could not fetch that track: `{msg[:200]}`"

    async def _fetch_track(self, query: str, requester: discord.Member) -> Track | None:
        loop = asyncio.get_event_loop()
        ydl_opts = get_ytdl_opts()

        search_query = query
        is_external_url = query.startswith("http")

        if is_external_url:
            if self._is_spotify_url(query):
                try:
                    info = await self._get_spotify_track_info(query)
                    if info:
                        search_query = f"{info['title']} {info['artist']}"
                        print(f"Spotify detected, searching YouTube for: {search_query}")
                except Exception as e:
                    print(f"Spotify info error: {e}")

            elif self._is_apple_url(query):
                try:
                    info = await self._get_apple_track_info(query)
                    if info:
                        search_query = f"{info['title']} {info['artist']}"
                        print(f"Apple Music detected, searching YouTube for: {search_query}")
                except Exception as e:
                    print(f"Apple Music info error: {e}")

            elif self._is_soundcloud_url(query):
                print(f"SoundCloud URL detected: {query}")

        try:
            ytdl_instance = yt_dlp.YoutubeDL(ydl_opts)

            if search_query.startswith("http"):
                full_query = search_query
            else:
                full_query = self._get_youtube_search_query(search_query)

            self._last_fetch_error = None
            data = await loop.run_in_executor(
                None,
                functools.partial(ytdl_instance.extract_info, full_query, download=False),
            )
        except Exception as e:
            print(f"yt-dlp error: {e}")
            self._last_fetch_error = self._classify_ytdl_error(e)
            return None

        if data is None:
            return None

        if "entries" in data:
            if not data["entries"]:
                return None
            data = data["entries"][0]

        return Track(data, requester)

    async def _get_spotify_track_info(self, url: str) -> dict | None:
        loop = asyncio.get_event_loop()
        try:
            ydl_opts = {
                "quiet": True,
                "skip_download": True,
                "extract_flat": False,
            }
            ytdl = yt_dlp.YoutubeDL(ydl_opts)
            info = await loop.run_in_executor(
                None,
                functools.partial(ytdl.extract_info, url, download=False),
            )
            if info:
                title = info.get("title", "")
                artist = info.get("artist", "") or info.get("uploader", "")
                if title and artist:
                    return {"title": title, "artist": artist}
        except Exception:
            pass
        return None

    async def _get_apple_track_info(self, url: str) -> dict | None:
        loop = asyncio.get_event_loop()
        try:
            ydl_opts = {
                "quiet": True,
                "skip_download": True,
                "extract_flat": False,
            }
            ytdl = yt_dlp.YoutubeDL(ydl_opts)
            info = await loop.run_in_executor(
                None,
                functools.partial(ytdl.extract_info, url, download=False),
            )
            if info:
                title = info.get("title", "")
                artist = info.get("artist", "") or info.get("uploader", "")
                if title:
                    return {"title": title, "artist": artist}
        except Exception:
            pass
        return None

    async def _play_next(self, guild_id: int) -> None:
        """Called when a track finishes; schedules the next one."""
        player = self._get_player(guild_id)
        if player.game_active:
            return
        player.skip_votes.clear()
        if player.loop and player.current:
            player.queue.appendleft(player.current)
        if player.queue:
            player.current = player.queue.popleft()
            filter_str = build_filter_string(player)
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(player.current.stream_url, **get_ffmpeg_opts(filter_str)),
                volume=player.volume,
            )
            guild = self.bot.get_guild(guild_id)
            voice_client = guild and guild.voice_client
            if not voice_client:
                return

            def after_callback(error: Exception | None) -> None:
                if error:
                    print(f"Playback error: {error}")
                try:
                    asyncio.run_coroutine_threadsafe(
                        self._play_next(guild_id), self.bot.loop
                    )
                except Exception:
                    pass

            try:
                player._start_time = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0
                voice_client.play(source, after=after_callback)
                await self._update_presence(player.current, guild)
                await self._maybe_start_spectrum(guild_id, guild)
                if player.text_channel:
                    await player.text_channel.send(
                        embed=self._build_now_playing_embed(player.current, player)
                    )
            except Exception as e:
                print(f"Voice connection error: {e}")
                player.queue.clear()
                player.current = None
                if player.text_channel:
                    embed = self._make_embed(
                        "❌ Voice Error", 0xE74C3C, "Voice connection failed. Please rejoin."
                    )
                    try:
                        await player.text_channel.send(embed=embed)
                    except Exception:
                        pass
        else:
            if player.autoplay and player.last_track:
                loop = asyncio.get_event_loop()
                try:
                    related_query = f"ytsearch1:{player.last_track.title} similar"
                    ydl_opts = get_ytdl_opts()
                    ytdl_instance = yt_dlp.YoutubeDL(ydl_opts)
                    data = await loop.run_in_executor(
                        None,
                        functools.partial(ytdl_instance.extract_info, related_query, download=False),
                    )
                    if data and "entries" in data and data["entries"]:
                        entry = data["entries"][0]
                        if entry:
                            track = Track(entry, player.last_track.requester)
                            player.queue.append(track)
                            await self._play_next(guild_id)
                            return
                except Exception:
                    pass
            player.current = None
            player.skip_votes.clear()
            guild = self.bot.get_guild(guild_id)
            if guild and guild.voice_client:
                await self._update_presence(None, guild)
            if player.text_channel:
                embed = self._make_embed(
                    "🎵 Queue Finished", 0x95A5A6, "No more tracks in queue."
                )
                await player.text_channel.send(embed=embed)

    # ── join ──────────────────────────────────────────────────────────────────
    @commands.command(name="join", aliases=["connect", "j", "cd"])
    async def join(self, ctx: commands.Context) -> None:
        """Join your voice channel to play music. Usage: sudo join"""
        if not ctx.author.voice:
            embed = self._make_embed(
                "❌ Not Connected", 0xE74C3C, "You are not in a voice channel"
            )
            await ctx.send(embed=embed)
            return
        channel = ctx.author.voice.channel
        try:
            if ctx.voice_client:
                try:
                    await ctx.voice_client.disconnect()
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
            await channel.connect()
            embed = self._make_embed(
                "Connected", 0x3498DB, f"Joined voice channel: **{channel.name}**"
            )
            await ctx.send(embed=embed)
        except Exception as e:
            embed = self._make_embed(
                "❌ Connection Failed", 0xE74C3C, f"Could not join voice channel: {e}"
            )
            await ctx.send(embed=embed)

    # ── leave ─────────────────────────────────────────────────────────────────
    @commands.command(name="leave", aliases=["disconnect", "dc", "exit"])
    async def leave(self, ctx: commands.Context) -> None:
        """Leave the voice channel and stop playback. Usage: sudo leave"""
        if not ctx.voice_client:
            embed = self._make_embed(
                "❌ Not Connected", 0xE74C3C, "Bot is not in a voice channel"
            )
            await ctx.send(embed=embed)
            return
        player = self._get_player(ctx.guild.id)
        player.last_track = player.current
        player.queue.clear()
        player.current = None
        self._reset_player_settings(player)
        vc = ctx.voice_client
        await self._update_presence(None, ctx.guild)
        await self._maybe_stop_spectrum(ctx.guild.id)
        await vc.disconnect()
        embed = self._make_embed("Disconnected", 0x3498DB, "Left the voice channel.")
        await ctx.send(embed=embed)

    async def _maybe_start_spectrum(self, guild_id: int, guild: discord.Guild) -> None:
        """Start spectrum visualizer if the cog is loaded and enabled."""
        try:
            spectrum_cog = self.bot.get_cog("spectrum")
            if spectrum_cog and spectrum_cog._spectrum_enabled.get(guild_id, False):
                viz = spectrum_cog._get_visualizer(guild_id)
                if not viz.is_active:
                    await viz.start(self.bot, guild_id)
        except Exception:
            pass

    async def _maybe_stop_spectrum(self, guild_id: int) -> None:
        """Stop spectrum visualizer."""
        try:
            spectrum_cog = self.bot.get_cog("spectrum")
            if spectrum_cog:
                viz = spectrum_cog._get_visualizer(guild_id)
                if viz.is_active:
                    await viz.stop()
        except Exception:
            pass

    def _reset_player_settings(self, player: GuildPlayer) -> None:
        """Reset all player settings to default."""
        player.volume = 1.0
        player.loop = False
        player.autoplay = False
        player.bassboost = False
        player.nightcore = False
        player.eight_d = False
        player.slowed = False
        player.equalizer = "flat"

    # ── revive ────────────────────────────────────────────────────────────────
    @commands.command(name="revive", aliases=["resumequeue", "rq"])
    async def revive(self, ctx: commands.Context) -> None:
        """Revive the last track after bot disconnect. Usage: sudo revive"""
        player = self._get_player(ctx.guild.id)

        if player.current or player.queue:
            embed = self._make_embed(
                "❌ Queue Active", 0xE74C3C, "A queue is already active. Use `sudo skip` to clear it first."
            )
            await ctx.send(embed=embed)
            return

        if not player.last_track:
            embed = self._make_embed(
                "❌ No Queue", 0xE74C3C, "No previous queue found to revive."
            )
            await ctx.send(embed=embed)
            return

        if not ctx.author.voice:
            embed = self._make_embed(
                "❌ Not in VC", 0xE74C3C, "You must be in a voice channel"
            )
            await ctx.send(embed=embed)
            return

        if not ctx.voice_client:
            await ctx.author.voice.channel.connect()

        player.current = player.last_track
        player.last_track = None
        filter_str = build_filter_string(player)
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(player.current.stream_url, **get_ffmpeg_opts(filter_str)),
            volume=player.volume,
        )

        def after_callback(error: Exception | None) -> None:
            if error:
                print(f"Playback error: {error}")
            asyncio.run_coroutine_threadsafe(
                self._play_next(ctx.guild.id), self.bot.loop
            )

        ctx.voice_client.play(source, after=after_callback)
        await self._update_presence(player.current, ctx.guild)
        player.text_channel = ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
        await ctx.send(embed=self._build_now_playing_embed(player.current, player))

    # ── play ──────────────────────────────────────────────────────────────────
    @commands.command(name="play", aliases=["p"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """Play a song or add it to the queue. Usage: sudo play <url or search query>"""
        player = self._get_player(ctx.guild.id)
        if player.game_active:
            embed = self._make_embed(
                "❌ Game In Progress",
                0xE74C3C,
                "A song-guessing game is running in this voice channel. "
                "Wait for it to finish before playing music.",
            )
            await ctx.send(embed=embed)
            return
        if not ctx.author.voice:
            embed = self._make_embed(
                "❌ Not Connected", 0xE74C3C, "You must be in a voice channel"
            )
            await ctx.send(embed=embed)
            return
        if not ctx.voice_client:
            try:
                await ctx.author.voice.channel.connect()
            except Exception as e:
                embed = self._make_embed(
                    "❌ Connection Failed", 0xE74C3C, f"Could not join voice: {e}"
                )
                await ctx.send(embed=embed)
                return

        is_external = query.startswith("http")
        if is_external:
            if self._is_spotify_url(query):
                msg = await ctx.send(embed=self._make_embed("🔍 Spotify Detected", 0x1DB954, "Finding on YouTube..."))
            elif self._is_apple_url(query):
                msg = await ctx.send(embed=self._make_embed("🔍 Apple Music Detected", 0xFC3C44, "Finding on YouTube..."))
            elif self._is_soundcloud_url(query):
                msg = await ctx.send(embed=self._make_embed("🔍 SoundCloud Detected", 0xFF5500, "Loading..."))
            else:
                msg = await ctx.send(embed=self._make_embed("🔍 Searching...", 0x1DB954, query))
        else:
            msg = await ctx.send(embed=self._make_embed("🔍 Searching...", 0x1DB954, query))

        async with ctx.typing():
            track = await self._fetch_track(query, ctx.author)

        if msg:
            try:
                await msg.delete()
            except Exception:
                pass

        if track is None:
            friendly = getattr(self, "_last_fetch_error", None)
            embed = self._make_embed(
                "❌ Not Found", 0xE74C3C, friendly or f"Could not find **'{query}'**"
            )
            await ctx.send(embed=embed)
            return

        player = self._get_player(ctx.guild.id)
        player.text_channel = (
            ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
        )

        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            player.queue.append(track)
            embed = discord.Embed(color=0x1DB954)
            embed.set_author(
                name="➕ Added to Queue",
                icon_url=None,
            )
            embed.description = (
                f"[{track.title}]({track.url})" if track.url else track.title
            )
            embed.add_field(
                name="📍 Position", value=f"**{len(player.queue)}**", inline=True
            )
            embed.add_field(name="⏱️ Duration", value=track.fmt_duration(), inline=True)
            embed.set_footer(text=f"Requested by {track.requester.display_name}")
            await ctx.send(embed=embed)
            return

        player.current = track
        filter_str = build_filter_string(player)
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(track.stream_url, **get_ffmpeg_opts(filter_str)),
            volume=player.volume,
        )

        def after_callback(error: Exception | None) -> None:
            if error:
                print(f"Playback error: {error}")
            asyncio.run_coroutine_threadsafe(
                self._play_next(ctx.guild.id), self.bot.loop
            )

        player._start_time = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0
        ctx.voice_client.play(source, after=after_callback)
        await self._update_presence(track, ctx.guild)
        await self._maybe_start_spectrum(ctx.guild.id, ctx.guild)
        await ctx.send(embed=self._build_now_playing_embed(track, player))

    # ── pause ─────────────────────────────────────────────────────────────────
    @commands.command(name="pause")
    async def pause(self, ctx: commands.Context) -> None:
        """Pause the current track. Usage: sudo pause"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            embed = self._make_embed("Paused", 0x95A5A6, f"{EMOJI_MUSIC_PAUSE} Playback paused.")
            await ctx.send(embed=embed)
        else:
            embed = self._make_embed(
                "❌ Nothing Playing", 0xE74C3C, "Nothing is currently playing"
            )
            await ctx.send(embed=embed)

    # ── resume ────────────────────────────────────────────────────────────────
    @commands.command(name="resume", aliases=["unpause"])
    async def resume(self, ctx: commands.Context) -> None:
        """Resume paused playback. Usage: sudo resume"""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            embed = self._make_embed("Resumed", 0x2ECC71, f"{EMOJI_MUSIC_PLAY} Playback resumed.")
            await ctx.send(embed=embed)
        else:
            embed = self._make_embed(
                "❌ Not Paused", 0xE74C3C, "Playback is not paused"
            )
            await ctx.send(embed=embed)

    # ── stop ──────────────────────────────────────────────────────────────────
    @commands.command(name="stop")
    async def stop(self, ctx: commands.Context) -> None:
        """Stop playback and clear the queue. Usage: sudo stop"""
        if not ctx.voice_client:
            embed = self._make_embed(
                "❌ Not Connected", 0xE74C3C, "Bot is not in a voice channel"
            )
            await ctx.send(embed=embed)
            return
        player = self._get_player(ctx.guild.id)
        if player.game_active:
            embed = self._make_embed(
                "❌ Game In Progress",
                0xE74C3C,
                "A song-guessing game is running in this voice channel. "
                "Wait for it to finish before stopping playback.",
            )
            await ctx.send(embed=embed)
            return
        player.queue.clear()
        player.current = None
        self._reset_player_settings(player)
        ctx.voice_client.stop()
        await self._update_presence(None, ctx.guild)
        embed = self._make_embed(
            "Stopped",
            0xE74C3C,
            f"{EMOJI_MUSIC_STOP} Playback stopped and queue cleared.",
        )
        await ctx.send(embed=embed)

    # ── skip ──────────────────────────────────────────────────────────────────
    @commands.command(name="skip", aliases=["s", "next"])
    async def skip(self, ctx: commands.Context) -> None:
        """Vote to skip the current track (auto-votes). Skip triggers at 50% votes. Usage: sudo skip"""
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            embed = self._make_embed(
                "❌ Nothing Playing", 0xE74C3C, "Nothing is currently playing"
            )
            await ctx.send(embed=embed)
            return

        if not ctx.author.voice or ctx.author.voice.channel != ctx.voice_client.channel:
            embed = self._make_embed(
                "❌ Not in VC", 0xE74C3C, "You must be in the same voice channel"
            )
            await ctx.send(embed=embed)
            return

        player = self._get_player(ctx.guild.id)

        if not player.current:
            embed = self._make_embed(
                "❌ Nothing Playing", 0xE74C3C, "Nothing is currently playing"
            )
            await ctx.send(embed=embed)
            return

        if ctx.author.id == player.current.requester.id:
            await self._fade_out_and_skip(ctx.guild.id)
            embed = self._make_embed(
                "Skipped", 0xF39C12, f"Requester skipped: **{player.current.title}**"
            )
            await ctx.send(embed=embed)
            return

        if ctx.author.id in player.skip_votes:
            player.skip_votes.discard(ctx.author.id)
            total_members = len([m for m in ctx.voice_client.channel.members if not m.bot])
            needed = math.ceil(total_members / 2)
            embed = self._make_embed(
                "Vote Removed", 0x95A5A6,
                f"Vote removed. **{len(player.skip_votes)}/{needed}** votes needed."
            )
            await ctx.send(embed=embed)
            return

        player.skip_votes.add(ctx.author.id)

        total_members = len([m for m in ctx.voice_client.channel.members if not m.bot])
        needed = math.ceil(total_members / 2)
        current_votes = len(player.skip_votes)

        if current_votes >= needed:
            track_name = player.current.title if player.current else "Unknown"
            await self._fade_out_and_skip(ctx.guild.id)
            player.skip_votes.clear()
            embed = self._make_embed(
                "Vote Skip!", 0x2ECC71,
                f"Skip passed with **{current_votes}/{total_members}** votes!\nSkipped: **{track_name}**"
            )
            await ctx.send(embed=embed)
        else:
            embed = self._make_embed(
                "Vote Added", 0x3498DB,
                f"**{ctx.author}** voted to skip.\n**{current_votes}/{needed}** votes needed."
            )
            await ctx.send(embed=embed)

    async def _fade_out_and_skip(self, guild_id: int) -> None:
        """Fade out volume over 5 seconds then skip."""
        player = self._get_player(guild_id)
        guild = self.bot.get_guild(guild_id)
        if not guild or not guild.voice_client:
            return
        
        voice_client = guild.voice_client
        if not voice_client:
            return
        if not voice_client.source:
            try:
                voice_client.stop()
            except Exception:
                pass
            return

        original_volume = player.volume
        steps = 10
        fade_delay = 0.5
        volume_step = original_volume / steps

        for i in range(steps):
            await asyncio.sleep(fade_delay)
            try:
                if voice_client and voice_client.source:
                    new_vol = max(0, original_volume - (volume_step * (i + 1)))
                    voice_client.source.volume = new_vol
            except Exception:
                pass

        try:
            voice_client.stop()
            if voice_client.source:
                voice_client.source.volume = original_volume
        except Exception:
            pass

    # ── queue ─────────────────────────────────────────────────────────────────
    @commands.command(name="queue", aliases=["q"])
    async def queue(self, ctx: commands.Context) -> None:
        """View the current music queue. Usage: sudo queue"""
        player = self._get_player(ctx.guild.id)
        embed = discord.Embed(color=0x1DB954)
        embed.set_author(
            name=f"{EMOJI_MUSIC_QUEUE} Music Queue",
            icon_url=None,
        )

        if player.current:
            embed.add_field(
                name="Now Playing",
                value=f"`{player.current.title}` [{player.current.fmt_duration()}] — {player.current.requester.mention}",
                inline=False,
            )
        if player.queue:
            lines = "\n".join(
                f"`{i + 1}.` {t.title} [{t.fmt_duration()}]"
                for i, t in enumerate(list(player.queue)[:15])
            )
            if len(player.queue) > 15:
                lines += f"\n… and {len(player.queue) - 15} more"
            embed.add_field(
                name=f"Queue ({len(player.queue)} tracks)",
                value=lines,
                inline=False,
            )
        else:
            embed.add_field(name="Queue", value="Empty", inline=False)
        embed.add_field(
            name=f"{EMOJI_MUSIC_LOOP} Loop",
            value="ON" if player.loop else "OFF",
            inline=True,
        )
        embed.add_field(
            name=f"{EMOJI_MUSIC_VOL} Volume",
            value=f"{int(player.volume * 100)}%",
            inline=True,
        )
        await ctx.send(embed=embed)

    # ── nowplaying ────────────────────────────────────────────────────────────
    @commands.command(name="nowplaying", aliases=["np", "current"])
    async def nowplaying(self, ctx: commands.Context) -> None:
        """Show what's currently playing. Usage: sudo nowplaying"""
        player = self._get_player(ctx.guild.id)
        if not player.current:
            embed = self._make_embed(
                "❌ Nothing Playing", 0xE74C3C, "Nothing is currently playing"
            )
            await ctx.send(embed=embed)
            return
        await ctx.send(embed=self._build_now_playing_embed(player.current, player))

    # ── volume ────────────────────────────────────────────────────────────────
    @commands.command(name="volume", aliases=["vol"])
    async def volume(self, ctx: commands.Context, level: int) -> None:
        """Adjust the music volume. Usage: sudo volume <0-200>"""
        if not 0 <= level <= 200:
            embed = self._make_embed(
                "❌ Invalid Volume", 0xE74C3C, "Value must be between 0 and 200"
            )
            await ctx.send(embed=embed)
            return
        player = self._get_player(ctx.guild.id)
        player.volume = level / 100
        if ctx.voice_client and ctx.voice_client.source:
            ctx.voice_client.source.volume = player.volume
        embed = self._make_embed(
            "Volume Changed", 0x2ECC71, f"{EMOJI_MUSIC_VOL} Volume set to **{level}%**"
        )
        await ctx.send(embed=embed)

    # ── shuffle ───────────────────────────────────────────────────────────────
    @commands.command(name="shuffle")
    async def shuffle(self, ctx: commands.Context) -> None:
        """Shuffle the music queue. Usage: sudo shuffle"""
        player = self._get_player(ctx.guild.id)
        if len(player.queue) < 2:
            embed = self._make_embed(
                "❌ Not Enough Tracks",
                0xE74C3C,
                "Not enough tracks in queue to shuffle",
            )
            await ctx.send(embed=embed)
            return
        q = list(player.queue)
        random.shuffle(q)
        player.queue = deque(q)
        embed = self._make_embed(
            "Queue Shuffled",
            0x9B59B6,
            f"{EMOJI_MUSIC_SHUFFLE} Queue shuffled ({len(player.queue)} tracks)",
        )
        await ctx.send(embed=embed)

    # ── loop ──────────────────────────────────────────────────────────────────
    @commands.command(name="loop", aliases=["repeat"])
    async def loop(self, ctx: commands.Context) -> None:
        """Toggle loop mode for the queue. Usage: sudo loop"""
        player = self._get_player(ctx.guild.id)
        player.loop = not player.loop
        state = "**enabled**" if player.loop else "**disabled**"
        embed = self._make_embed(
            "Loop Toggled", 0xF39C12, f"{EMOJI_MUSIC_LOOP} Loop {state}"
        )
        await ctx.send(embed=embed)

    # ── remove ────────────────────────────────────────────────────────────────
    @commands.command(name="remove")
    async def remove(self, ctx: commands.Context, index: int) -> None:
        """Remove a track from queue by position. Usage: sudo remove <position>"""
        player = self._get_player(ctx.guild.id)
        if not player.queue or not 1 <= index <= len(player.queue):
            embed = self._make_embed(
                "❌ Invalid Index", 0xE74C3C, "Invalid queue index"
            )
            await ctx.send(embed=embed)
            return
        q = list(player.queue)
        removed = q.pop(index - 1)
        player.queue = deque(q)
        embed = self._make_embed(
            "Track Removed", 0xE67E22, f"Removed: **{removed.title}**"
        )
        await ctx.send(embed=embed)

    # ── radio ─────────────────────────────────────────────────────────────────
    @commands.command(name="radio")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def radio(self, ctx: commands.Context, *, genre: str) -> None:
        """Play a radio stream of a music genre. Usage: sudo radio <genre>"""
        if not ctx.author.voice:
            embed = self._make_embed(
                "❌ Not Connected", 0xE74C3C, "You must be in a voice channel"
            )
            await ctx.send(embed=embed)
            return
        if not ctx.voice_client:
            await ctx.author.voice.channel.connect()

        loading_embed = self._make_embed(
            "📻 Loading Radio", 0x3498DB, f"Searching for **{genre}** genre mixes..."
        )
        loading_msg = await ctx.send(embed=loading_embed)

        player = self._get_player(ctx.guild.id)
        player.text_channel = (
            ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
        )

        search_queries = [
            f"ytsearch15:{genre} mix",
            f"ytsearch15:{genre} playlist popular",
            f"ytsearch10:{genre} music compilation",
        ]

        tracks_found = []
        loop = asyncio.get_event_loop()
        ydl_opts = get_ytdl_opts()
        ytdl_instance = yt_dlp.YoutubeDL(ydl_opts)

        for query in search_queries:
            if len(tracks_found) >= 10:
                break
            try:
                data = await loop.run_in_executor(
                    None,
                    functools.partial(ytdl_instance.extract_info, query, download=False),
                )
                if data and "entries" in data:
                    for entry in data["entries"]:
                        if entry and entry not in tracks_found:
                            tracks_found.append(entry)
            except Exception:
                continue

        if not tracks_found:
            await loading_msg.edit(embed=self._make_embed(
                "❌ No Results", 0xE74C3C, f"Could not find any **{genre}** genre tracks"
            ))
            return

        unique_tracks = []
        seen_urls = set()
        for track_data in tracks_found:
            if track_data and track_data.get("url") not in seen_urls:
                seen_urls.add(track_data["url"])
                unique_tracks.append(Track(track_data, ctx.author))

        random.shuffle(unique_tracks)

        added_count = len(unique_tracks)
        for track in unique_tracks:
            player.queue.append(track)

        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            embed = self._make_embed(
                "📻 Radio Queued", 0x9B59B6,
                f"Added **{added_count}** tracks from **{genre}** genre to queue"
            )
            await loading_msg.edit(embed=embed)
        else:
            if player.queue:
                player.current = player.queue.popleft()
                filter_str = build_filter_string(player)
                source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(player.current.stream_url, **get_ffmpeg_opts(filter_str)),
                    volume=player.volume,
                )

                def after_callback(error: Exception | None) -> None:
                    if error:
                        print(f"Playback error: {error}")
                    asyncio.run_coroutine_threadsafe(
                        self._play_next(ctx.guild.id), self.bot.loop
                    )

                ctx.voice_client.play(source, after=after_callback)
                await self._update_presence(player.current, ctx.guild)

            embed = discord.Embed(color=0x9B59B6)
            embed.set_author(name="📻 Radio Started", icon_url=None)
            embed.description = f"Playing **{len(player.queue) + (1 if player.current else 0)}** tracks from **{genre}** genre"
            embed.add_field(name="Genre", value=genre.title(), inline=True)
            embed.add_field(name="Tracks", value=f"**{added_count}** in queue", inline=True)
            if player.current:
                embed.add_field(
                    name="Now Playing",
                    value=f"[{player.current.title}]({player.current.url})" if player.current.url else player.current.title,
                    inline=False,
                )
            await loading_msg.edit(embed=embed)

    # ── clearqueue ────────────────────────────────────────────────────────────
    @commands.command(name="clearqueue", aliases=["cq"])
    async def clearqueue(self, ctx: commands.Context) -> None:
        """Clear all tracks from the queue. Usage: sudo clearqueue"""
        player = self._get_player(ctx.guild.id)
        count = len(player.queue)
        player.queue.clear()
        embed = self._make_embed(
            "Queue Cleared", 0x95A5A6, f"Cleared **{count}** track(s) from queue"
        )
        await ctx.send(embed=embed)

    # ── seek ──────────────────────────────────────────────────────────────────
    @commands.command(name="seek")
    async def seek(self, ctx: commands.Context, position: str) -> None:
        """Seek to a position in the track. Usage: sudo seek <MM:SS>"""
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            embed = self._make_embed("❌ Nothing Playing", 0xE74C3C, "Nothing is currently playing")
            await ctx.send(embed=embed)
            return
        
        player = self._get_player(ctx.guild.id)
        if not player.current:
            embed = self._make_embed("❌ No Track", 0xE74C3C, "No track loaded")
            await ctx.send(embed=embed)
            return

        try:
            parts = position.split(":")
            if len(parts) == 2:
                secs = int(parts[0]) * 60 + int(parts[1])
            else:
                secs = int(position)
        except ValueError:
            embed = self._make_embed("❌ Invalid Format", 0xE74C3C, "Use format: MM:SS or seconds")
            await ctx.send(embed=embed)
            return

        if secs < 0 or secs > player.current.duration:
            embed = self._make_embed("❌ Out of Range", 0xE74C3C, f"Track duration is {player.current.fmt_duration()}")
            await ctx.send(embed=embed)
            return

        ctx.voice_client.pause()
        filter_str = build_filter_string(player)
        opts = get_ffmpeg_opts(filter_str)
        opts["before_options"] = f"{opts['before_options']} -ss {secs}"
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(player.current.stream_url, **opts),
            volume=player.volume,
        )

        def after_callback(error: Exception | None) -> None:
            if error:
                print(f"Playback error: {error}")
            asyncio.run_coroutine_threadsafe(self._play_next(ctx.guild.id), self.bot.loop)

        ctx.voice_client.play(source, after=after_callback)
        embed = self._make_embed("⏩ Seeked", 0x2ECC71, f"Seeked to **{position}**")
        await ctx.send(embed=embed)

    # ── replay ────────────────────────────────────────────────────────────────
    @commands.command(name="replay")
    async def replay(self, ctx: commands.Context) -> None:
        """Replay the current track from the beginning. Usage: sudo replay"""
        if not ctx.voice_client or not (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            embed = self._make_embed("❌ Nothing Playing", 0xE74C3C, "Nothing is currently playing")
            await ctx.send(embed=embed)
            return
        
        player = self._get_player(ctx.guild.id)
        if not player.current:
            embed = self._make_embed("❌ No Track", 0xE74C3C, "No track to replay")
            await ctx.send(embed=embed)
            return

        ctx.voice_client.stop()
        player.queue.appendleft(player.current)
        await self._play_next(ctx.guild.id)
        embed = self._make_embed("🔄 Replaying", 0x9B59B6, f"Replaying: **{player.current.title if player.current else 'Unknown'}**")
        await ctx.send(embed=embed)

    # ── autoplay ─────────────────────────────────────────────────────────────
    @commands.command(name="autoplay")
    async def autoplay(self, ctx: commands.Context) -> None:
        """Toggle autoplay for similar tracks. Usage: sudo autoplay"""
        player = self._get_player(ctx.guild.id)
        player.autoplay = not player.autoplay
        state = "**enabled**" if player.autoplay else "**disabled**"
        embed = self._make_embed("🔄 Autoplay", 0xF39C12, f"Autoplay {state}")
        await ctx.send(embed=embed)

    # ── bassboost ────────────────────────────────────────────────────────────
    @commands.command(name="bassboost")
    async def bassboost(self, ctx: commands.Context) -> None:
        """Toggle bass boost effect. Usage: sudo bassboost"""
        player = self._get_player(ctx.guild.id)
        player.bassboost = not player.bassboost
        state = "**enabled**" if player.bassboost else "**disabled**"
        embed = self._make_embed("🔊 Bass Boost", 0xE67E22, f"Bass boost {state}")
        await ctx.send(embed=embed)

    # ── nightcore ────────────────────────────────────────────────────────────
    @commands.command(name="nightcore")
    async def nightcore(self, ctx: commands.Context) -> None:
        """Toggle nightcore effect (faster + higher pitch). Usage: sudo nightcore"""
        player = self._get_player(ctx.guild.id)
        player.nightcore = not player.nightcore
        state = "**enabled**" if player.nightcore else "**disabled**"
        embed = self._make_embed("🌙 Nightcore", 0x9B59B6, f"Nightcore effect {state}")
        await ctx.send(embed=embed)

    # ── 8d ───────────────────────────────────────────────────────────────────
    @commands.command(name="8d", aliases=["eightd"])
    async def eight_d(self, ctx: commands.Context) -> None:
        """Toggle 8D audio effect. Usage: sudo 8d"""
        if not ctx.voice_client or not (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            embed = self._make_embed("❌ Nothing Playing", 0xE74C3C, "Nothing is currently playing")
            await ctx.send(embed=embed)
            return
        player = self._get_player(ctx.guild.id)
        player.eight_d = not player.eight_d
        state = "**enabled**" if player.eight_d else "**disabled**"
        embed = self._make_embed("🎧 8D Audio", 0x3498DB, f"8D effect {state}\n*Rotating audio with reverb*")
        await ctx.send(embed=embed)

    # ── equalizer ────────────────────────────────────────────────────────────
    @commands.command(name="equalizer", aliases=["eq"])
    async def equalizer(self, ctx: commands.Context, preset: str = "flat") -> None:
        """Set equalizer preset. Usage: sudo equalizer <preset>"""
        player = self._get_player(ctx.guild.id)
        valid_presets = ["flat", "bass", "treble", "pop", "rock", "jazz", "classical", "electronic"]
        preset = preset.lower()
        if preset not in valid_presets:
            embed = self._make_embed("❌ Invalid Preset", 0xE74C3C, f"Valid presets: {', '.join(valid_presets)}")
            await ctx.send(embed=embed)
            return
        player.equalizer = preset
        embed = self._make_embed("🎚️ Equalizer", 0x2ECC71, f"Equalizer set to **{preset}**")
        await ctx.send(embed=embed)

    # ── lyrics ───────────────────────────────────────────────────────────────
    @commands.command(name="lyrics")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def lyrics(self, ctx: commands.Context, *, query: str = None) -> None:
        """Search for song lyrics. Usage: sudo lyrics <song name>"""
        if not query:
            player = self._get_player(ctx.guild.id)
            if player.current:
                query = player.current.title
            else:
                embed = self._make_embed("❌ No Query", 0xE74C3C, "Provide a song name or play a song first")
                await ctx.send(embed=embed)
                return

        msg = await ctx.send(embed=self._make_embed("🔍 Searching...", 0x9B59B6, f"Searching lyrics for: **{query}**"))

        loop = asyncio.get_event_loop()
        try:
            search_query = f"ytsearch1:{query} lyrics official"
            ydl_opts = get_ytdl_opts()
            ytdl_instance = yt_dlp.YoutubeDL(ydl_opts)
            data = await loop.run_in_executor(
                None,
                functools.partial(ytdl_instance.extract_info, search_query, download=False),
            )
            if data and "entries" in data and data["entries"]:
                entry = data["entries"][0]
                title = entry.get("title", query)
                url = entry.get("webpage_url", "")
                
                embed = discord.Embed(color=0x9B59B6)
                embed.set_author(name="🎤 Lyrics Search", icon_url=None)
                embed.description = f"**{title}**"
                embed.add_field(name="Search", value=f"[YouTube Search]({url})", inline=True)
                embed.add_field(name="Tip", value="Use /lyrics slash command or search on Genius/Lyrics.com", inline=True)
                await msg.edit(embed=embed)
            else:
                await msg.edit(embed=self._make_embed("❌ Not Found", 0xE74C3C, f"Could not find lyrics for: **{query}**"))
        except Exception as e:
            await msg.edit(embed=self._make_embed("❌ Error", 0xE74C3C, f"Search failed: {e}"))

    # ── favorites ────────────────────────────────────────────────────────────
    @commands.command(name="favorites", aliases=["favs"])
    async def favorites(self, ctx: commands.Context, action: str = None, *, query: str = None) -> None:
        """Manage your favorites. Usage: sudo favorites [add|remove|list] [song name]"""
        player = self._get_player(ctx.guild.id)
        user_id = str(ctx.author.id)
        
        favorites_file = f"data/favorites_{user_id}.txt"
        os.makedirs("data", exist_ok=True)
        
        if not os.path.exists(favorites_file):
            with open(favorites_file, "w") as f:
                pass
        
        with open(favorites_file, "r") as f:
            user_favs = [line.strip() for line in f if line.strip()]
        
        if not action:
            if not user_favs:
                embed = self._make_embed("⭐ Favorites", 0xF1C40F, "Your favorites list is empty. Use `sudo favorites add <song>` to add.")
                await ctx.send(embed=embed)
                return
            embed = discord.Embed(color=0xF1C40F)
            embed.set_author(name="⭐ Your Favorites", icon_url=None)
            lines = "\n".join(f"`{i+1}.` {f}" for i, f in enumerate(user_favs[:15]))
            if len(user_favs) > 15:
                lines += f"\n… and {len(user_favs) - 15} more"
            embed.description = lines
            await ctx.send(embed=embed)
            return
        
        action = action.lower()
        
        if action == "add":
            if not query:
                embed = self._make_embed("❌ No Song", 0xE74C3C, "Provide a song name to add")
                await ctx.send(embed=embed)
                return
            if player.current and query.lower() in player.current.title.lower():
                fav_entry = player.current.title
            else:
                fav_entry = query
            with open(favorites_file, "a") as f:
                f.write(f"{fav_entry}\n")
            embed = self._make_embed("⭐ Added", 0xF1C40F, f"Added to favorites: **{fav_entry}**")
            await ctx.send(embed=embed)
        
        elif action == "remove":
            if not query:
                embed = self._make_embed("❌ No Song", 0xE74C3C, "Provide a song name to remove")
                await ctx.send(embed=embed)
                return
            removed = False
            with open(favorites_file, "r") as f:
                lines = f.readlines()
            with open(favorites_file, "w") as f:
                for line in lines:
                    if query.lower() not in line.strip().lower():
                        f.write(line)
                    else:
                        removed = True
            if removed:
                embed = self._make_embed("⭐ Removed", 0xE74C3C, f"Removed from favorites: **{query}**")
            else:
                embed = self._make_embed("❌ Not Found", 0xE74C3C, f"Could not find: **{query}**")
            await ctx.send(embed=embed)
        
        elif action == "list":
            if not user_favs:
                embed = self._make_embed("⭐ Favorites", 0xF1C40F, "Your favorites list is empty")
                await ctx.send(embed=embed)
                return
            embed = discord.Embed(color=0xF1C40F)
            embed.set_author(name="⭐ Your Favorites", icon_url=None)
            lines = "\n".join(f"`{i+1}.` {f}" for i, f in enumerate(user_favs[:20]))
            embed.description = lines
            await ctx.send(embed=embed)
        
        else:
            embed = self._make_embed("❌ Invalid Action", 0xE74C3C, "Use: `sudo favorites add <song>`, `sudo favorites remove <song>`, or `sudo favorites`")
            await ctx.send(embed=embed)

    # ── playlist ────────────────────────────────────────────────────────────
    @commands.command(name="playlist")
    async def playlist(self, ctx: commands.Context, action: str = None, name: str = None, *, query: str = None) -> None:
        """Manage playlists. Usage: sudo playlist [create|delete|add|remove|play|list] [name] [song]"""
        playlists_dir = "data/playlists"
        os.makedirs(playlists_dir, exist_ok=True)
        
        if not action:
            playlists = [f.replace(".txt", "") for f in os.listdir(playlists_dir) if f.endswith(".txt")]
            if not playlists:
                embed = self._make_embed("🎶 Playlists", 0x9B59B6, "No playlists yet. Use `sudo playlist create <name>` to create one.")
                await ctx.send(embed=embed)
                return
            embed = discord.Embed(color=0x9B59B6)
            embed.set_author(name="🎶 Server Playlists", icon_url=None)
            embed.description = "\n".join(f"`{p}`" for p in playlists)
            await ctx.send(embed=embed)
            return
        
        action = action.lower()
        
        if action == "create":
            if not name:
                embed = self._make_embed("❌ No Name", 0xE74C3C, "Provide a playlist name")
                await ctx.send(embed=embed)
                return
            safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip()[:50]
            playlist_file = os.path.join(playlists_dir, f"{safe_name}.txt")
            if os.path.exists(playlist_file):
                embed = self._make_embed("❌ Exists", 0xE74C3C, f"Playlist **{safe_name}** already exists")
                await ctx.send(embed=embed)
                return
            with open(playlist_file, "w") as f:
                f.write(f"# {safe_name}\n")
            embed = self._make_embed("✅ Created", 0x2ECC71, f"Created playlist: **{safe_name}**")
            await ctx.send(embed=embed)
        
        elif action == "delete":
            if not name:
                embed = self._make_embed("❌ No Name", 0xE74C3C, "Provide a playlist name")
                await ctx.send(embed=embed)
                return
            safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip()[:50]
            playlist_file = os.path.join(playlists_dir, f"{safe_name}.txt")
            if not os.path.exists(playlist_file):
                embed = self._make_embed("❌ Not Found", 0xE74C3C, f"Playlist **{safe_name}** not found")
                await ctx.send(embed=embed)
                return
            os.remove(playlist_file)
            embed = self._make_embed("🗑️ Deleted", 0xE74C3C, f"Deleted playlist: **{safe_name}**")
            await ctx.send(embed=embed)
        
        elif action == "add":
            if not name or not query:
                embed = self._make_embed("❌ Missing Args", 0xE74C3C, "Usage: `sudo playlist add <name> <song>`")
                await ctx.send(embed=embed)
                return
            safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip()[:50]
            playlist_file = os.path.join(playlists_dir, f"{safe_name}.txt")
            if not os.path.exists(playlist_file):
                embed = self._make_embed("❌ Not Found", 0xE74C3C, f"Playlist **{safe_name}** not found")
                await ctx.send(embed=embed)
                return
            with open(playlist_file, "a") as f:
                f.write(f"{query}\n")
            embed = self._make_embed("➕ Added", 0x2ECC71, f"Added to **{safe_name}**: {query}")
            await ctx.send(embed=embed)
        
        elif action == "remove":
            if not name or not query:
                embed = self._make_embed("❌ Missing Args", 0xE74C3C, "Usage: `sudo playlist remove <name> <song>`")
                await ctx.send(embed=embed)
                return
            safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip()[:50]
            playlist_file = os.path.join(playlists_dir, f"{safe_name}.txt")
            if not os.path.exists(playlist_file):
                embed = self._make_embed("❌ Not Found", 0xE74C3C, f"Playlist **{safe_name}** not found")
                await ctx.send(embed=embed)
                return
            with open(playlist_file, "r") as f:
                lines = f.readlines()
            with open(playlist_file, "w") as f:
                for line in lines:
                    if query.lower() not in line.strip().lower():
                        f.write(line)
            embed = self._make_embed("➖ Removed", 0xF39C12, f"Removed from **{safe_name}**: {query}")
            await ctx.send(embed=embed)
        
        elif action == "play":
            if not name:
                embed = self._make_embed("❌ No Name", 0xE74C3C, "Provide a playlist name")
                await ctx.send(embed=embed)
                return
            if not ctx.author.voice:
                embed = self._make_embed("❌ Not in VC", 0xE74C3C, "You must be in a voice channel")
                await ctx.send(embed=embed)
                return
            safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip()[:50]
            playlist_file = os.path.join(playlists_dir, f"{safe_name}.txt")
            if not os.path.exists(playlist_file):
                embed = self._make_embed("❌ Not Found", 0xE74C3C, f"Playlist **{safe_name}** not found")
                await ctx.send(embed=embed)
                return
            
            with open(playlist_file, "r") as f:
                songs = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            
            if not songs:
                embed = self._make_embed("❌ Empty", 0xE74C3C, f"Playlist **{safe_name}** is empty")
                await ctx.send(embed=embed)
                return
            
            if not ctx.voice_client:
                await ctx.author.voice.channel.connect()
            
            player = self._get_player(ctx.guild.id)
            player.text_channel = ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
            
            added = 0
            for song in songs[:20]:
                track = await self._fetch_track(song, ctx.author)
                if track:
                    player.queue.append(track)
                    added += 1
            
            embed = self._make_embed("🎶 Playlist Queued", 0x9B59B6, f"Added **{added}** songs from **{safe_name}** to queue")
            await ctx.send(embed=embed)
            
            if not ctx.voice_client.is_playing():
                await self._play_next(ctx.guild.id)
        
        elif action == "list":
            if not name:
                playlists = [f.replace(".txt", "") for f in os.listdir(playlists_dir) if f.endswith(".txt")]
                embed = discord.Embed(color=0x9B59B6)
                embed.set_author(name="🎶 All Playlists", icon_url=None)
                embed.description = "\n".join(f"`{p}`" for p in playlists) if playlists else "No playlists yet"
                await ctx.send(embed=embed)
                return
            safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip()[:50]
            playlist_file = os.path.join(playlists_dir, f"{safe_name}.txt")
            if not os.path.exists(playlist_file):
                embed = self._make_embed("❌ Not Found", 0xE74C3C, f"Playlist **{safe_name}** not found")
                await ctx.send(embed=embed)
                return
            with open(playlist_file, "r") as f:
                songs = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            embed = discord.Embed(color=0x9B59B6)
            embed.set_author(name=f"🎶 {safe_name}", icon_url=None)
            embed.description = "\n".join(f"`{i+1}.` {s}" for i, s in enumerate(songs[:20]))
            if len(songs) > 20:
                embed.set_footer(text=f"… and {len(songs) - 20} more")
            await ctx.send(embed=embed)
        
        else:
            embed = self._make_embed("❌ Invalid Action", 0xE74C3C, "Use: create, delete, add, remove, play, list")
            await ctx.send(embed=embed)

    @commands.command(name="refresh")
    @perms_or_developer(administrator=True)
    async def refresh(self, ctx: commands.Context) -> None:
        """Refresh yt-dlp cookies. Usage: sudo refresh"""
        cookies_file = "cookies.txt"
        
        if not os.path.exists(cookies_file):
            embed = discord.Embed(color=0xE74C3C)
            embed.set_author(name="❌ No Cookies File")
            embed.description = "No `cookies.txt` file found in bot directory.\nCreate one with YouTube cookies for age-restricted content."
            await ctx.send(embed=embed)
            return

        if os.path.getsize(cookies_file) == 0:
            embed = discord.Embed(color=0xE74C3C)
            embed.set_author(name="❌ Empty Cookies")
            embed.description = "`cookies.txt` is empty. Please add valid YouTube cookies."
            await ctx.send(embed=embed)
            return

        ydl_opts = get_ytdl_opts()
        if "cookiefile" in ydl_opts:
            embed = discord.Embed(color=0x2ECC71)
            embed.set_author(name="✅ Cookies Refreshed")
            embed.description = "yt-dlp cookies have been **refreshed** and are active.\n\nAge-restricted content should now work."
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(color=0xF39C12)
            embed.set_author(name="⚠️ Cookies Not Active")
            embed.description = "Cookies file exists but is not being used.\nPlease check the file format."
            await ctx.send(embed=embed)

    @refresh.error
    async def refresh_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingPermissions):
            embed = self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission.")
            await ctx.send(embed=embed)

    @commands.command(name="slowed")
    async def slowed(self, ctx: commands.Context) -> None:
        """Toggle slowed + reverb effect. Usage: sudo slowed"""
        if not ctx.voice_client or not (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            embed = self._make_embed("❌ Nothing Playing", 0xE74C3C, "Nothing is currently playing")
            await ctx.send(embed=embed)
            return

        player = self._get_player(ctx.guild.id)
        player.slowed = not player.slowed
        state = "**enabled**" if player.slowed else "**disabled**"
        embed = self._make_embed("🐌 Slowed + Reverb", 0x9B59B6, f"Slowed effect {state}")
        await ctx.send(embed=embed)

    @app_commands.command(name="slowed", description="Toggle slowed + reverb effect")
    async def slash_slowed(self, interaction: discord.Interaction) -> None:
        """Slash command for slowed effect."""
        if not interaction.guild or not interaction.guild.voice_client:
            await interaction.response.send_message(
                embed=self._make_embed("❌ Not in VC", 0xE74C3C, "Bot is not in a voice channel"),
                ephemeral=True
            )
            return
        if not (interaction.guild.voice_client.is_playing() or interaction.guild.voice_client.is_paused()):
            await interaction.response.send_message(
                embed=self._make_embed("❌ Nothing Playing", 0xE74C3C, "Nothing is currently playing"),
                ephemeral=True
            )
            return

        player = self._get_player(interaction.guild_id)
        player.slowed = not player.slowed
        state = "**enabled**" if player.slowed else "**disabled**"
        await interaction.response.send_message(
            embed=self._make_embed("🐌 Slowed + Reverb", 0x9B59B6, f"Slowed effect {state}")
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
