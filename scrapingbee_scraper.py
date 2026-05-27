"""
scrapingbee_scraper.py - ScrapingBee YouTube Search.

Parallel YouTube search source alongside the official YouTube Data API v3.
Results are normalized into the same creator-row shape used by yt_scraper.py,
then merged and deduplicated in app.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import Optional

import aiohttp


SCRAPINGBEE_YT_URL = "https://app.scrapingbee.com/api/v1/youtube/search"


class SBKeyRing:
    """Key rotation for ScrapingBee: 402 exhausts, 429 cools down, repeated failures exhaust."""

    def __init__(self, keys: list[str] | str):
        if isinstance(keys, str):
            keys = [k.strip() for k in re.split(r"[,;\n]+", keys) if k.strip()]
        self.keys = [k for k in keys if k]
        self._index = 0
        self._exhausted: set[str] = set()
        self._cooldown_until: dict[str, float] = {}
        self._fail_counts: dict[str, int] = {}

    def next(self) -> Optional[str]:
        now = time.time()
        for _ in range(max(1, len(self.keys))):
            if not self.keys:
                return None
            key = self.keys[self._index % len(self.keys)]
            self._index += 1
            if key in self._exhausted:
                continue
            if self._cooldown_until.get(key, 0) > now:
                continue
            return key
        return None

    def mark_quota_exhausted(self, key: str) -> None:
        self._exhausted.add(key)
        print(f"[ScrapingBee] Key ...{key[-6:]} credits exhausted, rotating permanently")

    def mark_rate_limited(self, key: str, seconds: int = 60) -> None:
        self._cooldown_until[key] = time.time() + seconds
        print(f"[ScrapingBee] Key ...{key[-6:]} rate limited, {seconds}s cooldown")

    def mark_failed(self, key: str) -> None:
        self._fail_counts[key] = self._fail_counts.get(key, 0) + 1
        if self._fail_counts[key] >= 3:
            self._exhausted.add(key)
            print(f"[ScrapingBee] Key ...{key[-6:]} failed 3x, exhausted")

    @property
    def has_keys(self) -> bool:
        now = time.time()
        return bool(self.keys) and any(
            k not in self._exhausted and self._cooldown_until.get(k, 0) <= now
            for k in self.keys
        )

    @property
    def active_count(self) -> int:
        now = time.time()
        return sum(
            1 for k in self.keys
            if k not in self._exhausted and self._cooldown_until.get(k, 0) <= now
        )

    def health(self) -> dict:
        now = time.time()
        return {
            "total": len(self.keys),
            "exhausted": len(self._exhausted),
            "in_cooldown": sum(1 for t in self._cooldown_until.values() if t > now),
            "active": self.active_count,
        }


def _stable_fake_id(value: str) -> str:
    digest = hashlib.sha1(value.lower().encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"sb_{digest}"


def _extract_channel_id_from_url(url: str) -> str:
    url = str(url or "")
    for pattern in (
        r"/channel/([A-Za-z0-9_-]{10,})",
        r"/c/([A-Za-z0-9_-]{2,30})",
        r"/@([A-Za-z0-9_.-]{2,30})",
        r"/user/([A-Za-z0-9_-]{2,30})",
    ):
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return ""


def _parse_count(raw) -> int:
    if not raw:
        return 0
    text = str(raw).lower().replace(",", "").strip()
    text = re.sub(r"\b(subscribers?|views?|followers?)\b", "", text).strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*([km])?", text)
    if not match:
        return 0
    number = float(match.group(1))
    suffix = match.group(2)
    if suffix == "m":
        number *= 1_000_000
    elif suffix == "k":
        number *= 1_000
    return int(number)


def _first_value(item: dict, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value:
            return str(value).strip()
    return ""


def _yt_text(node) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("simpleText"):
            return str(node["simpleText"])
        if isinstance(node.get("runs"), list):
            return "".join(str(run.get("text", "")) for run in node["runs"] if isinstance(run, dict)).strip()
        if isinstance(node.get("accessibility"), dict):
            return _yt_text(node["accessibility"].get("accessibilityData", {}))
        if node.get("label"):
            return str(node["label"])
    return ""


def _yt_channel_from_runs(item: dict) -> tuple[str, str, str]:
    for key in ("longBylineText", "ownerText", "shortBylineText"):
        runs = (item.get(key) or {}).get("runs") or []
        if not runs:
            continue
        first = runs[0] or {}
        channel_name = str(first.get("text") or "").strip()
        endpoint = first.get("navigationEndpoint") or {}
        metadata = (endpoint.get("commandMetadata") or {}).get("webCommandMetadata") or {}
        browse = endpoint.get("browseEndpoint") or {}
        channel_url = metadata.get("url") or browse.get("canonicalBaseUrl") or ""
        channel_id = browse.get("browseId") or ""
        if channel_url and channel_url.startswith("/"):
            channel_url = "https://www.youtube.com" + channel_url
        return channel_name, channel_url, channel_id
    return "", "", ""


def _yt_thumbnail(item: dict) -> str:
    thumbs = ((item.get("thumbnail") or {}).get("thumbnails") or [])
    if thumbs and isinstance(thumbs[-1], dict):
        return str(thumbs[-1].get("url") or "")
    avatar_sources = (
        (((item.get("avatar") or {}).get("decoratedAvatarViewModel") or {}).get("avatar") or {})
        .get("avatarViewModel", {})
        .get("image", {})
        .get("sources", [])
    )
    if avatar_sources and isinstance(avatar_sources[-1], dict):
        return str(avatar_sources[-1].get("url") or "")
    return ""


def _yt_description(item: dict) -> str:
    snippets = item.get("detailedMetadataSnippets") or []
    parts: list[str] = []
    for snippet in snippets[:2]:
        if isinstance(snippet, dict):
            text = _yt_text(snippet.get("snippetText") or {})
            if text:
                parts.append(text)
    return " ".join(parts).strip()


def _yt_video_url(item: dict) -> str:
    video_id = str(item.get("videoId") or "")
    endpoint = item.get("navigationEndpoint") or {}
    metadata = (endpoint.get("commandMetadata") or {}).get("webCommandMetadata") or {}
    url = str(metadata.get("url") or "")
    if url.startswith("/"):
        return "https://www.youtube.com" + url
    if url:
        return url
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return ""


def normalize_sb_channel_result(item: dict, query: str, plan_item: dict) -> Optional[dict]:
    """
    Convert a ScrapingBee YouTube search item into a normalized channel candidate.

    The official endpoint returns structured search results; field names can vary
    between videos/channels, so this accepts several common aliases.
    """
    run_name, run_url, run_id = _yt_channel_from_runs(item)
    channel_name = _first_value(item, "channel_name", "channel", "uploader", "author", "owner") or run_name
    channel_url = _first_value(item, "channel_url", "channel_link", "uploader_url", "author_url") or run_url
    channel_id = _first_value(item, "channel_id", "channelId") or run_id
    if not channel_id and channel_url:
        channel_id = _extract_channel_id_from_url(channel_url)
    if not channel_name and not channel_id:
        return None
    if not channel_id:
        channel_id = _stable_fake_id(channel_name)

    video_title = _first_value(item, "video_title") or _yt_text(item.get("title")) or _first_value(item, "title")
    video_url = _first_value(item, "url", "link", "video_url") or _yt_video_url(item)
    description = _first_value(item, "description", "excerpt", "snippet") or _yt_description(item)
    # --- Subscriber extraction: ScrapingBee returns subscriber counts buried in accessibility strings ---
    # Primary: flat keys (sometimes present in structured responses)
    _subs_raw = _first_value(item, "subscribers", "subscriber_count", "subscriberCount", "subscriberCountText")
    # Secondary: the subtitle field (e.g. {"content": "‎@ganeshlonkar8703‬ subscribers‬"}) — strip handle prefix
    if not _subs_raw:
        _subtitle = _yt_text(item.get("subtitle") or {})
        if _subtitle and ("subscriber" in _subtitle.lower() or "k" in _subtitle.lower() or "m" in _subtitle.lower()):
            _subs_raw = _subtitle
    # Tertiary: accessibilityText at item level (e.g. "Ganesh Lonkar , अण्णा. Go to channel.")
    if not _subs_raw:
        _acc_text = str(item.get("accessibilityText") or "")
        _acc_match = re.search(r"([\d,.]+\s*[KkMm]?)\s*subscriber", _acc_text)
        if _acc_match:
            _subs_raw = _acc_match.group(1)
    # Quaternary: rendererContext → accessibilityContext → label
    if not _subs_raw:
        _label = (
            ((item.get("rendererContext") or {}).get("accessibilityContext") or {}).get("label") or ""
        )
        _label_match = re.search(r"([\d,.]+\s*[KkMm]?)\s*subscriber", _label, re.IGNORECASE)
        if _label_match:
            _subs_raw = _label_match.group(1)
    # Also check one level up if item is nested (sometimes SB wraps in channelRenderer)
    if not _subs_raw:
        for _wrapper_key in ("channelRenderer", "channelViewModelRenderer", "lockupViewModel"):
            _wrapped = item.get(_wrapper_key) or {}
            if _wrapped:
                _inner_label = (
                    ((_wrapped.get("rendererContext") or {}).get("accessibilityContext") or {}).get("label") or ""
                )
                _inner_match = re.search(r"([\d,.]+\s*[KkMm]?)\s*subscriber", _inner_label, re.IGNORECASE)
                if _inner_match:
                    _subs_raw = _inner_match.group(1)
                    break
                _inner_sub = _yt_text(_wrapped.get("subscriberCountText") or {})
                if _inner_sub and "subscriber" in _inner_sub.lower():
                    _subs_raw = _inner_sub
                    break
    subscribers = _parse_count(_subs_raw)
    thumbnail = _first_value(item, "thumbnail_url") or _yt_thumbnail(item) or _first_value(item, "thumbnail")

    return {
        "platform": "youtube",
        "match_status": "review",
        "review_reason": "ScrapingBee result - needs AI scorer confirmation",
        "reject_reason": "",
        "channel_id": channel_id,
        "channel_name": channel_name or channel_id,
        "channel_url": channel_url or (f"https://www.youtube.com/channel/{channel_id}" if channel_id.startswith("UC") else ""),
        "handle_url": channel_url,
        "handle": _extract_channel_id_from_url(channel_url),
        "subscribers": subscribers,
        "total_views": _parse_count(_first_value(item, "views", "view_count") or _yt_text(item.get("viewCountText"))),
        "video_count": 0,
        "country": "",
        "description": description,
        "uploads_playlist": "",
        "thumbnail": thumbnail,
        "channel_created": "",
        "video_title": video_title,
        "video_url": video_url,
        "video_published": _first_value(item, "published", "published_time", "publishedAt") or _yt_text(item.get("publishedTimeText")),
        "email": "",
        "phone": "",
        "instagram_url": "",
        "website": "",
        "aggregator_url": "",
        "local_match_score": 40,
        "_quality_score": 40,
        "_lang_score": 0,
        "_location_score": 0,
        "_search_query": query,
        "_search_type": "video",
        "_source": "scrapingbee",
        "_intent_terms": plan_item.get("intent_terms", []),
        "_negative_terms": plan_item.get("negative_terms", []),
        "_creator_evidence_score": 1,
        "_creator_evidence": "ScrapingBee YouTube search result",
        "_india_score": 1,
        "_india_confidence": "medium",
        "_gender_score": 0,
        "_female_score": 0,
        "_gender_label": "unknown",
        "_niche_score": 1,
    }


async def _enrich_sb_with_yt_api(
    channel_candidates: dict[str, dict],
    yt_api_keys: list[str],
    min_subs: int,
    max_subs: int,
    gender_filter: str,
    location_hints: list[str],
    lang_hints: list[str],
    exclude_terms: list[str] | None,
    allow_international: bool,
    progress_callback=None,
) -> list[dict]:
    """
    Take the raw ScrapingBee channel stubs (subscribers=0) and enrich them
    by calling the YouTube Data API v3 channels endpoint to get real stats.
    Then run the same _normalize_channel filter as yt_scraper uses.
    This is cheap quota-wise: channels.list costs 1 unit per 50 channels.
    """
    # Lazy import to avoid circular dependency
    from yt_scraper import YTScraper, _normalize_channel

    if not yt_api_keys or not channel_candidates:
        return []

    # Build channel_id -> match map preserving the original SB match info
    # Only enrich channels with real YouTube UC IDs — fake sb_ IDs can't be fetched
    cid_list = [cid for cid in channel_candidates.keys() if cid.startswith("UC")]
    skipped_fake = len(channel_candidates) - len(cid_list)
    if skipped_fake:
        print(f"[ScrapingBee] Skipping {skipped_fake} stubs without real channel IDs")
    print(f"[ScrapingBee] Enriching {len(cid_list)} channels via YouTube API")
    if progress_callback:
        progress_callback(f"ScrapingBee: enriching {len(cid_list)} channels via YouTube API")

    async with aiohttp.ClientSession() as session:
        scraper = YTScraper(yt_api_keys)
        scraper.session = session

        all_channels: dict[str, dict] = {}
        batch_tasks = []
        for i in range(0, len(cid_list), 50):
            batch_tasks.append(scraper.batch_fetch_channels(cid_list[i : i + 50]))
        batch_results = await asyncio.gather(*batch_tasks)
        for r in batch_results:
            all_channels.update(r)

    results: list[dict] = []
    for cid, ch in all_channels.items():
        st = ch.get("statistics", {})
        subs = int(st.get("subscriberCount") or 0)
        if min_subs > 0 and subs < min_subs:
            continue
        if max_subs > 0 and subs > max_subs:
            continue
        match = channel_candidates.get(cid, {})
        creator = _normalize_channel(
            ch=ch,
            match=match,
            location_hints=location_hints,
            lang_hints=lang_hints,
            gender_filter=gender_filter,
            region="IN",
            exclude_terms=exclude_terms,
            allow_international=allow_international,
        )
        if creator:
            creator["_source"] = "scrapingbee"
            results.append(creator)

    print(f"[ScrapingBee] Enrichment complete: {len(results)} filtered creators")
    return results


async def run_scrapingbee_search(
    api_keys: list[str] | str,
    search_plan: list[dict],
    min_subs: int = 0,
    max_subs: int = 0,
    progress_callback=None,
    yt_api_keys: list[str] | None = None,
    gender_filter: str = "ANY",
    location_hints: list[str] | None = None,
    lang_hints: list[str] | None = None,
    exclude_terms: list[str] | None = None,
    allow_international: bool = False,
) -> list[dict]:
    """Run YouTube searches via ScrapingBee and return unique channel candidates."""
    keyring = SBKeyRing(api_keys)
    if not keyring.has_keys:
        print("[ScrapingBee] No API keys available, skipping")
        return []

    video_queries = [item for item in (search_plan or []) if item.get("search_type") != "channel"]
    # ScrapingBee searches videos only — channel search_type items are skipped.
    # But we do want a cap so we don't burn all credits on one search run.
    # Limit to 8 queries max per ScrapingBee run to conserve credits
    video_queries = video_queries[:8]
    if not video_queries:
        print("[ScrapingBee] No video queries in search plan, skipping")
        return []
    print(f"[ScrapingBee] Will run {len(video_queries)} queries (capped at 8 to save credits)")

    print(f"[ScrapingBee] Running {len(video_queries)} queries with {keyring.active_count} key(s)")
    channel_candidates: dict[str, dict] = {}
    semaphore = asyncio.Semaphore(2)
    timeout = aiohttp.ClientTimeout(total=35)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def search_one(plan_item: dict) -> None:
            async with semaphore:
                key = keyring.next()
                if not key:
                    return
                query = plan_item.get("query", "")
                if not query:
                    return
                if progress_callback:
                    progress_callback(f"ScrapingBee: {query[:50]}")
                try:
                    async with session.get(
                        SCRAPINGBEE_YT_URL,
                        params={"api_key": key, "search": query, "sort_by": "relevance"},
                    ) as resp:
                        if resp.status == 200:
                            try:
                                data = await resp.json(content_type=None)
                            except Exception:
                                data = json.loads(await resp.text())
                            if isinstance(data, list):
                                items = data
                            elif isinstance(data, dict):
                                items = data.get("results") or data.get("items") or data.get("data") or data.get("videos") or []
                            else:
                                items = []
                            if isinstance(items, str):
                                try:
                                    parsed_items = json.loads(items)
                                    items = parsed_items if isinstance(parsed_items, list) else []
                                except Exception:
                                    items = []
                            if not isinstance(items, list):
                                items = []
                            print(f"[ScrapingBee] '{query}' -> {len(items)} results")
                            for item in items:
                                if isinstance(item, dict):
                                    candidate = normalize_sb_channel_result(item, query, plan_item)
                                    if candidate:
                                        channel_candidates.setdefault(candidate["channel_id"], candidate)
                        elif resp.status == 402:
                            keyring.mark_quota_exhausted(key)
                        elif resp.status == 429:
                            keyring.mark_rate_limited(key, seconds=60)
                        else:
                            body = await resp.text()
                            print(f"[ScrapingBee] HTTP {resp.status}: {body[:200]}")
                            keyring.mark_failed(key)
                except asyncio.TimeoutError:
                    print(f"[ScrapingBee] Timeout for '{query}'")
                    keyring.mark_failed(key)
                except Exception as exc:
                    print(f"[ScrapingBee] Error for '{query}': {exc}")
                    keyring.mark_failed(key)

        await asyncio.gather(*(search_one(item) for item in video_queries))

    raw_count = len(channel_candidates)
    print(f"[ScrapingBee] {raw_count} unique channel stubs discovered")

    # Enrich with real YouTube channel stats if YT API keys are provided.
    # This is the CRITICAL step: without it, subscribers=0 for everything
    # and Beer Biceps / Madhuri Dixit pass the subscriber filter.
    if yt_api_keys:
        return await _enrich_sb_with_yt_api(
            channel_candidates=channel_candidates,
            yt_api_keys=yt_api_keys,
            min_subs=min_subs,
            max_subs=max_subs,
            gender_filter=gender_filter,
            location_hints=location_hints or [],
            lang_hints=lang_hints or [],
            exclude_terms=exclude_terms,
            allow_international=allow_international,
            progress_callback=progress_callback,
        )

    # Fallback (no YT keys): return stubs but warn they are unfiltered
    results = list(channel_candidates.values())
    print(f"[ScrapingBee] WARNING: no YT API keys for enrichment, {len(results)} unfiltered stubs returned")
    if progress_callback:
        progress_callback(f"ScrapingBee: {len(results)} raw stubs (no YT enrichment)")
    return results
