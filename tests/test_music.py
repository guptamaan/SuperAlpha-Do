"""Music cog: favorite-current-track support and save-queue-as-playlist."""

from __future__ import annotations

import asyncio
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bot.cogs import music as music_cog
import discord

from bot.cogs.music import Music
from bot.services.music import sources as music_sources
from bot.services.music.models import Track
from bot.services.music.sources import (
    fetch_apple_metadata,
    fetch_spotify_metadata,
    parse_apple_url,
    parse_spotify_url,
    search_query_for,
)

from helpers import USER_IDS, make_ctx, make_guild, make_member


def _track(title: str, requester):
    return Track({"title": title, "url": ""}, requester)


def _favorites_file(member_id: int) -> pathlib.Path:
    return pathlib.Path("data") / f"favorites_{member_id}.txt"


def test_add_favorite_dedups(bot):
    cog = Music(bot)
    user_id = USER_IDS["member"]
    assert cog._add_favorite(user_id, "Never Gonna Give You Up") is True
    assert cog._add_favorite(user_id, "never gonna give you up") is False
    lines = _favorites_file(user_id).read_text().splitlines()
    assert lines.count("Never Gonna Give You Up") == 1


async def test_favorite_current_track(bot):
    cog = Music(bot)
    member = make_member(USER_IDS["member"])
    player = cog._get_player(1001)
    player.current = _track("Fireflies", member)

    ctx = make_ctx(bot, author=member)
    await cog.favorite.callback(cog, ctx)

    embed = ctx.send.await_args.kwargs["embed"]
    assert "Fireflies" in embed.description
    assert "Fireflies" in _favorites_file(USER_IDS["member"]).read_text()


async def test_favorite_duplicate_reports_already(bot):
    cog = Music(bot)
    member = make_member(USER_IDS["member"])
    player = cog._get_player(1001)
    player.current = _track("Fireflies", member)
    cog._add_favorite(USER_IDS["member"], "Fireflies")

    ctx = make_ctx(bot, author=member)
    await cog.favorite.callback(cog, ctx)

    embed = ctx.send.await_args.kwargs["embed"]
    assert "already in your favorites" in embed.description


async def test_favorite_nothing_playing(bot):
    cog = Music(bot)
    ctx = make_ctx(bot)
    await cog.favorite.callback(cog, ctx)
    assert "Nothing is currently playing" in ctx.send.await_args.kwargs["embed"].description


async def test_playlist_save_saves_whole_queue(bot):
    cog = Music(bot)
    requester = make_member(USER_IDS["member"])
    player = cog._get_player(1001)
    player.current = _track("Song One", requester)
    player.queue.append(_track("Song Two", requester))
    player.queue.append(_track("Song Three", requester))

    ctx = make_ctx(bot, author=requester)
    await cog.playlist.callback(cog, ctx, "create", "RoadTrip")
    await cog.playlist.callback(cog, ctx, "save", "RoadTrip")

    embed = ctx.send.await_args.kwargs["embed"]
    assert "Saved **3** track(s) from the queue to **RoadTrip**" in embed.description

    songs = pathlib.Path("data/playlists/RoadTrip.txt").read_text().splitlines()
    assert "Song One" in songs and "Song Two" in songs and "Song Three" in songs


async def test_playlist_save_empty_queue(bot):
    cog = Music(bot)
    ctx = make_ctx(bot)
    await cog.playlist.callback(cog, ctx, "create", "EmptyList")
    await cog.playlist.callback(cog, ctx, "save", "EmptyList")
    assert "Nothing in the queue to save" in ctx.send.await_args.kwargs["embed"].description


# ── queue looping ─────────────────────────────────────────────────────────────
async def test_requeue_finished_modes(bot):
    cog = Music(bot)
    player = cog._get_player(1001)
    member = make_member(USER_IDS["member"])
    player.current = _track("Original", member)

    assert cog._requeue_finished(player) is None
    player.loop = True
    assert cog._requeue_finished(player) == "front"
    player.loop = False
    player.queue_loop = True
    assert cog._requeue_finished(player) == "back"


def test_loop_state_label(bot):
    cog = Music(bot)
    player = cog._get_player(1001)
    assert cog._loop_state(player) == "OFF"
    player.loop = True
    assert cog._loop_state(player) == "ON — single"
    player.queue_loop = True
    assert cog._loop_state(player) == "ON — queue"


async def test_loop_no_arg_toggles_single_track(bot):
    cog = Music(bot)
    ctx = make_ctx(bot)
    player = cog._get_player(1001)
    await cog.loop.callback(cog, ctx)
    assert player.loop is True and player.queue_loop is False
    await cog.loop.callback(cog, ctx)
    assert player.loop is False and player.queue_loop is False


async def test_loop_queue_toggles_and_excludes_single(bot):
    cog = Music(bot)
    ctx = make_ctx(bot)
    player = cog._get_player(1001)
    await cog.loop.callback(cog, ctx, "queue")
    assert player.queue_loop is True and player.loop is False
    assert "enabled (**whole queue**)" in ctx.send.await_args.kwargs["embed"].description

    await cog.loop.callback(cog, ctx, "single")
    assert player.loop is True and player.queue_loop is False

    await cog.loop.callback(cog, ctx, "off")
    assert player.loop is False and player.queue_loop is False


async def test_loop_off_turns_everything_off(bot):
    cog = Music(bot)
    ctx = make_ctx(bot)
    player = cog._get_player(1001)
    player.loop = True
    player.queue_loop = True
    await cog.loop.callback(cog, ctx, "off")
    assert player.loop is False and player.queue_loop is False


async def test_loop_invalid_mode(bot):
    cog = Music(bot)
    ctx = make_ctx(bot)
    player = cog._get_player(1001)
    player.loop = True
    await cog.loop.callback(cog, ctx, "banana")
    eb = ctx.send.await_args.kwargs["embed"]
    assert "Invalid Mode" in eb.author.name
    assert player.loop is True

def test_parse_spotify_link_and_uri():
    track_id = "4cOdK2wGLETKBW3PvgPWqT"
    forms = [
        f"https://open.spotify.com/track/{track_id}",
        f"https://open.spotify.com/track/{track_id}?si=8f2b1c3d4e5f6a7b",
        f"open.spotify.com/track/{track_id}",
        f"spotify:track:{track_id}",
        f"spotify:intl-de:track:{track_id}",
        f"https://open.spotify.com/intl-de/track/{track_id}",
        f"  https://open.spotify.com/track/{track_id}  ",
    ]
    for form in forms:
        assert parse_spotify_url(form) == ("track", track_id), form


def test_parse_spotify_non_track_kinds():
    assert parse_spotify_url("https://open.spotify.com/album/1DFixLWuPkv3KT3TnV35m3")[0] == "album"
    assert parse_spotify_url("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")[0] == "playlist"
    assert parse_spotify_url("spotify:episode:512ojhOuo1ktJprKbVcKyQ")[0] == "episode"


def test_parse_spotify_rejects_non_spotify():
    for junk in (
        "https://open.spotify.com/track/short",
        "https://open.spotify.com/",
        "spotify:track",
        "https://youtube.com/watch?v=4cOdK2wGLETKBW3PvgPWqT",
        "https://notspotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
        "never gonna give you up",
    ):
        assert parse_spotify_url(junk) is None, junk


async def test_spotify_track_is_translated_to_a_youtube_search(bot, monkeypatch):
    """A Spotify link must become `title artist`, never be handed to yt-dlp."""
    cog = Music(bot)
    seen = {}

    async def fake_metadata(spotify_id):
        seen["id"] = spotify_id
        return {"title": "Never Gonna Give You Up", "artist": "Rick Astley"}

    async def fake_extract(query, **kwargs):
        seen["query"] = query
        return {"title": "Never Gonna Give You Up", "url": "https://youtu.be/x", "webpage_url": "https://youtu.be/x"}

    monkeypatch.setattr(music_cog, "fetch_spotify_metadata", fake_metadata)
    monkeypatch.setattr(music_cog, "extract_info", fake_extract)

    track = await cog._fetch_track(
        "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT?si=abc", make_member(USER_IDS["member"])
    )

    assert track is not None
    assert seen["id"] == "4cOdK2wGLETKBW3PvgPWqT"
    assert seen["query"] == "ytsearch1:Rick Astley - Never Gonna Give You Up"
    # the raw Spotify URL must never reach yt-dlp
    assert "spotify" not in seen["query"]


async def test_spotify_album_link_is_rejected_with_a_clear_message(bot, monkeypatch):
    cog = Music(bot)

    async def boom(*args, **kwargs):
        raise AssertionError("yt-dlp must not be called for an album link")

    monkeypatch.setattr(music_cog, "extract_info", boom)

    track = await cog._fetch_track(
        "https://open.spotify.com/album/1DFixLWuPkv3KT3TnV35m3", make_member(USER_IDS["member"])
    )

    assert track is None
    assert "album" in cog._last_fetch_error


async def test_spotify_unresolvable_link_reports_config_hint(bot, monkeypatch):
    cog = Music(bot)

    async def no_metadata(spotify_id):
        return None

    async def boom(*args, **kwargs):
        raise AssertionError("yt-dlp must not be called when metadata is unavailable")

    monkeypatch.setattr(music_cog, "fetch_spotify_metadata", no_metadata)
    monkeypatch.setattr(music_cog, "extract_info", boom)

    track = await cog._fetch_track("spotify:track:4cOdK2wGLETKBW3PvgPWqT", make_member(USER_IDS["member"]))

    assert track is None
    assert "SPOTIPY_CLIENT_ID" in cog._last_fetch_error


async def test_spotify_metadata_works_without_credentials(bot, monkeypatch):
    """No API keys: the embed page still yields both title and artist."""
    monkeypatch.delenv("SPOTIPY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIPY_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(music_sources, "_spotify_token", None)

    info = await fetch_spotify_metadata("4cOdK2wGLETKBW3PvgPWqT")

    assert info == {"title": "Never Gonna Give You Up", "artist": "Rick Astley"}


def test_spotify_access_token_needs_credentials(bot, monkeypatch):
    monkeypatch.delenv("SPOTIPY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIPY_CLIENT_SECRET", raising=False)
    assert asyncio.run(music_sources._spotify_access_token(None)) is None


def test_parse_apple_song_link():
    # ?i= carries the track id; the slashed number is the album
    url = "https://music.apple.com/us/album/never-gonna-give-you-up/1559885420?i=1559885421"
    assert parse_apple_url(url) == ("song", "1559885421")
    # newer /song/ share form
    song = "https://music.apple.com/us/song/never-gonna-give-you-up/1559885421"
    assert parse_apple_url(song) == ("song", "1559885421")
    # scheme-less paste
    assert parse_apple_url("music.apple.com/us/song/x/1559885421") == ("song", "1559885421")


def test_parse_apple_album_and_rejects():
    assert parse_apple_url("https://music.apple.com/us/album/hits/1559885420")[0] == "album"
    assert parse_apple_url("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT") is None
    assert parse_apple_url("https://youtube.com/watch?v=abc") is None
    assert parse_apple_url("a search term") is None


async def test_apple_song_is_translated_to_a_youtube_search(bot, monkeypatch):
    cog = Music(bot)
    seen = {}

    async def fake_metadata(song_id):
        seen["id"] = song_id
        return {"title": "Never Gonna Give You Up", "artist": "Rick Astley"}

    async def fake_extract(query, **kwargs):
        seen["query"] = query
        return {"title": "x", "url": "https://youtu.be/x", "webpage_url": "https://youtu.be/x"}

    monkeypatch.setattr(music_cog, "fetch_apple_metadata", fake_metadata)
    monkeypatch.setattr(music_cog, "extract_info", fake_extract)

    track = await cog._fetch_track(
        "https://music.apple.com/us/album/x/1559885420?i=1559885421",
        make_member(USER_IDS["member"]),
    )

    assert track is not None
    assert seen["id"] == "1559885421"
    assert seen["query"] == "ytsearch1:Rick Astley - Never Gonna Give You Up"


async def test_apple_album_link_is_rejected(bot, monkeypatch):
    cog = Music(bot)

    async def boom(*args, **kwargs):
        raise AssertionError("yt-dlp must not be called for an album link")

    monkeypatch.setattr(music_cog, "extract_info", boom)

    track = await cog._fetch_track(
        "https://music.apple.com/us/album/hits/1559885420", make_member(USER_IDS["member"])
    )

    assert track is None
    assert "album" in cog._last_fetch_error


async def test_unparseable_streaming_link_never_reaches_ytdlp(bot, monkeypatch):
    cog = Music(bot)

    async def boom(*args, **kwargs):
        raise AssertionError("yt-dlp must not be called for a broken streaming link")

    monkeypatch.setattr(music_cog, "extract_info", boom)

    track = await cog._fetch_track(
        "https://open.spotify.com/playlist/not-a-real-id", make_member(USER_IDS["member"])
    )

    assert track is None
    assert cog._last_fetch_error


async def test_apple_metadata_live_lookup(bot):
    """iTunes lookup needs no credentials and returns title + artist."""
    info = await fetch_apple_metadata("1559885421")
    assert info == {"title": "Never Gonna Give You Up", "artist": "Rick Astley"}


def test_metadata_from_embed_html_parses_entity():
    html = (
        '<html><head><script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"state":{"data":{"entity":{"name":"Blinding Lights",'
        '"artists":[{"name":"The Weeknd"}]}}}}}}</script></head></html>'
    )
    assert music_sources._metadata_from_embed_html(html) == {
        "title": "Blinding Lights",
        "artist": "The Weeknd",
    }


def test_metadata_from_embed_html_joins_multiple_artists():
    html = (
        '<script id="__NEXT_DATA__">{"props":{"pageProps":{"state":{"data":{"entity":'
        '{"name":"Song","artists":[{"name":"A"},{"name":"B"}]}}}}}}</script>'
    )
    assert music_sources._metadata_from_embed_html(html)["artist"] == "A, B"


def test_metadata_from_embed_html_is_resilient():
    assert music_sources._metadata_from_embed_html("<html>no json here</html>") is None
    assert music_sources._metadata_from_embed_html(
        '<script id="__NEXT_DATA__">{ not json }</script>'
    ) is None
    assert music_sources._metadata_from_embed_html(
        '<script id="__NEXT_DATA__">{"props":{}}</script>'
    ) is None


def test_search_query_prefers_artist_title():
    assert search_query_for("Hello", "Adele") == "Adele - Hello"
    assert search_query_for("Hello", "") == "Hello"
    assert search_query_for("", "Adele") == ""
    assert search_query_for(" Hello ", " Adele ") == "Adele - Hello"


def _voice_chat_channel():
    """A voice channel's text chat, as discord.py represents it."""
    from unittest.mock import MagicMock

    return MagicMock(spec=discord.VoiceChannel)


def test_status_channel_accepts_voice_channel_chat(bot):
    """Commands run in a voice channel's chat must still get status messages."""
    cog = Music(bot)
    player = cog._get_player(1001)
    chat = _voice_chat_channel()

    cog._remember_text_channel(player, SimpleNamespace(channel=chat))

    assert player.text_channel is chat


def test_status_channel_accepts_text_channel(bot):
    cog = Music(bot)
    player = cog._get_player(1001)
    text = MagicMock(spec=discord.TextChannel)

    cog._remember_text_channel(player, SimpleNamespace(channel=text))

    assert player.text_channel is text


def test_status_channel_ignores_unusable_channel(bot):
    cog = Music(bot)
    player = cog._get_player(1001)

    cog._remember_text_channel(player, SimpleNamespace(channel=object()))

    assert player.text_channel is None


def _queued_player(cog, guild, member, count: int):
    player = cog._get_player(guild.id)
    for i in range(count):
        player.queue.append(_track(f"song {i}", member))
    voice_client = MagicMock()
    voice_client.channel = MagicMock()
    guild.voice_client = voice_client
    return player, voice_client


async def test_failed_status_update_does_not_clear_the_queue(bot, monkeypatch):
    """A cosmetic failure must never destroy the queue.

    The now-playing send and presence update used to share one
    try/except that cleared the queue, so a blocked channel or a failed presence
    update silently wiped everything.
    """
    import discord as discord_mod

    monkeypatch.setattr(discord_mod, "FFmpegOpusAudio", MagicMock())

    cog = Music(bot)
    monkeypatch.setattr(cog, "_refresh_stream_url", AsyncMock())
    member = make_member(USER_IDS["member"])
    guild = make_guild()
    bot.get_guild = MagicMock(return_value=guild)
    player, voice_client = _queued_player(cog, guild, member, 3)

    # every cosmetic step fails, as it would with no permissions
    async def boom(*args, **kwargs):
        raise RuntimeError("Missing Permissions")

    monkeypatch.setattr(cog, "_update_presence", boom)
    player.text_channel = MagicMock(spec=discord.VoiceChannel)
    player.text_channel.send = AsyncMock(side_effect=boom)

    await cog._play_next_impl(guild.id)

    voice_client.play.assert_called_once()
    assert player.current is not None  # playback started
    assert len(player.queue) == 2  # one popped, the rest survived


async def test_failed_presence_alone_keeps_the_queue(bot, monkeypatch):
    import discord as discord_mod

    monkeypatch.setattr(discord_mod, "FFmpegOpusAudio", MagicMock())

    cog = Music(bot)
    monkeypatch.setattr(cog, "_refresh_stream_url", AsyncMock())
    member = make_member(USER_IDS["member"])
    guild = make_guild()
    bot.get_guild = MagicMock(return_value=guild)
    player, _ = _queued_player(cog, guild, member, 2)

    async def boom(*args, **kwargs):
        raise RuntimeError("cannot edit channel status")

    monkeypatch.setattr(cog, "_update_presence", boom)
    player.text_channel = None

    await cog._play_next_impl(guild.id)

    assert len(player.queue) == 1


async def test_notify_swallows_send_failures(bot):
    cog = Music(bot)
    player = cog._get_player(1001)
    player.text_channel = MagicMock(spec=discord.VoiceChannel)
    player.text_channel.send = AsyncMock(side_effect=RuntimeError("Missing Permissions"))

    # must not raise
    await cog._notify(player, discord.Embed(title="now playing"))


async def test_notify_without_channel_is_a_noop(bot):
    cog = Music(bot)
    player = cog._get_player(1001)

    await cog._notify(player, discord.Embed(title="now playing"))
