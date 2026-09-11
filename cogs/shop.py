"""
cogs/shop.py — Economy shop.
Spend SP (from the XP system) on items. The primary item type is a
per-user custom role with user-managed name and color.
Data stored in data/shop/items.json and data/shop/custom_roles.json.
Commands: shop, shop add, shop remove, shop buy, shop rename, shop color
"""

import json
import os

import discord
from discord.ext import commands

from cogs.checks import perms_or_developer
from cogs.xp import load_user, save_user

DATA_DIR = "data/shop"
ITEMS_FILE = os.path.join(DATA_DIR, "items.json")
ROLES_FILE = os.path.join(DATA_DIR, "custom_roles.json")

ROLE_PREFIX = "⭐"


def _load_json(path: str) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _next_item_id(items: list[dict]) -> int:
    return max((item.get("id", 0) for item in items), default=0) + 1


class Shop(commands.Cog, name="shop"):
    """SP economy shop."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title, icon_url=None)
        if description:
            embed.description = description
        return embed

    def _load_items(self, guild_id: int) -> list[dict]:
        items = _load_json(ITEMS_FILE)
        return items.get(str(guild_id)) or []

    def _save_items(self, guild_id: int, items: list[dict]) -> None:
        data = _load_json(ITEMS_FILE)
        data[str(guild_id)] = items
        _save_json(ITEMS_FILE, data)

    def _load_roles(self, guild_id: int) -> dict:
        roles = _load_json(ROLES_FILE)
        return roles.get(str(guild_id)) or {}

    def _save_roles(self, guild_id: int, roles: dict) -> None:
        data = _load_json(ROLES_FILE)
        data[str(guild_id)] = roles
        _save_json(ROLES_FILE, data)

    def _get_balance(self, user_id: int) -> int:
        return load_user(user_id)["sp"]

    def _add_balance(self, user_id: int, amount: int) -> None:
        data = load_user(user_id)
        data["sp"] += amount
        save_user(user_id, data)

    @commands.command(name="shop", aliases=["store"])
    async def shop(self, ctx: commands.Context, action: str = None, *, rest: str = None) -> None:
        """Browse and buy from the shop. Usage: alpha shop [list|buy|add|remove|rename|color]"""
        if not action:
            await self._shop_list(ctx)
            return

        action = action.lower()

        if action in ["list", "items", "view", "ls"]:
            await self._shop_list(ctx)
        elif action in ["buy", "purchase", "get"]:
            await self._buy(ctx, rest)
        elif action in ["add", "new", "create"]:
            await self._add(ctx, rest)
        elif action in ["remove", "rm", "delete", "del"]:
            await self._remove(ctx, rest)
        elif action in ["rename", "name", "renamemy"]:
            await self._rename(ctx, rest)
        elif action in ["color", "colour", "recolor"]:
            await self._color(ctx, rest)
        else:
            embed = self._make_embed(
                "❌ Invalid Action", 0xE74C3C,
                "Usage: `alpha shop` · `alpha shop buy <id>`\n"
                "Admin: `alpha shop add <price> <name>` · `alpha shop remove <id>`\n"
                "Owned role: `alpha shop rename <name>` · `alpha shop color <#hex>`",
            )
            await ctx.send(embed=embed)

    async def _shop_list(self, ctx: commands.Context) -> None:
        items = self._load_items(ctx.guild.id)
        embed = discord.Embed(color=0xF1C40F)
        embed.set_author(name="🛒 Server Shop")
        embed.set_footer(text=f"Your balance: {self._get_balance(ctx.author.id):,} SP")

        if not items:
            embed.description = "No items yet. Admins can add items with `alpha shop add <price> <name>`."
            await ctx.send(embed=embed)
            return

        lines = []
        for item in items:
            price = item["price"]
            name = item["name"]
            lines.append(f"`{item['id']}.` **{name}** — {price:,} SP\n  └ *{item.get('description', '')}*")
        embed.description = "\n".join(lines)
        embed.add_field(name="Buy", value="Use `alpha shop buy <id>` to purchase.", inline=False)
        await ctx.send(embed=embed)

    async def _add(self, ctx: commands.Context, rest: str | None) -> None:
        if not ctx.author.guild_permissions.administrator and not await self.bot.is_owner(ctx.author):
            embed = self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission.")
            await ctx.send(embed=embed)
            return
        if not rest:
            embed = self._make_embed("❌ Missing Args", 0xE74C3C, "Usage: `alpha shop add <price> <item name>`")
            await ctx.send(embed=embed)
            return

        parts = rest.split(maxsplit=1)
        if len(parts) < 2 or not parts[0].isdigit():
            embed = self._make_embed("❌ Invalid Args", 0xE74C3C, "Usage: `alpha shop add <price> <item name>`")
            await ctx.send(embed=embed)
            return

        price = int(parts[0])
        name = parts[1].strip()[:60]
        if price <= 0:
            embed = self._make_embed("❌ Invalid Price", 0xE74C3C, "Price must be a positive number.")
            await ctx.send(embed=embed)
            return

        items = self._load_items(ctx.guild.id)
        items.append({
            "id": _next_item_id(items),
            "name": name,
            "price": price,
            "description": "Grants a custom role you can rename and recolor.",
        })
        self._save_items(ctx.guild.id, items)

        embed = self._make_embed("✅ Item Added", 0x2ECC71, f"**{name}** added for **{price:,} SP**.")
        await ctx.send(embed=embed)

    async def _remove(self, ctx: commands.Context, rest: str | None) -> None:
        if not ctx.author.guild_permissions.administrator and not await self.bot.is_owner(ctx.author):
            embed = self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Administrator** permission.")
            await ctx.send(embed=embed)
            return
        if not rest or not rest.strip().isdigit():
            embed = self._make_embed("❌ Missing ID", 0xE74C3C, "Usage: `alpha shop remove <id>`")
            await ctx.send(embed=embed)
            return

        item_id = int(rest.strip())
        items = self._load_items(ctx.guild.id)
        item = next((i for i in items if i["id"] == item_id), None)
        if not item:
            embed = self._make_embed("❌ Not Found", 0xE74C3C, f"No item with id **{item_id}**.")
            await ctx.send(embed=embed)
            return

        items.remove(item)
        self._save_items(ctx.guild.id, items)
        embed = self._make_embed("🗑️ Item Removed", 0x95A5A6, f"Removed **{item['name']}** from the shop.")
        await ctx.send(embed=embed)

    async def _buy(self, ctx: commands.Context, rest: str | None) -> None:
        if not rest or not rest.strip().isdigit():
            embed = self._make_embed("❌ Missing ID", 0xE74C3C, "Usage: `alpha shop buy <id>`")
            await ctx.send(embed=embed)
            return

        item_id = int(rest.strip())
        items = self._load_items(ctx.guild.id)
        item = next((i for i in items if i["id"] == item_id), None)
        if not item:
            embed = self._make_embed("❌ Not Found", 0xE74C3C, f"No item with id **{item_id}**.")
            await ctx.send(embed=embed)
            return

        roles = self._load_roles(ctx.guild.id)
        if str(ctx.author.id) in roles:
            embed = self._make_embed("❌ Already Owned", 0xE74C3C, "You already own a custom role from the shop.")
            await ctx.send(embed=embed)
            return

        balance = self._get_balance(ctx.author.id)
        if balance < item["price"]:
            embed = self._make_embed(
                "❌ Insufficient SP", 0xE74C3C,
                f"**{item['name']}** costs {item['price']:,} SP but you have {balance:,} SP.",
            )
            await ctx.send(embed=embed)
            return

        if not ctx.guild.me.guild_permissions.manage_roles:
            embed = self._make_embed(
                "❌ Missing Permission", 0xE74C3C,
                "I need the **Manage Roles** permission to create your role.",
            )
            await ctx.send(embed=embed)
            return

        role_name = f"{ROLE_PREFIX} {ctx.author.display_name}"[:50]
        try:
            role = await ctx.guild.create_role(
                name=role_name,
                colour=discord.Colour(0x5865F2),
                reason=f"Shop purchase by {ctx.author}",
            )
            await ctx.author.add_roles(role, reason="Shop purchase")
        except Exception:
            embed = self._make_embed(
                "❌ Purchase Failed", 0xE74C3C,
                "I couldn't create your role. My top role may be too low in the hierarchy.",
            )
            await ctx.send(embed=embed)
            return

        self._add_balance(ctx.author.id, -item["price"])
        roles[str(ctx.author.id)] = role.id
        self._save_roles(ctx.guild.id, roles)

        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name="🛍️ Purchase Complete!")
        embed.description = f"You bought **{item['name']}** for **{item['price']:,} SP**."
        embed.add_field(name="Your Role", value=role.mention, inline=True)
        embed.add_field(
            name="Customize",
            value="`alpha shop rename <name>` · `alpha shop color <#hex>`",
            inline=False,
        )
        await ctx.send(embed=embed)

    async def _get_owned_role(self, ctx: commands.Context):
        roles = self._load_roles(ctx.guild.id)
        role_id = roles.get(str(ctx.author.id))
        if not role_id:
            embed = self._make_embed("❌ No Custom Role", 0xE74C3C, "You don't own a shop role yet. Use `alpha shop buy <id>`.")
            await ctx.send(embed=embed)
            return None
        role = ctx.guild.get_role(role_id)
        if role is None:
            embed = self._make_embed("❌ Role Missing", 0xE74C3C, "Your custom role no longer exists on this server.")
            await ctx.send(embed=embed)
            return None
        return role

    async def _rename(self, ctx: commands.Context, rest: str | None) -> None:
        role = await self._get_owned_role(ctx)
        if role is None:
            return
        if not rest:
            embed = self._make_embed("❌ Missing Name", 0xE74C3C, "Usage: `alpha shop rename <new name>`")
            await ctx.send(embed=embed)
            return
        new_name = rest.strip()[:50]
        try:
            await role.edit(name=new_name, reason="Shop rename")
        except Exception:
            embed = self._make_embed("❌ Rename Failed", 0xE74C3C, "I couldn't rename your role.")
            await ctx.send(embed=embed)
            return
        embed = self._make_embed("✅ Role Renamed", 0x2ECC71, f"Your role is now **{new_name}**.")
        await ctx.send(embed=embed)

    async def _color(self, ctx: commands.Context, rest: str | None) -> None:
        role = await self._get_owned_role(ctx)
        if role is None:
            return
        if not rest:
            embed = self._make_embed("❌ Missing Color", 0xE74C3C, "Usage: `alpha shop color <#hex>` (e.g. `#ff55aa`).")
            await ctx.send(embed=embed)
            return
        raw = rest.strip().lstrip("#")
        if len(raw) != 6:
            embed = self._make_embed("❌ Invalid Color", 0xE74C3C, "Use a 6-digit hex like `#ff55aa`.")
            await ctx.send(embed=embed)
            return
        try:
            value = int(raw, 16)
        except ValueError:
            embed = self._make_embed("❌ Invalid Color", 0xE74C3C, "Use a 6-digit hex like `#ff55aa`.")
            await ctx.send(embed=embed)
            return
        try:
            await role.edit(colour=discord.Colour(value), reason="Shop recolor")
        except Exception:
            embed = self._make_embed("❌ Color Failed", 0xE74C3C, "I couldn't recolor your role.")
            await ctx.send(embed=embed)
            return
        embed = self._make_embed("🎨 Role Colored", 0x2ECC71, f"Your role is now **#{raw.upper()}**.")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shop(bot))