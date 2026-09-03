"""
cogs/checks.py — Shared command checks.

perms_or_developer(**perms): passes if the user has the given guild
permissions OR is the bot owner/developer (SUPER_USERS in main.py).
"""

from discord.ext import commands


def perms_or_developer(**perms) -> commands.check:
    """Allow a command if the user has the given permissions, or is the developer."""
    return commands.check_any(commands.is_owner(), commands.has_permissions(**perms))