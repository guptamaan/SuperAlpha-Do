"""Git helpers: local HEAD/branch and the latest commits pushed to GitHub."""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime

import aiohttp

GIT_REPO = "guptamaan/SuperAlpha-Do"

_git_cache: dict = {}
_GIT_CACHE_TTL = 120


def _local_head() -> tuple[str, str] | None:
    """(short_sha, branch) of the running checkout, or None if not a git repo."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode != 0:
            return None
        head = proc.stdout.strip()
        branch = "main"
        try:
            b = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, timeout=5,
            )
            if b.returncode == 0 and b.stdout.strip():
                branch = b.stdout.strip()
        except Exception:
            pass
        return head, branch
    except Exception:
        return None


def _local_latest() -> dict | None:
    """Best-effort local `git log -1` fallback when GitHub is unreachable."""
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%h|%s|%an|%ad", "--date=iso"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode != 0:
            return None
        short, message, author, date = proc.stdout.strip().split("|", 3)
        return {
            "sha": short,
            "short": short,
            "message": message or "?",
            "author": author or "?",
            "date": date.strip(),
            "url": "",
        }
    except Exception:
        return None


def _git_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%b %d, %Y · %H:%M")
    except Exception:
        return iso or "?"


async def _latest_commits() -> list[dict] | None:
    """Latest commits pushed to GitHub, cached for a short window."""
    now = time.time()
    cached = _git_cache.get("commits")
    if cached and now - cached[0] < _GIT_CACHE_TTL:
        return cached[1]
    commits: list[dict] | None = None
    try:
        headers = {"Accept": "application/vnd.github+json"}
        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"https://api.github.com/repos/{GIT_REPO}/commits?per_page=5"
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    payload = await resp.json()
                    if isinstance(payload, list):
                        commits = [
                            {
                                "sha": c.get("sha", ""),
                                "short": c.get("sha", "")[:7],
                                "message": ((c.get("commit") or {}).get("message") or "").strip().splitlines()[0] or "?",
                                "author": (((c.get("commit") or {}).get("author") or {}).get("name")) or "?",
                                "date": (((c.get("commit") or {}).get("author") or {}).get("date")) or "",
                                "url": c.get("html_url") or "",
                            }
                            for c in payload
                        ]
    except Exception:
        commits = None
    _git_cache["commits"] = (now, commits)
    return commits