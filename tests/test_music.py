"""Music cog: favorite-current-track support and save-queue-as-playlist."""

from __future__ import annotations

import pathlib

from bot.cogs.music import Music
from bot.services.music.models import Track

from helpers import USER_IDS, make_ctx, make_member


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