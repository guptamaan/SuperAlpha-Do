"""
cogs/suggestions.py — Suggestion / Feedback board.

Members submit feature ideas with `alpha suggest <idea>`. Posts go to the
configured board channel (falling back to the current channel), get a
discussion thread, and accumulate 👍/👎 votes from the community. Moderators
can approve, reject, implement (with a changelog → auto-archive) or reopen
suggestions. Approved suggestions can be linked to a GitHub issue or
auto-created as one when a GITHUB_TOKEN is present in .env.

Commands: suggest, suggestion [list|view|upvote|unvote|approve|reject|
implement|archive|reopen|link|delete|channel|repo]
Data stored in data/suggestions/ (records + per-guild config).
"""

import asyncio
import json
import os
import pathlib
import time

import aiohttp
import discord
from discord.ext import commands

DATA_DIR = pathlib.Path("data/suggestions")
DATA_FILE = DATA_DIR / "data.json"
CONFIG_FILE = DATA_DIR / "config.json"

UP_EMOJI = "👍"
DOWN_EMOJI = "👎"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

STATUS_EMOJI = {
    "open": "🟢",
    "approved": "✅",
    "rejected": "❌",
    "implemented": "🚀",
    "archived": "🗄️",
}
STATUS_COLOR = {
    "open": 0x9B59B6,
    "approved": 0x2ECC71,
    "rejected": 0xE74C3C,
    "implemented": 0x3498DB,
    "archived": 0x95A5A6,
}
VALID_STATUSES = set(STATUS_EMOJI)


def _load_json(path: pathlib.Path) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _score(rec: dict) -> int:
    return sum(v for v in (rec.get("reactions") or {}).values())


def _upvotes(rec: dict) -> int:
    return sum(1 for v in (rec.get("reactions") or {}).values() if v == 1)


def _downvotes(rec: dict) -> int:
    return sum(1 for v in (rec.get("reactions") or {}).values() if v == -1)


def _message_link(guild_id: int, channel_id: int, message_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


class Suggestions(commands.Cog, name="suggestions"):
    """Suggestion / feedback board with votes, threads and GitHub tracking."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _make_embed(self, title: str, color: int, description: str = "") -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=title, icon_url=None)
        if description:
            embed.description = description
        return embed

    def _load(self) -> dict:
        return _load_json(DATA_FILE)

    def _save(self, data: dict) -> None:
        _save_json(DATA_FILE, data)

    def _load_config(self) -> dict:
        return _load_json(CONFIG_FILE)

    def _save_config(self, config: dict) -> None:
        _save_json(CONFIG_FILE, config)

    def _guild_items(self, guild_id: int) -> tuple[dict, dict]:
        data = self._load()
        g = data.setdefault(str(guild_id), {"next_id": 1, "items": {}})
        return g, g.setdefault("items", {})

    def _get_rec(self, guild_id: int, sid: int) -> dict | None:
        _, items = self._guild_items(guild_id)
        return items.get(str(sid))

    def _save_rec(self, guild_id: int, rec: dict) -> None:
        data = self._load()
        default = {"next_id": 1, "items": {}}
        g = data.setdefault(str(guild_id), default)
        g["items"][str(rec["id"])] = rec
        self._save(data)

    def _save_votes(self, guild_id: int, rec: dict) -> None:
        self._save_rec(guild_id, rec)

    async def _is_mod(self, ctx: commands.Context) -> bool:
        perms = ctx.author.guild_permissions
        return (
            perms.administrator
            or perms.manage_guild
            or perms.manage_messages
            or ctx.author.id == ctx.guild.owner_id
            or await self.bot.is_owner(ctx.author)
        )

    def _status_embed(self, rec: dict) -> discord.Embed:
        status = rec.get("status", "open")
        embed = discord.Embed(color=STATUS_COLOR.get(status, 0x9B59B6))
        embed.set_author(name=f"💡 Suggestion #{rec['id']} — {status.title()}")
        embed.description = rec.get("content", "")
        embed.add_field(
            name="Votes",
            value=f"{UP_EMOJI} {_upvotes(rec)} · {DOWN_EMOJI} {_downvotes(rec)} · "
            f"**Score {_score(rec)}**",
            inline=True,
        )
        embed.add_field(name="Status", value=STATUS_EMOJI.get(status, "🟢") + " " + status.title(), inline=True)
        embed.add_field(
            name="By",
            value=f"<@{rec.get('author_id', 0)}>",
            inline=True,
        )
        embed.add_field(
            name="Submitted",
            value=f"<t:{int(rec.get('created_ts', time.time()))}:R>",
            inline=True,
        )
        if rec.get("gh_url"):
            embed.add_field(name="GitHub", value=rec["gh_url"], inline=False)
        if rec.get("reason"):
            embed.add_field(name="Reason", value=rec["reason"], inline=False)
        if rec.get("changelog"):
            embed.add_field(name="Changelog", value=rec["changelog"], inline=False)
        return embed

    async def _refresh_board(self, guild_id: int, rec: dict) -> None:
        channel = self.bot.get_channel(rec.get("channel_id") or 0)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            msg = channel.get_partial_message(rec.get("message_id") or 0)
            await msg.edit(embed=self._status_embed(rec))
        except Exception:
            pass

    # ── GitHub helpers ──────────────────────────────────────────────────────
    async def _create_gh_issue(self, rec: dict, config: dict) -> str | None:
        repo = (config.get("gh_repo") or "").strip().strip("/")
        if not repo or not GITHUB_TOKEN:
            return None
        content = rec.get("content", "")
        title = content[:70] + ("…" if len(content) > 70 else "")
        body = (
            f"**Suggestion #{rec['id']}** submitted by "
            f"<@{rec.get('author_id', 0)}> in the Discord server.\n\n"
            f"> {content}\n\n"
            f"Discussion: {_message_link(rec.get('guild_id', 0), rec.get('channel_id', 0), rec.get('message_id', 0))}"
        )
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"https://api.github.com/repos/{repo}/issues",
                    headers=headers,
                    json={"title": f"Suggestion #{rec['id']}: {title}", "body": body},
                ) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        return data.get("html_url")
        except Exception:
            return None
        return None

    # ── Submitting ──────────────────────────────────────────────────────────
    @commands.command(name="suggest")
    async def suggest(self, ctx: commands.Context, *, text: str = None) -> None:
        """Submit a suggestion to the board. Usage: alpha suggest <idea>"""
        if text is None:
            embed = self._make_embed("❌ Missing Idea", 0xE74C3C, "Share your idea: `alpha suggest <your idea>`")
            await ctx.send(embed=embed)
            return

        content = " ".join(text.strip().split())
        if len(content) < 3:
            embed = self._make_embed("❌ Too Short", 0xE74C3C, "Give a little more detail about your idea.")
            await ctx.send(embed=embed)
            return
        if len(content) > 2000:
            content = content[:1997] + "…"

        g, items = self._guild_items(ctx.guild.id)
        sid = g["next_id"]
        g["next_id"] = sid + 1
        rec = {
            "id": sid,
            "guild_id": ctx.guild.id,
            "author_id": ctx.author.id,
            "author_tag": str(ctx.author),
            "content": content,
            "status": "open",
            "reactions": {},
            "created_ts": time.time(),
            "updated_ts": time.time(),
            "reason": "",
            "changelog": "",
            "gh_url": "",
            "channel_id": 0,
            "message_id": 0,
            "thread_id": 0,
        }
        items[str(sid)] = rec
        data = self._load()
        data.setdefault(str(ctx.guild.id), g)
        self._save(data)

        config = self._load_config().get(str(ctx.guild.id), {})
        board = self.bot.get_channel(config.get("channel_id") or 0)
        target = board if isinstance(board, discord.TextChannel) else ctx.channel

        embed = self._status_embed(rec)
        embed.set_footer(text="React to vote or join the discussion thread.")
        try:
            msg = await target.send(embed=embed)
        except discord.HTTPException:
            msg = await ctx.send(embed=self._status_embed(rec))

        rec["channel_id"] = msg.channel.id
        rec["message_id"] = msg.id
        try:
            thread = await msg.create_thread(
                name=f"💬 Discuss #{sid}",
                auto_archive_duration=10080,
            )
            rec["thread_id"] = thread.id
        except Exception:
            pass
        for emoji in (UP_EMOJI, DOWN_EMOJI):
            try:
                await msg.add_reaction(emoji)
            except Exception:
                pass
        self._save_rec(ctx.guild.id, rec)

        confirm = self._make_embed(
            "✅ Suggestion Submitted",
            0x2ECC71,
            f"Thanks! Your idea is now **Suggestion #{sid}** on the board.\n"
            f"[Jump to it]({_message_link(ctx.guild.id, msg.channel.id, msg.id)})",
        )
        confirm.add_field(name="Live in", value=target.mention, inline=True)
        confirm.add_field(name="Vote", value="Use the reactions or `alpha suggestion upvote %d`" % sid, inline=True)
        await ctx.send(embed=confirm)

    # ── Root dispatcher ─────────────────────────────────────────────────────
    async def _dispatch(self, ctx: commands.Context, action: str, rest: str) -> None:
        action = (action or "").lower()
        if action in ("list", "board", "all", "show"):
            await self._list(ctx, rest)
        elif action in ("view", "info", "detail"):
            await self._view(ctx, rest)
        elif action in ("upvote", "up", "vote", "agree", "yes"):
            await self._vote(ctx, rest, 1)
        elif action in ("unvote", "down", "disagree", "no"):
            await self._vote(ctx, rest, 0)
        elif action in ("approve", "accepted"):
            await self._approve(ctx, rest)
        elif action in ("reject", "deny"):
            await self._reject(ctx, rest)
        elif action in ("implement", "shipped"):
            await self._implement(ctx, rest)
        elif action in ("archive", "close"):
            await self._archive(ctx, rest)
        elif action in ("reopen",):
            await self._reopen(ctx, rest)
        elif action in ("link", "gh", "github"):
            await self._link(ctx, rest)
        elif action in ("delete", "remove", "purge"):
            await self._delete(ctx, rest)
        elif action in ("channel", "chan", "board"):
            await self._channel(ctx, rest)
        elif action in ("repo", "githubrepo"):
            await self._repo(ctx, rest)
        else:
            embed = self._make_embed(
                "❌ Invalid Action", 0xE74C3C,
                "Usage: `alpha suggestion list [status]` · `alpha suggestion upvote <id>`\n"
                "Mods: `approve <id>` · `reject <id> [reason]` · `implement <id> <changelog>`\n"
                "`archive <id>` · `reopen <id>` · `link <id> <gh-url-or-#>` · `delete <id>`\n"
                "Admin: `channel [#channel|clear]` · `repo <owner/repo|clear>`",
            )
            await ctx.send(embed=embed)

    @commands.command(name="suggestion", aliases=["suggestions", "sug"])
    async def suggestion(self, ctx: commands.Context, action: str = None, *, rest: str = None) -> None:
        """Manage the suggestion board. Usage: alpha suggestion [action]"""
        await self._dispatch(ctx, action, rest)

    # ── Listing / viewing ───────────────────────────────────────────────────
    async def _list(self, ctx: commands.Context, rest: str | None) -> None:
        _, items = self._guild_items(ctx.guild.id)
        if not items:
            embed = self._make_embed("💡 Suggestion Board", 0x9B59B6, "No suggestions yet. Be the first with `alpha suggest <idea>`.")
            await ctx.send(embed=embed)
            return

        status_filter = (rest or "").strip().lower().rstrip("s")
        if status_filter and status_filter not in VALID_STATUSES:
            embed = self._make_embed("❌ Bad Status", 0xE74C3C, f"Filter by one of: `{', '.join(sorted(VALID_STATUSES))}`.")
            await ctx.send(embed=embed)
            return

        pool = [r for r in items.values() if not status_filter or r.get("status") == status_filter]
        pool.sort(key=_score, reverse=True)
        pool = pool[:15]

        embed = discord.Embed(color=0x9B59B6)
        embed.set_author(name=f"💡 Suggestion Board — {status_filter.title() if status_filter else 'Top'}")
        for rec in pool:
            status = rec.get("status", "open")
            votes = f"{_upvotes(rec)}↑ {_downvotes(rec)}↓" if status == "open" else f"{_upvotes(rec)}↑"
            embed.add_field(
                name=f"#{rec['id']} · {STATUS_EMOJI.get(status, '🟢')} · {votes}",
                value=(rec.get("content") or "…")[:100] + "…",
                inline=False,
            )
        embed.set_footer(text=f"Use `alpha suggestion view <id>` · showing up to {len(pool)}")
        await ctx.send(embed=embed)

    async def _view(self, ctx: commands.Context, rest: str) -> None:
        rec = self._find(ctx, rest)
        if not rec:
            return
        try:
            await ctx.send(embed=self._status_embed(rec))
        except Exception:
            pass

    def _find(self, ctx: commands.Context, rest: str | None) -> dict | None:
        try:
            sid = int((rest or "").split()[0])
        except (ValueError, IndexError):
            embed = self._make_embed("❌ Missing ID", 0xE74C3C, "Provide a suggestion ID: `alpha suggestion view <id>`")
            asyncio.ensure_future(ctx.send(embed=embed))
            return None
        rec = self._get_rec(ctx.guild.id, sid)
        if rec is None:
            embed = self._make_embed("❌ Not Found", 0xE74C3C, f"There is no suggestion `#{sid}` in this server.")
            asyncio.ensure_future(ctx.send(embed=embed))
            return None
        return rec

    # ── Voting ──────────────────────────────────────────────────────────────
    async def _vote(self, ctx: commands.Context, rest: str, value: int) -> None:
        rec = self._find(ctx, rest)
        if not rec:
            return
        if rec.get("status") != "open":
            embed = self._make_embed("⛔ Closed", 0xE74C3C, "This suggestion is no longer open for voting.")
            await ctx.send(embed=embed)
            return
        reactions = rec.setdefault("reactions", {})
        if value == 0:
            reactions.pop(str(ctx.author.id), None)
        else:
            reactions[str(ctx.author.id)] = 1
        self._save_votes(ctx.guild.id, rec)
        await self._refresh_board(ctx.guild.id, rec)
        if rec.get("message_id"):
            channel = self.bot.get_channel(rec.get("channel_id") or 0)
            if isinstance(channel, discord.TextChannel):
                try:
                    msg = channel.get_partial_message(rec["message_id"])
                    if value == 0:
                        await msg.clear_reaction(UP_EMOJI, ctx.author)
                    else:
                        await msg.clear_reaction(DOWN_EMOJI, ctx.author)
                except Exception:
                    pass
        verb = "Upvoted" if value else "Vote removed"
        embed = self._make_embed(
            verb, 0x2ECC71 if value else 0x95A5A6,
            f"**#{rec['id']}** now has **{_upvotes(rec)}** {UP_EMOJI} and **{_score(rec)}** score.",
        )
        await ctx.send(embed=embed)

    # ── Mod actions ─────────────────────────────────────────────────────────
    async def _approve(self, ctx: commands.Context, rest: str) -> None:
        if not await self._is_mod(ctx):
            await self._deny_perm(ctx)
            return
        rec = self._find(ctx, rest)
        if not rec:
            return
        rec["status"] = "approved"
        rec["updated_ts"] = time.time()
        rec["reason"] = f"Approved by {ctx.author.display_name}"
        config = self._load_config().get(str(ctx.guild.id), {})
        if not rec.get("gh_url"):
            url = await self._create_gh_issue(rec, config)
            if url:
                rec["gh_url"] = url
        self._save_rec(ctx.guild.id, rec)
        await self._refresh_board(ctx.guild.id, rec)
        embed = self._make_embed("✅ Suggestion Approved", 0x2ECC71, f"**#{rec['id']}** was approved.")
        if rec.get("gh_url"):
            embed.add_field(name="GitHub", value=rec["gh_url"], inline=False)
        await ctx.send(embed=embed)

    async def _reject(self, ctx: commands.Context, rest: str) -> None:
        if not await self._is_mod(ctx):
            await self._deny_perm(ctx)
            return
        parts = (rest or "").split(" ", 1)
        rec = self._find(ctx, parts[0])
        if not rec:
            return
        reason = parts[1].strip() if len(parts) > 1 else "Not pursued at this time."
        rec["status"] = "rejected"
        rec["reason"] = reason[:1000]
        rec["updated_ts"] = time.time()
        self._save_rec(ctx.guild.id, rec)
        await self._refresh_board(ctx.guild.id, rec)
        embed = self._make_embed("❌ Suggestion Rejected", 0xE74C3C, f"**#{rec['id']}** was rejected.\n**Reason:** {rec['reason']}")
        await ctx.send(embed=embed)

    async def _implement(self, ctx: commands.Context, rest: str) -> None:
        if not await self._is_mod(ctx):
            await self._deny_perm(ctx)
            return
        parts = (rest or "").split(" ", 1)
        rec = self._find(ctx, parts[0])
        if not rec:
            return
        changelog = parts[1].strip() if len(parts) > 1 else "Implemented"
        rec["status"] = "implemented"
        rec["changelog"] = changelog[:1000]
        rec["updated_ts"] = time.time()
        self._save_rec(ctx.guild.id, rec)
        await self._refresh_board(ctx.guild.id, rec)
        embed = self._make_embed("🚀 Suggestion Implemented", 0x3498DB, f"**#{rec['id']}** is now live and archived.")
        embed.add_field(name="Changelog", value=rec["changelog"], inline=False)
        await ctx.send(embed=embed)

    async def _archive(self, ctx: commands.Context, rest: str) -> None:
        if not await self._is_mod(ctx):
            await self._deny_perm(ctx)
            return
        rec = self._find(ctx, rest)
        if not rec:
            return
        rec["status"] = "archived"
        rec["updated_ts"] = time.time()
        self._save_rec(ctx.guild.id, rec)
        await self._refresh_board(ctx.guild.id, rec)
        embed = self._make_embed("🗄️ Suggestion Archived", 0x95A5A6, f"**#{rec['id']}** was archived.")
        await ctx.send(embed=embed)

    async def _reopen(self, ctx: commands.Context, rest: str) -> None:
        if not await self._is_mod(ctx):
            await self._deny_perm(ctx)
            return
        rec = self._find(ctx, rest)
        if not rec:
            return
        rec["status"] = "open"
        rec["updated_ts"] = time.time()
        rec["reason"] = ""
        self._save_rec(ctx.guild.id, rec)
        await self._refresh_board(ctx.guild.id, rec)
        embed = self._make_embed("🔄 Suggestion Reopened", 0x2ECC71, f"**#{rec['id']}** is open for voting again.")
        await ctx.send(embed=embed)

    async def _link(self, ctx: commands.Context, rest: str) -> None:
        if not await self._is_mod(ctx):
            await self._deny_perm(ctx)
            return
        parts = (rest or "").split()
        rec = self._find(ctx, parts[0] if parts else "")
        if not rec:
            return
        if len(parts) < 2:
            embed = self._make_embed("❌ Missing GitHub", 0xE74C3C, "Usage: `alpha suggestion link <id> <issue-url-or-number>`")
            await ctx.send(embed=embed)
            return
        target = parts[1]
        config = self._load_config().get(str(ctx.guild.id), {})
        repo = (config.get("gh_repo") or "").strip().strip("/")
        if target.isdigit() and repo:
            rec["gh_url"] = f"https://github.com/{repo}/issues/{target}"
        elif "github.com" in target:
            rec["gh_url"] = target
        else:
            embed = self._make_embed("❌ Bad Link", 0xE74C3C, "Give a full GitHub URL or an issue number (with `repo` set).")
            await ctx.send(embed=embed)
            return
        rec["updated_ts"] = time.time()
        self._save_rec(ctx.guild.id, rec)
        await self._refresh_board(ctx.guild.id, rec)
        embed = self._make_embed("🔗 GitHub Linked", 0x2ECC71, f"**#{rec['id']}** → {rec['gh_url']}")
        await ctx.send(embed=embed)

    async def _delete(self, ctx: commands.Context, rest: str) -> None:
        rec = self._find(ctx, rest)
        if not rec:
            return
        is_author = rec.get("author_id") == ctx.author.id
        if not (is_author or await self._is_mod(ctx)):
            await self._deny_perm(ctx)
            return
        data = self._load()
        g = data.setdefault(str(ctx.guild.id), {"next_id": 1, "items": {}})
        g["items"].pop(str(rec["id"]), None)
        self._save(data)
        embed = self._make_embed("🧹 Suggestion Deleted", 0x95A5A6, f"**#{rec['id']}** was removed.")
        await ctx.send(embed=embed)

    # ── Admin config ────────────────────────────────────────────────────────
    async def _channel(self, ctx: commands.Context, rest: str | None) -> None:
        if not await self._is_mod(ctx):
            await self._deny_perm(ctx)
            return
        config = self._load_config()
        cfg = config.setdefault(str(ctx.guild.id), {})
        rest = (rest or "").strip()

        if not rest or rest.lower() in ("clear", "none", "off", "reset"):
            cfg.pop("channel_id", None)
            self._save_config(config)
            embed = self._make_embed("📌 Board Channel", 0x95A5A6, "Suggestions will post in the command channel.")
            await ctx.send(embed=embed)
            return

        try:
            channel = await commands.TextChannelConverter().convert(ctx, rest)
        except Exception:
            channel = None
        if channel is None:
            embed = self._make_embed("❌ Bad Channel", 0xE74C3C, "Usage: `alpha suggestion channel #suggestions` or `channel clear`.")
            await ctx.send(embed=embed)
            return
        cfg["channel_id"] = channel.id
        self._save_config(config)
        embed = self._make_embed("📌 Board Channel", 0x2ECC71, f"New suggestions will post in {channel.mention}.")
        await ctx.send(embed=embed)

    async def _repo(self, ctx: commands.Context, rest: str | None) -> None:
        if not await self._is_mod(ctx):
            await self._deny_perm(ctx)
            return
        config = self._load_config()
        cfg = config.setdefault(str(ctx.guild.id), {})
        rest = (rest or "").strip().strip("/")
        if not rest or rest.lower() in ("clear", "none", "off"):
            cfg.pop("gh_repo", None)
            self._save_config(config)
            embed = self._make_embed("🐙 GitHub Repo", 0x95A5A6, "GitHub tracking disabled for this server.")
            await ctx.send(embed=embed)
            return
        if "/" not in rest:
            embed = self._make_embed("❌ Bad Repo", 0xE74C3C, "Format as `owner/repository`, e.g. `alpha suggestion repo guptamaan/SuperAlpha-Do`.")
            await ctx.send(embed=embed)
            return
        cfg["gh_repo"] = rest
        self._save_config(config)
        embed = self._make_embed("🐙 GitHub Repo", 0x2ECC71, f"Approved suggestions will link to **{rest}**.")
        embed.set_footer(text="Auto-creating issues needs a GITHUB_TOKEN in .env.")
        await ctx.send(embed=embed)

    async def _deny_perm(self, ctx: commands.Context) -> None:
        embed = self._make_embed("❌ Permission Denied", 0xE74C3C, "You need **Manage Messages**, **Manage Server**, or **Administrator**.")
        await ctx.send(embed=embed)

    # ── Reaction voting ─────────────────────────────────────────────────────
    async def _apply_reaction(self, payload: discord.RawReactionActionEvent, add: bool) -> None:
        if payload.guild_id is None:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        _, items = self._guild_items(payload.guild_id)
        rec = next((r for r in items.values()
                    if r.get("message_id") == payload.message_id), None)
        if rec is None or rec.get("status") != "open":
            return
        emoji = getattr(payload.emoji, "name", None)
        if emoji not in (UP_EMOJI, DOWN_EMOJI):
            return
        reactions = rec.setdefault("reactions", {})
        user = str(payload.user_id)
        if add:
            reactions[user] = 1 if emoji == UP_EMOJI else -1
        else:
            reactions.pop(user, None)
        self._save_votes(payload.guild_id, rec)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        try:
            await self._apply_reaction(payload, True)
        except Exception:
            import traceback
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        try:
            await self._apply_reaction(payload, False)
        except Exception:
            import traceback
            traceback.print_exc()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Suggestions(bot))