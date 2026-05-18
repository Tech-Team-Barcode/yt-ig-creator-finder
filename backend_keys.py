"""Backend-only API key helpers.

Keys are read from environment variables and optional UI overrides. Do not
hardcode secrets in repo-tracked source.
"""

from __future__ import annotations

import os
import re
from typing import Iterable


KEY_SPLIT_RE = re.compile(r"[\s,;'\"]+")
_DOTENV_LOADED = False


def load_dotenv_once() -> None:
    """Load local .env values without adding another dependency."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return

    _DOTENV_LOADED = True
    root = os.path.dirname(os.path.abspath(__file__))
    paths: list[str] = []
    for candidate in (os.path.join(root, ".env"), os.path.join(os.getcwd(), ".env")):
        if candidate not in paths:
            paths.append(candidate)

    for path in paths:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                        value = value[1:-1]
                    if key and key not in os.environ:
                        os.environ[key] = value
        except OSError:
            continue


def parse_keys(raw: str | Iterable[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = KEY_SPLIT_RE.split(raw.strip())
    else:
        parts = []
        for item in raw:
            parts.extend(KEY_SPLIT_RE.split(str(item).strip()))
    keys: list[str] = []
    for part in parts:
        key = part.strip().strip("'\"")
        if key and key not in keys:
            keys.append(key)
    return keys


def env_keys(name: str) -> list[str]:
    load_dotenv_once()
    return parse_keys(os.getenv(name, ""))


def first_non_empty(*groups: Iterable[str]) -> list[str]:
    for group in groups:
        keys = parse_keys(group)
        if keys:
            return keys
    return []


def backend_key_counts() -> dict[str, int]:
    apify_discovery = first_non_empty(env_keys("APIFY_DISCOVERY_KEYS"), env_keys("APIFY_API_KEYS"))
    apify_profile = first_non_empty(env_keys("APIFY_PROFILE_KEYS"), apify_discovery)
    return {
        "gemini": len(env_keys("GEMINI_API_KEYS") or env_keys("GEMINI_API_KEY")),
        "apify_discovery": len(apify_discovery),
        "apify_profile": len(apify_profile),
        "youtube": len(env_keys("YOUTUBE_API_KEYS") or env_keys("YOUTUBE_API_KEY")),
    }


class KeyRing:
    """Small round-robin key rotator for HTTP/API calls."""

    def __init__(self, keys: str | Iterable[str] | None):
        self.keys = parse_keys(keys)
        self.index = 0
        self.exhausted: set[str] = set()

    def __len__(self) -> int:
        return len(self.keys)

    def has_keys(self) -> bool:
        return bool(self.keys)

    def next(self) -> str:
        if not self.keys:
            return ""
        for _ in range(len(self.keys)):
            key = self.keys[self.index % len(self.keys)]
            self.index += 1
            if key not in self.exhausted:
                return key
        return ""

    def mark_exhausted(self, key: str) -> None:
        if key:
            self.exhausted.add(key)
