from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent / "theme_packs"


def _load_json(path: Path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text())


def stable_seed(*parts: str) -> int:
    raw = "::".join(parts).encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:16], 16)


def load_theme_pack(theme_key: str) -> dict:
    key = theme_key or "frontier_kingdom"
    themed_file = BASE_DIR / f"{key}.json"
    if themed_file.exists():
        return _load_json(themed_file, {})

    # Backward-compatible folder pack fallback.
    theme_dir = BASE_DIR / key
    if not theme_dir.exists():
        theme_dir = BASE_DIR / "default"

    return {
        "threats": _load_json(theme_dir / "threats.json", []),
        "bosses": _load_json(theme_dir / "bosses.json", []),
        "sidequests": _load_json(theme_dir / "sidequests.json", []),
        "narrative": _load_json(theme_dir / "narrative_snippets.json", {}),
    }


def weighted_choice(rng: random.Random, entries: list[dict]) -> dict:
    if not entries:
        return {}
    total = sum(max(1, int(entry.get("weight", 1))) for entry in entries)
    pick = rng.randint(1, total)
    running = 0
    for entry in entries:
        running += max(1, int(entry.get("weight", 1)))
        if pick <= running:
            return entry
    return entries[-1]


def narrative_line(theme_pack: dict, key: str, seed: int, fallback: str) -> str:
    lines = theme_pack.get(key) or theme_pack.get("narrative", {}).get(key, [])
    if not lines:
        return fallback
    rng = random.Random(seed)
    return rng.choice(lines)
