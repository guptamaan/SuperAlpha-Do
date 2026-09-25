"""Pure distro-game rules: difficulty tiers, reward math, and answer matching.

Depends only on ``bot.models.distro_store`` for metadata/asset paths (resolved
dynamically so tests can re-point the store and everything follows).
"""

from __future__ import annotations

import pathlib

from bot.models import distro_store as store

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MANAGED_FILES = {"names.json", ".gitkeep"}

FIRST_HINT_DELAY = 45    # seconds after spawn: first hint
SECOND_HINT_DELAY = 150  # seconds after spawn: second hint
EXPIRE_TIMEOUT = 180     # seconds after spawn: unanswered round expires
GUESS_COOLDOWN = 2.5     # seconds a user must wait between (non-winning) guesses
HINT_PENALTY = 0.6       # reward multiplier per hint used (base * 0.6 ** hints)
MIN_XP = 5
MIN_SP = 1

DEFAULT_TIER = "medium"
TIER_REWARDS = {
    "easy": {"xp": 15, "sp": 3},
    "medium": {"xp": 25, "sp": 5},
    "hard": {"xp": 45, "sp": 10},
}
TIER_COLORS = {"easy": 0x2ECC71, "medium": 0xF1C40F, "hard": 0xE74C3C}

_AUTO_SPAWN_MIN = 1200  # 20 minutes
_AUTO_SPAWN_MAX = 2400  # 40 minutes


def _image_files() -> list[pathlib.Path]:
    if not store.DISTRO_DIR.exists():
        return []
    return [
        p for p in store.DISTRO_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower() in IMAGE_EXTENSIONS
        and p.name not in MANAGED_FILES
    ]


_SUFFIX_TOKENS = ("os", "linux")


def _normalise_text(text: str) -> str:
    """Normalise a guess: lowercase, no underscores/dashes, no punctuation,
    no trailing file extension, collapsed whitespace."""
    cleaned = text.lower().replace("_", " ").replace("-", " ")
    cleaned = cleaned.strip(" .,!?;:\"'()[]")
    for ext in IMAGE_EXTENSIONS:
        if cleaned.endswith(ext):
            cleaned = cleaned[: -len(ext)]
            break
    return " ".join(cleaned.split())


def _primary_name(stem: str) -> str:
    """The canonical answer for a filename stem: the cleaned filename itself."""
    return " ".join(stem.split(".")[0].replace("_", " ").replace("-", " ").lower().split())


def _answer_variants(stem: str) -> set[str]:
    """Accepted answers for an image filename stem, e.g. `windows` ->
    {"windows", "windows os", "windows linux", "windows os linux", ...}."""
    base = _primary_name(stem)
    if not base:
        return set()
    tokens = base.split()
    bases = {base}
    # Accept the bare name when the filename already ends in os/linux (e.g. arch-linux.png).
    if tokens and tokens[-1] in _SUFFIX_TOKENS:
        bases.add(" ".join(tokens[:-1]).rstrip())
    # Accept any base with any combination of "os" / "linux" appended,
    # plus concatenated spellings like "popos" or "nixos".
    variants = set(bases)
    for name in bases:
        for combo in ("os", "linux", "os linux", "linux os"):
            variants.add(f"{name} {combo}")
        variants.add(f"{name}os")
        variants.add(f"{name}linux")
    return {v for v in variants if v}


def _metadata_for(stem: str) -> dict:
    meta = store._load_metadata()
    key = _primary_name(stem)
    entry = meta.get(key, {})
    return entry if isinstance(entry, dict) else {}


def _tier_for(stem: str) -> str:
    tier = str(_metadata_for(stem).get("tier", DEFAULT_TIER)).lower()
    return tier if tier in TIER_REWARDS else DEFAULT_TIER


def _accepted_answers(stem: str) -> set[str]:
    """Every accepted guess for an image stem: filename variants + metadata aliases."""
    variants = _answer_variants(stem)
    for alias in (_metadata_for(stem).get("aliases") or []):
        normalised = _normalise_text(str(alias))
        if normalised:
            variants.add(normalised)
    return variants