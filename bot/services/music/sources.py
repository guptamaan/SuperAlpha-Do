"""yt-dlp source adapter: options, URL sniffing, metadata, and error messages."""

from __future__ import annotations

import asyncio
import atexit
import base64
import json
import multiprocessing as mp
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor
from urllib.parse import parse_qs, urlsplit
import aiohttp
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

# Dedicated process pool so heavy yt-dlp work stays off the event-loop thread pool.
_ytdl_pool: ProcessPoolExecutor | None = None
_YTDL_POOL_WORKERS = 2


def _get_ytdl_pool() -> ProcessPoolExecutor:
    global _ytdl_pool
    if _ytdl_pool is None:
        _ytdl_pool = ProcessPoolExecutor(
            max_workers=_YTDL_POOL_WORKERS,
            mp_context=mp.get_context("spawn"),
        )
    return _ytdl_pool


def shutdown_ytdl_pool() -> None:
    """Shut down the shared yt-dlp process pool (idempotent)."""
    global _ytdl_pool
    if _ytdl_pool is not None:
        _ytdl_pool.shutdown(wait=False, cancel_futures=True)
        _ytdl_pool = None


atexit.register(shutdown_ytdl_pool)


def _ytdl_extract(query: str, opts: dict) -> dict | None:
    """Picklable worker: run yt-dlp extract_info in a child process."""
    with yt_dlp.YoutubeDL(opts) as ytdl:
        return ytdl.extract_info(query, download=False)


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


def _host_part(url: str) -> str:
    """The host of a URL, tolerating a missing scheme and trailing junk."""
    text = url.strip().lower().split("://", 1)[-1]
    return text.split("/", 1)[0].split("?", 1)[0]


def is_spotify_url(url: str) -> bool:
    return _is_domain(_host_part(url), "spotify.com")


def is_soundcloud_url(url: str) -> bool:
    return _is_domain(_hostname(url), "soundcloud.com")


SPOTIFY_API = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_OEMBED = "https://open.spotify.com/oembed"
SPOTIFY_ID_RE = re.compile(r"[0-9A-Za-z]{22}")
SPOTIFY_INTL_RE = re.compile(r"intl[.-][a-z]{2}", re.IGNORECASE)
SPOTIFY_KINDS = ("track", "album", "playlist", "episode", "show")
_spotify_token: tuple[str, float] | None = None


def parse_spotify_url(url: str) -> tuple[str, str] | None:
    """Return ``(kind, spotify_id)`` for a Spotify track/album/playlist link.

    Handles both the ``https://open.spotify.com/track/<id>?si=...`` form and the
    ``spotify:track:<id>`` URI people paste out of the mobile app, plus the
    localised ``/intl-de/track/<id>`` path. ``None`` means "not a Spotify link".
    """
    text = url.strip()
    lowered = text.lower()

    if lowered.startswith("spotify:"):
        # spotify:intl-de:track:<id> -> the country prefix is optional noise
        parts = [p for p in text.split(":") if p and not SPOTIFY_INTL_RE.fullmatch(p)]
        if len(parts) < 3:
            return None
        kind, spotify_id = parts[-2].lower(), parts[-1]

    elif _is_domain(_host_part(lowered), "spotify.com"):
        # Discord doesn't autolink scheme-less text, and people paste it anyway
        if "://" not in text:
            text = f"https://{text}"
        segments = [s for s in urlsplit(text).path.split("/") if s]
        if len(segments) >= 3 and SPOTIFY_INTL_RE.fullmatch(segments[0]):
            segments = segments[1:]
        if len(segments) < 2:
            return None
        kind, spotify_id = segments[0].lower(), segments[1]

    else:
        return None

    if kind not in SPOTIFY_KINDS or not SPOTIFY_ID_RE.fullmatch(spotify_id):
        return None
    return kind, spotify_id


async def _spotify_access_token(session: aiohttp.ClientSession) -> str | None:
    """Client-credentials token from the Spotify Web API, cached until it expires."""
    global _spotify_token
    client_id = os.environ.get("SPOTIPY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIPY_CLIENT_SECRET")
    if not (client_id and client_secret):
        return None
    if _spotify_token and _spotify_token[1] > time.monotonic():
        return _spotify_token[0]

    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    try:
        async with session.post(
            SPOTIFY_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {auth}"},
        ) as response:
            if response.status != 200:
                return None
            payload = await response.json()
    except Exception:
        return None

    token = payload.get("access_token")
    if not token:
        return None
    # refresh a minute early so a request never races the expiry
    lifetime = max(60, int(payload.get("expires_in", 3600)) - 60)
    _spotify_token = (token, time.monotonic() + lifetime)
    return token


SPOTIFY_EMBED = "https://open.spotify.com/embed"
_SPOTIFY_BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_SPOTIFY_ENTITY_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def _metadata_from_embed_html(html: str) -> dict | None:
    """Pull ``{title, artist}`` out of a Spotify embed page.

    The zero-config path: the embed widget ships the full track entity as JSON,
    including every credited artist, so no API credentials are needed.
    """
    match = _SPOTIFY_ENTITY_RE.search(html)
    if not match:
        return None
    try:
        entity = json.loads(match.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(entity, dict):
        return None

    title = (entity.get("name") or entity.get("title") or "").strip()
    artists = entity.get("artists") or []
    artist = ", ".join(
        a.get("name", "") for a in artists if isinstance(a, dict) and a.get("name")
    ).strip()
    if title:
        return {"title": title, "artist": artist}
    return None


async def _fetch_spotify_embed(session: aiohttp.ClientSession, spotify_id: str) -> dict | None:
    try:
        async with session.get(
            f"{SPOTIFY_EMBED}/track/{spotify_id}",
            headers={"User-Agent": _SPOTIFY_BROWSER_UA},
        ) as response:
            if response.status != 200:
                return None
            html = await response.text()
    except Exception:
        return None
    return _metadata_from_embed_html(html)


async def fetch_spotify_metadata(spotify_id: str) -> dict | None:
    """Resolve a Spotify track id to ``{title, artist}`` for a YouTube search.

    yt-dlp cannot do this: its Spotify extractor was removed because the audio is
    DRM-protected, so we ask Spotify directly. Three tiers, best first:

    1. the Web API, when ``SPOTIPY_CLIENT_ID``/``SPOTIPY_CLIENT_SECRET`` are set;
    2. the public embed page, which needs no credentials and still includes the
       credited artists;
    3. the oEmbed endpoint, which yields the title alone.
    """
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        token = await _spotify_access_token(session)
        if token:
            try:
                async with session.get(
                    f"{SPOTIFY_API}/tracks/{spotify_id}",
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        title = (data.get("name") or "").strip()
                        artist = ", ".join(
                            a["name"] for a in (data.get("artists") or []) if a.get("name")
                        )
                        if title and artist:
                            return {"title": title, "artist": artist}
            except Exception:
                pass

        embed = await _fetch_spotify_embed(session, spotify_id)
        if embed:
            return embed

        try:
            async with session.get(
                SPOTIFY_OEMBED, params={"url": f"https://open.spotify.com/track/{spotify_id}"}
            ) as response:
                if response.status != 200:
                    return None
                data = await response.json()
            title = (data.get("title") or "").strip()
            if title:
                return {"title": title, "artist": ""}
        except Exception:
            return None
    return None


def search_query_for(title: str, artist: str) -> str:
    """Build the YouTube search string for a resolved track.

    ``Artist - Title`` is how YouTube tracks are conventionally titled, and it
    steers the search toward the artist's own upload over reupload/lyrics
    channels: ``Hello Adele`` finds a lyrics channel, ``Adele - Hello`` finds
    Adele.
    """
    title = (title or "").strip()
    artist = (artist or "").strip()
    if artist and title:
        return f"{artist} - {title}"
    return title



def is_apple_url(url: str) -> bool:
    return _host_part(url) in {"music.apple.com", "itunes.apple.com"}


def parse_apple_url(url: str) -> tuple[str, str] | None:
    """Return ``("song", itunes_id)`` / ``("album", "")`` for an Apple Music link.

    Apple's song links carry the track id in the ``?i=`` query parameter
    (``/album/<slug>/<album_id>?i=<track_id>``); newer share links use a
    ``/song/<slug>/<track_id>`` path instead.
    """
    text = url.strip()
    if "://" not in text:
        text = f"https://{text}"
    if not is_apple_url(text):
        return None

    parts = urlsplit(text)
    segments = [s for s in parts.path.split("/") if s]
    if segments and re.fullmatch(r"[a-z]{2}", segments[0], re.IGNORECASE):
        segments = segments[1:]  # drop the storefront, e.g. /us/

    track_id = (parse_qs(parts.query).get("i") or [""])[0]
    if track_id.isdigit():
        return "song", track_id
    if len(segments) >= 2 and segments[0] == "song" and segments[-1].isdigit():
        return "song", segments[-1]
    if segments and segments[0] == "album":
        return "album", ""
    return None


async def fetch_apple_metadata(song_id: str) -> dict | None:
    """Resolve an Apple Music song id to ``{title, artist}`` via iTunes lookup.

    yt-dlp dropped its Apple Music extractor for the same DRM reason as Spotify,
    but the iTunes lookup API needs no credentials.
    """
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                "https://itunes.apple.com/lookup",
                params={"id": song_id, "entity": "song"},
            ) as response:
                if response.status != 200:
                    return None
                # iTunes serves JSON as text/javascript, which aiohttp refuses by default
                data = await response.json(content_type=None)
    except Exception:
        return None

    results = data.get("results") or []
    if not results:
        return None
    result = results[0]
    title = (result.get("trackName") or result.get("collectionName") or "").strip()
    artist = (result.get("artistName") or "").strip()
    if title:
        return {"title": title, "artist": artist}
    return None



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


async def extract_info(
    query: str,
    *,
    skip_download: bool = False,
    flat: bool = False,
) -> dict | None:
    """Run yt-dlp in a process pool and return the extracted info dict.

    Use ``flat=True`` (``extract_flat``) for playlist/search listings where
    stream URLs are not needed yet — e.g. radio mode and related-track search.
    Full extraction (``flat=False``) is required when a playable stream URL
    is needed.
    """
    loop = asyncio.get_running_loop()
    if skip_download:
        opts = {
            "quiet": True,
            "skip_download": True,
            "extract_flat": "in_playlist" if flat else False,
            "noplaylist": not flat,
        }
    else:
        opts = get_ytdl_opts()
        if flat:
            opts["extract_flat"] = "in_playlist"
            opts["noplaylist"] = False
    return await loop.run_in_executor(
        _get_ytdl_pool(),
        _ytdl_extract,
        query,
        opts,
    )

