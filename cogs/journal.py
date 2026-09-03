"""
cogs/journal.py — Global command journal (`journalctl`).

Records every command invocation across every server into a persistent
journal, masking sensitive information (AI prompts, hashed values, message
content, raw snowflake IDs). `sudo journalctl` shows the last 10 commands and
accepts filters such as `--music` for a category summary.

Prefix  usage: sudo journalctl [count] [--<filter> ...]
Example:      sudo journalctl --music
"""

import hashlib
import json
import pathlib
import re
import time
from collections import Counter

import discord
from discord.ext import commands

JOURNAL_FILE = pathlib.Path("data/command_journal.json")
JOURNAL_DIR = JOURNAL_FILE.parent
MAX_ENTRIES = 400
DEFAULT_SHOW = 10
MAX_SHOW = 25

# Commands whose full argument content is treated as sensitive and is
# replaced with a redaction marker in the journal.
SENSITIVE_COMMANDS = {
    "ai", "aiclear", "aitranslate", "announce", "base64", "code", "embed",
    "explain", "hash", "imagine", "remind", "say", "shorten", "summarize",
    "translate",
}

# Flag -> set of cog names (lowercased) matched by `--<flag>`.
COG_FILTERS: dict[str, set[str]] = {
    "music": {"music", "musicgames"},
    "ai": {"ai"},
    "games": {"games"},
    "fun": {"fun"},
    "mod": {"moderation"},
    "system": {"system"},
    "info": {"info"},
    "utility": {"utility"},
    "xp": {"xp"},
    "vc": {"tempvc"},
    "afk": {"afk"},
    "welcome": {"welcomelogs"},
    "reaction": {"reactionroles"},
    "clan": {"clans"},
    "spectrum": {"spectrum"},
}

ALL_FILTERS = set(COG_FILTERS) | {"all"}

_SNOWFLAKE_RE = re.compile(r"<@!?(\d+)>")


# ── Persistence ────────────────────────────────────────────────────────────────
def _load_journal() -> list[dict]:
    if not JOURNAL_FILE.exists():
        return []
    try:
        with open(JOURNAL_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_journal(entries: list[dict]) -> None:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = JOURNAL_FILE.with_name(JOURNAL_FILE.name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(entries[-MAX_ENTRIES:], f, ensure_ascii=False, indent=1)
    tmp.replace(JOURNAL_FILE)


# ── Masking helpers ────────────────────────────────────────────────────────────
def _id_hash(value: int | str) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()[:10]


def _clean(value: str | None) -> str:
    if not value:
        return "?"
    for ch in "`*~|":
        value = value.replace(ch, "")
    return value.replace("\n", " ").strip() or "?"


def _mask_tokens(cmd_name: str, tokens: list[str]) -> tuple[list[str] | None, int]:
    """Return (masked_arg_tokens, count). tokens=None means fully redacted."""
    if cmd_name in SENSITIVE_COMMANDS:
        return None, len(tokens)
    masked: list[str] = []
    for tok in tokens:
        if tok.isdigit() and len(tok) >= 9:
            masked.append(f"<@{_id_hash(tok)}>")
        elif _SNOWFLAKE_RE.fullmatch(tok):
            masked.append(f"<@{_id_hash(_SNOWFLAKE_RE.match(tok).group(1))}>")
        else:
            masked.append(tok[:28] + ("…" if len(tok) > 28 else ""))
    return masked, len(tokens)


def _bare_args(content: str, prefix: str, invoked_with: str | None) -> list[str]:
    """Extract argument tokens from the raw message after the invoked command."""
    if not content:
        return []
    tokens = content.split()
    if not invoked_with:
        return tokens[1:]
    try:
        idx = [t.lower() for t in tokens].index(invoked_with.lower())
    except ValueError:
        return tokens[1:]
    return tokens[idx + 1:]


def _options_from_interaction(interaction: discord.Interaction, cmd_name: str) -> list[str]:
    """Masked option list for a slash command interaction."""
    data = interaction.data
    opts = data.get("options", []) if isinstance(data, dict) else []
    parts: list[str] = []
    for opt in opts:
        if not isinstance(opt, dict):
            continue
        name = opt.get("name", "?")
        value = opt.get("value")
        if value is None:
            continue
        if cmd_name in SENSITIVE_COMMANDS:
            value = "[REDACTED]"
        parts.append(f"{name}={value}")
    return parts


def _build_prefix_entry(ctx: commands.Context) -> dict:
    cmd = ctx.command
    cmd_name = cmd.name
    tokens = _bare_args(ctx.message.content, ctx.prefix or "", ctx.invoked_with)
    masked, argc = _mask_tokens(cmd_name, tokens)
    guild = ctx.guild
    return {
        "ts": time.time(),
        "kind": "sudo",
        "cmd": cmd.qualified_name,
        "root": cmd_name,
        "cog": (cmd.cog_name or "?").lower(),
        "user": _clean(getattr(ctx.author, "display_name", None)),
        "uid": "#" + _id_hash(ctx.author.id),
        "guild": _clean(guild.name) if guild else "DM",
        "gid": "&" + _id_hash(guild.id) if guild else None,
        "args": masked,
        "argc": argc,
    }


def _build_slash_entry(interaction: discord.Interaction) -> dict | None:
    cmd = interaction.command
    if cmd is None or getattr(cmd, "hidden", False):
        return None
    cmd_name = getattr(cmd, "name", None) or (interaction.data or {}).get("name", "?")
    options = _options_from_interaction(interaction, cmd_name)
    guild = interaction.guild
    cog_name = "?"
    cog = getattr(cmd, "cog", None)
    if cog is not None:
        cog_name = getattr(cog, "name", None) or getattr(cog, "qualified_name", None) or "?"
    return {
        "ts": time.time(),
        "kind": "slash",
        "cmd": getattr(cmd, "qualified_name", cmd_name),
        "root": cmd_name,
        "cog": str(cog_name).lower(),
        "user": _clean(getattr(interaction.user, "display_name", None)),
        "uid": "#" + _id_hash(interaction.user.id),
        "guild": _clean(guild.name) if guild else "DM",
        "gid": "&" + _id_hash(guild.id) if guild else None,
        "args": options,
        "argc": len(options),
    }


def _record(entry: dict) -> None:
    try:
        entries = _load_journal()
        entries.append(entry)
        _save_journal(entries)
    except Exception:
        pass


# ── Rendering ──────────────────────────────────────────────────────────────────
def _format_args(entry: dict) -> str:
    args = entry.get("args")
    argc = entry.get("argc") or 0
    if args is None:
        return f"[REDACTED×{argc}]" if argc else "[REDACTED]"
    if not args:
        return "—"
    text = " ".join(args[:3])
    if len(args) > 3:
        text += " …"
    return text


def _render(entries: list[dict], count: int, filters: list[str]) -> str:
    """Return the terminal-style text block for the journal."""
    if filters and "all" not in filters:
        matched = set()
        for f in filters:
            matched |= COG_FILTERS.get(f, set())
        entries = [e for e in entries if e.get("cog") in matched]
    servers = len({e.get("gid") for e in entries})
    fmt_filters = " ".join(f"--{f}" for f in filters) or "--all"
    lines = [f"$ sudo journalctl {fmt_filters}"]
    lines.append(
        f"-- last {min(count, len(entries))} of {len(entries)} "
        f"· {servers} server{'s' if servers != 1 else ''} --"
    )
    for e in entries[-count:]:
        when = time.strftime("%H:%M:%S", time.localtime(e.get("ts") or 0))
        if (e.get("ts") or 0) and time.strftime(
            "%Y-%m-%d", time.localtime(e["ts"])
        ) != time.strftime("%Y-%m-%d"):
            when = time.strftime("%m-%d %H:%M", time.localtime(e["ts"]))
        guild = (e.get("guild") or "DM")[:12]
        user = (e.get("user") or "?")[:12]
        cog = (e.get("cog") or "?")[:4].upper()
        kind = "sudo " if e.get("kind") == "sudo" else "slash"
        line = (
            f"{when}  {guild:<12} {user:<12} {e.get('uid', '????'):<11} "
            f"{kind:<6}{cog:<5} {e.get('cmd', '?'):<24} {_format_args(e)}"
        )
        lines.append(line[:104])
    if filters and "all" not in filters:
        matched = set()
        for f in filters:
            matched |= COG_FILTERS.get(f, set())
        matched_entries = [e for e in entries if e.get("cog") in matched]
        today = time.strftime("%Y-%m-%d")
        today_entries = [e for e in matched_entries
                         if time.strftime("%Y-%m-%d", time.localtime(e.get("ts") or 0)) == today]
        counts = Counter(e.get("root", "?") for e in today_entries)
        if counts:
            top = "   ".join(f"{name} ×{n}" for name, n in counts.most_common(8))
            lines.append("-- summary (today) --")
            lines.append(top[:104])
        else:
            lines.append("-- summary (today): no activity --")
    return "\n".join(lines)


# ── Cog ────────────────────────────────────────────────────────────────────────
class Journal(commands.Cog, name="journal"):
    """Global command journal (`journalctl`)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── listeners ─────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context) -> None:
        cmd = ctx.command
        if cmd is None or getattr(cmd, "hidden", False):
            return
        try:
            _record(_build_prefix_entry(ctx))
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type is not discord.InteractionType.application_command:
            return
        try:
            entry = _build_slash_entry(interaction)
            if entry:
                _record(entry)
        except Exception:
            pass

    # ── journalctl ─────────────────────────────────────────────────────────────
    @commands.command(name="journalctl")
    async def journalctl(self, ctx: commands.Context, *parts: str) -> None:
        """Show the global command journal. Usage: sudo journalctl [count] [--music]"""
        count = DEFAULT_SHOW
        filters: list[str] = []
        for part in parts:
            if part.isdigit():
                count = max(1, min(int(part), MAX_SHOW))
            elif part.startswith("--"):
                filters.append(part[2:].lower())
            else:
                embed = self._make_embed(
                    "❌ Invalid Flag",
                    0xE74C3C,
                    f"Unknown argument: `{part}`.\n"
                    f"Filters: `{', '.join(sorted(ALL_FILTERS))}`",
                )
                await ctx.send(embed=embed)
                return
        unknown = [f for f in filters if f not in ALL_FILTERS]
        if unknown:
            embed = self._make_embed(
                "❌ Unknown Filter",
                0xE74C3C,
                f"Unknown filter: `{', '.join(unknown)}`.\n"
                f"Available: `{', '.join(sorted(ALL_FILTERS))}`",
            )
            await ctx.send(embed=embed)
            return

        entries = _load_journal()
        if filters and "all" not in filters:
            matched = set()
            for f in filters:
                matched |= COG_FILTERS.get(f, set())
            entries = [e for e in entries if e.get("cog") in matched]

        text = _render(entries, count, filters)
        embed = discord.Embed(
            title="📜  sudo journalctl",
            description=f"```bash\n{text}\n```",
            color=0x1ABC9C,
        )
        embed.set_footer(text="sudo journalctl [count] --<music|ai|games|…> · all commands are masked")
        await ctx.send(embed=embed)

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title)
        if description:
            embed.description = description
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Journal(bot))