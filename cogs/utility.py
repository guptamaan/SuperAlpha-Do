"""
cogs/utility.py — Utility commands.
Commands: poll, remind, calc, rand, publicip, wiki, weather, base64, hash, timestamp,
          embed, say, announce, urban, translate, shorten, define
"""

import ast
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import base64
import hashlib
import datetime
import aiohttp
import re
import random
from typing import Any
from urllib.parse import quote

from cogs.checks import perms_or_developer


_ALLOWED_BINOPS: dict[type[ast.operator], Any] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}
_ALLOWED_UNARYOPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
}


def _safe_eval_math_expression(expression: str) -> float | int:
    expr = expression.strip()
    if not re.fullmatch(r"[0-9+\-*/(). %^\s]+", expr):
        raise ValueError("invalid expression characters")
    expr = expr.replace("^", "**")
    tree = ast.parse(expr, mode="eval")

    def eval_node(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
            return _ALLOWED_UNARYOPS[type(node.op)](eval_node(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            return _ALLOWED_BINOPS[type(node.op)](eval_node(node.left), eval_node(node.right))
        raise ValueError("unsupported expression")

    return eval_node(tree)


class Utility(commands.Cog, name="utility"):
    """Utility and productivity commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None
        self._reminder_tasks: set[asyncio.Task[None]] = set()

    async def cog_load(self) -> None:
        self._session = aiohttp.ClientSession()

    async def cog_unload(self) -> None:
        for task in list(self._reminder_tasks):
            task.cancel()
        self._reminder_tasks.clear()
        if self._session:
            await self._session.close()

    def _make_embed(self, title: str, color: int) -> discord.Embed:
        return discord.Embed(color=color).set_author(
            name=title, icon_url=None
        )

    # ── poll ──────────────────────────────────────────────────────────────────
    @commands.command(name="poll")
    async def poll(self, ctx: commands.Context, question: str, *options: str) -> None:
        """Create a poll. Usage: sudo poll "Question" "Option1" "Option2" ..."""
        if len(options) < 2:
            embed = self._make_embed("📊 Poll Error", 0xE74C3C)
            embed.description = "❌ Provide at least 2 options"
            await ctx.send(embed=embed)
            return
        if len(options) > 10:
            embed = self._make_embed("📊 Poll Error", 0xE74C3C)
            embed.description = "❌ Maximum 10 options allowed"
            await ctx.send(embed=embed)
            return

        number_emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        description = "\n".join(f"{number_emojis[i]}  **{opt}**" for i, opt in enumerate(options))
        embed = discord.Embed(
            title=f"📊 {question}",
            description=description,
            color=0x3498DB,
        )
        embed.set_footer(text=f"Poll by {ctx.author}")
        embed.set_author(name="📊 New Poll", icon_url=None)
        msg = await ctx.send(embed=embed)
        for i in range(len(options)):
            await msg.add_reaction(number_emojis[i])

    # ── remind ────────────────────────────────────────────────────────────────
    @commands.command(name="remind", aliases=["reminder"])
    async def remind(self, ctx: commands.Context, time_str: str, *, message: str) -> None:
        """Set a reminder. Usage: sudo remind <time> <message>  (e.g. 10m, 2h, 1d)"""
        pattern = re.match(r"^(\d+)([smhd])$", time_str.lower())
        if not pattern:
            embed = self._make_embed("⏰ Reminder Error", 0xE74C3C)
            embed.description = "❌ Invalid format. Use `30s`, `10m`, `2h`, or `1d`"
            await ctx.send(embed=embed)
            return

        amount, unit = int(pattern.group(1)), pattern.group(2)
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        seconds = amount * multipliers[unit]

        if seconds > 7 * 86400:
            embed = self._make_embed("⏰ Reminder Error", 0xE74C3C)
            embed.description = "❌ Maximum reminder time is 7 days"
            await ctx.send(embed=embed)
            return

        embed = self._make_embed("⏰ Reminder Set", 0x2ECC71)
        embed.add_field(name="Duration", value=f"`{time_str}`", inline=True)
        embed.add_field(name="Message", value=f"**{message}**", inline=False)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

        author_mention = f"<@{ctx.author.id}>"
        task = asyncio.create_task(
            self._remind_later(
                user_id=ctx.author.id,
                channel_id=ctx.channel.id,
                author_mention=author_mention,
                seconds=seconds,
                message=message,
                time_str=time_str,
            )
        )
        self._reminder_tasks.add(task)
        task.add_done_callback(lambda t: self._reminder_tasks.discard(t))

    async def _remind_later(
        self,
        *,
        user_id: int,
        channel_id: int,
        author_mention: str,
        seconds: int,
        message: str,
        time_str: str,
    ) -> None:
        try:
            await asyncio.sleep(seconds)
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            embed = discord.Embed(
                title="⏰  Reminder",
                description=message,
                color=0xF39C12,
            )
            embed.set_footer(text=f"Set {time_str} ago")
            await user.send(embed=embed)
        except asyncio.CancelledError:
            return
        except discord.Forbidden:
            channel = self.bot.get_channel(channel_id)
            if channel:
                await channel.send(f"⏰ {author_mention} Reminder: **{message}**")
        except Exception:
            channel = self.bot.get_channel(channel_id)
            if channel:
                await channel.send(f"⏰ {author_mention} Reminder failed to deliver.")

    # ── calc ──────────────────────────────────────────────────────────────────
    @commands.command(name="calc", aliases=["math", "bc", "expr"])
    async def calc(self, ctx: commands.Context, *, expression: str) -> None:
        try:
            result = _safe_eval_math_expression(expression)
            if isinstance(result, float) and result.is_integer():
                result = int(result)
            embed = self._make_embed("🧮 Calculator", 0x2ECC71)
            embed.add_field(name="Expression", value=f"`{expression}`", inline=False)
            embed.add_field(name="Result", value=f"# **{result}**", inline=False)
            await ctx.send(embed=embed)
        except Exception as exc:
            embed = self._make_embed("🧮 Calculator Error", 0xE74C3C)
            embed.description = f"❌ {exc}"
            await ctx.send(embed=embed)

    # ── rand ──────────────────────────────────────────────────────────────────
    @commands.command(name="rand", aliases=["random", "randint"])
    async def rand(self, ctx: commands.Context, a: int, b: int) -> None:
        """Random integer between a and b. Usage: sudo rand <a> <b>"""
        lo, hi = (a, b) if a <= b else (b, a)
        value = random.randint(lo, hi)
        embed = self._make_embed("🎲 Random Number", 0x9B59B6)
        embed.add_field(name="Range", value=f"`{lo}` — `{hi}`", inline=True)
        embed.add_field(name="Result", value=f"# **{value}**", inline=False)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    # ── publicip ─────────────────────────────────────────────────────────────
    @commands.command(name="publicip", aliases=["ip"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def publicip(self, ctx: commands.Context) -> None:
        """Show the bot's perceived public IP. Usage: sudo publicip"""
        url = "https://api.ipify.org?format=json"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                data = await resp.json(content_type=None)
            ip = data.get("ip")
            if not ip:
                raise ValueError("no ip field in response")
            embed = self._make_embed("🌐 Public IP", 0x3498DB)
            embed.add_field(name="IP Address", value=f"`{ip}`", inline=False)
            embed.set_footer(text=f"Requested by {ctx.author}")
            await ctx.send(embed=embed)
        except Exception as exc:
            embed = self._make_embed("🌐 IP Error", 0xE74C3C)
            embed.description = f"❌ {exc}"
            await ctx.send(embed=embed)

    # ── wiki ──────────────────────────────────────────────────────────────────
    @commands.command(name="wiki", aliases=["wikipedia", "apropos"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def wiki(self, ctx: commands.Context, *, query: str) -> None:
        """Fetch a short Wikipedia summary. Usage: sudo wiki <query>"""
        title = quote(query.replace(" ", "_"))
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    raise ValueError(f"no Wikipedia page found for '{query}'")
                data = await resp.json(content_type=None)

            summary = data.get("extract") or ""
            if not summary:
                raise ValueError("no summary available")

            page_title = data.get("title") or query
            page_url = (
                (data.get("content_urls") or {}).get("desktop") or {}
            ).get("page") or data.get("content_urls", {}).get("desktop", {}).get("page")

            if len(summary) > 900:
                summary = summary[:900] + "\n..."

            embed = discord.Embed(
                title=f"📚 {page_title}",
                description=summary,
                color=0x3498DB,
            )
            if page_url:
                embed.url = page_url
            embed.set_footer(text=f"Requested by {ctx.author}")
            embed.set_author(name="📖 Wikipedia", icon_url=None)
            await ctx.send(embed=embed)
        except Exception as exc:
            embed = self._make_embed("📚 Wiki Error", 0xE74C3C)
            embed.description = f"❌ {exc}"
            await ctx.send(embed=embed)

    # ── base64 ────────────────────────────────────────────────────────────────
    @commands.command(name="base64", aliases=["b64"])
    async def base64_cmd(self, ctx: commands.Context, mode: str, *, text: str) -> None:
        """Encode/decode base64. Usage: sudo base64 <encode|decode> <text>"""
        mode = mode.lower()
        if mode in ("encode", "enc", "-e"):
            result = base64.b64encode(text.encode()).decode()
            label, color = "Encoded", 0x2ECC71
        elif mode in ("decode", "dec", "-d"):
            try:
                result = base64.b64decode(text.encode()).decode()
                label, color = "Decoded", 0x3498DB
            except Exception:
                embed = self._make_embed("🔐 Base64 Error", 0xE74C3C)
                embed.description = "❌ Invalid base64 input"
                await ctx.send(embed=embed)
                return
        else:
            embed = self._make_embed("🔐 Base64 Error", 0xE74C3C)
            embed.description = "❌ Mode must be `encode` or `decode`"
            await ctx.send(embed=embed)
            return

        embed = self._make_embed(f"🔐 Base64 — {label}", color)
        embed.add_field(name="Input", value=f"`{text}`", inline=False)
        embed.add_field(name=label, value=f"`{result}`", inline=False)
        await ctx.send(embed=embed)

    # ── hash ──────────────────────────────────────────────────────────────────
    @commands.command(name="hash", aliases=["md5sum", "sha256sum"])
    async def hash_cmd(self, ctx: commands.Context, algorithm: str, *, text: str) -> None:
        """Hash text. Usage: sudo hash <md5|sha1|sha256|sha512> <text>"""
        algo = algorithm.lower()
        supported = {"md5": hashlib.md5, "sha1": hashlib.sha1,
                     "sha256": hashlib.sha256, "sha512": hashlib.sha512}
        if algo not in supported:
            embed = self._make_embed("🔏 Hash Error", 0xE74C3C)
            embed.description = f"❌ Supported: `{', '.join(supported)}`"
            await ctx.send(embed=embed)
            return
        result = supported[algo](text.encode()).hexdigest()
        embed = self._make_embed(f"🔏 Hash — {algo.upper()}", 0x9B59B6)
        embed.add_field(name="Algorithm", value=f"`{algo}`", inline=True)
        embed.add_field(name="Input", value=f"`{text}`", inline=False)
        embed.add_field(name="Hash", value=f"`{result}`", inline=False)
        await ctx.send(embed=embed)

    # ── timestamp ─────────────────────────────────────────────────────────────
    @commands.command(name="timestamp", aliases=["ts", "epoch", "date"])
    async def timestamp(self, ctx: commands.Context) -> None:
        """Show current Unix timestamp. Usage: sudo timestamp"""
        now = datetime.datetime.now(datetime.timezone.utc)
        epoch = int(now.timestamp())
        embed = self._make_embed("⏱️ Timestamp", 0x2ECC71)
        embed.add_field(name="Unix", value=f"`{epoch}`", inline=True)
        embed.add_field(name="Human", value=now.strftime("%Y-%m-%d %H:%M:%S UTC"), inline=True)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    # ── say ───────────────────────────────────────────────────────────────────
    @commands.command(name="say", aliases=["echo", "printf"])
    @perms_or_developer(manage_messages=True)
    async def say(self, ctx: commands.Context, *, message: str) -> None:
        """Make the bot say something. Usage: sudo say <message>"""
        await ctx.message.delete()
        await ctx.send(message, suppress_embeds=True)

    # ── announce ──────────────────────────────────────────────────────────────
    @commands.command(name="announce")
    @perms_or_developer(manage_guild=True)
    async def announce(self, ctx: commands.Context, channel: discord.TextChannel, *, message: str) -> None:
        """Send an announcement embed. Usage: sudo announce #channel <message>"""
        embed = discord.Embed(
            title="📢 Announcement",
            description=message,
            color=0xE74C3C,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"Announced by {ctx.author}")
        await channel.send(embed=embed)
        embed = self._make_embed("📢 Announcement Sent", 0x2ECC71)
        embed.add_field(name="Channel", value=channel.mention, inline=True)
        embed.add_field(name="Status", value="✅ Delivered", inline=True)
        await ctx.send(embed=embed)

    # ── embed ─────────────────────────────────────────────────────────────────
    @commands.command(name="embed")
    @perms_or_developer(manage_messages=True)
    async def embed_cmd(self, ctx: commands.Context, title: str, *, description: str) -> None:
        """Send a custom embed. Usage: sudo embed "Title" Description text"""
        await ctx.message.delete()
        embed = discord.Embed(title=title, description=description, color=0x2ECC71)
        embed.set_footer(text=f"By {ctx.author}")
        await ctx.send(embed=embed)

    # ── weather ───────────────────────────────────────────────────────────────
    @commands.command(name="weather", aliases=["wttr"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def weather(self, ctx: commands.Context, *, city: str) -> None:
        """Get weather for a city. Usage: sudo weather <city>"""
        url = f"https://wttr.in/{city.replace(' ', '+')}?format=j1"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    raise ValueError("City not found")
                data = await resp.json(content_type=None)
            cur = data["current_condition"][0]
            temp_c = cur["temp_C"]
            temp_f = cur["temp_F"]
            desc   = cur["weatherDesc"][0]["value"]
            feels  = cur["FeelsLikeC"]
            humid  = cur["humidity"]
            wind   = cur["windspeedKmph"]
            icon_map = {
                "sunny": "☀️", "clear": "🌙", "cloudy": "☁️", "rain": "🌧️",
                "snow": "❄️", "thunder": "⛈️", "fog": "🌫️", "mist": "🌫️"
            }
            icon = "🌤️"
            for key, val in icon_map.items():
                if key in desc.lower():
                    icon = val
                    break

            embed = discord.Embed(
                title=f"{icon} Weather — {city.title()}",
                color=0x87CEEB,
            )
            embed.add_field(name="☁️ Condition", value=f"**{desc}**", inline=True)
            embed.add_field(name="🌡️ Temperature", value=f"**{temp_c}°C** / {temp_f}°F", inline=True)
            embed.add_field(name="🌡️ Feels Like", value=f"**{feels}°C**", inline=True)
            embed.add_field(name="💧 Humidity", value=f"**{humid}%**", inline=True)
            embed.add_field(name="🌬️ Wind", value=f"**{wind} km/h**", inline=True)
            embed.set_footer(text=f"Requested by {ctx.author}")
            await ctx.send(embed=embed)
        except Exception as exc:
            embed = self._make_embed("🌤️ Weather Error", 0xE74C3C)
            embed.description = f"❌ {exc}"
            await ctx.send(embed=embed)

    # ── urban ────────────────────────────────────────────────────────────────
    @commands.command(name="urban", aliases=["ud"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def urban(self, ctx: commands.Context, *, term: str) -> None:
        """Search Urban Dictionary. Usage: sudo urban <term>"""
        url = f"https://api.urbandictionary.com/v0/define?term={quote(term)}"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json()
            results = data.get("list", [])
            if not results:
                raise ValueError("No results found")
            entry = results[0]
            definition = entry["definition"][:500]
            if len(entry["definition"]) > 500:
                definition += "..."

            embed = discord.Embed(
                title=f"📖 Urban Dictionary: {term}",
                description=definition,
                color=0x9B59B6,
            )
            embed.add_field(name="📝 Example", value=entry.get("example", "N/A")[:300] or "N/A", inline=False)
            embed.add_field(name="👍 Upvotes", value=f"**{entry.get('thumbs_up', 0)}**", inline=True)
            embed.add_field(name="👎 Downvotes", value=f"**{entry.get('thumbs_down', 0)}**", inline=True)
            await ctx.send(embed=embed)
        except Exception as exc:
            embed = self._make_embed("📖 Urban Error", 0xE74C3C)
            embed.description = f"❌ {exc}"
            await ctx.send(embed=embed)

    # ── define ───────────────────────────────────────────────────────────────
    @commands.command(name="define", aliases=["dict"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def define(self, ctx: commands.Context, *, word: str) -> None:
        """Define a word. Usage: sudo define <word>"""
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(word)}"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    raise ValueError(f"Word '{word}' not found")
                data = await resp.json()
            entry = data[0]
            meanings = entry.get("meanings", [])
            if not meanings:
                raise ValueError("No definitions available")

            embed = discord.Embed(
                title=f"📕 {word.title()}",
                color=0x3498DB,
            )
            for meaning in meanings[:2]:
                part = meaning.get("partOfSpeech", "unknown")
                defs = meaning.get("definitions", [])
                if defs:
                    definition = defs[0].get("definition", "N/A")
                    example = defs[0].get("example", "")
                    value = f"**Definition:** {definition}"
                    if example:
                        value += f"\n*Example:* {example}"
                    embed.add_field(name=f"📝 {part.title()}", value=value[:1024], inline=False)

            embed.set_footer(text=f"Requested by {ctx.author}")
            await ctx.send(embed=embed)
        except Exception as exc:
            embed = self._make_embed("📕 Define Error", 0xE74C3C)
            embed.description = f"❌ {exc}"
            await ctx.send(embed=embed)

    # ── shorten ──────────────────────────────────────────────────────────────
    @commands.command(name="shorten", aliases=["tinyurl"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def shorten(self, ctx: commands.Context, *, url: str) -> None:
        """Shorten a URL. Usage: sudo shorten <url>"""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        tiny_url = f"http://tinyurl.com/api-create.php?url={quote(url)}"
        try:
            async with self._session.get(tiny_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                short = await resp.text()
            embed = self._make_embed("🔗 URL Shortened", 0x2ECC71)
            embed.add_field(name="Original", value=url, inline=False)
            embed.add_field(name="Shortened", value=short, inline=False)
            await ctx.send(embed=embed)
        except Exception:
            embed = self._make_embed("🔗 URL Error", 0xE74C3C)
            embed.description = "❌ Could not shorten URL"
            await ctx.send(embed=embed)

    # ── translate ────────────────────────────────────────────────────────────
    @commands.command(name="translate", aliases=["trans"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def translate(self, ctx: commands.Context, lang: str, *, text: str) -> None:
        """Translate text. Usage: sudo translate <lang> <text>"""
        lang_map = {
            "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
            "pt": "Portuguese", "ru": "Russian", "ja": "Japanese", "ko": "Korean",
            "zh": "Chinese", "ar": "Arabic", "hi": "Hindi", "tr": "Turkish",
            "pl": "Polish", "nl": "Dutch", "sv": "Swedish", "da": "Danish",
        }
        lang_code = lang.lower()
        lang_name = lang_map.get(lang_code, lang_code.upper())

        url = f"https://api.mymemory.translated.net/get?q={quote(text)}&langpair={lang_code}|en"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json()
            translated = data.get("responseData", {}).get("translatedText", "")
            if not translated:
                raise ValueError("Translation failed")

            embed = self._make_embed(f"🌐 Translation ({lang_name})", 0x3498DB)
            embed.add_field(name="Original", value=f"**{text}**", inline=False)
            embed.add_field(name="Translated", value=f"**{translated}**", inline=False)
            embed.set_footer(text=f"Requested by {ctx.author}")
            await ctx.send(embed=embed)
        except Exception:
            embed = self._make_embed("🌐 Translation Error", 0xE74C3C)
            embed.description = f"❌ Could not translate. Use: {', '.join(lang_map)}"
            await ctx.send(embed=embed)

    # ── Slash Commands ────────────────────────────────────────────────────────
    @app_commands.command(name="poll", description="Create a poll")
    @app_commands.describe(question="The poll question", options="Poll options (at least 2 required)")
    async def slash_poll(self, interaction: discord.Interaction, question: str, options: str) -> None:
        """Slash command version of poll."""
        opts = options.split("|")
        if len(opts) < 2:
            embed = self._make_embed("📊 Poll Error", 0xE74C3C)
            embed.description = "❌ Provide at least 2 options separated by `|`"
            await interaction.response.send_message(embed=embed)
            return
        if len(opts) > 10:
            embed = self._make_embed("📊 Poll Error", 0xE74C3C)
            embed.description = "❌ Maximum 10 options allowed"
            await interaction.response.send_message(embed=embed)
            return

        number_emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        description = "\n".join(f"{number_emojis[i]}  **{opt.strip()}**" for i, opt in enumerate(opts))
        embed = discord.Embed(
            title=f"📊 {question}",
            description=description,
            color=0x3498DB,
        )
        embed.set_footer(text=f"Poll by {interaction.user}")
        embed.set_author(name="📊 New Poll", icon_url=None)
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        for i in range(len(opts)):
            await msg.add_reaction(number_emojis[i])

    @app_commands.command(name="calc", description="Calculate a math expression")
    @app_commands.describe(expression="Math expression (e.g. 2+2, 5*3)")
    async def slash_calc(self, interaction: discord.Interaction, expression: str) -> None:
        """Slash command version of calc."""
        try:
            result = _safe_eval_math_expression(expression)
            if isinstance(result, float) and result.is_integer():
                result = int(result)
            embed = self._make_embed("🧮 Calculator", 0x2ECC71)
            embed.add_field(name="Expression", value=f"`{expression}`", inline=False)
            embed.add_field(name="Result", value=f"# **{result}**", inline=False)
            await interaction.response.send_message(embed=embed)
        except Exception as exc:
            embed = self._make_embed("🧮 Calculator Error", 0xE74C3C)
            embed.description = f"❌ {exc}"
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="weather", description="Get weather for a city")
    @app_commands.describe(city="City name")
    async def slash_weather(self, interaction: discord.Interaction, city: str) -> None:
        """Slash command version of weather."""
        url = f"https://wttr.in/{city.replace(' ', '+')}?format=j1"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    raise ValueError("City not found")
                data = await resp.json(content_type=None)
            cur = data["current_condition"][0]
            temp_c = cur["temp_C"]
            temp_f = cur["temp_F"]
            desc = cur["weatherDesc"][0]["value"]
            feels = cur["FeelsLikeC"]
            humid = cur["humidity"]
            wind = cur["windspeedKmph"]
            icon_map = {
                "sunny": "☀️", "clear": "🌙", "cloudy": "☁️", "rain": "🌧️",
                "snow": "❄️", "thunder": "⛈️", "fog": "🌫️", "mist": "🌫️"
            }
            icon = "🌤️"
            for key, val in icon_map.items():
                if key in desc.lower():
                    icon = val
                    break

            embed = discord.Embed(
                title=f"{icon} Weather — {city.title()}",
                color=0x87CEEB,
            )
            embed.add_field(name="☁️ Condition", value=f"**{desc}**", inline=True)
            embed.add_field(name="🌡️ Temperature", value=f"**{temp_c}°C** / {temp_f}°F", inline=True)
            embed.add_field(name="💧 Humidity", value=f"**{humid}%**", inline=True)
            embed.add_field(name="🌬️ Wind", value=f"**{wind} km/h**", inline=True)
            await interaction.response.send_message(embed=embed)
        except Exception as exc:
            embed = self._make_embed("🌤️ Weather Error", 0xE74C3C)
            embed.description = f"❌ {exc}"
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="define", description="Define a word")
    @app_commands.describe(word="Word to define")
    async def slash_define(self, interaction: discord.Interaction, word: str) -> None:
        """Slash command version of define."""
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(word)}"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    raise ValueError(f"Word '{word}' not found")
                data = await resp.json()
            entry = data[0]
            meanings = entry.get("meanings", [])
            if not meanings:
                raise ValueError("No definitions available")

            embed = discord.Embed(
                title=f"📕 {word.title()}",
                color=0x3498DB,
            )
            for meaning in meanings[:2]:
                part = meaning.get("partOfSpeech", "unknown")
                defs = meaning.get("definitions", [])
                if defs:
                    definition = defs[0].get("definition", "N/A")
                    example = defs[0].get("example", "")
                    value = f"**Definition:** {definition}"
                    if example:
                        value += f"\n*Example:* {example}"
                    embed.add_field(name=f"📝 {part.title()}", value=value[:1024], inline=False)

            await interaction.response.send_message(embed=embed)
        except Exception as exc:
            embed = self._make_embed("📕 Define Error", 0xE74C3C)
            embed.description = f"❌ {exc}"
            await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Utility(bot))
