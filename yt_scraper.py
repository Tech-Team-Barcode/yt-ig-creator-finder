"""
YouTube Creator Scraper.

Uses the YouTube Data API v3 directly. The search layer accepts a structured
search plan so the app can combine video searches, direct channel searches,
deterministic male-creator queries, user-provided phrases, and grounded AI
query suggestions.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

import aiohttp


YT_API_BASE = "https://www.googleapis.com/youtube/v3"

SAFE_SEARCH_NEGATIVES = {
    "clinic", "doctor", "dr", "dermatologist", "hospital", "transplant",
    "salon", "shop", "store", "academy", "institute", "school", "college",
}

BUSINESS_TITLE_RE = re.compile(
    r"\b(news|tv|network|official channel|pvt\.?\s*ltd|private limited|llp|"
    r"limited|company|ministry|government|university|school|college|academy|"
    r"institute|hospital|clinic|salon|spa|store|shop|wholesale|distributor|"
    r"manufacturer|dealer|music label|record label|brand)\b",
    re.IGNORECASE,
)

BUSINESS_DESC_RE = re.compile(
    r"\b(india'?s leading|world'?s leading|our products|our product|"
    r"products?\s+(?:developed|crafted|available|delivered|designed)|"
    r"free shipping|free returns|buy now|shop now|order now|cash on delivery|"
    r"official page|official account|brand page|grooming brand|hair color brand|"
    r"skincare brand|cosmetic brand|venture|paraben free|sulphate free|"
    r"dermatolog|cosmetic surger|aesthetic|hair transplant)\b",
    re.IGNORECASE,
)

AGGREGATOR_RE = re.compile(
    r"https?://[^\s\"'<>]*(linktr\.ee|beacons\.ai|bio\.link|linkin\.bio|"
    r"stan\.store|allmylinks|campsite\.bio|komi\.io|carrd\.co)[^\s\"'<>]*",
    re.IGNORECASE,
)

FEMALE_SIGNAL_RE = re.compile(
    r"\b(she|her|girl|girls|woman|women|lady|ladies|female|wife|mom|mommy|"
    r"mother|bride|didi|bhabhi|anjali|simran|pooja|neha|priya|riya|shreya|"
    r"tanya|megha|nidhi|sakshi|swati|shruti|isha|aarti|kavya|khushi|shalini|"
    r"sonam|jyoti|divya|komal|nisha|sneha|payal|priyanka|ananya|makeup|"
    r"bridal|mua|beauty|grwm|saree|kurti|lehenga|mehndi)\b",
    re.IGNORECASE,
)

MALE_SIGNAL_RE = re.compile(
    r"\b(he|him|boy|boys|man|men|mens|men's|male|guy|guys|gents|husband|"
    r"father|dad|bhai|bhaiya|bro|groom|beard|shaving|grooming|mens skincare|"
    r"men skincare|skincare for men|men fashion|mens fashion|men style|"
    r"hair color for men|hair colour for men|rahul|rohit|akash|aakash|sahil|"
    r"aditya|vivek|arjun|karan|varun|abhishek|harsh|manish|deepak|ayush|"
    r"nikhil|mohit|gaurav|ankit|vikram|rishi|rishabh|piyush|yash|aman|"
    r"kunal|saurabh)\b",
    re.IGNORECASE,
)

MALE_COMPACT_RE = re.compile(
    r"(mensskincare|menskincare|skincareformen|mensgrooming|malegrooming|"
    r"groomingformen|mensfashion|menfashion|hairstyleformen|haircolorformen|"
    r"haircolourformen|beardcare)"
)

MALE_CHANNEL_SIGNAL_RE = re.compile(
    r"\b(men|mens|men's|male|man|boys|boy|gents|groom|beard|shaving|grooming|"
    r"skincare for men|men skincare|mens skincare|men fashion|mens fashion|"
    r"men style|hair color for men|hair colour for men|bhai|bhaiya)\b",
    re.IGNORECASE,
)

FEMALE_CHANNEL_SIGNAL_RE = re.compile(
    r"\b(women|woman|female|girls|girl|ladies|lady|beauty|makeup|mua|grwm|"
    r"skincare routine|fashion haul|women fashion|female lifestyle|didi|"
    r"anjali|simran|pooja|neha|priya|riya|shreya|tanya|megha|nidhi|sakshi|"
    r"swati|shruti|isha|aarti|kavya|khushi|shalini|sonam|jyoti|divya|"
    r"komal|nisha|sneha|payal|priyanka|ananya)\b",
    re.IGNORECASE,
)

CREATOR_SIGNAL_RE = re.compile(
    r"\b(creator|vlogger|blogger|youtuber|content creator|influencer|lifestyle|"
    r"fashion|skincare|grooming|review|reviews|unboxing|haul|routine|vlog|"
    r"honest review|collab|collaboration|business enquiries|for business|"
    r"instagram|follow me|my channel|welcome to my channel)\b",
    re.IGNORECASE,
)

FIRST_PERSON_RE = re.compile(
    r"\b(i am|i'm|my name|my channel|my self|myself|hey guys|hello guys|hi guys|"
    r"welcome to my channel|on this channel|i share|i make|namaste|namaskar)\b",
    re.IGNORECASE,
)

CREATOR_VIDEO_RE = re.compile(
    r"\b(review|routine|vlog|tutorial|haul|unboxing|before after|transformation|"
    r"honest|try|trying|worth it|under\s*\d+|affordable|budget|tips|hacks)\b",
    re.IGNORECASE,
)

INDIA_SIGNAL_RE = re.compile(
    r"\b(india|indian|hindi|hinglish|mumbai|maharashtra|pune|gujarat|gujarati|"
    r"ahmedabad|surat|vadodara|rajkot|madhya pradesh|indore|bhopal|delhi|"
    r"bangalore|bengaluru|chennai|hyderabad|kolkata|punjab|punjabi|rajasthan|"
    r"jaipur|karnataka|kannada|tamil|telugu|marathi|kerala|malayalam|"
    r"namaste|namaskar|bhai|yaar|dost|kya|achha|bilkul|rupees?|rs\.?|inr)\b",
    re.IGNORECASE,
)

INDIAN_BRANDS_RE = re.compile(
    r"\b(minimalist|mamaearth|nykaa|mcaffeine|m caffeine|dot ?& ?key|derma co|"
    r"beardo|bombay shaving|man matters|ustraa|wow|plum|garnier india|"
    r"flipkart|myntra|ajio|meesho)\b",
    re.IGNORECASE,
)

INDIAN_MALE_NAME_RE = re.compile(
    r"\b(rahul|rohit|akash|aakash|amit|sahil|aditya|ravi|vivek|arjun|karan|"
    r"varun|saurabh|abhishek|harsh|manish|deepak|rijul|ayush|aman|nikhil|"
    r"mohit|gaurav|ankit|vikram|vikas|kunal|yash|rishi|rishabh|piyush|"
    r"dilip|vishwakarma|nishad|marathe)\b",
    re.IGNORECASE,
)

INDIAN_FEMALE_NAME_RE = re.compile(
    r"\b(anjali|simran|pooja|neha|priya|riya|shreya|tanya|megha|nidhi|"
    r"sakshi|swati|shruti|isha|aarti|kavya|khushi|shalini|sonam|jyoti|"
    r"divya|komal|nisha|sneha|payal|priyanka|ananya|ankita|kritika|"
    r"sonali|richa|risha|rhea|aishwarya|sanya|saniya|mansi|diksha|"
    r"harshita|shivani|preeti|preetika|avantika)\b",
    re.IGNORECASE,
)

NICHES_RE = re.compile(
    r"\b(hair color|hair colour|hair dye|hair transformation|hair care|hair style|"
    r"grooming|mens grooming|male grooming|beard|shaving|skincare|skin care|"
    r"face care|fashion|style|lifestyle|review|routine|before after)\b",
    re.IGNORECASE,
)


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _expand_hints(hints: list[str] | None) -> list[str]:
    result: list[str] = []
    for hint in hints or []:
        for part in re.split(r"[,/|]+|\band\b", str(hint), flags=re.IGNORECASE):
            clean = re.sub(r"\s+", " ", part.strip().lower())
            if clean and clean not in result:
                result.append(clean)
    return result


def _has_male_signal(text: str) -> bool:
    return bool(MALE_SIGNAL_RE.search(text or "") or MALE_COMPACT_RE.search(_compact(text or "")))


def _has_female_signal(text: str) -> bool:
    text = text or ""
    return bool(FEMALE_SIGNAL_RE.search(text) or INDIAN_FEMALE_NAME_RE.search(text))


def _contains_excluded_channel_term(ch: dict, exclude_terms: list[str] | None) -> bool:
    if not exclude_terms:
        return False
    sn = ch.get("snippet", {})
    channel_text = " ".join([
        sn.get("title", "") or "",
        sn.get("customUrl", "") or "",
        (sn.get("description", "") or "")[:180],
    ]).lower()
    return any(term.lower() in channel_text for term in exclude_terms if term)


class QuotaManager:
    """Rotates YouTube API keys and tracks exhausted keys."""

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

    def mark_exhausted(self, key: str) -> None:
        self.exhausted.add(key)
        print("[YT] API key quota exhausted, rotating...")

    @property
    def has_quota(self) -> bool:
        return bool(self.keys) and len(self.exhausted) < len(self.keys)


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

        request_params = dict(params)
        request_params["key"] = key
        url = f"{YT_API_BASE}/{endpoint}"

        try:
            async with self.session.get(
                url,
                params=request_params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                if resp.status in (403, 429):
                    self.quota.mark_exhausted(key)
                    return await self._get(endpoint, params)
                text = await resp.text()
                print(f"[YT] {endpoint} HTTP {resp.status}: {text[:200]}")
                return None
        except Exception as e:
            print(f"[YT] Request error: {e}")
            return None

    async def search_items(
        self,
        query: str,
        search_type: str = "video",
        region: str = "IN",
        lang_code: Optional[str] = None,
        max_results: int = 50,
        page_token: Optional[str] = None,
        negative_terms: list[str] | None = None,
    ) -> tuple[list, Optional[str]]:
        """Search videos or channels and return (items, next_page_token)."""
        search_type = "channel" if search_type == "channel" else "video"
        negatives = SAFE_SEARCH_NEGATIVES.intersection(set(negative_terms or SAFE_SEARCH_NEGATIVES))
        clean_query = query + "".join(f" -{term}" for term in sorted(negatives))

        params = {
            "part": "snippet",
            "type": search_type,
            "q": clean_query,
            "maxResults": max(1, min(int(max_results), 50)),
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


def _is_business_channel(ch: dict) -> bool:
    sn = ch.get("snippet", {})
    title = (sn.get("title") or "").lower()
    desc = (sn.get("description") or "").lower()
    if BUSINESS_TITLE_RE.search(title):
        return True
    if BUSINESS_DESC_RE.search(desc[:900]):
        return True
    return False


def _is_personal_creator(ch: dict) -> bool:
    """Fast hard gate for obvious non-creator channels."""
    sn = ch.get("snippet", {})
    st = ch.get("statistics", {})
    subs = _safe_int(st.get("subscriberCount", 0))
    vids = _safe_int(st.get("videoCount", 0))

    if _is_business_channel(ch):
        return False
    if vids < 3:
        return False
    if subs > 200_000 and vids < 15:
        return False
    if subs > 500_000 and vids < 30:
        return False
    title = sn.get("title", "") or ""
    desc = sn.get("description", "") or ""
    if title and len(title.split()) <= 2 and not (
        INDIAN_MALE_NAME_RE.search(title)
        or INDIAN_FEMALE_NAME_RE.search(title)
        or _has_male_signal(desc)
        or _has_female_signal(desc)
    ):
        return False
    return True


def _extract_contact(desc: str, links: list[str] | None = None) -> dict:
    """Extract email, phone, Instagram, website from text."""
    links = links or []
    full_text = desc + " " + " ".join(links)

    email = ""
    emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", full_text)
    junk = {"example.com", "sentry.io", "noreply", "youtube.com", "@2x", "@3x"}
    for e in emails:
        if not any(j in e.lower() for j in junk) and len(e) < 80:
            email = e
            break

    phone = ""
    m = re.search(r"(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{2,5}\)?[\s\-.]?)\d{3,5}[\s\-.]?\d{3,5}", desc)
    if m:
        digits = re.sub(r"\D", "", m.group())
        if 8 <= len(digits) <= 15:
            phone = m.group().strip()

    instagram = ""
    ig_match = re.search(
        r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]{2,30})(?![A-Za-z0-9._])",
        full_text,
        re.IGNORECASE,
    )
    if ig_match:
        handle = ig_match.group(1)
        if handle.lower() not in {"p", "reel", "tv", "explore", "stories", "accounts", "about"}:
            instagram = f"https://www.instagram.com/{handle}/"

    if not instagram:
        labeled = re.search(r"(?:ig|insta|instagram)\s*[:-]\s*@?([a-zA-Z0-9._]{3,30})", full_text, re.IGNORECASE)
        if labeled:
            instagram = f"https://www.instagram.com/{labeled.group(1)}/"

    website = ""
    social_domains = r"(youtube\.com|youtu\.be|instagram\.com|facebook\.com|twitter\.com|x\.com|tiktok\.com|linktr\.ee)"
    for link in links:
        if not re.search(social_domains, link, re.IGNORECASE):
            website = link
            break

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


def _score_creator(ch: dict, contact: dict) -> int:
    """Score basic channel quality before AI scoring."""
    sn = ch.get("snippet", {})
    st = ch.get("statistics", {})
    subs = _safe_int(st.get("subscriberCount", 0))
    views = _safe_int(st.get("viewCount", 0))
    vids = _safe_int(st.get("videoCount", 0))
    desc = (sn.get("description", "") or "").lower()
    title = (sn.get("title", "") or "").lower()

    score = 30
    if vids < 5:
        return 5

    if subs > 0:
        ratio = views / subs
        if ratio > 50:
            score += 15
        elif ratio > 30:
            score += 10
        elif ratio > 10:
            score += 5
        elif ratio < 3:
            score -= 15
        elif ratio < 5:
            score -= 5

    if 10_000 <= subs <= 100_000:
        score += 18
    elif 100_000 < subs <= 500_000:
        score += 12
    elif 5_000 <= subs < 10_000:
        score += 6

    if contact.get("email"):
        score += 20
    if contact.get("instagram_url") or contact.get("aggregator_url"):
        score += 15
    if contact.get("phone"):
        score += 8
    if CREATOR_SIGNAL_RE.search(desc + " " + title):
        score += 10
    if FIRST_PERSON_RE.search(desc):
        score += 10

    return max(5, min(95, score))


def _creator_evidence_score(ch: dict, match: dict, contact: dict) -> tuple[int, list[str]]:
    sn = ch.get("snippet", {})
    title = sn.get("title", "") or ""
    desc = sn.get("description", "") or ""
    item = match.get("item") or {}
    video_title = (item.get("snippet") or {}).get("title", "") or ""
    video_desc = (item.get("snippet") or {}).get("description", "") or ""
    full = " ".join([title, desc, video_title, video_desc, match.get("query", "")])
    signals: list[str] = []
    score = 0
    if FIRST_PERSON_RE.search(desc):
        score += 2
        signals.append("first-person bio")
    if CREATOR_SIGNAL_RE.search(full):
        score += 1
        signals.append("creator language")
    if INDIAN_MALE_NAME_RE.search(title + " " + desc[:150]):
        score += 1
        signals.append("personal/Indian male name")
    if INDIAN_FEMALE_NAME_RE.search(title + " " + desc[:150]):
        score += 1
        signals.append("personal/Indian female name")
    if contact.get("email") or contact.get("instagram_url") or contact.get("aggregator_url"):
        score += 1
        signals.append("contact/social link")
    if CREATOR_VIDEO_RE.search(video_title + " " + video_desc[:200]):
        score += 1
        signals.append("creator-style matched video")
    return score, signals


def _india_score(ch: dict, match: dict, location_hints: list[str]) -> tuple[int, str]:
    sn = ch.get("snippet", {})
    country = (sn.get("country") or "").upper()
    item = match.get("item") or {}
    video_text = " ".join([
        (item.get("snippet") or {}).get("title", "") or "",
        (item.get("snippet") or {}).get("description", "") or "",
    ])
    full = " ".join([
        sn.get("title", "") or "",
        sn.get("description", "") or "",
        ((ch.get("brandingSettings") or {}).get("channel", {}) or {}).get("keywords", "") or "",
        video_text,
    ])
    query = match.get("query", "") or ""
    score = 0
    if country == "IN":
        score += 3
    if INDIA_SIGNAL_RE.search(full):
        score += 2
    if any(hint and hint.lower() in full.lower() for hint in location_hints):
        score += 2
    if INDIAN_MALE_NAME_RE.search(full) or INDIAN_FEMALE_NAME_RE.search(full):
        score += 1
    if INDIAN_BRANDS_RE.search(full):
        score += 1
    if INDIA_SIGNAL_RE.search(query):
        score += 1

    if score >= 4:
        conf = "high"
    elif score >= 2:
        conf = "medium"
    elif score >= 1:
        conf = "low"
    else:
        conf = "unknown"
    return score, conf


def _gender_text(ch: dict, match: dict) -> str:
    sn = ch.get("snippet", {})
    item = match.get("item") or {}
    return " ".join([
        sn.get("title", "") or "",
        sn.get("customUrl", "") or "",
        sn.get("description", "") or "",
        (item.get("snippet") or {}).get("title", "") or "",
        (item.get("snippet") or {}).get("description", "") or "",
        match.get("query", "") or "",
    ])


def _gender_score(ch: dict, match: dict) -> tuple[int, bool]:
    full = _gender_text(ch, match)
    male = 1 if _has_male_signal(full) else 0
    female_conflict = _has_female_signal(full) and not _has_male_signal(full)
    if INDIAN_MALE_NAME_RE.search(full):
        male += 1
    return male, female_conflict


def _female_score(ch: dict, match: dict) -> tuple[int, bool]:
    full = _gender_text(ch, match)
    female = 1 if _has_female_signal(full) else 0
    male_conflict = _has_male_signal(full) and not _has_female_signal(full)
    if INDIAN_FEMALE_NAME_RE.search(full):
        female += 1
    return female, male_conflict


def _gender_label(male_score: int, female_score: int) -> str:
    if male_score > 0 and female_score > 0:
        return "mixed_signals"
    if male_score > 0:
        return "male"
    if female_score > 0:
        return "female"
    return "unknown"


def _niche_score(ch: dict, match: dict) -> int:
    sn = ch.get("snippet", {})
    item = match.get("item") or {}
    intent_terms = match.get("intent_terms") or []
    full = " ".join([
        sn.get("title", "") or "",
        sn.get("description", "") or "",
        (item.get("snippet") or {}).get("title", "") or "",
        (item.get("snippet") or {}).get("description", "") or "",
    ]).lower()
    score = len([term for term in intent_terms if term and str(term).lower() in full])
    if NICHES_RE.search(full):
        score += 1
    return score


def _normalize_channel(
    ch: dict,
    match: dict,
    location_hints: list[str],
    lang_hints: list[str],
    gender_filter: str,
    region: str,
    exclude_terms: list[str] | None = None,
    allow_international: bool = False,
) -> Optional[dict]:
    """Convert raw channel + matched search item to the standard creator row."""
    sn = ch.get("snippet", {})
    st = ch.get("statistics", {})
    br = (ch.get("brandingSettings") or {}).get("channel", {})
    cd = (ch.get("contentDetails") or {}).get("relatedPlaylists", {})

    channel_id = ch.get("id", "")
    desc = sn.get("description", "") or ""
    title = sn.get("title", "") or ""
    custom_url = sn.get("customUrl", "") or ""
    country = (sn.get("country") or "").upper()

    # Hard reject only if country is explicitly set to a non-target country
    # (e.g. US, GB). If country is blank/unset, fall through to india_score check.
    if not allow_international and country and country not in ("", region.upper()):
        return None

    if _contains_excluded_channel_term(ch, exclude_terms):
        return None
    if not _is_personal_creator(ch):
        return None

    urls = re.findall(r"https?://[^\s\"'<>]+", desc)
    contact = _extract_contact(desc, urls)
    creator_score, creator_signals = _creator_evidence_score(ch, match, contact)

    # Relaxed gate: at least 1 creator-evidence signal (was 2)
    if creator_score < 1:
        return None

    loc_hints = _expand_hints(location_hints)
    india_score, india_conf = _india_score(ch, match, loc_hints)

    # India gate: if region is IN and country is blank, require at least 1 india signal.
    # If allow_international, skip this gate entirely.
    if not allow_international and region.upper() == "IN" and not country and india_score < 1:
        return None

    gender_score, female_conflict = _gender_score(ch, match)
    female_score, male_conflict = _female_score(ch, match)
    inferred_gender = _gender_label(gender_score, female_score)
    if gender_filter == "M":
        channel_gender_text = " ".join([title, custom_url, desc[:500]])
        channel_male_signal = bool(
            MALE_CHANNEL_SIGNAL_RE.search(channel_gender_text)
            or MALE_COMPACT_RE.search(_compact(channel_gender_text))
            or INDIAN_MALE_NAME_RE.search(channel_gender_text)
        )
        if female_conflict or gender_score <= 0:
            return None
        if not channel_male_signal:
            return None
    elif gender_filter == "F":
        channel_gender_text = " ".join([title, custom_url, desc[:500]])
        channel_female_signal = bool(
            FEMALE_CHANNEL_SIGNAL_RE.search(channel_gender_text)
            or INDIAN_FEMALE_NAME_RE.search(channel_gender_text)
        )
        if male_conflict or female_score <= 0:
            return None
        if not channel_female_signal:
            return None

    niche_score = _niche_score(ch, match)
    # Removed hard niche_score <= 0 reject — AI scorer will handle weak-niche channels.
    # Instead penalise quality score slightly.

    quality_score = _score_creator(ch, contact)
    if gender_filter == "M":
        gender_bonus = gender_score
    elif gender_filter == "F":
        gender_bonus = female_score
    else:
        gender_bonus = max(gender_score, female_score)
    quality_score = min(95, quality_score + creator_score * 3 + india_score * 3 + gender_bonus * 3 + min(niche_score, 4) * 2)

    full_text = (title + " " + desc + " " + (br.get("keywords", "") or "")).lower()
    lang_score = sum(1 for hint in lang_hints if hint and hint.lower() in full_text)
    location_score = sum(1 for hint in loc_hints if hint and hint in full_text)

    item = match.get("item") or {}
    snippet = item.get("snippet") or {}
    vid_title = snippet.get("title", "") or ""
    vid_desc = snippet.get("description", "") or ""
    location_score += sum(1 for hint in loc_hints if hint and hint in (vid_title + " " + vid_desc).lower())
    vid_id = ""
    if isinstance(item.get("id"), dict):
        vid_id = item["id"].get("videoId", "") or ""

    # For ANY gender campaigns, don't require a positive gender_score (which only counts male signals).
    # Female creators will have gender_score=0 but should still reach "high" status.
    if gender_filter == "M":
        gender_ok = gender_score > 0
    elif gender_filter == "F":
        gender_ok = female_score > 0
    else:
        gender_ok = True
    local_status = "high" if quality_score >= 65 and india_score >= 1 and gender_ok else "review"

    return {
        "platform": "youtube",
        "match_status": local_status,
        "review_reason": "Needs AI YouTube scorer confirmation" if local_status == "review" else "",
        "reject_reason": "",
        "channel_id": channel_id,
        "channel_name": title,
        "channel_url": f"https://www.youtube.com/channel/{channel_id}",
        "handle_url": f"https://www.youtube.com/{custom_url}" if custom_url else "",
        "handle": custom_url,
        "subscribers": _safe_int(st.get("subscriberCount", 0)),
        "total_views": _safe_int(st.get("viewCount", 0)),
        "video_count": _safe_int(st.get("videoCount", 0)),
        "country": country,
        "description": desc,
        "uploads_playlist": cd.get("uploads", ""),
        "thumbnail": (sn.get("thumbnails", {}) or {}).get("medium", {}).get("url", ""),
        "channel_created": (sn.get("publishedAt", "") or "")[:10],
        "video_title": vid_title,
        "video_url": f"https://www.youtube.com/watch?v={vid_id}" if vid_id else "",
        "video_published": (snippet.get("publishedAt", "") or "")[:10],
        "email": contact["email"],
        "phone": contact["phone"],
        "instagram_url": contact["instagram_url"],
        "website": contact["website"],
        "aggregator_url": contact["aggregator_url"],
        "local_match_score": quality_score,
        "_quality_score": quality_score,
        "_lang_score": lang_score,
        "_location_score": location_score,
        "_search_query": match.get("query", ""),
        "_search_type": match.get("search_type", "video"),
        "_source": match.get("source", ""),
        "_intent_terms": match.get("intent_terms", []),
        "_negative_terms": match.get("negative_terms", []),
        "_creator_evidence_score": creator_score,
        "_creator_evidence": "; ".join(creator_signals),
        "_india_score": india_score,
        "_india_confidence": india_conf,
        "_gender_score": gender_score,
        "_female_score": female_score,
        "_gender_label": inferred_gender,
        "_niche_score": niche_score,
    }


def _channel_id_from_search_item(item: dict) -> str:
    item_id = item.get("id") if isinstance(item.get("id"), dict) else {}
    return item_id.get("channelId") or (item.get("snippet") or {}).get("channelId", "") or ""


def _coerce_search_plan(queries: list[str] | None, search_plan: list[dict] | None) -> list[dict]:
    if search_plan:
        plan = []
        for row in search_plan:
            if isinstance(row, dict) and row.get("query"):
                plan.append({
                    "query": str(row.get("query", "")).strip(),
                    "search_type": "channel" if row.get("search_type") == "channel" else "video",
                    "source": row.get("source", "analysis"),
                    "intent_terms": row.get("intent_terms", []),
                    "negative_terms": row.get("negative_terms", list(SAFE_SEARCH_NEGATIVES)),
                    "paginate": row.get("paginate", True),  # page-2 enabled by default
                })
        return plan
    return [
        {
            "query": str(query).strip(),
            "search_type": "video",
            "source": "legacy",
            "intent_terms": [],
            "negative_terms": list(SAFE_SEARCH_NEGATIVES),
            "paginate": True,
        }
        for query in (queries or [])
        if str(query).strip()
    ]


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
    progress_callback=None,
    search_plan: list[dict] | None = None,
    exclude_terms: list[str] | None = None,
    allow_international: bool = False,
    deep_search: bool = True,
) -> list[dict]:
    """
    Main async entry for YouTube search.
    1. Search all planned video/channel queries.
    2. If deep_search=True, fetch page 2 for video queries that returned a next_page_token.
    3. Batch-fetch unique channel details.
    4. Apply strict local filters and normalize for AI scoring.
    """
    plan = _coerce_search_plan(queries, search_plan)
    if not plan:
        return []

    async with aiohttp.ClientSession() as session:
        scraper = YTScraper(api_keys)
        scraper.session = session

        channel_matches: dict[str, dict] = {}
        # Track next_page_tokens for pagination; key = plan_item index
        page_tokens: dict[int, str] = {}
        semaphore = asyncio.Semaphore(3)

        def remember_match(cid: str, item: dict, plan_item: dict) -> None:
            if not cid:
                return
            existing = channel_matches.get(cid)
            match = {
                "item": item,
                "query": plan_item.get("query", ""),
                "search_type": plan_item.get("search_type", "video"),
                "source": plan_item.get("source", ""),
                "intent_terms": plan_item.get("intent_terms", []),
                "negative_terms": plan_item.get("negative_terms", []),
            }
            if not existing:
                channel_matches[cid] = match
                return
            # Prefer video-match records (have a matched video title as evidence)
            if existing.get("search_type") == "channel" and match["search_type"] == "video":
                channel_matches[cid] = match

        async def search_one(idx: int, plan_item: dict, page_token: Optional[str] = None) -> None:
            async with semaphore:
                if not scraper.quota.has_quota:
                    return
                query = plan_item.get("query", "")
                search_type = plan_item.get("search_type", "video")
                max_results = min(results_per_query, 12) if search_type == "channel" else results_per_query
                page_label = " (p2)" if page_token else ""
                if progress_callback:
                    label = "channel" if search_type == "channel" else "video"
                    progress_callback(f"YouTube {label} search{page_label}: '{query[:50]}'")
                print(f"[YT] Searching {search_type}{page_label}: '{query}'")
                items, next_token = await scraper.search_items(
                    query=query,
                    search_type=search_type,
                    region=region,
                    lang_code=lang_code,
                    max_results=max_results,
                    page_token=page_token,
                    negative_terms=plan_item.get("negative_terms"),
                )
                if progress_callback:
                    progress_callback(f"Searched{page_label}: '{query[:45]}' → {len(items)} results")
                for item in items:
                    cid = _channel_id_from_search_item(item)
                    remember_match(cid, item, plan_item)
                # Store next_page_token for page-2 pass (video only)
                if deep_search and search_type == "video" and next_token and plan_item.get("paginate", True):
                    page_tokens[idx] = next_token

        # Page 1: all queries
        await asyncio.gather(*(search_one(i, item) for i, item in enumerate(plan)))

        # Page 2: video queries that have a next page (deep_search mode)
        if deep_search and page_tokens:
            print(f"[YT] Deep search: fetching page 2 for {len(page_tokens)} video queries")
            if progress_callback:
                progress_callback(f"YouTube deep search: fetching page 2 ({len(page_tokens)} queries)")
            p2_tasks = [
                search_one(idx, plan[idx], token)
                for idx, token in page_tokens.items()
                if idx < len(plan)
            ]
            await asyncio.gather(*p2_tasks)

        if not channel_matches:
            return []

        total_unique = len(channel_matches)
        print(f"[YT] Found {total_unique} unique channels across all searches")
        if progress_callback:
            progress_callback(f"YouTube channel enrichment: {total_unique} unique channels")

        channel_ids = list(channel_matches.keys())
        all_channels: dict[str, dict] = {}
        batch_tasks = []
        for i in range(0, len(channel_ids), 50):
            batch_tasks.append(scraper.batch_fetch_channels(channel_ids[i:i + 50]))

        batch_results = await asyncio.gather(*batch_tasks)
        for result in batch_results:
            all_channels.update(result)

        results: list[dict] = []
        for cid, ch in all_channels.items():
            st = ch.get("statistics", {})
            subs = _safe_int(st.get("subscriberCount", 0))
            if subs < min_subs:
                continue
            if max_subs > 0 and subs > max_subs:
                continue
            creator = _normalize_channel(
                ch=ch,
                match=channel_matches.get(cid, {}),
                location_hints=location_hints,
                lang_hints=lang_hints,
                gender_filter=gender_filter,
                region=region,
                exclude_terms=exclude_terms,
                allow_international=allow_international,
            )
            if creator:
                results.append(creator)

        def gender_sort_score(row: dict) -> int:
            if gender_filter == "M":
                return int(row.get("_gender_score", 0) or 0)
            if gender_filter == "F":
                return int(row.get("_female_score", 0) or 0)
            return 0

        results.sort(key=lambda row: (
            0 if row.get("match_status") == "high" else 1,
            -row.get("_india_score", 0),
            -gender_sort_score(row),
            -row.get("_niche_score", 0),
            -row.get("_quality_score", 0),
        ))

        print(f"[YT] Final local candidates: {len(results)} after strict filters")
        if progress_callback:
            progress_callback(f"YouTube local filtering: {len(results)} strict candidates kept")
        return results
