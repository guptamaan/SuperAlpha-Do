"""pytest fixtures: mock bot, context, and fully isolated storage.

``db_env`` is autouse so no test ever touches the real ``data/`` directory.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from discord.ext import commands

from helpers import BOT_USER_ID, USER_IDS, isolate_storage, make_guild


@pytest.fixture(autouse=True)
def db_env(tmp_path, monkeypatch):
    """Point every storage path at a throwaway tmp dir and chdir there."""
    monkeypatch.chdir(tmp_path)
    isolate_storage(tmp_path)
    return tmp_path


@pytest.fixture
def bot():
    """A real ``commands.Bot`` that never touches the network."""
    instance = commands.Bot(
        command_prefix=("alpha ", "Alpha "),
        intents=discord.Intents.all(),
        help_command=None,
        case_insensitive=True,
    )
    instance.owner_id = USER_IDS["owner"]
    instance.is_owner = AsyncMock(
        side_effect=lambda user: getattr(user, "id", None) == instance.owner_id
    )
    instance.ws = SimpleNamespace(latency=0.0)
    return instance


@pytest.fixture
def guild():
    return make_guild()


def register_cog(cog):
    """Register a cog's prefix commands onto its bot for can_run/permission tests."""
    for command in cog.get_commands():
        cog.bot.add_command(command)
    return cog