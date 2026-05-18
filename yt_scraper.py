"""
yt_scraper.py — YouTube Creator Scraper (Async + Quota Smart)
==============================================================
Uses YouTube Data API v3 directly (no Apify needed for YT).

Key improvements over old GAS system:
- Async parallel fetching (aiohttp)
- Batched channel lookups (50 IDs per request instead of 1)
- Smart quota rotation across multiple API keys
- No 6-minute execution cap
- Better gender + location filtering
"""

import asyncio
import aiohttp
import re
from typing import Optional


YT_API_BASE = "https://www.googleapis.com/youtube/v3"

# ─── FILTER PATTERNS ──────────────────────────────────────────────────────────
BUSINESS_REJECT = re.compile(
    r"\b(news|official channel|pvt\.?\s*ltd|private limited|llp|ministry|"
    r"government|university|school|college|academy|institute|hospital|clinic|"
    r"entertainment|music label|record label|tv network|salon|spa|skin clinic|"
    r"hair clinic|dermatolog|cosmetic surger)\b",
    re.IGNORECASE
)

AGGREGATOR_RE = re.compile(
    r"https?://[^\s\"'<>]*(linktr\.ee|beacons\.ai|bio\.link|linkin\.bio|"
    r"stan\.store|allmylinks|campsite\.bio|komi\.io|carrd\.co)[^\s\"'<>]*",
    re.IGNORECASE
)

FEMALE_SIGNALS = re.compile(
    r"\b(she|her|girl|girls|woman|women|lady|ladies|female|wife|mom|mommy|"
    r"mother|bride|didi|bhabhi|anjali|simran|pooja|neha|priya|riya|shreya|"
    r"tanya|megha|nidhi|sakshi|swati|shruti|isha|aarti|kavya|khushi|shalini|"
    r"sonam|jyoti|divya|komal|nisha|sneha|payal|priyanka|ananya)\b",
    re.IGNORECASE
)

MALE_SIGNALS = re.compile(
    r"\b(he|him|boy|boys|man|men|mens|male|guy|guys|husband|father|dad|"
    r"bhai|bhaiya|groom|beard|shaving|grooming|mens skincare|men skincare|"
    r"rahul|rohit|akash|sahil|aditya|vivek|arjun|karan|varun|abhishek|"
    r"harsh|manish|deepak|ayush|nikhil|mohit|gaurav|ankit|vikram|rishabh)\b",
    re.IGNORECASE
)

CREATOR_SIGNALS = re.compile(
    r"\b(creator|vlogger|blogger|youtuber|content creator|lifestyle|beauty|"
    r"skincare|travel|food|fitness|fashion|makeup|review|haul|routine|"
    r"honest review|collab|ig|instagram|collaboration)\b",
    re.IGNORECASE
)


class QuotaManager:
    """Rotates YouTube API keys and tracks usage."""
    def __init__(self, api_keys: list[str]):
        self.keys = [k for k in api_keys if k and k.strip()]
        self.index = 0
        self.exhausted = set()

    def get_key(self) -> Optional[str]:
        for _ in range(len(self.keys)):
            key = self.keys[self.index % len(self.keys)]
            self.index += 1
            if key not in self.exhausted:
                return key
        return None

    def mark_exhausted(self, key: str):
        self.exhausted.add(key)
        print(f"[YT] API key quota exhausted, rotating...")

    @property
    def has_quota(self) -> bool:
        return len(self.exhausted) < len(self.keys)


class YTScraper:
    def __init__(self, api_keys: list[str]):
        self.quota = QuotaManager(api_keys)
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get(self, endpoint: str, params: dict) -> Optional[dict]:
        """Make a YouTube API request with quota rotation."""
        key = self.quota.get_key()
        if not key:
            print("[YT] All API keys exhausted")
            return None
        
        params["key"] = key
        url = f"{YT_API_BASE}/{endpoint}"
        
        try:
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status in (403, 429):
                    self.quota.mark_exhausted(key)
                    return await self._get(endpoint, params)  # retry with next key
                else:
                    text = await resp.text()
                    print(f"[YT] {endpoint} HTTP {resp.status}: {text[:200]}")
                    return None
        except Exception as e:
            print(f"[YT] Request error: {e}")
            return None

    async def search_videos(self, query: str, region: str = "IN", 
                             lang_code: Optional[str] = None,
                             max_results: int = 50,
                             page_token: Optional[str] = None) -> tuple[list, Optional[str]]:
        """Search videos and return (items, next_page_token)."""
        # Exclude noise
        clean_query = query + " -clinic -doctor -dr -dermatologist -hospital -transplant -salon -shop -store -academy"
        
        params = {
            "part": "snippet",
            "type": "video",
            "q": clean_query,
            "maxResults": max_results,
            "order": "relevance",
            "regionCode": region,
        }
        if lang_code:
            params["relevanceLanguage"] = lang_code
        if page_token:
            params["pageToken"] = page_token

        data = await self._get("search", params)
        if not data:
            return [], None

        return data.get("items", []), data.get("nextPageToken")

    async def batch_fetch_channels(self, channel_ids: list[str]) -> dict[str, dict]:
        """Fetch channel details for up to 50 IDs in one API call."""
        if not channel_ids:
            return {}

        params = {
            "part": "snippet,statistics,brandingSettings,topicDetails,contentDetails",
            "id": ",".join(channel_ids[:50]),
            "maxResults": 50,
        }
        data = await self._get("channels", params)
        if not data:
            return {}

        return {item["id"]: item for item in data.get("items", [])}

    async def batch_fetch_videos(self, video_ids: list[str]) -> dict[str, dict]:
        """Fetch video stats for up to 50 IDs in one API call."""
        if not video_ids:
            return {}

        params = {
            "part": "statistics,contentDetails,snippet",
            "id": ",".join(video_ids[:50]),
        }
        data = await self._get("videos", params)
        if not data:
            return {}

        return {item["id"]: item for item in data.get("items", [])}


def _is_personal_creator(ch: dict) -> bool:
    """Check if a channel is a personal creator (not brand/institution)."""
    sn = ch.get("snippet", {})
    st = ch.get("statistics", {})
    subs = int(st.get("subscriberCount", 0))
    vids = int(st.get("videoCount", 0))
    title = (sn.get("title", "") or "").lower()
    desc = (sn.get("description", "") or "").lower()

    if BUSINESS_REJECT.search(title + " " + desc[:300]):
        return False
    if vids < 3:
        return False
    if subs > 200_000 and vids < 15:
        return False

    return True


def _score_creator(ch: dict) -> int:
    """Score creator quality (0-100)."""
    sn = ch.get("snippet", {})
    st = ch.get("statistics", {})
    subs = int(st.get("subscriberCount", 0))
    views = int(st.get("viewCount", 0))
    vids = int(st.get("videoCount", 0))
    desc = (sn.get("description", "") or "").lower()

    score = 30

    if vids < 5:
        return 5

    # Engagement ratio
    if subs > 0:
        ratio = views / subs
        if ratio > 50:    score += 15
        elif ratio > 30:  score += 10
        elif ratio > 10:  score += 5
        elif ratio < 3:   score -= 15
        elif ratio < 5:   score -= 5

    # Subscriber sweet spot
    if 5000 <= subs <= 100_000:    score += 15
    elif 1000 <= subs < 5000:      score += 8
    elif 100_000 < subs <= 500_000: score += 5

    # Contact info = strong signal
    if re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", desc):
        score += 25
    if re.search(r"instagram\.com/", desc):
        score += 15
    if re.search(r"\+?\d[\d\s\-]{8,14}\d", desc):
        score += 10

    # Creator signals in description
    if CREATOR_SIGNALS.search(desc):
        score += 10

    return max(5, min(95, score))


def _extract_contact(desc: str, links: list[str] = None) -> dict:
    """Extract email, phone, Instagram, website from text."""
    links = links or []
    full_text = desc + " " + " ".join(links)

    # Email
    email = ""
    emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", full_text)
    junk = {"example.com", "sentry.io", "noreply", "youtube.com", "@2x", "@3x"}
    for e in emails:
        if not any(j in e for j in junk) and len(e) < 80:
            email = e
            break

    # Phone
    phone = ""
    m = re.search(r"(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{2,5}\)?[\s\-.]?)\d{3,5}[\s\-.]?\d{3,5}", desc)
    if m:
        digits = re.sub(r"\D", "", m.group())
        if 8 <= len(digits) <= 15:
            phone = m.group().strip()

    # Instagram
    instagram = ""
    ig_match = re.search(
        r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]{2,30})(?![A-Za-z0-9._])",
        full_text, re.IGNORECASE
    )
    if ig_match:
        handle = ig_match.group(1)
        junk_paths = {"p", "reel", "tv", "explore", "stories", "accounts", "about"}
        if handle.lower() not in junk_paths:
            instagram = f"https://www.instagram.com/{handle}/"
    
    if not instagram:
        # Check for @handle near "instagram" label
        labeled = re.search(
            r"(?:ig|insta|instagram)\s*[:\-–]\s*@?([a-zA-Z0-9._]{3,30})",
            full_text, re.IGNORECASE
        )
        if labeled:
            instagram = f"https://www.instagram.com/{labeled.group(1)}/"

    # Website (non-social)
    website = ""
    social_domains = r"(youtube\.com|youtu\.be|instagram\.com|facebook\.com|twitter\.com|x\.com|tiktok\.com|linktr\.ee)"
    for link in links:
        if not re.search(social_domains, link, re.IGNORECASE):
            website = link
            break

    # Aggregator
    agg = ""
    agg_match = AGGREGATOR_RE.search(full_text)
    if agg_match:
        agg = agg_match.group(0).rstrip(")],.")

    return {
        "email": email,
        "phone": phone,
        "instagram_url": instagram,
        "website": website,
        "aggregator_url": agg,
    }


def _normalize_channel(ch: dict, video_info: dict, query: str, 
                         location_hints: list[str], lang_hints: list[str],
                         gender_filter: str) -> Optional[dict]:
    """Convert raw channel + video data to standard creator format."""
    sn = ch.get("snippet", {})
    st = ch.get("statistics", {})
    br = (ch.get("brandingSettings") or {}).get("channel", {})
    cd = (ch.get("contentDetails") or {}).get("relatedPlaylists", {})

    channel_id = ch.get("id", "")
    desc = sn.get("description", "") or ""
    title = sn.get("title", "") or ""
    custom_url = sn.get("customUrl", "") or ""
    country = (sn.get("country") or "").upper()

    # Get URLs from description
    urls = re.findall(r"https?://[^\s\"'<>]+", desc)

    contact = _extract_contact(desc, urls)
    score = _score_creator(ch)

    # Language match
    full_text = (title + " " + desc + " " + (br.get("keywords", "") or "")).lower()
    lang_score = sum(1 for hint in lang_hints if hint.lower() in full_text)

    # Location match
    loc_score = sum(1 for hint in location_hints if hint.lower() in full_text)
    # Also check video title
    vid_title = (video_info.get("snippet", {}) or {}).get("title", "") or ""
    vid_desc = (video_info.get("snippet", {}) or {}).get("description", "") or ""
    loc_score += sum(1 for hint in location_hints if hint.lower() in vid_title.lower())

    # Gender filter (hard gate)
    if gender_filter == "M":
        if FEMALE_SIGNALS.search(title + " " + desc[:200]):
            return None
        if not MALE_SIGNALS.search(title + " " + desc[:200] + " " + query):
            return None
    elif gender_filter == "F":
        if MALE_SIGNALS.search(title + " " + desc[:200]):
            return None
        if not FEMALE_SIGNALS.search(title + " " + desc[:200] + " " + query):
            return None

    vid_id = video_info.get("id", {}).get("videoId", "") if isinstance(video_info.get("id"), dict) else ""

    return {
        "platform": "youtube",
        "channel_id": channel_id,
        "channel_name": title,
        "channel_url": f"https://www.youtube.com/channel/{channel_id}",
        "handle_url": f"https://www.youtube.com/{custom_url}" if custom_url else "",
        "handle": custom_url,
        "subscribers": int(st.get("subscriberCount", 0)),
        "total_views": int(st.get("viewCount", 0)),
        "video_count": int(st.get("videoCount", 0)),
        "country": country,
        "description": desc,
        "uploads_playlist": cd.get("uploads", ""),
        "thumbnail": (sn.get("thumbnails", {}) or {}).get("medium", {}).get("url", ""),
        "channel_created": (sn.get("publishedAt", "") or "")[:10],
        "video_title": vid_title,
        "video_url": f"https://www.youtube.com/watch?v={vid_id}" if vid_id else "",
        "video_published": ((video_info.get("snippet") or {}).get("publishedAt", "") or "")[:10],
        "email": contact["email"],
        "phone": contact["phone"],
        "instagram_url": contact["instagram_url"],
        "website": contact["website"],
        "aggregator_url": contact["aggregator_url"],
        "_quality_score": score,
        "_lang_score": lang_score,
        "_location_score": loc_score,
        "_search_query": query,
    }


async def run_yt_search(
    api_keys: list[str],
    queries: list[str],
    min_subs: int,
    max_subs: int,
    gender_filter: str,
    location_hints: list[str],
    lang_hints: list[str],
    lang_code: Optional[str],
    region: str = "IN",
    results_per_query: int = 50,
    progress_callback=None
) -> list[dict]:
    """
    Main async entry for YouTube search.
    1. Search all queries in parallel (semaphore limited)
    2. Batch-fetch all unique channel details
    3. Filter + normalize
    """
    async with aiohttp.ClientSession() as session:
        scraper = YTScraper(api_keys)
        scraper.session = session

        # Step 1: Search all queries (max 3 concurrent to be quota-smart)
        channel_to_video = {}  # channel_id -> video_item
        semaphore = asyncio.Semaphore(3)

        async def search_query(query: str):
            async with semaphore:
                if not scraper.quota.has_quota:
                    return
                print(f"[YT] Searching: '{query}'")
                items, _ = await scraper.search_videos(
                    query, region=region, lang_code=lang_code,
                    max_results=results_per_query
                )
                if progress_callback:
                    progress_callback(f"Searched: '{query[:50]}' → {len(items)} results")
                for item in items:
                    cid = (item.get("snippet") or {}).get("channelId", "")
                    if cid and cid not in channel_to_video:
                        channel_to_video[cid] = item

        await asyncio.gather(*[search_query(q) for q in queries])

        if not channel_to_video:
            return []

        print(f"[YT] Found {len(channel_to_video)} unique channels across all queries")
        if progress_callback:
            progress_callback(f"Enriching {len(channel_to_video)} YouTube channels...")

        # Step 2: Batch-fetch channel details (50 at a time, parallel)
        channel_ids = list(channel_to_video.keys())
        all_channels = {}

        batch_tasks = []
        for i in range(0, len(channel_ids), 50):
            batch = channel_ids[i:i+50]
            batch_tasks.append(scraper.batch_fetch_channels(batch))

        batch_results = await asyncio.gather(*batch_tasks)
        for r in batch_results:
            all_channels.update(r)

        # Step 3: Filter + normalize
        results = []
        seen_ids = set()

        for cid, ch in all_channels.items():
            if cid in seen_ids:
                continue

            st = ch.get("statistics", {})
            subs = int(st.get("subscriberCount", 0))

            # Quick pre-filters
            if subs < min_subs:
                continue
            if max_subs > 0 and subs > max_subs:
                continue
            if not _is_personal_creator(ch):
                continue

            video_info = channel_to_video.get(cid, {})
            # Find which query found this channel
            found_query = ""
            for q in queries:
                # We don't track query->channel precisely, use video title heuristic
                break

            creator = _normalize_channel(
                ch, video_info,
                query=found_query,
                location_hints=location_hints,
                lang_hints=lang_hints,
                gender_filter=gender_filter
            )
            if creator:
                seen_ids.add(cid)
                results.append(creator)

        # Sort: location match → lang match → quality score
        results.sort(key=lambda x: (
            -x.get("_location_score", 0),
            -x.get("_lang_score", 0),
            -x.get("_quality_score", 0)
        ))

        print(f"[YT] Final: {len(results)} creators after all filters")
        return results
