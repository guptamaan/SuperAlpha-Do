"""Utility commands: safe math, calculator, and the weather slash regression."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.cogs.utility import Utility, _safe_eval_math_expression

from helpers import make_ctx


def test_math_basic_ops():
    assert _safe_eval_math_expression("2 + 2 * 3") == 8
    assert _safe_eval_math_expression("2 ^ 3") == 8
    assert _safe_eval_math_expression("2 ** 3") == 8
    assert _safe_eval_math_expression("(10 / 4)") == 2.5
    assert _safe_eval_math_expression("-3") == -3
    assert _safe_eval_math_expression("5 % 2") == 1
    assert _safe_eval_math_expression("1.5 * 2") == 3.0


@pytest.mark.parametrize("expr", [
    "1; os.system('x')",  # no identifiers at all
    "2 + open('/etc/passwd')",  # unsupported node
    "",
    "abc",
])
def test_math_rejects_unsafe(expr):
    with pytest.raises(ValueError):
        _safe_eval_math_expression(expr)


async def test_calc_command(bot):
    cog = Utility(bot)
    ctx = make_ctx(bot)
    await cog.calc.callback(cog, ctx, expression="2+2*3")
    embed = ctx.send.await_args.kwargs["embed"]
    assert embed.author.name == "🧮 Calculator"
    by_name = {f.name: f.value for f in embed.fields}
    assert by_name["Result"] == "# **8**"


async def test_calc_command_error(bot):
    cog = Utility(bot)
    ctx = make_ctx(bot)
    await cog.calc.callback(cog, ctx, expression="3 / 0")
    embed = ctx.send.await_args.kwargs["embed"]
    assert embed.author.name == "🧮 Calculator Error"


async def test_rand_returns_in_range(bot):
    cog = Utility(bot)
    ctx = make_ctx(bot)
    await cog.rand.callback(cog, ctx, 5, 1)
    embed = ctx.send.await_args.kwargs["embed"]
    assert embed.author.name == "🎲 Random Number"


def _fake_session(payload: dict):
    resp = SimpleNamespace(status=200)
    async def json_fn(content_type=None):
        return payload
    resp.json = json_fn
    cm = MagicMock()
    cm.__aenter__.return_value = resp
    cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=cm)
    return session


def _weather_payload():
    return {
        "current_condition": [{
            "temp_C": "19",
            "temp_F": "66",
            "FeelsLikeC": "18",
            "humidity": "52",
            "windspeedKmph": "11",
            "weatherDesc": [{"value": "Sunny"}],
        }]
    }


async def test_slash_weather_includes_feels_like(bot):
    """Regression: prefix weather had a Feels Like field that slash lacked."""
    cog = Utility(bot)
    cog._session = _fake_session(_weather_payload())
    interaction = SimpleNamespace(response=SimpleNamespace(send_message=AsyncMock()))

    await cog.slash_weather.callback(cog, interaction, "London")

    embed = interaction.response.send_message.await_args.kwargs["embed"]
    field_names = {f.name for f in embed.fields}
    assert "🌡️ Feels Like" in field_names
    assert "🌡️ Temperature" in field_names


async def test_slash_weather_handles_bad_response(bot):
    cog = Utility(bot)
    resp = SimpleNamespace(status=500)
    resp.json = AsyncMock()
    cm = MagicMock()
    cm.__aenter__.return_value = resp
    cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=cm)
    cog._session = session

    interaction = SimpleNamespace(response=SimpleNamespace(send_message=AsyncMock()))
    await cog.slash_weather.callback(cog, interaction, "Atlantis")
    embed = interaction.response.send_message.await_args.kwargs["embed"]
    assert embed.author.name == "🌤️ Weather Error"