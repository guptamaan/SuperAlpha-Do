"""
cogs/ai.py — AI chat and generation commands.
Uses the official OpenAI SDK (Responses API) against Groq.
Per-user conversation memory stored in data/ai_memory/.
Commands: ai, imagine, summarize, explain, code, aitranslate, aihistory, aiclear
"""

import json
import logging
import os
import pathlib

import discord
from discord.ext import commands
from openai import AsyncOpenAI

log = logging.getLogger("SuperUser Do")

MEMORY_DIR = pathlib.Path("data/ai_memory")
MEMORY_MAX = 20

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-20b"

# Discord limits
EMBED_DESC_MAX = 4096
EMBED_FIELD_MAX = 1024


def _load_history(user_id: int) -> list[dict]:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path = MEMORY_DIR / f"{user_id}.json"
    if path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save_history(user_id: int, history: list[dict]) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path = MEMORY_DIR / f"{user_id}.json"
    with open(path, "w") as f:
        json.dump(history, f, indent=2)


def _trim_history(history: list[dict]) -> list[dict]:
    if len(history) > MEMORY_MAX:
        return history[-MEMORY_MAX:]
    return history


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


class AI(commands.Cog, name="ai"):
    """AI-powered commands using Groq."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._api_key: str = os.getenv("GROQ_API_KEY", "")
        self._model: str = os.getenv("GROQ_MODEL", DEFAULT_MODEL)
        self._client: AsyncOpenAI | None = None
        self._last_error: Exception | None = None

    async def cog_load(self) -> None:
        if self._api_key:
            self._client = AsyncOpenAI(
                api_key=self._api_key, base_url=GROQ_BASE_URL
            )
        else:
            log.warning(
                "GROQ_API_KEY not set in .env — AI commands will fail."
            )

    async def cog_unload(self) -> None:
        if self._client:
            await self._client.close()
        self._client = None

    def _make_embed(self, title: str, color: int) -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title, icon_url=None)
        return embed

    async def _groq_chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_output_tokens: int = 1024,
    ) -> str | None:
        if not self._api_key or self._client is None:
            return None

        request_input = messages
        instructions: str | None = None
        if messages and messages[0].get("role") == "system":
            instructions = messages[0].get("content")
            request_input = messages[1:]

        try:
            response = await self._client.responses.create(
                model=self._model,
                instructions=instructions,
                input=request_input,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
        except Exception as e:
            self._last_error = e
            log.error("Groq request failed: %s", e)
            return None

        text = getattr(response, "output_text", None)
        if not text or not isinstance(text, str):
            log.error("Groq API returned no output_text: %r", response)
            return None

        return text.strip()

    async def _groq_request(
        self, user_id: int, system_prompt: str, user_message: str
    ) -> str | None:
        history = _load_history(user_id)

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for msg in history:
            role = msg.get("role")
            content = msg.get("content")
            if role in ("user", "assistant") and isinstance(content, str):
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})

        text = await self._groq_chat(messages, temperature=0.7, max_output_tokens=1024)
        if not text:
            return None

        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": text})
        _save_history(user_id, _trim_history(history))
        return text

    async def _groq_single(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.3,
        max_output_tokens: int = 512,
    ) -> str | None:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        return await self._groq_chat(
            messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

    def _missing_key_hint(self) -> str:
        if not self._api_key:
            return (
                "Could not get AI response. Make sure `GROQ_API_KEY` is set in `.env`.\n"
                "Get a free API key at https://console.groq.com/keys"
            )
        error = self._last_error
        if error is None:
            return "Groq returned an empty response. Please try again."
        message = str(error)
        if "401" in message:
            return (
                "Groq rejected your API key (401). Check `GROQ_API_KEY` in `.env` "
                "and regenerate one at https://console.groq.com/keys"
            )
        if "403" in message:
            return (
                "Groq returned 403 Access denied — that's a Groq-side network/region "
                "or API-key permission issue. Verify the key and that this server's "
                "IP is allowed."
            )
        if "429" in message:
            return "Groq rate limit hit (429). Please try again in a minute."
        return f"Groq request failed: {_truncate(message, 200)}"

    @commands.command(name="ai", aliases=["chat", "ask"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def ai_chat(self, ctx: commands.Context, *, question: str) -> None:
        """Chat with AI. Remembers previous messages. Usage: sudo ai <question>"""
        await ctx.typing()

        system_prompt = (
            "You are a helpful, witty, and friendly Discord bot assistant named SuperUser Do. "
            "Keep responses concise and friendly. Use markdown formatting when helpful. "
            "You can discuss programming, technology, general knowledge, and more. "
            "Be playful but helpful. Remember the conversation context."
        )

        response = await self._groq_request(ctx.author.id, system_prompt, question)

        if not response:
            embed = self._make_embed("AI Error", 0xE74C3C)
            embed.description = self._missing_key_hint()
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(color=0x9B59B6)
        embed.set_author(name="AI Response", icon_url=None)
        embed.description = _truncate(response, EMBED_DESC_MAX)
        embed.set_footer(text=f"Requested by {ctx.author} | {self._model}")
        await ctx.send(embed=embed)

    @commands.command(name="imagine", aliases=["generate", "draw", "img"])
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def imagine(self, ctx: commands.Context, *, prompt: str) -> None:
        """Generate an image prompt. Usage: sudo imagine <description>"""
        if len(prompt) < 5:
            embed = self._make_embed("Prompt Too Short", 0xE74C3C)
            embed.description = "Please provide a more detailed description."
            await ctx.send(embed=embed)
            return

        await ctx.typing()

        system_prompt = (
            "Generate a concise image generation prompt (max 30 words) for the given description. "
            "Only respond with the prompt, nothing else."
        )

        enhanced_prompt = await self._groq_single(
            system_prompt, prompt, temperature=0.5, max_output_tokens=80
        )

        if not enhanced_prompt:
            embed = self._make_embed("Generation Failed", 0xE74C3C)
            embed.description = self._missing_key_hint()
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(color=0x3498DB)
        embed.set_author(name="Image Prompt Generated", icon_url=None)
        embed.add_field(
            name="Original", value=_truncate(prompt, EMBED_FIELD_MAX), inline=False
        )
        embed.add_field(
            name="Enhanced Prompt",
            value=_truncate(f"*{enhanced_prompt}*", EMBED_FIELD_MAX),
            inline=False,
        )
        embed.set_footer(
            text=f"Requested by {ctx.author} | Use this on Midjourney, DALL-E, etc."
        )
        await ctx.send(embed=embed)

    @commands.command(name="summarize", aliases=["summary"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def summarize(self, ctx: commands.Context, *, text: str) -> None:
        """Summarize text. Usage: sudo summarize <text>"""
        if len(text) < 50:
            embed = self._make_embed("Text Too Short", 0xE74C3C)
            embed.description = "Please provide at least 50 characters to summarize."
            await ctx.send(embed=embed)
            return

        await ctx.typing()

        system_prompt = (
            "You are a summarization assistant. Create a concise summary of the provided text "
            "in 2-3 sentences. Focus on the key points."
        )

        response = await self._groq_single(
            system_prompt,
            f"Summarize this:\n\n{text}",
            temperature=0.3,
            max_output_tokens=256,
        )

        if not response:
            embed = self._make_embed("Summarization Failed", 0xE74C3C)
            embed.description = self._missing_key_hint()
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name="Summary", icon_url=None)
        embed.add_field(
            name="Original",
            value=_truncate(text, EMBED_FIELD_MAX),
            inline=False,
        )
        embed.add_field(
            name="Summary", value=_truncate(response, EMBED_FIELD_MAX), inline=False
        )
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    @commands.command(name="explain", aliases=["whatis"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def explain(self, ctx: commands.Context, *, topic: str) -> None:
        """Explain a concept simply. Usage: sudo explain <topic>"""
        await ctx.typing()

        system_prompt = (
            "You are an explainer bot. Explain concepts in simple, easy-to-understand terms. "
            "Use analogies when helpful. Keep it concise (2-3 paragraphs max)."
        )

        response = await self._groq_single(
            system_prompt,
            f"Explain in simple terms: {topic}",
            temperature=0.4,
            max_output_tokens=512,
        )

        if not response:
            embed = self._make_embed("Explanation Failed", 0xE74C3C)
            embed.description = self._missing_key_hint()
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(color=0xE74C3C)
        embed.set_author(
            name=_truncate(f"Explain: {topic}", 256), icon_url=None
        )
        embed.description = _truncate(response, EMBED_DESC_MAX)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    @commands.command(name="code")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def code_review(self, ctx: commands.Context, *, request: str) -> None:
        """Get code help or generate code. Usage: sudo code <request>"""
        await ctx.typing()

        system_prompt = (
            "You are a programming assistant. Provide clean, well-commented code examples. "
            "Use markdown code blocks with appropriate language tags. Keep explanations brief."
        )

        response = await self._groq_request(ctx.author.id, system_prompt, request)

        if not response:
            embed = self._make_embed("Code Help Failed", 0xE74C3C)
            embed.description = self._missing_key_hint()
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name="Code Assistant", icon_url=None)
        embed.description = _truncate(response, EMBED_DESC_MAX)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    @commands.command(name="aitranslate", aliases=["aitrans"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def ai_translate(self, ctx: commands.Context, lang: str, *, text: str) -> None:
        """Translate text using AI. Usage: sudo aitranslate <lang> <text>"""
        await ctx.typing()

        system_prompt = (
            "You are a translator. Translate the user's text to the specified language. "
            "Only respond with the translation, nothing else."
        )

        response = await self._groq_single(
            system_prompt,
            f"Translate to {lang}: {text}",
            temperature=0.2,
            max_output_tokens=512,
        )

        if not response:
            embed = self._make_embed("Translation Failed", 0xE74C3C)
            embed.description = self._missing_key_hint()
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(color=0x3498DB)
        embed.set_author(
            name=_truncate(f"Translation to {lang}", 256), icon_url=None
        )
        embed.add_field(
            name="Original", value=_truncate(text, EMBED_FIELD_MAX), inline=False
        )
        embed.add_field(
            name="Translated",
            value=_truncate(response, EMBED_FIELD_MAX),
            inline=False,
        )
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    @commands.command(name="aihistory")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def ai_history(self, ctx: commands.Context) -> None:
        """View your AI conversation history. Usage: sudo aihistory"""
        history = _load_history(ctx.author.id)

        if not history:
            embed = self._make_embed("AI History", 0x3498DB)
            embed.description = (
                "No conversation history yet. Start chatting with `sudo ai`!"
            )
            await ctx.send(embed=embed)
            return

        lines = []
        for msg in history:
            role = "You" if msg.get("role") == "user" else "AI"
            content = msg.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            content = _truncate(content, 100)
            lines.append(f"**{role}**: {content}")

        description = "\n".join(lines)
        embed = discord.Embed(color=0x3498DB)
        embed.set_author(name="AI Conversation History", icon_url=None)
        embed.description = _truncate(description, EMBED_DESC_MAX)
        embed.set_footer(
            text=f"{len(history)} messages | Last {MEMORY_MAX} kept in memory"
        )
        await ctx.send(embed=embed)

    @commands.command(name="aiclear")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def ai_clear(self, ctx: commands.Context) -> None:
        """Clear your AI conversation history. Usage: sudo aiclear"""
        path = MEMORY_DIR / f"{ctx.author.id}.json"
        if path.exists():
            path.unlink()

        embed = discord.Embed(color=0x2ECC71)
        embed.set_author(name="AI History Cleared", icon_url=None)
        embed.description = "Your conversation history has been cleared."
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AI(bot))
