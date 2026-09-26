"""Music services: playback domain objects, audio filters, and yt-dlp sources."""

from bot.services.music.filters import build_filter_string, get_ffmpeg_opts
from bot.services.music.models import GuildPlayer, Track
from bot.services.music.sources import (
    BASE_YTDL_OPTS,
    classify_ytdl_error,
    extract_info,
    fetch_metadata,
    get_ytdl_opts,
    is_apple_url,
    is_playable_url,
    is_soundcloud_url,
    is_spotify_url,
    youtube_search_query,
)

__all__ = [
    "BASE_YTDL_OPTS",
    "GuildPlayer",
    "Track",
    "build_filter_string",
    "classify_ytdl_error",
    "extract_info",
    "fetch_metadata",
    "get_ffmpeg_opts",
    "get_ytdl_opts",
    "is_apple_url",
    "is_playable_url",
    "is_soundcloud_url",
    "is_spotify_url",
    "youtube_search_query",
]