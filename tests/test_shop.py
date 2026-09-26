"""Shop commands: listing, admin add/remove, buy flows, role ownership."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock

import bot.cogs.xp as xp
from bot.cogs.shop import Shop

from helpers import (
    GUILD_ID,
    TEXT_CHANNEL_ID,
    USER_IDS,
    make_channel,
    make_ctx,
    make_guild,
    make_member,
    make_permissions,
    make_role,
)


def magic_role(role):
    return MagicMock(return_value=role)


async def test_shop_list_empty(bot):
    cog = Shop(bot)
    ctx = make_ctx(bot)
    await cog.shop.callback(cog, ctx)
    embed = ctx.send.await_args.kwargs["embed"]
    assert embed.author.name == "🛒 Server Shop"
    assert "No items yet" in embed.description


async def test_shop_list_shows_items(bot):
    cog = Shop(bot)
    cog._save_items(GUILD_ID, [{"id": 1, "name": "Cool Hat", "price": 50, "description": "A hat"}])
    ctx = make_ctx(bot)
    await cog.shop.callback(cog, ctx, "list", rest=None)
    embed = ctx.send.await_args.kwargs["embed"]
    assert "Cool Hat" in embed.description
    assert "50 SP" in embed.description


async def test_shop_add_requires_admin(bot):
    cog = Shop(bot)
    guild = make_guild()
    member = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=member, guild=guild)
    await cog.shop.callback(cog, ctx, "add", rest="50 Cool Hat")
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Permission Denied"
    assert cog._load_items(GUILD_ID) == []


async def test_shop_add_persists_item(bot, tmp_path):
    cog = Shop(bot)
    guild = make_guild()
    admin = make_member(USER_IDS["admin"], guild=guild, permissions=make_permissions(administrator=True))
    ctx = make_ctx(bot, author=admin, guild=guild)
    await cog.shop.callback(cog, ctx, "add", rest="50 Cool Hat")

    assert ctx.send.await_args.kwargs["embed"].author.name == "✅ Item Added"
    items = cog._load_items(GUILD_ID)
    assert items[0]["name"] == "Cool Hat"
    assert items[0]["price"] == 50
    assert items[0]["id"] == 1

    saved = json.load(open(os.path.join(tmp_path, "shop", "items.json")))
    assert str(GUILD_ID) in saved


async def test_shop_add_invalid_price(bot):
    cog = Shop(bot)
    guild = make_guild()
    admin = make_member(USER_IDS["admin"], guild=guild, permissions=make_permissions(administrator=True))
    ctx = make_ctx(bot, author=admin, guild=guild)
    await cog.shop.callback(cog, ctx, "add", rest="abc free")
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Invalid Args"


async def test_shop_buy_unknown_item(bot):
    cog = Shop(bot)
    cog._save_items(GUILD_ID, [{"id": 1, "name": "Hat", "price": 50, "description": ""}])
    ctx = make_ctx(bot)
    await cog.shop.callback(cog, ctx, "buy", rest="99")
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Not Found"


async def test_shop_buy_insufficient_funds(bot):
    cog = Shop(bot)
    cog._save_items(GUILD_ID, [{"id": 1, "name": "Hat", "price": 5000, "description": ""}])
    data = xp.load_user(USER_IDS["member"])
    data["sp"] = 10
    xp.save_user(USER_IDS["member"], data)
    ctx = make_ctx(bot)
    await cog.shop.callback(cog, ctx, "buy", rest="1")
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Insufficient SP"


async def test_shop_buy_creates_role_and_deducts(bot):
    cog = Shop(bot)
    cog._save_items(GUILD_ID, [{"id": 1, "name": "Cool Hat", "price": 50, "description": ""}])
    data = xp.load_user(USER_IDS["member"])
    data["sp"] = 100
    xp.save_user(USER_IDS["member"], data)

    guild = make_guild()
    role = make_role(777, name="⭐ User7004")
    guild.create_role = AsyncMock(return_value=role)
    author = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=author, guild=guild)

    await cog.shop.callback(cog, ctx, "buy", rest="1")

    guild.create_role.assert_awaited_once()
    author.add_roles.assert_awaited_once_with(role, reason="Shop purchase")
    assert xp.load_user(author.id)["sp"] == 50
    roles = cog._load_roles(GUILD_ID)
    assert roles[str(author.id)] == 777
    assert ctx.send.await_args.kwargs["embed"].author.name == "🛍️ Purchase Complete!"


async def test_shop_buy_twice_denied(bot):
    cog = Shop(bot)
    cog._save_items(GUILD_ID, [{"id": 1, "name": "Hat", "price": 50, "description": ""}])
    data = xp.load_user(USER_IDS["member"])
    data["sp"] = 500
    xp.save_user(USER_IDS["member"], data)
    cog._save_roles(GUILD_ID, {str(USER_IDS["member"]): 777})

    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.shop.callback(cog, ctx, "buy", rest="1")
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Already Owned"


async def test_shop_buy_missing_manage_roles(bot):
    cog = Shop(bot)
    cog._save_items(GUILD_ID, [{"id": 1, "name": "Hat", "price": 50, "description": ""}])
    data = xp.load_user(USER_IDS["member"])
    data["sp"] = 500
    xp.save_user(USER_IDS["member"], data)

    guild = make_guild(permissions_for_me=make_permissions(send_messages=True))  # no manage_roles
    author = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.shop.callback(cog, ctx, "buy", rest="1")
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Missing Permission"


async def test_shop_remove_requires_admin(bot):
    cog = Shop(bot)
    cog._save_items(GUILD_ID, [{"id": 1, "name": "Hat", "price": 50, "description": ""}])
    guild = make_guild()
    member = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=member, guild=guild)
    await cog.shop.callback(cog, ctx, "remove", rest="1")
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Permission Denied"


async def test_shop_remove_deletes_item(bot):
    cog = Shop(bot)
    cog._save_items(GUILD_ID, [{"id": 1, "name": "Hat", "price": 50, "description": ""}])
    guild = make_guild()
    admin = make_member(USER_IDS["admin"], guild=guild, permissions=make_permissions(administrator=True))
    ctx = make_ctx(bot, author=admin, guild=guild)
    await cog.shop.callback(cog, ctx, "remove", rest="1")
    assert ctx.send.await_args.kwargs["embed"].author.name == "🗑️ Item Removed"
    assert cog._load_items(GUILD_ID) == []


async def test_shop_rename_no_role(bot):
    cog = Shop(bot)
    guild = make_guild()
    author = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.shop.callback(cog, ctx, "rename", rest="Pixel Hat")
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ No Custom Role"


async def test_shop_rename_edits_role(bot):
    cog = Shop(bot)
    guild = make_guild()
    role = make_role(777, name="⭐ old")
    role.edit = AsyncMock()
    guild.get_role = magic_role(role)
    cog._save_roles(GUILD_ID, {str(USER_IDS["member"]): 777})
    author = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.shop.callback(cog, ctx, "rename", rest="Pixel Hat")
    role.edit.assert_awaited_once_with(name="Pixel Hat", reason="Shop rename")
    assert ctx.send.await_args.kwargs["embed"].author.name == "✅ Role Renamed"


async def test_shop_color_invalid_hex(bot):
    cog = Shop(bot)
    guild = make_guild()
    role = make_role(777, name="⭐ old")
    role.edit = AsyncMock()
    guild.get_role = magic_role(role)
    cog._save_roles(GUILD_ID, {str(USER_IDS["member"]): 777})
    author = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.shop.callback(cog, ctx, "color", rest="ff55")
    assert ctx.send.await_args.kwargs["embed"].author.name == "❌ Invalid Color"


async def test_shop_color_sets_colour(bot):
    cog = Shop(bot)
    guild = make_guild()
    role = make_role(777, name="⭐ old")
    role.edit = AsyncMock()
    guild.get_role = magic_role(role)
    cog._save_roles(GUILD_ID, {str(USER_IDS["member"]): 777})
    author = make_member(USER_IDS["member"], guild=guild)
    ctx = make_ctx(bot, author=author, guild=guild)
    await cog.shop.callback(cog, ctx, "color", rest="#ff55aa")
    role.edit.assert_awaited_once()
    assert ctx.send.await_args.kwargs["embed"].author.name == "🎨 Role Colored"