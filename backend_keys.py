"""Backend-only API key helpers.
backend_keys.py
Keys are read from environment variables and optional UI overrides. Do not
hardcode secrets in repo-tracked source.
"""

from __future__ import annotations

import os
import re
import time
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

    env_values: dict[str, str] = {}
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
                    if not key or key in os.environ:
                        continue
                    if key in env_values and env_values[key]:
                        env_values[key] = ",".join([env_values[key], value])
                    else:
                        env_values[key] = value
        except OSError:
            continue

    for key, value in env_values.items():
        os.environ[key] = value


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
        key = part.strip().strip("[]'\"")
        if key and key not in keys:
            keys.append(key)
    return keys


def streamlit_secret_keys(name: str) -> list[str]:
    """Read root-level Streamlit secrets when running on Streamlit Cloud.

    Streamlit TOML arrays live in st.secrets. Root-level scalar secrets may also
    be exposed as environment variables, but arrays are safer to read here.
    """
    try:
        import streamlit as st

        if name in st.secrets:
            return parse_keys(st.secrets.get(name))
    except Exception:
        pass
    return []


def env_keys(name: str) -> list[str]:
    load_dotenv_once()
    return first_non_empty(parse_keys(os.getenv(name, "")), streamlit_secret_keys(name))


def first_non_empty(*groups: Iterable[str]) -> list[str]:
    for group in groups:
        keys = parse_keys(group)
        if keys:
            return keys
    return []


def backend_key_counts() -> dict[str, int]:
    apify_discovery = first_non_empty(env_keys("APIFY_DISCOVERY_KEYS"), env_keys("APIFY_API_KEYS"))
    apify_profile = first_non_empty(env_keys("APIFY_PROFILE_KEYS"), apify_discovery)
    apify_ig_related = env_keys("APIFY_IG_RELATED_KEYS")
    return {
        "gemini": len(env_keys("GEMINI_API_KEYS") or env_keys("GEMINI_API_KEY")),
        "apify_discovery": len(apify_discovery),
        "apify_profile": len(apify_profile),
        "apify_ig_related": len(apify_ig_related),
        "youtube": len(env_keys("YOUTUBE_API_KEYS") or env_keys("YOUTUBE_API_KEY")),
        "scrapingbee": len(env_keys("SCRAPINGBEE_KEYS") or env_keys("SCRAPINGBEE_API_KEY")),
    }


class KeyRing:
    """Small round-robin key rotator for HTTP/API calls."""

    def __init__(self, keys: str | Iterable[str] | None):
        self.keys = parse_keys(keys)
        self.index = 0
        self.exhausted: set[str] = set()
        self._cooldown_until: dict[str, float] = {}
        self._usage_counts: dict[str, int] = {}

    def __len__(self) -> int:
        return len(self.keys)

    def has_keys(self) -> bool:
        return bool(self.keys)

    def next(self) -> str:
        if not self.keys:
            return ""
        now = time.time()
        for _ in range(len(self.keys)):
            key = self.keys[self.index % len(self.keys)]
            self.index += 1
            if key in self.exhausted:
                continue
            if self._cooldown_until.get(key, 0) > now:
                continue
            self._usage_counts[key] = self._usage_counts.get(key, 0) + 1
            if key not in self.exhausted:
                return key
        return ""

    def mark_exhausted(self, key: str) -> None:
        if key:
            self.exhausted.add(key)

    def mark_cooldown(self, key: str, seconds: int = 60) -> None:
        """Put a key in temporary cooldown (rate limited, not fully exhausted)."""
        if not key:
            return
        self._cooldown_until[key] = time.time() + seconds
        suffix = key[-6:] if len(key) >= 6 else key
        print(f"[KeyRing] Key ...{suffix} in {seconds}s cooldown")

    def health_report(self) -> dict:
        """Return health summary for all keys."""
        now = time.time()
        return {
            "total": len(self.keys),
            "exhausted": len(self.exhausted),
            "in_cooldown": sum(1 for t in self._cooldown_until.values() if t > now),
            "active": sum(
                1 for key in self.keys
                if key not in self.exhausted and self._cooldown_until.get(key, 0) <= now
            ),
            "usage_counts": dict(self._usage_counts),
        }
