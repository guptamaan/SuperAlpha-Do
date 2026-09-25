"""Shared test helpers: factories for mock Discord objects and storage isolation.

Everything in this module is importable from tests. Modules under tests/ that
need real storage (SQLite/JSON) should request the ``db_env`` fixture, which
points every persistence path at a throwaway tmp directory.
"""

from __future__ import annotations

import pathlib
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

GUILD_ID = 1001
TEXT_CHANNEL_ID = 2001
VOICE_CHANNEL_ID = 3001
BOT_USER_ID = 12345

USER_IDS = {
    "owner": 7001,  # bot owner
    "admin": 7002,
    "guild_owner": 7003,
    "member": 7004,
}


# ── Permission helpers ────────────────────────────────────────────────────────
def make_permissions(**flags: bool) -> discord.Permissions:
    """Build a real ``discord.Permissions`` with the given flags enabled."""
    perms = discord.Permissions()
    for name, value in flags.items():
        if hasattr(perms, name):
            setattr(perms, name, bool(value))
    return perms


# ── Discord-like factories (MagicMock based) ──────────────────────────────────
def make_member(
    user_id: int,
    *,
    name: str | None = None,
    guild=None,
    permissions: discord.Permissions | None = None,
    voice_channel=None,
    bot: bool = False,
) -> MagicMock:
    member = MagicMock()
    member.id = user_id
    member.name = name or f"User{user_id}"
    member.display_name = name or f"User{user_id}"
    member.mention = f"<@{user_id}>"
    member.bot = bot
    member.guild = guild
    member.guild_permissions = permissions if permissions is not None else make_permissions()
    member.display_avatar = SimpleNamespace(url=f"https://cdn.example/{user_id}.png")
    member.voice = None if voice_channel is None else SimpleNamespace(channel=voice_channel)
    member.add_roles = AsyncMock()
    member.move_to = AsyncMock()
    return member


def make_role(role_id: int, *, name: str = "role", colour: int | None = None) -> MagicMock:
    role = MagicMock()
    role.id = role_id
    role.name = name
    role.mention = f"<@&{role_id}>"
    role.colour = discord.Colour(colour or 0)
    return role


def make_channel(
    channel_id: int = TEXT_CHANNEL_ID,
    *,
    guild=None,
    name: str = "general",
    nsfw: bool = False,
    permissions_for_me: discord.Permissions | None = None,
) -> MagicMock:
    channel = MagicMock()
    channel.id = channel_id
    channel.name = name
    channel.mention = f"<#{channel_id}>"
    channel.guild = guild
    channel.is_nsfw = MagicMock(return_value=nsfw)

    def perms_for(target):
        if target is not None and getattr(target, "id", None) == BOT_USER_ID and permissions_for_me is not None:
            return permissions_for_me
        return make_permissions(send_messages=True, attach_files=True, manage_roles=True)

    channel.permissions_for = MagicMock(side_effect=perms_for)
    channel.send = AsyncMock()
    channel.fetch_message = AsyncMock()
    channel.edit = AsyncMock()
    channel.set_permissions = AsyncMock()
    return channel


def make_text_channel(
    channel_id: int = TEXT_CHANNEL_ID,
    *,
    guild=None,
    name: str = "general",
) -> discord.TextChannel:
    """A *real* discord.TextChannel (passes isinstance) with Mock send/fetch."""
    guild_ref = SimpleNamespace(id=getattr(guild, "id", None), name=name)
    data = {
        "id": channel_id,
        "name": name,
        "type": 0,
        "position": 0,
        "nsfw": False,
        "topic": None,
        "category_id": None,
        "parent_id": None,
        "permissions": 0,
    }
    channel = discord.TextChannel(state=MagicMock(), guild=guild_ref, data=data)
    return channel


def make_real_message(
    content: str = "",
    *,
    channel=None,
    author=None,
    message_id: int = 1,
    attachments=None,
    embeds=None,
) -> discord.Message:
    """A *real* discord.Message (passes isinstance) with mocked io methods."""
    state = MagicMock()
    channel_ref = channel if channel is not None else SimpleNamespace(id=TEXT_CHANNEL_ID)
    data = {
        "id": message_id,
        "channel_id": getattr(channel_ref, "id", TEXT_CHANNEL_ID),
        "content": content,
        "attachments": [],
        "embeds": [],
        "reactions": [],
        "pinned": False,
        "type": 0,
        "tts": False,
        "mention_everyone": False,
        "timestamp": "2020-01-01T00:00:00+00:00",
        "edited_timestamp": None,
        "flags": 0,
        "components": [],
        "sticker_items": [],
        "referenced_message": None,
    }
    msg = discord.Message(state=state, channel=channel_ref, data=data)
    if author is not None:
        msg.author = author
    if attachments is not None:
        msg.attachments = list(attachments)
    if embeds is not None:
        msg.embeds = list(embeds)
    return msg


def make_guild(
    *,
    guild_id: int = GUILD_ID,
    owner_id: int = USER_IDS["guild_owner"],
    channels=None,
    members=None,
    permissions_for_me=None,
) -> MagicMock:
    guild = MagicMock()
    guild.id = guild_id
    guild.name = "Test Server"
    guild.owner_id = owner_id
    channels = list(channels) if channels is not None else []
    members = list(members) if members is not None else []

    guild.text_channels = channels
    guild.channels = channels
    guild.members = members
    guild.default_role = make_role(guild_id * 10, name="everyone")

    me = make_member(BOT_USER_ID, name="Alpha", guild=guild)
    me.guild_permissions = permissions_for_me if permissions_for_me is not None else make_permissions(
        send_messages=True, attach_files=True, manage_roles=True, manage_channels=True,
        manage_expressions=True,
    )
    guild.me = me

    def get_channel(cid):
        for c in channels:
            if c.id == cid:
                return c
        return None

    def get_member(mid):
        for m in members:
            if m.id == mid:
                return m
        return None

    guild.get_channel = MagicMock(side_effect=get_channel)
    guild.get_member = MagicMock(side_effect=get_member)
    guild.create_role = AsyncMock()
    return guild


def make_reaction(emoji: str, users) -> MagicMock:
    reaction = MagicMock()
    reaction.emoji = emoji
    reaction.users = AsyncMock(return_value=users)
    return reaction


def make_message(
    content: str = "",
    *,
    author=None,
    channel=None,
    guild=None,
    message_id: int = 1,
    reactions=None,
    embeds=None,
) -> MagicMock:
    msg = MagicMock()
    msg.id = message_id
    msg.content = content
    msg.author = author
    msg.channel = channel
    msg.guild = guild
    msg.embeds = list(embeds) if embeds else []
    msg.reactions = list(reactions) if reactions else []
    msg.edit = AsyncMock()
    msg.delete = AsyncMock()
    msg.add_reaction = AsyncMock()
    return msg


def make_ctx(
    bot,
    *,
    author=None,
    guild=None,
    channel=None,
    message=None,
    command=None,
):
    if guild is None:
        guild = make_guild()
    if channel is None:
        channel = make_channel(TEXT_CHANNEL_ID, guild=guild)
    if author is None:
        author = make_member(USER_IDS["member"], guild=guild)
    if message is None:
        message = make_message("", author=author, channel=channel, guild=guild)

    ctx = SimpleNamespace(
        bot=bot,
        author=author,
        guild=guild,
        channel=channel,
        message=message,
        prefix="alpha ",
        command=command,
        invoked_with=None,
        cog=None,
        permissions=author.guild_permissions,
        send=AsyncMock(side_effect=_sent_message),
    )
    return ctx


def _sent_message(*_args, **_kwargs):
    msg = MagicMock()
    msg.id = 9001
    msg.edit = AsyncMock()
    msg.delete = AsyncMock()
    return msg


def sent_embed(ctx) -> discord.Embed | None:
    """Return the embed passed to the last ``ctx.send`` call (if any)."""
    if not ctx.send.call_args_list:
        return None
    return ctx.send.call_args_list[-1].kwargs.get("embed")


# ── Storage isolation ─────────────────────────────────────────────────────────
def isolate_storage(tmp_path: pathlib.Path) -> None:
    """Point every persistence path at *tmp_path* (used by the db_env fixture)."""
    import cogs.distro as distro_mod
    import cogs.giveaways as giveaways_mod
    import cogs.linux as linux_mod
    import cogs.shop as shop_mod
    import cogs.spam as spam_mod
    import cogs.xp as xp_mod

    # SQLite-backed modules: close cached connections and point them at tmp.
    xp_mod.DATABASE_FILE = str(tmp_path / "xp.db")
    xp_mod.DATA_DIR = str(tmp_path / "xp")
    xp_mod.CONFIG_FILE = str(tmp_path / "xp" / "config.json")
    xp_mod._db_conn = None
    xp_mod._user_cache = {}
    xp_mod._dirty_users = set()
    xp_mod._config_cache = None
    xp_mod._config_cache_loaded = 0.0

    spam_mod.DATABASE_FILE = str(tmp_path / "spam.db")
    spam_mod.DATA_DIR = str(tmp_path / "spam")
    spam_mod.CONFIG_FILE = str(tmp_path / "spam" / "spam.json")
    spam_mod._db_conn = None

    shop_mod.DATA_DIR = str(tmp_path / "shop")
    shop_mod.ITEMS_FILE = str(tmp_path / "shop" / "items.json")
    shop_mod.ROLES_FILE = str(tmp_path / "shop" / "custom_roles.json")

    giveaways_mod.DATA_DIR = str(tmp_path / "giveaways")
    giveaways_mod.DATA_FILE = str(tmp_path / "giveaways" / "giveaways.json")

    distro_mod.DISTRO_DIR = REPO_ROOT / "distro"
    distro_mod.METADATA_FILE = distro_mod.DISTRO_DIR / "names.json"
    distro_mod.ENABLED_FILE = tmp_path / "distro" / "enabled.json"
    distro_mod.STATS_FILE = tmp_path / "distro" / "stats.json"

    linux_mod.MODE_FILE = tmp_path / "linux_mode.json"
    linux_mod.MODE_DIR = tmp_path

    for path in (xp_mod.DATA_DIR, spam_mod.DATA_DIR, shop_mod.DATA_DIR, giveaways_mod.DATA_DIR):
        pathlib.Path(path).mkdir(parents=True, exist_ok=True)

    xp_mod.init_db()
    spam_mod._init_db()


def copy_distro_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Copy the real distro/ images into tmp_path for hermetic tests."""
    target = tmp_path / "distro"
    if target.exists():
        shutil.copytree(REPO_ROOT / "distro", target, dirs_exist_ok=True)
    else:
        shutil.copytree(REPO_ROOT / "distro", target)
    return target