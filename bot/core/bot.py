"""Bot construction: prefix resolver and the concrete ``commands.Bot``.

Kept separate from ``main.py`` so tests and tooling can build a bot without
running the entry point.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.config.settings import DEFAULT_PREFIXES, SUPER_USERS, build_intents


def get_prefix(bot: commands.Bot, message: discord.Message) -> list[str]:
    content = message.content
    for p in DEFAULT_PREFIXES:
        if content.startswith(p):
            return [p, f"<@{bot.user.id}> ", f"<@!{bot.user.id}> "]
    return [f"<@{bot.user.id}> ", f"<@!{bot.user.id}> "]


def make_bot() -> commands.Bot:
    return commands.Bot(
        command_prefix=get_prefix,
        intents=build_intents(),
        help_command=None,
        case_insensitive=True,
        owner_ids=SUPER_USERS,
    )