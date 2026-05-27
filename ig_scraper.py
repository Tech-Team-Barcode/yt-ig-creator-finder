"""Instagram creator discovery funnels.
ig_scraper.py
The live workflow expands Instagram handles found on YouTube creator results
through a bounded related-profile graph and enriches each public profile.
The older hashtag funnel remains available for legacy callers.
"""

from __future__ import annotations

import asyncio
import re
import sys
from typing import Callable, Iterable, Optional

import aiohttp

from backend_keys import KeyRing, parse_keys
from hashtag_planner import evaluate_hashtag_quality, normalize_hashtag

try:
    from debug_logger import log_ig_raw
    _DEBUG_LOG = True
except ImportError:
    _DEBUG_LOG = False
    def log_ig_raw(*a, **k): pass

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


APIFY_BASE = "https://api.apify.com/v2"
ACTOR_HASHTAG = "apify~instagram-hashtag-scraper"
ACTOR_PROFILE = "apify~instagram-profile-scraper"
ACTOR_RELATED_PROFILE = "figue~instagram-profile-scraper"

POSTS_PER_HASHTAG = 30
MAX_CANDIDATES_BEFORE_ENRICH = 150
ENRICH_BATCH_SIZE = 20
ENRICH_TIMEOUT = 240
RELATED_PROFILE_BATCH_SIZE = 50
RELATED_PROFILE_DEPTH = 2
MAX_RELATED_PER_PROFILE = 50
MAX_RELATED_PER_HOP = 1000

INSTAGRAM_RESERVED_PATHS = {
    "about", "accounts", "developer", "direct", "directory", "emails",
    "explore", "legal", "p", "press", "privacy", "reel", "reels",
    "stories", "terms", "tv", "web",
}

SPAM_TAGS = {
    "love", "photo", "picture", "follow", "like", "instagram", "insta",
    "instagood", "photooftheday", "picoftheday", "instalike", "instalove",
    "daily", "beautiful", "amazing", "instadaily", "explore", "viral",
    "trending", "reels", "reelsinstagram", "reelsvideo", "reelsindia",
    "foryou", "foryoupage", "fyp", "explorepage", "exploreindia",
    "india", "mumbai", "delhi", "bangalore", "bengaluru", "karnataka",
}

BUSINESS_REJECT = re.compile(
    r"\b(pvt\s*ltd|private\s*limited|llp|wholesale|bulk\s*orders?|distributor|"
    r"supplier|manufacturer|retailer|dermatolog|skin\s*clinic|hair\s*clinic|"
    r"transplant|hospital|clinic|pharmacy|medical|doctor|school|college|"
    r"university|academy|institute|ministry|government|news\s*channel|"
    r"tv\s*channel|dm\s*for\s*orders?|whatsapp\s*to\s*order|"
    r"cash\s*on\s*delivery|pan\s*india\s*delivery|worldwide\s*shipping|"
    r"available\s*on\s*amazon|available\s*on\s*flipkart|shop\s*now|buy\s*now|"
    r"kitchen|restaurant|cafe|catering|recipe\s*business)\b",
    re.IGNORECASE,
)

INDIA_SIGNAL_RE = re.compile(
    r"\b(india|indian|bharat|desi|mumbai|delhi|bangalore|bengaluru|hyderabad|"
    r"chennai|kolkata|pune|ahmedabad|jaipur|lucknow|chandigarh|indore|bhopal|"
    r"nagpur|surat|kochi|coimbatore|noida|gurgaon|gurugram|thane|navi\s*mumbai|"
    r"maharashtra|karnataka|tamil\s*nadu|tamilnadu|andhra|telangana|gujarat|"
    r"rajasthan|kerala|punjab|haryana|dilli|mumbaikar|bangalorean|punekar|"
    r"hindi|kannada|tamil|telugu|marathi|malayalam|gujarati|bengali|punjabi|"
    r"inr|rs\.?|rupees)\b|[₹]",
    re.IGNORECASE,
)

INDIAN_BRANDS_RE = re.compile(
    r"\b(minimalist|mamaearth|nykaa|mcaffeine|dot\s*&?\s*key|the\s*derma\s*co|"
    r"wow\s*skin|plum\s*goodness|pilgrim|re\s*equil|beardo|bombay\s*shaving|"
    r"ustraa|the\s*man\s*company|man\s*matters|vedix|arata|biotique|"
    r"himalaya|patanjali|lotus\s*herbals|lakme|ponds|myntra|flipkart|"
    r"bigbasket|zepto|blinkit|swiggy|zomato)\b",
    re.IGNORECASE,
)

HINGLISH_RE = re.compile(
    r"\b(yaar|bhai|dost|bilkul|achha|accha|abhi|bas|haan|nahi|sahi|"
    r"ekdum|mast|bindaas|jugaad|arrey|arre|waise|matlab)\b",
    re.IGNORECASE,
)

MALE_SIGNAL_RE = re.compile(
    r"\b(men|mens|men'?s|male|boy|boys|guy|guys|he/him|beard|shaving|barber|"
    r"menskincare|mensgrooming|skincareformen|groomingformen|malegrooming|"
    r"mensroutine|beardcare|gentlemen?|bro|dude|bhai)\b",
    re.IGNORECASE,
)

FEMALE_SIGNAL_RE = re.compile(
    r"\b(she/her|women|womens|woman|female|girl|girls|ladies|lady|"
    r"girlboss|mama|mom|mum|bridal|bride|makeup\s*artist|beauty\s*blogger)\b",
    re.IGNORECASE,
)

CREATOR_SIGNAL_RE = re.compile(
    r"\b(content\s*creator|digital\s*creator|influencer|blogger|vlogger|"
    r"ugc|nano\s*influencer|micro\s*influencer|content\s*creation|reels|"
    r"dm\s*for\s*collab|collab\s*inquir|business\s*inquir|brand\s*deals?|"
    r"paid\s*collab|honest\s*review|reviewer|skincare\s*enthusiast|"
    r"grooming\s*enthusiast|sharing\s*my|personal\s*blog|worked\s*with)\b",
    re.IGNORECASE,
)

NON_INDIA_RE = re.compile(
    r"\b(based\s*in\s*(new\s*york|nyc|london|dubai|singapore|toronto|sydney|"
    r"melbourne|los\s*angeles|chicago|paris|berlin|amsterdam|bangkok|"
    r"manila|karachi|lahore|dhaka|colombo|kathmandu)|"
    r"(uk|us|uae|usa|american|british|australian)\s*creator)\b",
    re.IGNORECASE,
)

FOREIGN_SIGNAL_RE = re.compile(
    r"\b(china|chinese|beijing|shanghai|guangzhou|shenzhen|sweden|swedish|"
    r"korea|korean|seoul|japan|japanese|tokyo|usa|united\s*states|america|"
    r"canada|toronto|uk|united\s*kingdom|london|australia|sydney|"
    r"dubai|uae|singapore|malaysia|indonesia|thailand|bangkok|"
    r"pakistan|karachi|lahore|bangladesh|dhaka|sri\s*lanka|colombo)\b",
    re.IGNORECASE,
)

BAD_CATEGORIES = {
    "shopping & retail", "health/beauty brand", "product/service",
    "e-commerce website", "beauty supply store", "drug store",
    "grocery store", "pharmacy", "medical & health", "doctor",
    "hospital", "clinic", "school", "education", "restaurant",
    "food & beverage", "local service", "news & media website",
}

NICHE_TERMS = {
    "skin", "skincare", "grooming", "menskincare", "mensgrooming",
    "skincareformen", "groomingformen", "beard", "beardcare", "shaving",
    "routine", "review", "grwm", "haul", "tutorial", "serum", "cleanser",
    "moisturizer", "sunscreen", "facewash", "spf", "acne", "retinol",
    "niacinamide", "selfcare", "haircare", "fashion", "fitness", "beauty",
    "lifestyle", "wellness", "food", "travel", "tech",
}


def _safe_int(value, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default


def _clean_text(*parts) -> str:
    return " ".join(str(part or "") for part in parts)


def _extract_email(text: str) -> str:
    emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text or "")
    junk = {"example.com", "sentry.io", "noreply", "youtube.com", "@2x", "@3x"}
    for email in emails:
        if len(email) < 90 and not any(bad in email.lower() for bad in junk):
            return email
    return ""


def _extract_phone(text: str) -> str:
    match = re.search(r"(?:\+?91[\s\-.]?)?(?:\(?\d{2,5}\)?[\s\-.]?)?\d{3,5}[\s\-.]?\d{4,5}", text or "")
    if not match:
        return ""
    digits = re.sub(r"\D", "", match.group())
    if 8 <= len(digits) <= 13:
        return match.group().strip()
    return ""


def _terms_for_niche(niche: str) -> set[str]:
    text = str(niche or "").lower()
    terms = set(NICHE_TERMS)
    for word in re.findall(r"[a-z0-9]{4,}", text):
        terms.add(word)
    if "skin" in text or "groom" in text:
        terms.update({
            "skin", "skincare", "menskincare", "mensgrooming",
            "skincareformen", "groomingformen", "beard", "shaving",
            "serum", "cleanser", "sunscreen", "facewash",
        })
    return terms


async def _run_actor(
    session: aiohttp.ClientSession,
    actor_id: str,
    payload: dict,
    keys: KeyRing,
    timeout: int,
    log: Callable[[str], None],
) -> list:
    if not keys.has_keys():
        log(f"No API keys available for {actor_id}")
        return []
    attempts = max(1, len(keys))
    for _ in range(attempts):
        key = keys.next()
        if not key:
            return []
        url = f"{APIFY_BASE}/acts/{actor_id}/run-sync-get-dataset-items"
        try:
            async with session.post(
                url,
                json=payload,
                params={"token": key},
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status in (401, 403, 429):
                    keys.mark_exhausted(key)
                    reason = {
                        401: "unauthorized token",
                        403: "forbidden or actor access not enabled",
                        429: "rate limited or quota exhausted",
                    }[resp.status]
                    log(f"{actor_id} HTTP {resp.status} ({reason}); rotating key")
                    continue
                if resp.status == 502:
                    log(f"{actor_id} returned 502; skipping call")
                    return []
                if resp.status not in (200, 201):
                    text = await resp.text()
                    log(f"{actor_id} HTTP {resp.status}: {text[:180]}")
                    return []
                data = await resp.json()
                return data if isinstance(data, list) else []
        except asyncio.TimeoutError:
            log(f"{actor_id} timed out after {timeout}s")
            return []
        except Exception as exc:
            log(f"{actor_id} error: {exc}")
            return []
    return []


def _normalize_post(post: dict, source_hashtag: str, content_type: str) -> Optional[dict]:
    owner = post.get("owner") if isinstance(post.get("owner"), dict) else {}
    username = (
        post.get("ownerUsername")
        or post.get("username")
        or owner.get("username")
        or ""
    )
    username = str(username).strip().lower()
    if not username:
        return None

    raw_hashtags = post.get("hashtags") or []
    if not isinstance(raw_hashtags, list):
        raw_hashtags = []
    hashtags = [str(tag).strip().lstrip("#").lower() for tag in raw_hashtags if str(tag).strip()]
    caption = str(post.get("caption") or "")
    for tag in re.findall(r"#([A-Za-z0-9_]{3,40})", caption):
        clean = tag.lower()
        if clean not in hashtags:
            hashtags.append(clean)

    return {
        "platform": "instagram",
        "username": username,
        "full_name": str(post.get("ownerFullName") or owner.get("fullName") or owner.get("full_name") or ""),
        "bio": str(owner.get("biography") or owner.get("bio") or post.get("ownerBio") or ""),
        "caption": caption,
        "hashtags": hashtags,
        "followers": _safe_int(post.get("ownerFollowersCount") or owner.get("followersCount") or owner.get("followers")),
        "likes": _safe_int(post.get("likesCount") or post.get("likes"), 0),
        "comments": _safe_int(post.get("commentsCount") or post.get("comments"), 0),
        "is_private": bool(post.get("ownerIsPrivate") or owner.get("isPrivate") or owner.get("private")),
        "posts_count": _safe_int(owner.get("postsCount") or owner.get("mediaCount"), 0),
        "is_business": bool(owner.get("isBusinessAccount") or False),
        "business_category": str(owner.get("businessCategoryName") or ""),
        "post_url": str(post.get("url") or ""),
        "sample_post_url": str(post.get("url") or ""),
        "timestamp": str(post.get("timestamp") or ""),
        "location_name": str(post.get("locationName") or post.get("location") or ""),
        "source_hashtag": source_hashtag,
        "source_hashtags": [source_hashtag],
        "source_content_type": content_type,
        "external_url": "",
        "profile_url": f"https://www.instagram.com/{username}/",
        "enriched": False,
    }


async def scrape_hashtag(
    session: aiohttp.ClientSession,
    keys: KeyRing,
    hashtag: str,
    limit: int,
    log: Callable[[str], None],
) -> list[dict]:
    clean = normalize_hashtag(hashtag).lstrip("#")
    if not clean:
        return []
    limit = max(5, min(int(limit), POSTS_PER_HASHTAG))
    payload = {"hashtags": [clean], "resultsType": "posts", "resultsLimit": limit}
    rows = await _run_actor(session, ACTOR_HASHTAG, payload, keys, timeout=100, log=log)
    content_type = "posts"

    if len(rows) < max(5, limit // 4):
        reel_payload = {"hashtags": [clean], "resultsType": "reels", "resultsLimit": limit}
        reel_rows = await _run_actor(session, ACTOR_HASHTAG, reel_payload, keys, timeout=100, log=log)
        if len(reel_rows) > len(rows):
            rows = reel_rows
            content_type = "reels"

    seen: set[str] = set()
    normalized: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        post = _normalize_post(row, clean, content_type)
        if not post or post["username"] in seen:
            continue
        seen.add(post["username"])
        normalized.append(post)
    log(f"#{clean}: {len(rows)} {content_type} rows -> {len(normalized)} unique usernames")
    return normalized


def extract_co_hashtags(posts: list[dict], seed_tags: Iterable[str], top_n: int = 20) -> list[dict]:
    seed = {normalize_hashtag(tag).lstrip("#") for tag in seed_tags}
    freq: dict[str, int] = {}
    for post in posts:
        for tag in post.get("hashtags") or []:
            clean = normalize_hashtag(tag).lstrip("#")
            if not clean or clean in seed or clean in SPAM_TAGS:
                continue
            freq[clean] = freq.get(clean, 0) + 1
    rows = [{"tag": f"#{tag}", "count": count} for tag, count in sorted(freq.items(), key=lambda x: -x[1])]
    return rows[:top_n]


def _pre_niche_hits(post: dict, niche: str) -> int:
    terms = _terms_for_niche(niche)
    text = _clean_text(
        post.get("caption"),
        " ".join(post.get("hashtags") or []),
        post.get("source_hashtag"),
        post.get("full_name"),
    ).lower()
    return sum(1 for term in terms if term in text)


def pre_filter_candidates(posts: list[dict], niche: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for post in posts:
        username = post.get("username", "").strip().lower()
        if not username:
            continue
        if username not in seen:
            seen[username] = dict(post)
            seen[username]["all_captions"] = [post.get("caption", "")]
            seen[username]["source_hashtags"] = list(dict.fromkeys(post.get("source_hashtags") or []))
        else:
            existing = seen[username]
            caption = post.get("caption", "")
            if caption:
                existing["all_captions"].append(caption)
                existing["caption"] = (existing.get("caption", "") + " " + caption)[:2500]
            for tag in post.get("hashtags") or []:
                if tag not in existing.get("hashtags", []):
                    existing.setdefault("hashtags", []).append(tag)
            for tag in post.get("source_hashtags") or []:
                if tag not in existing["source_hashtags"]:
                    existing["source_hashtags"].append(tag)
            if post.get("likes", 0) > existing.get("likes", 0):
                existing["likes"] = post.get("likes", 0)
                existing["sample_post_url"] = post.get("sample_post_url", "")
                existing["source_hashtag"] = post.get("source_hashtag", "")

    candidates: list[dict] = []
    for username, post in seen.items():
        post["pre_reject_reason"] = ""
        if post.get("is_private"):
            post["pre_reject_reason"] = "private account"
            continue
        if BUSINESS_REJECT.search(_clean_text(username, post.get("full_name"))):
            post["pre_reject_reason"] = "hard business pattern in name"
            continue
        hits = _pre_niche_hits(post, niche)
        if hits == 0:
            post["pre_reject_reason"] = "no niche signal in post"
            continue
        post["niche_hits"] = hits
        candidates.append(post)

    candidates.sort(key=lambda c: (-c.get("niche_hits", 0), -c.get("likes", 0), c.get("username", "")))
    return candidates


def _profile_external_text(raw: dict) -> tuple[str, str]:
    external_url = str(raw.get("externalUrl") or raw.get("external_url") or raw.get("websiteUrl") or "")
    pieces = [external_url]
    for key in ("externalUrls", "bioLinks", "external_urls", "bio_links"):
        values = raw.get(key) or []
        if isinstance(values, list):
            for item in values:
                if isinstance(item, dict):
                    pieces.append(str(item.get("url") or item.get("lynx_url") or ""))
                else:
                    pieces.append(str(item))
    return external_url, " ".join(pieces)


def _latest_post_context(raw: dict) -> tuple[str, list[str], str]:
    latest = raw.get("latestPosts") or raw.get("latest_posts") or raw.get("posts") or []
    captions: list[str] = []
    hashtags: list[str] = []
    sample_url = ""
    if isinstance(latest, list):
        for item in latest[:12]:
            if not isinstance(item, dict):
                continue
            caption = str(item.get("caption") or "")
            if caption:
                captions.append(caption)
            if not sample_url:
                sample_url = str(item.get("url") or "")
            for tag in item.get("hashtags") or []:
                clean = str(tag).strip().lstrip("#").lower()
                if clean and clean not in hashtags:
                    hashtags.append(clean)
            for tag in re.findall(r"#([A-Za-z0-9_]{3,40})", caption):
                clean = tag.lower()
                if clean not in hashtags:
                    hashtags.append(clean)
    return " ".join(captions)[:3000], hashtags, sample_url


async def enrich_profiles(
    session: aiohttp.ClientSession,
    keys: KeyRing,
    candidates: list[dict],
    log: Callable[[str], None],
    max_to_enrich: int = MAX_CANDIDATES_BEFORE_ENRICH,
) -> list[dict]:
    to_enrich = candidates[:max_to_enrich]
    usernames = [c["username"] for c in to_enrich]
    log(f"Enriching {len(usernames)} profiles in batches of {ENRICH_BATCH_SIZE}")

    raw_profiles: list[dict] = []
    for start in range(0, len(usernames), ENRICH_BATCH_SIZE):
        chunk = usernames[start:start + ENRICH_BATCH_SIZE]
        payload = {"usernames": chunk, "includeAboutSection": False}
        batch = await _run_actor(session, ACTOR_PROFILE, payload, keys, timeout=ENRICH_TIMEOUT, log=log)
        raw_profiles.extend(item for item in batch if isinstance(item, dict))
        log(f"Profile batch {start // ENRICH_BATCH_SIZE + 1}: {len(batch)} returned")

    profile_map: dict[str, dict] = {}
    for raw in raw_profiles:
        username = str(raw.get("username") or "").strip().lower()
        if username:
            profile_map[username] = raw

    enriched_count = 0
    for candidate in to_enrich:
        raw = profile_map.get(candidate["username"])
        if not raw:
            continue
        enriched_count += 1
        external_url, external_text = _profile_external_text(raw)
        latest_captions, latest_hashtags, latest_url = _latest_post_context(raw)
        bio = str(raw.get("biography") or raw.get("bio") or candidate.get("bio") or "")
        all_hashtags = list(candidate.get("hashtags") or [])
        for tag in latest_hashtags:
            if tag not in all_hashtags:
                all_hashtags.append(tag)
        candidate.update({
            "full_name": str(raw.get("fullName") or raw.get("full_name") or candidate.get("full_name") or ""),
            "bio": bio,
            "followers": _safe_int(raw.get("followersCount") or raw.get("followers"), 0),
            "following": _safe_int(raw.get("followsCount") or raw.get("following"), 0),
            "posts_count": _safe_int(raw.get("postsCount") or raw.get("mediaCount"), 0),
            "is_private": bool(raw.get("private") or raw.get("isPrivate") or candidate.get("is_private")),
            "is_business": bool(raw.get("isBusinessAccount") or raw.get("isBusiness") or candidate.get("is_business")),
            "business_category": str(raw.get("businessCategoryName") or raw.get("category") or candidate.get("business_category") or ""),
            "external_url": external_url,
            "thumbnail": str(raw.get("profilePicUrl") or raw.get("profile_pic_url") or ""),
            "is_verified": bool(raw.get("verified") or raw.get("isVerified")),
            "recent_captions": latest_captions or candidate.get("caption", ""),
            "hashtags": all_hashtags,
            "sample_post_url": latest_url or candidate.get("sample_post_url", ""),
            "email": _extract_email(_clean_text(bio, external_text)),
            "phone": _extract_phone(_clean_text(bio, external_text)),
            "enriched": True,
        })

    log(f"Enriched {enriched_count}/{len(to_enrich)} profiles")
    return to_enrich


def _niche_confidence(creator: dict, niche: str) -> tuple[int, list[str]]:
    terms = _terms_for_niche(niche)
    content_text = _clean_text(
        creator.get("username"),
        creator.get("full_name"),
        creator.get("bio"),
    ).lower()
    caption_text = re.sub(r"#\w+", " ", _clean_text(creator.get("caption"), creator.get("recent_captions"))).lower()
    hashtag_text = _clean_text(" ".join(creator.get("hashtags") or []), " ".join(creator.get("source_hashtags") or [])).lower()
    text = f"{content_text} {caption_text} {hashtag_text}"
    hits = [term for term in sorted(terms, key=len, reverse=True) if term in text]
    content_hits = [term for term in hits if term in content_text or term in caption_text]
    score = min(100, len(hits) * 16 + len(content_hits) * 12)
    if any(term in f"{content_text} {caption_text}" for term in ("skincareformen", "menskincare", "mensgrooming", "groomingformen")):
        score = max(score, 70)
    elif not content_hits and hits:
        score = min(score, 45)
    if any(term in f"{content_text} {caption_text}" for term in ("serum", "cleanser", "sunscreen", "moisturizer", "facewash")):
        score += 10
    return min(score, 100), hits[:8]


def _india_confidence(creator: dict, location_hints: list[str]) -> tuple[int, list[str]]:
    text = _clean_text(
        creator.get("username"),
        creator.get("full_name"),
        creator.get("bio"),
        creator.get("caption"),
        creator.get("recent_captions"),
        creator.get("external_url"),
        creator.get("phone"),
        creator.get("location_name"),
        " ".join(creator.get("hashtags") or []),
        " ".join(creator.get("source_hashtags") or []),
    )
    score = 0
    evidence: list[str] = []
    if INDIA_SIGNAL_RE.search(text):
        score += 35
        evidence.append("India/location/language signal")
    if INDIAN_BRANDS_RE.search(text):
        score += 25
        evidence.append("Indian brand signal")
    if HINGLISH_RE.search(text):
        score += 15
        evidence.append("Hinglish signal")
    if re.search(r"(?:\+?91|wa\.me/91|\.in\b|\.co\.in\b)", text, re.IGNORECASE):
        score += 25
        evidence.append("Indian contact/domain signal")
    for hint in location_hints:
        if hint and str(hint).lower() in text.lower():
            score += 20
            evidence.append(f"matches {hint}")
            break
    return min(score, 100), evidence[:5]


def _gender_confidence(creator: dict, gender_filter: str) -> tuple[int, list[str]]:
    if gender_filter == "ANY":
        return 100, ["any gender"]
    text = _clean_text(
        creator.get("username"),
        creator.get("full_name"),
        creator.get("bio"),
        creator.get("caption"),
        creator.get("recent_captions"),
        " ".join(creator.get("hashtags") or []),
        " ".join(creator.get("source_hashtags") or []),
    )
    male_hits = len(MALE_SIGNAL_RE.findall(text))
    female_hits = len(FEMALE_SIGNAL_RE.findall(text))
    if gender_filter == "M":
        if female_hits > male_hits and female_hits >= 1:
            return 10, ["female anti-signal"]
        if male_hits:
            return min(100, 45 + male_hits * 20), ["male/grooming signal"]
        return 45, ["ambiguous male"]
    if gender_filter == "F":
        if male_hits > female_hits and male_hits >= 1:
            return 10, ["male anti-signal"]
        if female_hits:
            return min(100, 45 + female_hits * 20), ["female signal"]
        return 45, ["ambiguous female"]
    return 50, ["ambiguous"]


def _creator_confidence(creator: dict) -> tuple[int, list[str]]:
    text = _clean_text(
        creator.get("username"),
        creator.get("full_name"),
        creator.get("bio"),
        creator.get("caption"),
        creator.get("recent_captions"),
    )
    score = 20
    evidence: list[str] = []
    if CREATOR_SIGNAL_RE.search(text):
        score += 35
        evidence.append("creator/collab language")
    if creator.get("email") or creator.get("phone") or creator.get("external_url"):
        score += 20
        evidence.append("contact/link available")
    if creator.get("posts_count", 0) >= 10:
        score += 15
        evidence.append("active public profile")
    if creator.get("is_verified"):
        score += 5
    return min(score, 100), evidence[:5]


def _business_risk(creator: dict) -> tuple[int, list[str]]:
    text = _clean_text(creator.get("username"), creator.get("full_name"), creator.get("bio"))
    category = str(creator.get("business_category") or "").lower().strip()
    score = 0
    evidence: list[str] = []
    if BUSINESS_REJECT.search(text):
        score += 60
        evidence.append("business/store wording")
    if category in BAD_CATEGORIES:
        score += 50
        evidence.append(f"bad category: {category}")
    if creator.get("is_business") and not CREATOR_SIGNAL_RE.search(text):
        score += 20
        evidence.append("business account without creator override")
    return min(score, 100), evidence[:5]


def apply_local_profile_scoring(
    creator: dict,
    niche: str,
    min_followers: int,
    max_followers: int,
    gender_filter: str,
    location_hints: list[str],
) -> dict:
    followers = _safe_int(creator.get("followers"), 0)
    reject_reason = ""
    review_reason = ""

    niche_conf, niche_hits = _niche_confidence(creator, niche)
    india_conf, india_evidence = _india_confidence(creator, location_hints)
    gender_conf, gender_evidence = _gender_confidence(creator, gender_filter)
    creator_conf, creator_evidence = _creator_confidence(creator)
    business_risk, business_evidence = _business_risk(creator)

    if creator.get("is_private"):
        reject_reason = "private account"
    elif not creator.get("enriched") or followers <= 0:
        reject_reason = "missing follower data after enrichment"
    elif followers < min_followers:
        reject_reason = f"followers below minimum ({followers})"
    elif max_followers > 0 and followers > max_followers:
        reject_reason = f"followers above maximum ({followers})"
    elif NON_INDIA_RE.search(_clean_text(creator.get("bio"), creator.get("location_name"))):
        reject_reason = "explicit non-India signal"
    elif business_risk >= 80 and creator_conf < 60:
        reject_reason = "business/store profile"
    elif business_risk >= 50 and niche_conf < 60:
        reject_reason = "business/store profile"
    elif niche_conf < 25:
        reject_reason = "weak niche evidence"
    elif niche_conf < 40 and creator_conf < 30:
        reject_reason = "weak niche/creator evidence"
    elif gender_filter != "ANY" and gender_conf < 25:
        reject_reason = "gender anti-match"

    local_score = round(
        niche_conf * 0.35
        + india_conf * 0.25
        + gender_conf * 0.20
        + creator_conf * 0.15
        + max(0, 100 - business_risk) * 0.05,
        1,
    )

    if reject_reason:
        status = "rejected"
    elif india_conf < 25:
        status = "review"
        review_reason = "weak India evidence"
    elif creator_conf < 35:
        status = "review"
        review_reason = "weak creator evidence"
    elif local_score >= 70 and niche_conf >= 55 and (gender_filter == "ANY" or gender_conf >= 45):
        status = "high"
    else:
        status = "review"
        review_reason = "borderline local confidence"

    evidence = []
    if niche_hits:
        evidence.append("niche: " + ", ".join(niche_hits[:5]))
    evidence.extend(india_evidence)
    evidence.extend(gender_evidence[:1])
    evidence.extend(creator_evidence[:2])
    evidence.extend(business_evidence[:1])

    creator.update({
        "niche_confidence": niche_conf,
        "india_confidence": india_conf,
        "gender_confidence": gender_conf,
        "creator_confidence": creator_conf,
        "business_risk": business_risk,
        "local_match_score": local_score,
        "match_status": status,
        "reject_reason": reject_reason,
        "review_reason": review_reason,
        "evidence": " | ".join(evidence[:8]),
        "genre_match": ", ".join(niche_hits[:5]),
        "location_score": 1 if india_conf >= 25 else 0,
        "recent_captions": creator.get("recent_captions") or creator.get("caption", ""),
    })
    return creator


def post_enrich_filter(
    candidates: list[dict],
    min_followers: int,
    max_followers: int,
    gender_filter: str,
    location_hints: list[str],
    niche: str,
) -> list[dict]:
    scored = [
        apply_local_profile_scoring(c, niche, min_followers, max_followers, gender_filter, location_hints)
        for c in candidates
    ]
    scored.sort(key=lambda c: (
        0 if c.get("match_status") == "high" else 1 if c.get("match_status") == "review" else 2,
        -float(c.get("local_match_score") or 0),
        -int(c.get("followers") or 0),
    ))
    return scored


def apply_instagram_graph_gate(
    creators: list[dict],
    location_hints: list[str],
    include_rejected: bool = False,
) -> list[dict]:
    """Keep graph expansion broad, but only surface brief/location-fit rows."""
    require_location = bool([hint for hint in location_hints if str(hint).strip()])
    gated: list[dict] = []
    for creator in creators:
        india_conf = _safe_int(creator.get("india_confidence"), 0)
        text = _clean_text(
            creator.get("username"),
            creator.get("full_name"),
            creator.get("bio"),
            creator.get("recent_captions"),
            creator.get("external_url"),
        )
        if creator.get("match_status") != "rejected":
            if require_location and india_conf < 25:
                creator["match_status"] = "rejected"
                creator["reject_reason"] = "missing India/location evidence"
            elif india_conf < 25 and FOREIGN_SIGNAL_RE.search(text):
                creator["match_status"] = "rejected"
                creator["reject_reason"] = "foreign profile without India evidence"
            elif india_conf >= 25 and FOREIGN_SIGNAL_RE.search(text):
                creator["review_reason"] = creator.get("review_reason") or "has foreign signal; review India fit"
                if creator.get("match_status") == "high":
                    creator["match_status"] = "review"
        if include_rejected or creator.get("match_status") != "rejected":
            gated.append(creator)
    gated.sort(key=lambda c: (
        0 if c.get("match_status") == "high" else 1,
        -float(c.get("local_match_score") or 0),
        int(c.get("ig_discovery_depth") or 0),
        -int(c.get("followers") or 0),
    ))
    return gated


def normalize_instagram_username(value: object) -> str:
    """Normalize an Instagram URL, @handle, or plain handle to a username."""
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(
        r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]{2,30})(?:[/?#]|$)",
        text,
        re.IGNORECASE,
    )
    if match:
        text = match.group(1)
    else:
        text = text.lstrip("@").split("?", 1)[0].split("#", 1)[0].strip("/")
    if not re.fullmatch(r"[A-Za-z0-9._]{2,30}", text):
        return ""
    username = text.lower()
    return "" if username in INSTAGRAM_RESERVED_PATHS else username


def instagram_seeds_from_youtube(creators: list[dict]) -> list[dict]:
    """Collect unique Instagram seeds exposed by completed YouTube result rows."""
    seeds: dict[str, dict] = {}
    for creator in creators:
        if creator.get("platform") != "youtube":
            continue
        username = ""
        for field in ("instagram_url", "instagram", "instagram_handle", "ig_username", "ig_handle"):
            username = normalize_instagram_username(creator.get(field))
            if username:
                break
        if not username:
            continue
        if username not in seeds:
            seeds[username] = {
                "username": username,
                "seed_username": username,
                "source_username": username,
                "discovery_depth": 0,
                "source_youtube_channel": str(creator.get("channel_name") or creator.get("handle") or ""),
                "source_youtube_url": str(creator.get("channel_url") or creator.get("handle_url") or ""),
            }
    return list(seeds.values())


def _related_usernames(raw: dict) -> list[str]:
    """Read related handles across the documented and common Instagram shapes."""
    values = (
        raw.get("edge_related_profiles")
        or raw.get("relatedProfiles")
        or raw.get("related_profiles")
        or []
    )
    if isinstance(values, dict):
        values = values.get("edges") or values.get("nodes") or values.get("items") or []
    usernames: list[str] = []
    if not isinstance(values, list):
        return usernames
    for item in values:
        node = item.get("node", item) if isinstance(item, dict) else item
        candidate = (
            node.get("username") or node.get("userName") or node.get("url") or ""
            if isinstance(node, dict)
            else node
        )
        username = normalize_instagram_username(candidate)
        if username and username not in usernames:
            usernames.append(username)
    return usernames


def _figue_profile_to_creator(raw: dict, provenance: dict) -> Optional[dict]:
    username = normalize_instagram_username(raw.get("username") or provenance.get("username"))
    if not username:
        return None
    external_url, external_text = _profile_external_text(raw)
    latest_captions, latest_hashtags, latest_url = _latest_post_context(raw)
    latest_posts = raw.get("latestPosts") or raw.get("latest_posts") or raw.get("posts") or []
    if not isinstance(latest_posts, list):
        latest_posts = []
    latest_reel_url = next(
        (
            str(post.get("video_url") or post.get("videoUrl") or "")
            for post in latest_posts
            if isinstance(post, dict) and (post.get("video_url") or post.get("videoUrl"))
        ),
        "",
    )
    bio = str(raw.get("biography") or raw.get("bio") or "")
    related = _related_usernames(raw)
    email = str(raw.get("business_email") or raw.get("businessEmail") or "").strip()
    phone = str(raw.get("business_phone_number") or raw.get("businessPhoneNumber") or "").strip()
    return {
        "platform": "instagram",
        "username": username,
        "full_name": str(raw.get("full_name") or raw.get("fullName") or ""),
        "bio": bio,
        "caption": latest_captions,
        "recent_captions": latest_captions,
        "hashtags": latest_hashtags,
        "source_hashtags": [],
        "followers": _safe_int(raw.get("followersCount") or raw.get("followers"), 0),
        "following": _safe_int(raw.get("followsCount") or raw.get("following"), 0),
        "posts_count": _safe_int(raw.get("postsCount") or raw.get("mediaCount"), 0),
        "is_private": bool(raw.get("is_private") or raw.get("private") or raw.get("isPrivate")),
        "is_business": bool(raw.get("is_business_account") or raw.get("isBusinessAccount") or raw.get("isBusiness")),
        "business_category": str(raw.get("category_name") or raw.get("businessCategoryName") or raw.get("category") or ""),
        "profile_url": f"https://www.instagram.com/{username}/",
        "external_url": external_url,
        "thumbnail": str(raw.get("profile_pic_url_hd") or raw.get("profilePicUrlHD") or raw.get("profile_pic_url") or raw.get("profilePicUrl") or ""),
        "is_verified": bool(raw.get("is_verified") or raw.get("verified") or raw.get("isVerified")),
        "sample_post_url": latest_url,
        "latest_posts": latest_posts[:12],
        "latest_reel_url": latest_reel_url,
        "email": email or _extract_email(_clean_text(bio, external_text)),
        "phone": phone or _extract_phone(_clean_text(bio, external_text)),
        "related_profiles": related,
        "ig_discovery_source": "youtube_seed" if provenance.get("discovery_depth", 0) == 0 else "related_profile",
        "ig_discovery_depth": int(provenance.get("discovery_depth", 0)),
        "ig_seed_username": str(provenance.get("seed_username") or username),
        "ig_parent_username": str(provenance.get("source_username") or ""),
        "source_youtube_channel": str(provenance.get("source_youtube_channel") or ""),
        "source_youtube_url": str(provenance.get("source_youtube_url") or ""),
        "enriched": True,
    }


async def _scrape_figue_profiles(
    session: aiohttp.ClientSession,
    keys: KeyRing,
    targets: list[dict],
    log: Callable[[str], None],
) -> list[tuple[dict, dict]]:
    results: list[tuple[dict, dict]] = []
    for start in range(0, len(targets), RELATED_PROFILE_BATCH_SIZE):
        chunk = targets[start:start + RELATED_PROFILE_BATCH_SIZE]
        usernames = [str(item.get("username") or "") for item in chunk if item.get("username")]
        payload = {"profiles": usernames, "includeRecentPosts": True}
        rows = await _run_actor(session, ACTOR_RELATED_PROFILE, payload, keys, timeout=ENRICH_TIMEOUT, log=log)
        provenance = {item["username"]: item for item in chunk if item.get("username")}
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            username = normalize_instagram_username(raw.get("username"))
            if username and username in provenance:
                results.append((raw, provenance[username]))
        log(f"Instagram graph batch {start // RELATED_PROFILE_BATCH_SIZE + 1}: {len(rows)} returned")
    return results


async def run_ig_related_search_from_youtube(
    yt_creators: list[dict],
    profile_api_keys: str | Iterable[str],
    min_followers: int,
    max_followers: int,
    location_hints: list[str],
    gender_filter: str = "ANY",
    niche: str = "",
    progress_callback: Optional[Callable[[str], None]] = None,
    related_depth: int = RELATED_PROFILE_DEPTH,
    max_related_per_profile: int = MAX_RELATED_PER_PROFILE,
    max_related_per_hop: int = MAX_RELATED_PER_HOP,
    include_rejected: bool = False,
    debug_state: Optional[dict] = None,
) -> list[dict]:
    """Discover Instagram creators from YouTube-linked profiles and their graph."""

    def log(message: str) -> None:
        print(f"[IG Graph] {message}")
        if progress_callback:
            try:
                progress_callback(message)
            except Exception:
                pass

    seeds = instagram_seeds_from_youtube(yt_creators)
    debug = debug_state if debug_state is not None else {}
    debug.clear()
    debug.update({
        "youtube_seed_profiles": len(seeds),
        "levels": [],
        "fetched_profiles": 0,
        "sample_profile_fields": [],
        "related_field_names": [],
        "related_profiles_discovered": 0,
    })
    if not seeds:
        log("No YouTube creators exposed an Instagram handle")
        return []

    profile_keys = KeyRing(profile_api_keys)
    if not profile_keys.has_keys():
        log("Missing Apify profile keys")
        return []

    max_depth = max(0, min(int(related_depth), 2))
    per_profile_limit = max(1, int(max_related_per_profile))
    hop_limit = max(1, int(max_related_per_hop))
    fetched: set[str] = set()
    creators: dict[str, dict] = {}
    frontier = seeds

    log(f"Instagram graph: {len(seeds)} YouTube-linked seed profile(s), {max_depth} related hop(s)")
    async with aiohttp.ClientSession() as session:
        for depth in range(max_depth + 1):
            pending = [item for item in frontier if item["username"] not in fetched]
            if not pending:
                break
            fetched.update(item["username"] for item in pending)
            scraped = await _scrape_figue_profiles(session, profile_keys, pending, log)
            next_targets: dict[str, dict] = {}
            for raw, provenance in scraped:
                if not debug["sample_profile_fields"]:
                    debug["sample_profile_fields"] = sorted(str(key) for key in raw.keys())
                for key in raw:
                    if ("related" in str(key).lower() or "edge" in str(key).lower()) and str(key) not in debug["related_field_names"]:
                        debug["related_field_names"].append(str(key))
                creator = _figue_profile_to_creator(raw, provenance)
                if not creator:
                    continue
                creators[creator["username"]] = creator
                debug["related_profiles_discovered"] += len(creator.get("related_profiles", []))
                if depth >= max_depth:
                    continue
                for related_username in creator.get("related_profiles", [])[:per_profile_limit]:
                    if related_username in fetched or related_username in next_targets:
                        continue
                    next_targets[related_username] = {
                        "username": related_username,
                        "seed_username": creator["ig_seed_username"],
                        "source_username": creator["username"],
                        "discovery_depth": depth + 1,
                        "source_youtube_channel": creator["source_youtube_channel"],
                        "source_youtube_url": creator["source_youtube_url"],
                    }
            frontier = list(next_targets.values())[:hop_limit]
            debug["levels"].append({
                "depth": depth,
                "requested": len(pending),
                "returned": len(scraped),
                "next_related": len(frontier),
            })
            log(f"Depth {depth}: enriched {len(scraped)} profile(s); queued {len(frontier)} related profile(s)")

    debug["fetched_profiles"] = len(creators)
    if not creators:
        log("Instagram actor returned no enriched profiles")
        return []

    scored = post_enrich_filter(
        list(creators.values()),
        min_followers=min_followers,
        max_followers=max_followers,
        gender_filter=gender_filter,
        location_hints=location_hints,
        niche=niche,
    )
    gated = apply_instagram_graph_gate(scored, location_hints, include_rejected=include_rejected)
    debug["surface_profiles"] = len(gated)
    debug["rejected_or_hidden"] = len(scored) - len(gated)
    log(f"Instagram graph complete: {len(scored)} enriched profile(s), {len(gated)} surfaced after brief/location gate")
    return gated


async def run_ig_search(
    api_key: str | Iterable[str],
    hashtags: list[str],
    min_followers: int,
    max_followers: int,
    location_hints: list[str],
    posts_per_tag: int = POSTS_PER_HASHTAG,
    gender_filter: str = "ANY",
    niche: str = "",
    progress_callback: Optional[Callable[[str], None]] = None,
    profile_api_keys: str | Iterable[str] | None = None,
    debug_state: Optional[dict] = None,
) -> list[dict]:
    """Run deterministic Instagram hashtag-to-profile discovery."""

    def log(message: str) -> None:
        print(f"[IG] {message}")
        if progress_callback:
            try:
                progress_callback(message)
            except Exception:
                pass

    debug = debug_state if debug_state is not None else {}
    debug.clear()
    debug.update({"hashtags": [], "co_hashtags": [], "funnel": {}})

    discovery_keys = KeyRing(api_key)
    profile_keys = KeyRing(profile_api_keys if profile_api_keys is not None else api_key)
    posts_per_tag = max(5, min(int(posts_per_tag), POSTS_PER_HASHTAG))

    seed_tags: list[str] = []
    for tag in hashtags:
        clean = normalize_hashtag(tag)
        if clean and clean not in seed_tags:
            seed_tags.append(clean)
    seed_tags = seed_tags[:MAX_FINAL_HASHTAGS if "MAX_FINAL_HASHTAGS" in globals() else 15]

    if not seed_tags:
        log("No valid hashtags provided")
        return []
    if not discovery_keys.has_keys() or not profile_keys.has_keys():
        log("Missing Apify discovery/profile keys")
        return []

    log(f"Scraping {len(seed_tags)} verified hashtags ({posts_per_tag} max rows each)")
    all_posts: list[dict] = []

    async with aiohttp.ClientSession() as session:
        semaphore = asyncio.Semaphore(4)

        async def scrape_one(tag: str) -> tuple[str, list[dict]]:
            async with semaphore:
                rows = await scrape_hashtag(session, discovery_keys, tag, posts_per_tag, log)
                return tag, rows

        scrape_results = await asyncio.gather(*(scrape_one(tag) for tag in seed_tags), return_exceptions=True)
        per_tag_posts: dict[str, int] = {}
        for result in scrape_results:
            if isinstance(result, Exception):
                log(f"Hashtag scrape error: {result}")
                continue
            tag, posts = result
            clean = tag.lstrip("#")
            per_tag_posts[clean] = len(posts)
            all_posts.extend(posts)

        debug["funnel"]["raw_posts"] = len(all_posts)
        if not all_posts:
            debug["hashtags"] = [
                {"tag": tag, "status": "skipped", "posts_scraped": 0, "candidates_found": 0, "reason": "no posts returned"}
                for tag in seed_tags
            ]
            log("No posts collected from hashtags")
            return []

        debug["co_hashtags"] = extract_co_hashtags(all_posts, seed_tags)

        candidates = pre_filter_candidates(all_posts, niche)
        debug["funnel"]["pre_filter_candidates"] = len(candidates)
        log(f"Pre-filter: {len(all_posts)} posts -> {len(candidates)} candidate usernames")
        
        # DEBUG: log all posts and pre-filter result
        if _DEBUG_LOG:
            log_ig_raw(all_posts, candidates)

        per_tag_candidates: dict[str, int] = {tag.lstrip("#"): 0 for tag in seed_tags}
        for candidate in candidates:
            for tag in candidate.get("source_hashtags") or []:
                if tag in per_tag_candidates:
                    per_tag_candidates[tag] += 1
        debug["hashtags"] = [
            {
                "tag": tag,
                "status": "selected",
                "posts_scraped": per_tag_posts.get(tag.lstrip("#"), 0),
                "candidates_found": per_tag_candidates.get(tag.lstrip("#"), 0),
                "reason": "scraped",
            }
            for tag in seed_tags
        ]

        if not candidates:
            log("No candidates passed pre-filter")
            return []

        enriched = await enrich_profiles(
            session,
            profile_keys,
            candidates[:MAX_CANDIDATES_BEFORE_ENRICH],
            log,
            max_to_enrich=MAX_CANDIDATES_BEFORE_ENRICH,
        )
        debug["funnel"]["enriched_or_attempted"] = len(enriched)

    final = post_enrich_filter(
        enriched,
        min_followers=min_followers,
        max_followers=max_followers,
        gender_filter=gender_filter,
        location_hints=location_hints,
        niche=niche,
    )
    debug["funnel"]["high_match"] = sum(1 for c in final if c.get("match_status") == "high")
    debug["funnel"]["review"] = sum(1 for c in final if c.get("match_status") == "review")
    debug["funnel"]["rejected"] = sum(1 for c in final if c.get("match_status") == "rejected")
    log(
        "Local scoring: "
        f"{debug['funnel']['high_match']} high, "
        f"{debug['funnel']['review']} review, "
        f"{debug['funnel']['rejected']} rejected"
    )
    return final
