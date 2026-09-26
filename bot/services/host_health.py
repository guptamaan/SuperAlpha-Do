"""Host-health probes (CPU, memory, load average, uptime) read from ``/proc``."""

from __future__ import annotations

import glob
import os
import time

START_TIME = time.time()


def _proc_read(path: str) -> str:
    try:
        with open(f"/proc/{path}") as f:
            return f.read()
    except OSError:
        return ""


def _bar(pct: float, width: int = 10) -> str:
    filled = max(0, min(width, round(pct / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def _cpu_usage() -> str:
    def sample() -> tuple[int, int] | None:
        stat = _proc_read("stat")
        if not stat:
            return None
        parts = stat.split("\n")[0].split()[1:]
        try:
            total = sum(int(p) for p in parts)
            idle = int(parts[3]) + int(parts[4])
        except (ValueError, IndexError):
            return None
        return total, idle

    try:
        a = sample()
        time.sleep(0.25)
        b = sample()
        if not a or not b:
            return "n/a"
        d_total = max(b[0] - a[0], 1)
        d_idle = b[1] - a[1]
        return f"{max(0, 100 * (d_total - d_idle) / d_total):.0f}%"
    except Exception:
        return "n/a"


def _mem_info() -> tuple[int, int, float] | None:
    info = _proc_read("meminfo")
    mem_total = mem_avail = 0
    for ln in info.splitlines():
        if ln.startswith("MemTotal:"):
            mem_total = int(ln.split()[1]) * 1024
        elif ln.startswith("MemAvailable:"):
            mem_avail = int(ln.split()[1]) * 1024
    if not mem_total:
        return None
    used = mem_total - mem_avail
    return mem_total, used, 100 * used / mem_total


def _load_avg() -> str:
    load = _proc_read("loadavg").split()
    if len(load) < 3:
        return "n/a"
    return "  ".join(load[:3])


def _format_age(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02d}:{mins:02d}:{secs:02d}"
    return f"{hours:02d}:{mins:02d}:{secs:02d}"


def _bot_age() -> str:
    """Process start time derived from /proc, falling back to module import."""
    stat = _proc_read("self/stat")
    uptime = _proc_read("uptime")
    try:
        boot_ticks = int(stat.split()[21])
        hz = os.sysconf("SC_CLK_TCK")
        age = float(uptime.split()[0]) - boot_ticks / hz
        return _format_age(int(age))
    except (IndexError, ValueError, OSError):
        return _format_age(int(time.time() - START_TIME))


def _task_count() -> int | None:
    try:
        return sum(1 for _ in glob.iglob("/proc/[0-9]*"))
    except OSError:
        return None