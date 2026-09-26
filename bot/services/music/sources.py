"""yt-dlp source adapter: options, URL sniffing, metadata, and error messages."""

from __future__ import annotations

import asyncio
import functools
import os
from urllib.parse import urlsplit

import yt_dlp

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


def _hostname(url: str) -> str:
    """The lowercased hostname of a URL, or ``""`` when unparseable."""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def is_spotify_url(url: str) -> bool:
    return _is_domain(_hostname(url), "spotify.com")


def is_apple_url(url: str) -> bool:
    host = _hostname(url)
    return host in {"music.apple.com", "itunes.apple.com"}


def is_soundcloud_url(url: str) -> bool:
    return _is_domain(_hostname(url), "soundcloud.com")


def is_playable_url(url: str) -> bool:
    supported = ("youtube.com", "youtu.be", "soundcloud.com", "spotify.com", "apple.com", "bandcamp.com", "twitch.tv")
    return any(_is_domain(_hostname(url), d) for d in supported)


def youtube_search_query(query: str) -> str:
    return f"ytsearch1:{query}"


def classify_ytdl_error(error: Exception) -> str:
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


async def extract_info(query: str, *, skip_download: bool = False) -> dict | None:
    """Run yt-dlp in an executor and return the extracted info dict."""
    loop = asyncio.get_running_loop()
    if skip_download:
        opts = {
            "quiet": True,
            "skip_download": True,
            "extract_flat": False,
        }
    else:
        opts = get_ytdl_opts()
    ytdl = yt_dlp.YoutubeDL(opts)
    return await loop.run_in_executor(
        None,
        functools.partial(ytdl.extract_info, query, download=False),
    )


async def fetch_metadata(url: str, *, require_artist: bool = False) -> dict | None:
    """Best-effort ``{title, artist}`` metadata for a non-YouTube URL.

    Used to translate Spotify / Apple Music links into a YouTube search.
    ``require_artist`` matches the old per-platform behaviour (Spotify needs an
    artist, Apple Music accepts a bare title).
    """
    try:
        info = await extract_info(url, skip_download=True)
        if not info:
            return None
        title = info.get("title", "")
        artist = info.get("artist", "") or info.get("uploader", "")
        if title and (artist or not require_artist):
            return {"title": title, "artist": artist}
    except Exception:
        return None
    return None