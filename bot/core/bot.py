"""Bot construction: prefix handling and the concrete ``commands.Bot``.

Kept separate from ``main.py`` so tests and tooling can build a bot without
running the entry point.
"""

from __future__ import annotations

from discord.ext import commands

from bot.config.settings import DEFAULT_PREFIXES, SUPER_USERS, build_intents


def get_prefix(ctx: commands.Context) -> str:
    """The prefix used to invoke this command, for human-readable output.

    Falls back to the first configured prefix before the framework has
    resolved the real one.
    """
    return str(getattr(ctx, "prefix", DEFAULT_PREFIXES[0])).strip() or DEFAULT_PREFIXES[0].strip()


def make_bot() -> commands.Bot:
    return commands.Bot(
        command_prefix=commands.when_mentioned_or(*DEFAULT_PREFIXES),
        intents=build_intents(),
        help_command=None,
        case_insensitive=True,
        owner_ids=SUPER_USERS,
    )