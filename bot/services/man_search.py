"""Command manual (``man``): man-page embeds, free-text ranking, and views."""

from __future__ import annotations

import re

import discord

from bot.config.settings import SUPPORT_SERVER

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _make_man_embed(cmd, prefix: str) -> discord.Embed:
    """Build the single-command man page embed (shared by man and man search)."""
    embed = discord.Embed(
        title=f"MAN PAGE — {prefix}{cmd.qualified_name}",
        description=cmd.help or "No description available.",
        color=0x2ECC71,
    )

    synopsis = None
    usage_hint = (cmd.help or "").splitlines()
    for line in usage_hint:
        line = line.strip()
        low = line.lower()
        if low.startswith("usage:") or low.startswith("synopsis:"):
            synopsis = line.split(":", 1)[1].strip()
            break
    synopsis = synopsis or f"{prefix}{cmd.qualified_name} {cmd.signature}"
    embed.add_field(name="SYNOPSIS", value=f"`{synopsis}`", inline=False)

    if cmd.aliases:
        embed.add_field(name="ALIASES", value=", ".join(f"`{a}`" for a in cmd.aliases), inline=False)

    try:
        from bot.cogs.linux import LINUX_ALIASES
        linux_aliases = LINUX_ALIASES.get(cmd.name)
        if linux_aliases:
            embed.add_field(
                name="LINUX ALIASES",
                value=", ".join(f"`{a}`" for a in linux_aliases),
                inline=False,
            )
    except Exception:
        pass

    embed.add_field(name="SUPPORT", value=f"Join the support server: {SUPPORT_SERVER}", inline=False)
    embed.set_footer(text=f"{prefix}man {cmd.qualified_name}")
    return embed


def _search_commands(bot, query: str) -> list[tuple[int, object]]:
    """Rank commands by how well they match a free-text query.

    Scores come from exact name/alias matches, name/alias token hits, and
    words that appear in the command's help text / signature.
    Returns ``[(score, command), ...]`` sorted best-first (ties by name).
    """
    words = _tokens(query)
    if not words:
        return []

    raw = []
    for cmd in bot.walk_commands():
        if getattr(cmd, "hidden", False):
            continue
        names = {cmd.name, *cmd.aliases}
        name_tokens = _tokens(" ".join(names))
        help_tokens = _tokens(f"{(cmd.help or '')} {cmd.signature}")

        exact = query.strip().lower()
        score = 0
        if exact in names:
            score += 50
        for word in words:
            if word in name_tokens:
                score += 8
            elif any(n.lower().startswith(word) for n in names):
                score += 4
            score += 3 if word in help_tokens else 0
        if score:
            raw.append((score, cmd))
    raw.sort(key=lambda t: (-t[0], t[1].qualified_name))
    return raw


class ManSearchView(discord.ui.View):
    """Interactive search-results menu for `man <query>`.

    Shows a dropdown of the best-matching commands; picking one swaps the
    message to that command's man page, with a back button to return.
    """

    def __init__(self, bot, query: str, results: list[tuple[int, object]], author_id: int, prefix: str, timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.query = query
        self.results = results[:25]
        self.author_id = author_id
        self.prefix = prefix
        self.index = 0
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear_items()
        if self.index == 0:
            select = discord.ui.Select(
                placeholder=f'Results for "{self.query}" — pick a command',
                min_values=1,
                max_values=1,
            )
            select.callback = self._on_pick
            for i, (_, cmd) in enumerate(self.results):
                desc = ""
                first = (cmd.help or "").strip().splitlines()
                if first:
                    desc = first[0][:90]
                select.add_option(
                    label=f"{self.prefix}{cmd.qualified_name}"[:100],
                    description=desc[:100],
                    value=str(i),
                )
            self.add_item(select)
            close = discord.ui.Button(label="🗑 Close", style=discord.ButtonStyle.danger)
            close.callback = self._on_close
            self.add_item(close)
        else:
            back = discord.ui.Button(label="← Back to results", style=discord.ButtonStyle.secondary)
            back.callback = self._on_back
            self.add_item(back)
            close = discord.ui.Button(label="🗑 Close", style=discord.ButtonStyle.danger)
            close.callback = self._on_close
            self.add_item(close)

    def _search_embed(self) -> discord.Embed:
        embed = discord.Embed(title=f'🔎  man — search: "{self.query}"', color=0x3498DB)
        lines = []
        for _, cmd in self.results:
            hint = ""
            first = (cmd.help or "").strip().splitlines()
            if first:
                synopsis = first[0].split("Usage:", 1)[-1].strip()
                hint = f"— {synopsis[:60]}" if synopsis else ""
            lines.append(f"`{self.prefix}{cmd.qualified_name}` {hint}".rstrip())
        embed.description = "\n".join(lines)
        embed.add_field(name="🛟 Support", value=f"Need help? Join the support server: {SUPPORT_SERVER}", inline=False)
        embed.set_footer(text=f"{self.prefix}man <command> for details · pick from the dropdown below")
        return embed

    async def _on_pick(self, interaction: discord.Interaction) -> None:
        self.index = int(interaction.data["values"][0]) + 1
        self._rebuild()
        cmd = self.results[self.index - 1][1]
        embed = _make_man_embed(cmd, self.prefix)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_back(self, interaction: discord.Interaction) -> None:
        self.index = 0
        self._rebuild()
        await interaction.response.edit_message(embed=self._search_embed(), view=self)

    async def _on_close(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await interaction.delete_original_response()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("These buttons aren't for you.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        try:
            message = self.message
            if message:
                await message.edit(view=self)
        except Exception:
            pass


class ManView(discord.ui.View):
    """Interactive paginated view for `man` with ◀ / ▶ buttons."""

    def __init__(self, embeds: list[discord.Embed], author_id: int, timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.author_id = author_id
        self.index = 0
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev.disabled = self.index == 0
        self.next.disabled = self.index == len(self.embeds) - 1
        self.counter.label = f"{self.index + 1}/{len(self.embeds)}"

    async def _show(self, interaction: discord.Interaction) -> None:
        self._update_buttons()
        embed = self.embeds[self.index]
        embed.set_footer(text=f"Page {self.index + 1}/{len(self.embeds)} · alpha man <command> for details")
        await interaction.response.edit_message(embed=embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("These buttons aren't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index = max(0, self.index - 1)
        await self._show(interaction)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True)
    async def counter(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()

    @discord.ui.button(label="▶", style=discord.ButtonStyle.success)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index = min(len(self.embeds) - 1, self.index + 1)
        await self._show(interaction)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        try:
            message = self.message
            if message:
                await message.edit(view=self)
        except Exception:
            pass