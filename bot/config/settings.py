"""Central settings: shared constants, intents, and bot-wide configuration.

No module here may import from ``bot.cogs`` (keep this layer dependency-free so
every cog can depend on it without risking import cycles).
"""

from __future__ import annotations

import discord

# ── Identity ───────────────────────────────────────────────────────────────────
SUPER_USERS: set[int] = {1224391248580972584}
INVITE_URL = "https://discord.com/oauth2/authorize?client_id=1472581750810083339"
SUPPORT_SERVER = "https://discord.gg/Z2NXkwkFK3"
OWNER_HANDLE = "@r4ve_x"

# ── Command prefix ─────────────────────────────────────────────────────────────
DEFAULT_PREFIXES: tuple[str, ...] = ("alpha ", "Alpha ")


# ── Guild / user denylists ─────────────────────────────────────────────────────
BANNED_GUILDS: set[int] = {1523771297090507005, 1446772086231138375}
BANNED_USERS: set[int] = set()


def build_intents() -> discord.Intents:
    """The intent set the bot requires."""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.guilds = True
    intents.voice_states = True
    intents.presences = True
    return intents