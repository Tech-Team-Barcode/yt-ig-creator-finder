"""Verified Instagram hashtag planning.

The planner turns brief intent + creator-search phrases into candidate
hashtags using Apify search/analytics actors, then applies a deterministic
quality gate so broad regional blogger tags do not poison niche searches.
"""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

import aiohttp

from backend_keys import KeyRing, parse_keys

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


APIFY_BASE = "https://api.apify.com/v2"
ACTOR_SEARCH = "apify~instagram-search-scraper"
ACTOR_ANALYTICS = "apify~instagram-hashtag-analytics-scraper"

MIN_USEFUL_POSTS = 1_000
IDEAL_MIN_POSTS = 5_000
IDEAL_MAX_POSTS = 900_000
MAX_SAFE_POSTS = 5_000_000
MAX_SEARCH_TERMS = 10
MAX_FINAL_HASHTAGS = 15

GENERIC_SPAM = {
    "love", "instagood", "instagram", "insta", "photooftheday", "picoftheday",
    "follow", "like", "likes", "viral", "trending", "explore", "explorepage",
    "reels", "reelsinstagram", "fyp", "foryou", "foryoupage", "daily",
    "beautiful", "fashion", "style", "india", "mumbai", "delhi", "bangalore",
    "bengaluru", "karnataka", "kannada", "nammabengaluru", "mumbaikar",
    "mumbaidiaries", "bangalorediaries",
}

BROAD_CREATOR_TAG_RE = re.compile(
    r"^(?:kannada|karnataka|bangalore|bengaluru|mumbai|delhi|india|indian|"
    r"chennai|hyderabad|pune|marathi|hindi|tamil|telugu|malayalam)"
    r"(?:blogger|influencer|creator|contentcreator|vlogger)s?$"
)

CAMPAIGN_TAG_RE = re.compile(r"\b(ad|sponsored|gifted|giveaway|contest|collab|paidpartnership)\b")

INDIA_TERMS = {
    "india", "indian", "desi", "bharat", "mumbai", "delhi", "bangalore",
    "bengaluru", "karnataka", "kannada", "hindi", "maharashtra", "mumbaikar",
    "pune", "hyderabad", "chennai", "telugu", "tamil", "marathi",
}

MALE_TERMS = {
    "men", "mens", "male", "boys", "guy", "guys", "beard", "shaving",
    "barber", "menskincare", "mensgrooming", "skincareformen", "groomingformen",
    "beardcare",
}

FEMALE_TERMS = {
    "women", "womens", "female", "girls", "makeup", "beauty", "bridal",
    "girl", "ladies",
}

NICHE_MAP = {
    "skin": {
        "skin", "skincare", "menskincare", "skincareformen", "grooming",
        "mensgrooming", "cleanser", "serum", "sunscreen", "moisturizer",
        "acne", "spf", "facewash", "beard", "shaving", "selfcare",
    },
    "groom": {
        "grooming", "mensgrooming", "beard", "beardcare", "shaving",
        "barber", "hair", "hairstyle", "menskincare", "skincareformen",
    },
    "fashion": {"fashion", "mensfashion", "style", "ootd", "menswear", "outfit"},
    "fitness": {"fitness", "gym", "workout", "bodybuilding", "health"},
    "food": {"food", "recipe", "cooking", "chef", "foodie"},
    "tech": {"tech", "gadgets", "technology", "mobile", "review"},
    "travel": {"travel", "traveller", "wanderlust", "trip"},
    "beauty": {"beauty", "makeup", "skincare", "haircare"},
}


def normalize_hashtag(tag: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_]", "", str(tag).strip().lstrip("#").lower())
    return f"#{clean}" if clean else ""


def parse_count(value) -> int:
    if value is None:
        return -1
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower().replace(",", "")
    if not text:
        return -1
    multiplier = 1
    if text.endswith(("g", "b")):
        multiplier = 1_000_000_000
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1_000_000
        text = text[:-1]
    elif text.endswith("k"):
        multiplier = 1_000
        text = text[:-1]
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return -1
    return int(float(match.group()) * multiplier)


def count_display(count: int) -> str:
    if count is None or count < 0:
        return "unverified"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.0f}K"
    return str(count)


def niche_terms_for(intent: dict) -> set[str]:
    text = " ".join(
        str(intent.get(key) or "")
        for key in ("niche", "secondary_niche", "campaign_type")
    ).lower()
    terms: set[str] = set()
    for key, mapped in NICHE_MAP.items():
        if key in text:
            terms.update(mapped)
    for word in re.findall(r"[a-z0-9]{4,}", text):
        terms.add(word)
    if not terms:
        terms.update({"creator", "review", "routine", "lifestyle"})
    return terms


def tag_has_any(tag_name: str, terms: Iterable[str]) -> bool:
    return any(term and term in tag_name for term in terms)


def evaluate_hashtag_quality(tag: str, intent: dict, post_count: int = -1) -> dict:
    tag = normalize_hashtag(tag)
    name = tag.lstrip("#")
    niche_terms = niche_terms_for(intent)
    gender = str(intent.get("gender") or "ANY").upper()
    niche_specific_search = bool(niche_terms - {"creator", "review", "routine", "lifestyle"})

    if not tag or len(name) < 3 or len(name) > 36:
        return {"tag": tag, "selected": False, "score": 0, "reason": "invalid tag length"}
    if name in GENERIC_SPAM or CAMPAIGN_TAG_RE.search(name):
        return {"tag": tag, "selected": False, "score": 0, "reason": "generic/campaign tag"}

    has_niche = tag_has_any(name, niche_terms)
    has_india = tag_has_any(name, INDIA_TERMS)
    has_male = tag_has_any(name, MALE_TERMS)
    has_female = tag_has_any(name, FEMALE_TERMS)
    has_gender = has_male if gender == "M" else has_female if gender == "F" else (has_male or has_female)

    if niche_specific_search and BROAD_CREATOR_TAG_RE.search(name) and not (has_niche or has_gender):
        return {
            "tag": tag,
            "selected": False,
            "score": 0,
            "reason": "broad regional creator tag without niche/gender",
        }

    if niche_specific_search and not has_niche and not has_gender:
        return {"tag": tag, "selected": False, "score": 0, "reason": "no niche or gender signal"}

    if gender == "M" and has_female and not has_male:
        return {"tag": tag, "selected": False, "score": 0, "reason": "female-skewed tag for male brief"}
    if gender == "F" and has_male and not has_female:
        return {"tag": tag, "selected": False, "score": 0, "reason": "male-skewed tag for female brief"}

    if post_count != -1 and post_count < MIN_USEFUL_POSTS:
        return {"tag": tag, "selected": False, "score": 0, "reason": "too few posts"}
    if post_count > MAX_SAFE_POSTS:
        return {"tag": tag, "selected": False, "score": 0, "reason": "too broad/high volume"}

    score = 0
    if has_niche:
        score += 45
    if has_gender:
        score += 25
    if has_india:
        score += 20
    if post_count == -1:
        score += 4
    elif IDEAL_MIN_POSTS <= post_count <= IDEAL_MAX_POSTS:
        score += 12
    elif post_count >= MIN_USEFUL_POSTS:
        score += 6

    if niche_specific_search and not (has_niche or has_gender):
        score -= 30

    selected = score >= 45
    reason = "selected" if selected else "weak niche/location fit"
    return {"tag": tag, "selected": selected, "score": score, "reason": reason}


def deterministic_fallback_hashtags(intent: dict) -> list[str]:
    niche = str(intent.get("niche") or "").lower()
    gender = str(intent.get("gender") or "ANY").upper()
    city = str(intent.get("city") or "").lower().replace(" ", "")
    state = str(intent.get("state") or "").lower().replace(" ", "")

    tags: list[str] = []
    if "skin" in niche or "groom" in niche or gender == "M":
        tags.extend([
            "#indianmenskincare", "#mensgroomingindia", "#skincareformen",
            "#menskincare", "#groomingformen", "#beardcareindia",
            "#mensskincareroutine", "#indiangrooming", "#menskincareindia",
        ])
    elif "beauty" in niche or gender == "F":
        tags.extend([
            "#indianskincare", "#indianbeautyblogger", "#skincareroutineindia",
            "#indianmakeupblogger", "#beautybloggerindia",
        ])
    else:
        core = re.sub(r"[^a-z0-9]", "", niche) or "lifestyle"
        tags.extend([f"#indian{core}", f"#{core}india", f"#indian{core}creator"])

    if city:
        tags.extend([f"#{city}skincare", f"#{city}grooming", f"#{city}mensfashion"])
    if state and state not in city:
        tags.extend([f"#{state}skincare", f"#{state}grooming"])

    result = []
    for tag in tags:
        quality = evaluate_hashtag_quality(tag, intent, -1)
        if quality["selected"] and quality["tag"] not in result:
            result.append(quality["tag"])
    return result[:MAX_FINAL_HASHTAGS]


def build_search_terms(intent: dict, ig_keywords: list[str], brief: str) -> list[str]:
    niche = str(intent.get("niche") or "creator").replace("_", " ").strip()
    gender = str(intent.get("gender") or "ANY").upper()
    city = str(intent.get("city") or "").strip()
    state = str(intent.get("state") or "").strip()
    language = str(intent.get("language") or "").strip()
    location = city or state or "india"

    base_terms = [niche]
    if "skin" in niche.lower() or "groom" in niche.lower() or gender == "M":
        base_terms.extend(["men skincare", "mens grooming", "skincare for men", "beard care"])
    elif gender == "F":
        base_terms.extend([f"women {niche}", f"female {niche}"])

    terms: list[str] = []
    for base in base_terms:
        terms.append(f"{base} india")
        terms.append(f"{base} {location}")
        if language:
            terms.append(f"{base} {language}")
    terms.extend(ig_keywords)
    terms.append(brief)

    cleaned: list[str] = []
    for term in terms:
        value = re.sub(r"\s+", " ", str(term).replace("#", " ").strip().lower())
        if 4 <= len(value) <= 80 and value not in cleaned:
            cleaned.append(value)
    return cleaned[:MAX_SEARCH_TERMS]


@dataclass
class HashtagPlanner:
    api_keys: str | Iterable[str] | None
    verify: bool = True
    progress_callback: Optional[Callable[[str], None]] = None

    def __post_init__(self) -> None:
        self.keys = KeyRing(self.api_keys)

    def log(self, message: str) -> None:
        print(f"[HashtagPlanner] {message}")
        if self.progress_callback:
            try:
                self.progress_callback(message)
            except Exception:
                pass

    async def _run_actor(self, session: aiohttp.ClientSession, actor_id: str, payload: dict, timeout: int) -> list:
        if not self.keys.has_keys():
            return []
        attempts = max(1, len(self.keys))
        for _ in range(attempts):
            key = self.keys.next()
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
                        self.keys.mark_exhausted(key)
                        continue
                    if resp.status not in (200, 201):
                        text = await resp.text()
                        self.log(f"{actor_id} HTTP {resp.status}: {text[:160]}")
                        return []
                    data = await resp.json()
                    return data if isinstance(data, list) else []
            except asyncio.TimeoutError:
                self.log(f"{actor_id} timed out")
                return []
            except Exception as exc:
                self.log(f"{actor_id} error: {exc}")
                return []
        return []

    def _add_candidate(self, candidates: dict[str, dict], tag: str, post_count: int, source: str, term: str) -> None:
        quality = evaluate_hashtag_quality(tag, self.intent, post_count)
        clean = quality["tag"]
        if not clean:
            return
        existing = candidates.get(clean)
        row = {
            "tag": clean,
            "post_count": post_count,
            "count_display": count_display(post_count),
            "verified": quality["selected"] and post_count >= MIN_USEFUL_POSTS,
            "selected": quality["selected"],
            "score": quality["score"],
            "reason": quality["reason"],
            "source": source,
            "search_term": term,
        }
        if not existing or row["score"] > existing.get("score", 0):
            candidates[clean] = row

    def _extract_search_candidates(self, items: list, candidates: dict[str, dict], term: str) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            tag = (
                item.get("hash")
                or item.get("hashtag")
                or item.get("name")
                or item.get("id")
                or item.get("tag")
            )
            count = parse_count(
                item.get("postsCount")
                or item.get("mediaCount")
                or item.get("posts")
                or item.get("info")
            )
            if tag:
                self._add_candidate(candidates, tag, count, "search", term)
            for group in ("average", "rare", "related", "relatedAverage", "relatedRare", "frequent"):
                for related in item.get(group) or []:
                    if isinstance(related, dict):
                        self._add_candidate(
                            candidates,
                            related.get("hash") or related.get("name") or "",
                            parse_count(related.get("info") or related.get("postsCount")),
                            f"search:{group}",
                            term,
                        )

    async def _search_hashtags(self, session: aiohttp.ClientSession, terms: list[str]) -> dict[str, dict]:
        candidates: dict[str, dict] = {}
        semaphore = asyncio.Semaphore(3)

        async def search_term(term: str) -> None:
            async with semaphore:
                payload = {"search": term, "searchType": "hashtag", "searchLimit": 12}
                items = await self._run_actor(session, ACTOR_SEARCH, payload, timeout=70)
                self.log(f"Hashtag search '{term[:45]}' -> {len(items)} rows")
                self._extract_search_candidates(items, candidates, term)

        await asyncio.gather(*(search_term(term) for term in terms))
        return candidates

    async def _verify_with_analytics(self, session: aiohttp.ClientSession, candidates: dict[str, dict]) -> None:
        selected = [row["tag"] for row in candidates.values() if row.get("selected")]
        selected = selected[:24]
        if not selected:
            return
        payload = {
            "hashtags": [tag.lstrip("#") for tag in selected],
            "includeLatestPosts": False,
            "includeTopPosts": False,
        }
        items = await self._run_actor(session, ACTOR_ANALYTICS, payload, timeout=90)
        if not items:
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            tag = normalize_hashtag(item.get("name") or item.get("id") or "")
            if tag not in candidates:
                continue
            count = parse_count(item.get("postsCount") or item.get("posts"))
            quality = evaluate_hashtag_quality(tag, self.intent, count)
            candidates[tag].update({
                "post_count": count,
                "count_display": count_display(count),
                "verified": quality["selected"] and count >= MIN_USEFUL_POSTS,
                "selected": quality["selected"],
                "score": quality["score"],
                "reason": quality["reason"],
                "source": candidates[tag].get("source", "search") + "+analytics",
            })

    async def plan_async(self, intent: dict, ig_keywords: list[str], brief: str) -> dict:
        self.intent = intent
        terms = build_search_terms(intent, ig_keywords, brief)
        candidates: dict[str, dict] = {}

        for tag in deterministic_fallback_hashtags(intent):
            self._add_candidate(candidates, tag, -1, "fallback", "deterministic")

        if self.keys.has_keys():
            async with aiohttp.ClientSession() as session:
                searched = await self._search_hashtags(session, terms)
                candidates.update(searched)
                if self.verify:
                    await self._verify_with_analytics(session, candidates)
        else:
            self.log("No Apify discovery keys configured; using deterministic fallback hashtags")

        rows = list(candidates.values())
        rows.sort(key=lambda row: (
            0 if row.get("selected") else 1,
            -int(row.get("score") or 0),
            abs((row.get("post_count") if row.get("post_count", -1) > 0 else 80_000) - 80_000),
        ))
        final = [row["tag"] for row in rows if row.get("selected")][:MAX_FINAL_HASHTAGS]
        return {
            "hashtags_verified": rows,
            "hashtags_final": final,
            "hashtag_search_terms": terms,
        }


def plan_hashtags(
    intent: dict,
    ig_keywords: list[str],
    brief: str,
    api_keys: str | Iterable[str] | None,
    verify: bool = True,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    planner = HashtagPlanner(api_keys=parse_keys(api_keys), verify=verify, progress_callback=progress_callback)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(planner.plan_async(intent, ig_keywords, brief))
    finally:
        loop.close()

