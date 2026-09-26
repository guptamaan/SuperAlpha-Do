"""Music domain objects: a single track and per-guild player state."""

from __future__ import annotations

import asyncio
from collections import deque

import discord


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
        self.queue_loop: bool = False
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