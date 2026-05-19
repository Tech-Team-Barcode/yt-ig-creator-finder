"""
ai_service.py — Gemini Influencer Marketing Genius
====================================================
Two-stage approach:
  Stage 1: Gemini deeply understands the campaign brief (niche, region, gender,
           creator tier, language, intent signals) and generates candidate
           hashtags + YT queries thinking like an influencer marketing expert.
  Stage 2: Hashtags are verified against real Instagram post counts via Apify.
           Only tags with proven usage (>= MIN_POST_COUNT) are kept.

Platform isolation: pass platforms=["YouTube"] to skip all Instagram work, or
platforms=["Instagram"] to skip all YouTube work.
"""

import json
import re
import asyncio
import aiohttp
import ast
import sys
from typing import Optional
from google import genai
from google.genai import types as genai_types
from backend_keys import KeyRing, parse_keys
from hashtag_planner import plan_hashtags

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ─── CONFIG ────────────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-3.1-flash-lite"
MIN_HASHTAG_POSTS = 10_000       # Tags with fewer posts are filtered out
MAX_HASHTAGS_TO_VERIFY = 30      # We ask Gemini for this many, verify all, return best
MAX_FINAL_HASHTAGS = 15          # Return top N verified tags
MAX_YT_QUERIES = 12
MAX_YT_VIDEO_QUERIES = 14
MAX_YT_CHANNEL_QUERIES = 4
MAX_YT_HASHTAG_QUERIES = 6       # YouTube hashtag-style searches (#mensgrooming etc.)
MAX_IG_KEYWORDS = 18

YT_NEGATIVE_TERMS = [
    "clinic", "doctor", "dr", "dermatologist", "hospital", "transplant",
    "salon", "shop", "store", "academy", "institute", "official", "brand"
]

FEMALE_QUERY_RE = re.compile(
    r"\b(women|woman|female|girls|girl|ladies|lady|bridal|bride|makeup|mua|"
    r"beauty|saree|kurti|lehenga|mehndi)\b",
    re.IGNORECASE,
)

MALE_QUERY_RE = re.compile(
    r"\b(men|mens|men's|male|boys|boy|guys|guy|gents|grooming|beard|shaving)\b",
    re.IGNORECASE,
)

MIXED_GENDER_INTENT_RE = re.compile(
    r"\b(?:male|men|boys|guys)\b(?:\s+(?:creators?|influencers?|youtubers?))?\s*(?:and|&|\+|/|,|or)\s*\b(?:female|women|girls|ladies)\b|"
    r"\b(?:female|women|girls|ladies)\b(?:\s+(?:creators?|influencers?|youtubers?))?\s*(?:and|&|\+|/|,|or)\s*\b(?:male|men|boys|guys)\b|"
    r"\b(?:mixed\s+(?:gender|genders|creators?|influencers?)|both\s+(?:genders?|creators?|male\s+and\s+female|men\s+and\s+women)|any\s+gender)\b",
    re.IGNORECASE,
)

FEMALE_INTENT_RE = re.compile(
    r"\b(female|women|woman|girls|girl|ladies|lady|women's|female-skewed|"
    r"beauty\s+creators?|beauty\s+influencers?|makeup\s+creators?|mua)\b",
    re.IGNORECASE,
)

MALE_INTENT_RE = re.compile(
    r"\b(male|men|man|boys|boy|guys|guy|gents|men's|mens|male-skewed|"
    r"mens?\s+grooming|beard|shaving|skincare\s+for\s+men|hair\s+color\s+for\s+men)\b",
    re.IGNORECASE,
)

KNOWN_LOCATION_TERMS = [
    "india", "indian", "hindi", "mumbai", "maharashtra", "pune", "gujarat",
    "gujarati", "ahmedabad", "surat", "vadodara", "rajkot", "madhya pradesh",
    "mp", "indore", "bhopal", "delhi", "bangalore", "bengaluru", "chennai",
    "hyderabad", "kolkata", "punjab", "punjabi", "rajasthan", "jaipur",
    "karnataka", "kannada", "tamil", "telugu", "marathi", "kerala", "malayalam",
]


def resolve_gender_intent(brief: str, parsed_intent: Optional[dict] = None) -> dict:
    """
    Deterministically resolve creator gender mode from the raw brief.

    Gemini can over-index on dominant niche words like "grooming". This helper
    gives explicit user wording priority so "male and female creators" cannot
    accidentally become male-only, and "female creators" cannot stay ANY.
    """
    parsed_intent = parsed_intent or {}
    parsed_gender = str(parsed_intent.get("gender") or "ANY").upper()
    text = " ".join([
        brief or "",
        str(parsed_intent.get("reasoning") or ""),
        str(parsed_intent.get("niche") or ""),
        str(parsed_intent.get("secondary_niche") or ""),
    ]).lower()

    if MIXED_GENDER_INTENT_RE.search(text):
        return {
            "gender": "ANY",
            "gender_mode": "mixed_balanced",
            "gender_reason": "Brief explicitly asks for both/mixed genders, so retrieval must stay balanced.",
        }

    female_signal = bool(FEMALE_INTENT_RE.search(text))
    male_signal = bool(MALE_INTENT_RE.search(text))

    if female_signal and not male_signal:
        return {
            "gender": "F",
            "gender_mode": "female_only",
            "gender_reason": "Brief contains female/women/beauty creator intent.",
        }
    if male_signal and not female_signal:
        return {
            "gender": "M",
            "gender_mode": "male_only",
            "gender_reason": "Brief contains male/men/grooming creator intent.",
        }
    if parsed_gender == "F":
        return {
            "gender": "F",
            "gender_mode": "female_only",
            "gender_reason": "AI parsed the brief as female-focused.",
        }
    if parsed_gender == "M":
        return {
            "gender": "M",
            "gender_mode": "male_only",
            "gender_reason": "AI parsed the brief as male-focused.",
        }
    return {
        "gender": "ANY",
        "gender_mode": "neutral_any",
        "gender_reason": "No single creator gender is required by the brief.",
    }


def apply_gender_intent(intent: dict, brief: str) -> dict:
    """Attach deterministic gender fields to a parsed campaign intent."""
    fixed = dict(intent or {})
    resolved = resolve_gender_intent(brief, fixed)
    fixed.update(resolved)
    has_explicit_size = bool(re.search(
        r"\b(?:\d+\s*[kKmM]?|followers?|subscribers?|subs|nano|micro|mid|macro)\b",
        brief or "",
    ))
    if has_explicit_size:
        fixed.setdefault("min_followers", 10_000)
        fixed.setdefault("max_followers", 500_000)
    else:
        fixed["min_followers"] = 10_000
        fixed["max_followers"] = 500_000
    return fixed


# ─── SYSTEM PROMPT — The "Influencer Marketing Genius" persona ─────────────────
SYSTEM_PROMPT = """You are an elite influencer marketing strategist with 10+ years finding 
nano and micro creators in India. You have deep knowledge of:

- How real Indian creators caption their posts and title their videos (not how brands talk)
- Which Instagram hashtags are actively browsed by creators in each niche (not brand campaign tags)
- Regional language social media culture across India (Kannada, Tamil, Telugu, Marathi, etc.)
- The difference between a hashtag with zero real creator posts vs one buzzing with daily uploads
- Creator tiers: nano (1K-10K), micro (10K-100K), mid-tier (100K-500K), macro (500K+)
- How search intent maps to YouTube video title patterns in India

Your goal: Given a campaign brief, think like someone who manually discovers creators 
every day. Generate hashtags that REAL creators use (not aspirational, not brand tags) 
and YouTube queries that match how creators actually title their content.

CRITICAL RULES:
- NEVER suggest hashtag campaign/brand tags like #ad #sponsored #partner #gifted
- NEVER suggest compound tags that clearly don't exist (e.g. #mumbaimenskincareindian)  
- ALWAYS include regional/language-specific tags when a city or language is mentioned
- Think about HOW creators tag, not how brands search
- Include a mix of broad discovery tags AND niche-specific ones
- For YouTube: think about words creators put in titles, not SEO jargon
"""


# ─── BRIEF ANALYSIS PROMPT ────────────────────────────────────────────────────
def build_analysis_prompt(brief: str) -> str:
    return f"""Analyze this influencer campaign brief and extract structured intent:

Brief: "{brief}"

Return ONLY valid JSON (no markdown, no explanation) with this exact structure:
{{
  "niche": "primary content niche (e.g. skincare, fashion, fitness, food, travel, tech, beauty, lifestyle, mensgrooming, menskincare)",
  "secondary_niche": "secondary niche if present, else null",
  "language": "regional language if mentioned (kannada, tamil, telugu, malayalam, marathi, punjabi, gujarati, bengali, hindi) else null",
  "city": "specific city in lowercase if mentioned, else null",
  "state": "state name if deducible, else null",
  "gender": "M if clearly male-focused, F if clearly female-focused, ANY otherwise",
  "gender_mode": "male_only | female_only | mixed_balanced | neutral_any",
  "creator_tier": "nano (1K-10K) | micro (10K-100K) | mid (100K-500K) | macro (500K+) | any",
  "min_followers": integer,
  "max_followers": integer,
  "content_formats": ["reels", "posts", "stories", "shorts", "long_form"] - whichever apply,
  "campaign_type": "awareness | product_review | haul | tutorial | lifestyle | ugc",
  "age_target": "teen | young_adult | adult | any",
  "confidence": "high | medium | low",
  "reasoning": "1-2 sentence explanation of your interpretation"
}}

Gender rules:
- If the brief says "female creators", "women creators", or targets women strongly, use F/female_only.
- If the brief says "male creators", "men creators", or men's grooming, use M/male_only.
- If the brief says "male and female", "men and women", "mixed creators", "both genders", or similar, use ANY/mixed_balanced.
- Do not let one niche word like grooming override an explicit mixed-gender request.

For follower ranges use these defaults if not specified:
- nano: 1000-10000, micro: 10000-100000, mid: 100000-500000, macro: 500000-5000000, any: 10000-500000"""


# ─── HASHTAG GENERATION PROMPT ────────────────────────────────────────────────
def build_hashtag_prompt(intent: dict, brief: str) -> str:
    niche = intent.get("niche", "lifestyle")
    lang = intent.get("language", "")
    city = intent.get("city", "")
    state = intent.get("state", "")
    gender = intent.get("gender", "ANY")
    tier = intent.get("creator_tier", "micro")
    secondary = intent.get("secondary_niche", "")

    location_context = ""
    if city:
        location_context = f"City: {city}"
        if state:
            location_context += f" ({state})"
    elif state:
        location_context = f"State/Region: {state}"
    elif lang:
        location_context = f"Language/Region: {lang}"

    gender_context = ""
    if gender == "M":
        gender_context = "MALE creators only"
    elif gender == "F":
        gender_context = "FEMALE creators only"

    city_str = city or ""
    lang_str = lang or ""

    return f"""You are an expert Indian influencer marketing strategist.

Campaign Brief: "{brief}"

Detected Intent:
- Primary Niche: {niche}
- Secondary Niche: {secondary or "none"}
- Location: {location_context or "India (general)"}
- Language: {lang_str or "Hindi/English mix"}
- Gender Focus: {gender_context or "Any gender"}
- Creator Tier: {tier}

Generate {MAX_HASHTAGS_TO_VERIFY} Instagram hashtags for discovering INDIAN CREATORS in this niche.

=== WHAT MAKES A GOOD SEED HASHTAG ===
✅ INTERSECTIONAL: combines niche + India/location signal in ONE tag
   Examples: #indianmenskincare, #mumbaiblogger, #delhigrooming, #indianskincareforguys
✅ MID-SIZE: 10K–500K posts (visible but not overwhelmed by brands)
✅ CREATOR-INTENT: tags that CREATORS use when posting their OWN content
✅ GENDER-SPECIFIC when needed: #mensgroomingIndia, #skincareformen, #beardcareIndia

=== WHAT MAKES A BAD HASHTAG — DO NOT GENERATE THESE ===
❌ MEGA-TAGS with millions of posts: #mumbai, #india, #skincare, #beauty (→ 502 errors, international noise)
❌ COMPOUND NONSENSE: #mumbaimaleskincarereviewer2024 (0 posts, made-up)
❌ BRAND/CAMPAIGN TAGS: #ad, #sponsored, #collab, #gifted
❌ PURE LOCATION with no niche: #mumbaikar, #mumbaidiaries (lifestyle noise)
❌ GENERIC TAGS: #love, #instagood, #photooftheday

=== GENERATION STRATEGY ===
Generate tags in these categories:

1. INTERSECTIONAL NICHE+INDIA (5-6 tags) — MOST IMPORTANT
   Tags that combine {niche} + India/Indian in one tag.
   Examples for male skincare: #indianmenskincare, #mensgroomingIndia, #skincareformen, #indianskincareforguys

2. LOCATION+CREATOR (3-4 tags) — if city/region is specified
   {("Tags combining " + city_str + " + creator/blogger: #" + city_str.lower() + "blogger, #" + city_str.lower() + "contentcreator") if city_str else "Regional India tags: #indiancontentcreator, #indianblogger"}
   {("Language-specific: tags with " + lang_str + " context") if lang_str else ""}

3. NICHE CORE (3-4 tags) — medium-sized niche tags
   Pure niche tags creators use: review, routine, grwm, haul style
   Examples: #skincareroutine, #grwm, #skincareobsessed, #groomingformen

4. CREATOR COMMUNITY (2-3 tags)
   Tags the creator community uses: #indiancontentcreator, #microinfluencer, #nanoinfluencer

{"CRITICAL: Gender is MALE — include male-specific niche tags like #menskincare #skincareformen #beardgang #mensgrooming" if gender_context == 'MALE creators only' else ""}
{"CRITICAL: Gender is FEMALE — include female-specific niche tags" if gender_context == 'FEMALE creators only' else ""}

Return ONLY a JSON array of hashtag strings with # prefix. No explanation. No markdown.
Example: ["#indianmenskincare", "#mensgroomingIndia", "#skincareformen", "#mumbaiblogger", "#grwm"]"""


# ─── YOUTUBE QUERY GENERATION PROMPT ─────────────────────────────────────────
def normalize_user_search_terms(raw_terms: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize optional user-entered hashtags/search phrases without splitting phrases on spaces."""
    if raw_terms is None:
        return []
    if isinstance(raw_terms, str):
        pieces = re.split(r"[\n,;]+", raw_terms)
    else:
        pieces = []
        for item in raw_terms:
            pieces.extend(re.split(r"[\n,;]+", str(item)))

    result: list[str] = []
    aliases = {
        "haircolor": "hair color",
        "haircolour": "hair colour",
        "mensgrooming": "mens grooming",
        "menskincare": "men skincare",
        "mensfashion": "men fashion",
        "skincareformen": "skincare for men",
        "groomingformen": "grooming for men",
    }
    for piece in pieces:
        clean = str(piece).strip().lower().lstrip("#")
        clean = clean.replace("_", " ")
        clean = aliases.get(clean.replace(" ", ""), clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        if 2 <= len(clean) <= 80 and clean not in result:
            result.append(clean)
    return result


def _split_location_value(value: str) -> list[str]:
    parts = re.split(r"[,/|]+|\band\b", str(value or ""), flags=re.IGNORECASE)
    return [re.sub(r"\s+", " ", p.strip().lower()) for p in parts if p.strip()]


def get_yt_location_terms(intent: dict, brief: str) -> list[str]:
    """Collect explicit and inferred India/location terms for query planning."""
    terms: list[str] = []
    for key in ("city", "state", "language"):
        value = intent.get(key)
        if value:
            terms.extend(_split_location_value(value))

    text = f"{brief} {json.dumps(intent, ensure_ascii=False)}".lower()
    for term in KNOWN_LOCATION_TERMS:
        if term in text and term not in terms:
            terms.append(term)

    for default_term in ("india", "indian", "hindi"):
        if default_term not in terms:
            terms.append(default_term)
    return [t for t in terms if t]


def _gender_mode(intent: dict) -> str:
    mode = str(intent.get("gender_mode") or "").lower()
    if mode in {"male_only", "female_only", "mixed_balanced", "neutral_any"}:
        return mode
    gender = str(intent.get("gender") or "ANY").upper()
    if gender == "M":
        return "male_only"
    if gender == "F":
        return "female_only"
    return "neutral_any"


def _gender_query_tokens(intent: dict) -> list[str]:
    gender = str(intent.get("gender") or "ANY").upper()
    mode = _gender_mode(intent)
    if gender == "M":
        return ["men", "male", "boys"]
    if gender == "F":
        return ["women", "female", "girls"]
    if mode == "mixed_balanced":
        return ["men", "women", "male", "female"]
    return [""]


def _gendered_query(topic: str, intent: dict, token: str | None = None) -> str:
    phrase = re.sub(r"\s+", " ", str(topic or "").strip().lower())
    if not phrase:
        return phrase
    if token is None:
        gender = str(intent.get("gender") or "ANY").upper()
        token = "men" if gender == "M" else "women" if gender == "F" else ""
    token = re.sub(r"\s+", " ", str(token or "").strip().lower())
    if not token:
        return phrase
    if MALE_QUERY_RE.search(phrase) or FEMALE_QUERY_RE.search(phrase):
        return phrase
    return f"{token} {phrase}"


def get_yt_topic_terms(intent: dict, brief: str) -> list[str]:
    """Turn a brief into creator-title topic terms without hidden gender defaults."""
    text = " ".join(
        str(x or "")
        for x in (
            brief,
            intent.get("niche"),
            intent.get("secondary_niche"),
            intent.get("campaign_type"),
        )
    ).lower()
    gender = str(intent.get("gender") or "ANY").upper()
    mode = _gender_mode(intent)
    topics: list[str] = []

    def add(term: str) -> None:
        term = re.sub(r"\s+", " ", term.strip().lower())
        if term and term not in topics:
            topics.append(term)

    if re.search(r"hair\s*colou?r|hair\s*dye|indigo|burgundy|black naturals", text):
        for term in ("hair color", "hair colour", "hair dye", "hair transformation", "hair color review"):
            add(term)
    if "hair" in text:
        for term in ("hair care", "hair styling", "hair routine"):
            add(term)
    if "facewash" in text or "face wash" in text or "cleanser" in text:
        for term in ("face wash", "cleanser", "skincare routine"):
            add(term)
    if "groom" in text or gender == "M":
        for term in ("mens grooming", "male grooming", "grooming routine", "beard care"):
            add(term)
    if "skin" in text:
        if gender == "M":
            for term in ("men skincare", "skincare for men", "face care for men"):
                add(term)
        elif gender == "F":
            for term in ("skincare routine", "beauty skincare", "skin care review"):
                add(term)
        else:
            for term in ("skincare routine", "skin care review"):
                add(term)
    if "fashion" in text or "style" in text:
        if gender == "M":
            for term in ("men fashion", "men style", "mens fashion"):
                add(term)
        elif gender == "F":
            for term in ("women fashion", "fashion haul", "style vlog"):
                add(term)
        else:
            for term in ("fashion haul", "style vlog", "fashion review"):
                add(term)
    if gender == "F" or mode == "mixed_balanced":
        if "beauty" in text or "skin" in text or "fashion" in text:
            for term in ("beauty routine", "grwm", "makeup review"):
                add(term)
    if "lifestyle" in text:
        if gender == "M":
            add("men lifestyle")
        elif gender == "F":
            add("women lifestyle")
        else:
            add("lifestyle vlog")
    if not topics:
        if gender == "M":
            add("men lifestyle")
            add("mens grooming")
        elif gender == "F":
            add("women lifestyle")
            add("beauty creator")
        else:
            add("lifestyle creator")
            add("skincare creator")
    return topics[:10]


def _make_plan_item(
    query: str,
    search_type: str,
    source: str,
    intent_terms: list[str],
    negative_terms: list[str] | None = None,
    paginate: bool = True,
) -> dict:
    clean = re.sub(r"\s+", " ", str(query).replace("#", " ").strip().lower())
    clean = clean.strip(" -")
    return {
        "query": clean,
        "search_type": "channel" if search_type == "channel" else "video",
        "source": source,
        "intent_terms": [t for t in intent_terms if t],
        "negative_terms": list(dict.fromkeys(negative_terms or YT_NEGATIVE_TERMS)),
        "paginate": paginate,
    }


def _query_allowed_for_gender(query: str, intent: dict) -> bool:
    gender = str(intent.get("gender") or "ANY").upper()
    if gender == "M":
        return not (FEMALE_QUERY_RE.search(query) and not MALE_QUERY_RE.search(query))
    if gender == "F":
        return not (MALE_QUERY_RE.search(query) and not FEMALE_QUERY_RE.search(query))
    return True


def normalize_yt_search_plan(rows: list, intent: dict, default_source: str) -> list[dict]:
    """Validate and dedupe AI/user/deterministic YouTube search-plan rows."""
    normalized: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows or []:
        if isinstance(row, str):
            item = _make_plan_item(row, "video", default_source, [])
        elif isinstance(row, dict):
            item = _make_plan_item(
                row.get("query", ""),
                str(row.get("search_type") or row.get("type") or "video").lower(),
                str(row.get("source") or default_source),
                [str(t).strip().lower() for t in row.get("intent_terms", []) if str(t).strip()],
                [str(t).strip().lower() for t in row.get("negative_terms", []) if str(t).strip()],
                bool(row.get("paginate", True)),
            )
        else:
            continue

        if not item["query"] or len(item["query"]) > 100:
            continue
        if not _query_allowed_for_gender(item["query"], intent):
            continue
        key = (item["search_type"], item["query"])
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    return normalized


def build_user_yt_search_plan(
    intent: dict,
    brief: str,
    user_search_terms: str | list[str] | tuple[str, ...] | None,
) -> list[dict]:
    terms = normalize_user_search_terms(user_search_terms)
    if not terms:
        return []
    topic_terms = get_yt_topic_terms(intent, brief)
    location_terms = get_yt_location_terms(intent, brief)
    plan: list[dict] = []
    tokens = _gender_query_tokens(intent)
    for term in terms[:8]:
        intent_terms = [term] + topic_terms[:2] + location_terms[:3]
        for token in tokens[:2]:
            base = _gendered_query(term, intent, token)
            if not any(loc in base for loc in ("india", "indian", "hindi")):
                base = f"{base} india"
            plan.append(_make_plan_item(base, "video", "user", intent_terms))
            plan.append(_make_plan_item(f"{base} review hindi", "video", "user", intent_terms))
    if terms:
        if str(intent.get("gender") or "ANY").upper() == "F":
            plan.append(_make_plan_item(f"{terms[0]} female creator india", "channel", "user", terms + location_terms[:2]))
        elif str(intent.get("gender") or "ANY").upper() == "M":
            plan.append(_make_plan_item(f"{terms[0]} male creator india", "channel", "user", terms + location_terms[:2]))
        elif _gender_mode(intent) == "mixed_balanced":
            plan.append(_make_plan_item(f"{terms[0]} male creator india", "channel", "user", terms + location_terms[:2]))
            plan.append(_make_plan_item(f"{terms[0]} female creator india", "channel", "user", terms + location_terms[:2]))
        else:
            plan.append(_make_plan_item(f"{terms[0]} creator india", "channel", "user", terms + location_terms[:2]))
    return normalize_yt_search_plan(plan, intent, "user")


def build_deterministic_yt_search_plan(intent: dict, brief: str) -> list[dict]:
    """Curated fallback plan for Indian creator discovery with explicit gender modes."""
    topic_terms = get_yt_topic_terms(intent, brief)
    location_terms = get_yt_location_terms(intent, brief)
    local_terms = [t for t in location_terms if t not in {"india", "indian"}][:4]
    gender = str(intent.get("gender") or "ANY").upper()
    mode = _gender_mode(intent)
    tokens = _gender_query_tokens(intent)

    plan: list[dict] = []
    for topic in topic_terms[:4]:
        for loc in local_terms:
            intent_terms = [topic, loc] + location_terms[:3]
            for token in tokens[:2]:
                creator_topic = _gendered_query(topic, intent, token)
                plan.append(_make_plan_item(f"{creator_topic} {loc}", "video", "deterministic", intent_terms))
                plan.append(_make_plan_item(f"{creator_topic} creator {loc}", "video", "deterministic", intent_terms))

    for topic in topic_terms[:5]:
        intent_terms = [topic] + location_terms[:4]
        suffixes = ["india", "hindi", "review india", "before after", "routine india"]
        if gender == "F":
            suffixes += ["grwm india", "haul hindi", "beauty creator india"]
        elif mode == "mixed_balanced":
            suffixes += ["creator india", "vlog hindi"]
        for token in tokens[:2]:
            creator_topic = _gendered_query(topic, intent, token)
            for suffix in suffixes:
                plan.append(_make_plan_item(f"{creator_topic} {suffix}", "video", "deterministic", intent_terms))

    if gender == "M":
        channel_queries = [
            "mens grooming creator india",
            "male grooming youtuber india",
            "men hair care creator india",
            "men fashion grooming creator india",
        ]
    elif gender == "F":
        channel_queries = [
            "female beauty creator india",
            "women skincare youtuber india",
            "female fashion lifestyle creator india",
            "indian women lifestyle youtuber",
        ]
    elif mode == "mixed_balanced":
        channel_queries = [
            "mens grooming creator india",
            "female beauty creator india",
            "men fashion lifestyle youtuber india",
            "women skincare lifestyle youtuber india",
        ]
    else:
        channel_queries = [
            "indian lifestyle creator",
            "skincare creator india",
            "fashion lifestyle youtuber india",
            "product review creator india",
        ]
    for loc in local_terms[:2]:
        if gender == "M":
            channel_queries.append(f"mens grooming creator {loc}")
            channel_queries.append(f"male grooming youtuber {loc}")
        elif gender == "F":
            channel_queries.append(f"female beauty creator {loc}")
            channel_queries.append(f"women lifestyle youtuber {loc}")
        elif mode == "mixed_balanced":
            channel_queries.append(f"male creator {loc}")
            channel_queries.append(f"female creator {loc}")
        else:
            channel_queries.append(f"lifestyle creator {loc}")
            channel_queries.append(f"content creator {loc}")
    for query in channel_queries:
        plan.append(_make_plan_item(query, "channel", "deterministic", topic_terms[:3] + location_terms[:4]))

    return normalize_yt_search_plan(plan, intent, "deterministic")


def build_yt_hashtag_search_plan(intent: dict, brief: str) -> list[dict]:
    """
    Build YouTube hashtag-style search queries (#hashtag searches on YouTube).

    YouTube supports searching for #mensgrooming or #haircolor as a query
    and returns videos/channels that used those hashtags. This surfaces creators
    that deterministic keyword queries might miss.
    """
    topic_terms = get_yt_topic_terms(intent, brief)
    location_terms = get_yt_location_terms(intent, brief)
    gender = str(intent.get("gender") or "ANY").upper()
    niche = (intent.get("niche") or "").lower()

    # Derive hashtag candidates from topic terms + niche
    raw_tags: list[str] = []

    if gender == "M":
        raw_tags += ["mensgrooming", "malegrooming", "skincareformen", "groomingformen", "menskincare"]
    elif gender == "F":
        raw_tags += ["indianbeautyblogger", "indianbeautycreator", "womenskincare", "girlsfashion", "beautyroutine", "makeupreview"]
    elif _gender_mode(intent) == "mixed_balanced":
        raw_tags += ["mensgrooming", "indianbeautyblogger", "menskincare", "womenskincare", "menfashion", "girlsfashion"]
    else:
        raw_tags += ["indiancontentcreator", "skincareroutine", "fashioncreator", "lifestylevlog"]

    for topic in topic_terms[:5]:
        slug = re.sub(r"\s+", "", topic.lower())
        raw_tags.append(slug)
        raw_tags.append(f"{slug}india")
        if gender == "M":
            raw_tags.append(f"men{slug}")
            raw_tags.append(f"mens{slug}")
        elif gender == "F":
            raw_tags.append(f"women{slug}")
            raw_tags.append(f"girls{slug}")
        elif _gender_mode(intent) == "mixed_balanced":
            raw_tags.append(f"men{slug}")
            raw_tags.append(f"women{slug}")

    # Niche-specific
    slug = re.sub(r"\s+", "", niche)
    if slug:
        raw_tags += [f"indian{slug}", f"{slug}india"]
        if gender == "M":
            raw_tags.append(f"men{slug}")
        elif gender == "F":
            raw_tags.append(f"women{slug}")
        elif _gender_mode(intent) == "mixed_balanced":
            raw_tags += [f"men{slug}", f"women{slug}"]

    # Deduplicate and limit
    seen: set[str] = set()
    hashtag_terms: list[str] = []
    for tag in raw_tags:
        tag = re.sub(r"[^a-z0-9]", "", tag.lower())
        if tag and tag not in seen and len(tag) >= 4:
            seen.add(tag)
            hashtag_terms.append(tag)
        if len(hashtag_terms) >= MAX_YT_HASHTAG_QUERIES:
            break

    plan: list[dict] = []
    india_location_terms = [t for t in location_terms if t in {"india", "indian", "hindi"}]
    for tag in hashtag_terms:
        plan.append(_make_plan_item(
            f"#{tag}",
            "video",
            "hashtag",
            [tag] + topic_terms[:2] + india_location_terms[:2],
            paginate=False,  # hashtag searches return fewer results; no page 2 needed
        ))

    return normalize_yt_search_plan(plan, intent, "hashtag")


def merge_yt_search_plans(*plans: list[dict]) -> list[dict]:
    """Merge with source priority, source caps, and global YouTube quota caps."""
    source_priority = {
        "user": 0,
        "strategist_ai": 1,
        "grounded_ai": 2,
        "deterministic": 3,
        "hashtag": 4,
    }
    source_caps = {
        "user": {"video": 4, "channel": 1},
        "strategist_ai": {"video": 6, "channel": 2},
        "grounded_ai": {"video": 4, "channel": 1},
        "deterministic": {"video": 12, "channel": MAX_YT_CHANNEL_QUERIES},
        "hashtag": {"video": MAX_YT_HASHTAG_QUERIES, "channel": 0},
    }
    all_items = [item for plan in plans for item in (plan or [])]
    all_items.sort(key=lambda item: source_priority.get(item.get("source", ""), 9))

    output: list[dict] = []
    seen: set[tuple[str, str]] = set()
    type_counts = {"video": 0, "channel": 0}
    source_type_counts: dict[tuple[str, str], int] = {}
    # hashtag queries count against video quota
    caps = {"video": MAX_YT_VIDEO_QUERIES + MAX_YT_HASHTAG_QUERIES, "channel": MAX_YT_CHANNEL_QUERIES}
    for item in all_items:
        search_type = item.get("search_type", "video")
        source = item.get("source", "")
        key = (search_type, item.get("query", ""))
        if key in seen or type_counts.get(search_type, 0) >= caps.get(search_type, 0):
            continue
        source_key = (source, search_type)
        per_source_cap = source_caps.get(source, {}).get(search_type)
        if per_source_cap is not None and source_type_counts.get(source_key, 0) >= per_source_cap:
            continue
        seen.add(key)
        type_counts[search_type] = type_counts.get(search_type, 0) + 1
        source_type_counts[source_key] = source_type_counts.get(source_key, 0) + 1
        output.append(item)
    return output


def build_yt_prompt(intent: dict, brief: str) -> str:
    niche = intent.get("niche", "lifestyle")
    lang = intent.get("language", "")
    city = intent.get("city", "")
    state = intent.get("state", "")
    gender = intent.get("gender", "ANY")
    secondary = intent.get("secondary_niche", "")

    return f"""Campaign Brief: "{brief}"
Niche: {niche} | Location: {city or state or lang or "India"} | Gender: {gender}

Generate {MAX_YT_QUERIES} YouTube search queries to find real {niche} creators from 
{"city of " + city if city else state or (lang + "-speaking regions") if lang else "India"}.

Think like a creator naming their video, NOT like a brand doing keyword research.

Rules:
- Use words creators ACTUALLY put in video titles
- Include regional terms: {"include '" + lang + "' and '" + city + "'" if city and lang else lang or city or "India"}
- Include format words: review, routine, haul, tutorial, vlog, grwm, honest, try on, before after, worth it
- Include price context where natural: under 500, affordable, budget, drugstore
- {"Include male-specific terms: men, mens, male, boys, guys" if gender == "M" else ""}
- {"Include female-specific terms: women, girls, ladies" if gender == "F" else ""}
- Mix languages: some in English, some with {lang or "Hindi"} words mixed in
- Avoid marketing jargon

Return ONLY a JSON array of plain search strings (no # prefix, no markdown).
Example: ["kannada skincare routine oily skin", "honest serum review hindi 2024"]"""


def build_yt_search_plan_prompt(
    intent: dict,
    brief: str,
    user_terms: list[str],
    exclude_terms: list[str],
    source_name: str = "strategist_ai",
) -> str:
    niche = intent.get("niche") or "lifestyle"
    gender = intent.get("gender") or "ANY"
    gender_mode = _gender_mode(intent)
    locations = get_yt_location_terms(intent, brief)
    topics = get_yt_topic_terms(intent, brief)
    if gender == "M":
        gender_rule = "Male-only: every query should carry male/men/boys/grooming intent unless the topic itself is already male-coded."
        avoid_rule = "Avoid women/girls/bridal/makeup-only queries."
    elif gender == "F":
        gender_rule = "Female-only: every query should carry female/women/girls/beauty/fashion creator intent unless the topic itself is already female-coded."
        avoid_rule = "Avoid men/mens/beard/shaving-only queries."
    elif gender_mode == "mixed_balanced":
        gender_rule = "Mixed/balanced: intentionally split searches across male and female creator language, plus a few neutral creator searches. Do not default to male."
        avoid_rule = "Do not let grooming or hair topics collapse the plan to male-only queries."
    else:
        gender_rule = "Any gender: use neutral creator searches and only add gendered variants when they improve discovery diversity."
        avoid_rule = "Do not over-bias toward male or female unless the brief asks for it."

    return f"""You are planning YouTube Data API searches for a senior Indian influencer marketing strategist.

Campaign brief:
"{brief}"

Detected intent:
- Niche: {niche}
- Gender: {gender}
- Gender mode: {gender_mode}
- Locations/language: {locations}
- Topic terms: {topics}
- User-provided search terms/hashtags: {user_terms or []}
- Exclude channel/brand terms: {exclude_terms or []}

Goal: find REAL Indian creator-led YouTube channels, mostly 10K-500K subscribers, that an influencer marketer would shortlist for this campaign.
Do not plan searches for brand channels, stores, clinics, salons, product companies, music/news channels, or international creators.

Think in creator archetypes, not just keywords:
- exact niche reviewers/tutorial creators
- routine/vlog/storytelling creators
- regional-language creators
- adjacent lifestyle/fashion/beauty/grooming creators
- long-tail micro creators with less obvious titles
- problem/benefit title patterns such as honest review, before after, under 500, worth it, routine, transformation, GRWM, haul

Return ONLY valid JSON array. Each item must use this exact shape:
[
  {{
    "query": "plain YouTube search query",
    "search_type": "video",
    "source": "{source_name}",
    "intent_terms": ["hair color", "india"],
    "negative_terms": ["clinic", "doctor", "salon", "store", "official", "brand"]
  }}
]

Rules:
- Most rows must be search_type "video"; include at most 4 "channel" rows.
- {gender_rule}
- Queries must contain India/location/language intent where natural.
- Use real creator title language: review, routine, before after, transformation, vlog, honest, tutorial, under 500, affordable.
- Include hair color / hair dye / mens grooming combinations when relevant.
- If user terms look like hashtags, turn them into YouTube search phrases without #.
- {avoid_rule}
- Do not output marketing slogans or brand-only searches.
- Avoid repeating the same query frame with small word swaps.
- Limit to 12 video rows and 4 channel rows."""


def build_ig_keyword_prompt(intent: dict, brief: str) -> str:
    niche = intent.get("niche") or "lifestyle"
    gender = intent.get("gender") or "ANY"
    lang = intent.get("language") or ""
    city = intent.get("city") or ""
    state = intent.get("state") or ""
    location = city or state or "India"

    return f"""You are an elite Instagram influencer discovery strategist.

Your task is to generate HIGH-INTENT Instagram discovery keywords for finding REAL creators and influencers.

IMPORTANT:

Generate search phrases that REAL creators use in captions, reels, and post text.
DO NOT generate brand/store/commercial keywords.
DO NOT generate hashtags.
Focus on creator-style phrases.
Focus on content discovery intent.
Prioritize niche + gender + location relevance.

Campaign Brief:
"{brief}"

Detected Intent:

Niche: {niche}
Gender: {gender}
Location: {location}
Language: {lang or "any"}

Generate:

Broad creator discovery phrases
Niche-specific creator phrases
Reel/caption style phrases
Regional/location phrases
Review/routine/tutorial style phrases

Rules:

Output ONLY phrases useful for Instagram content discovery
Avoid brands/stores/clinics
Avoid generic SEO terms
Avoid hashtags
Keep phrases natural and realistic
Focus on influencer content language

Return ONLY valid JSON array.

Example:
[
"mens skincare india",
"mens grooming routine",
"skincare for men",
"mumbai grooming creator",
"honest skincare review men",
"grwm men india"
]"""


# ─── MAIN AI SERVICE CLASS ─────────────────────────────────────────────────────
class AIService:
    def __init__(self, gemini_api_key: str | list[str], apify_api_key: str | list[str]):
        self.gemini_keys = KeyRing(gemini_api_key)
        self.apify_api_keys = parse_keys(apify_api_key)
        self.apify_api_key = self.apify_api_keys[0] if self.apify_api_keys else ""

    def _generate(
        self,
        prompt: str,
        system: str = SYSTEM_PROMPT,
        temperature: float = 0.3,
        response_mime_type: str = "application/json",
        grounded: bool = False,
    ) -> str:
        """Call Gemini with given prompt and return text."""
        if not self.gemini_keys.has_keys():
            print("[Gemini] No API keys configured")
            return ""

        attempts = max(1, len(self.gemini_keys))
        last_error = None
        for _ in range(attempts):
            api_key = self.gemini_keys.next()
            if not api_key:
                break
            config_kwargs: dict = {
                "system_instruction": system,
                "temperature": temperature,
                "max_output_tokens": 2048,
            }
            if response_mime_type:
                config_kwargs["response_mime_type"] = response_mime_type
            if grounded:
                config_kwargs["tools"] = [genai_types.Tool(googleSearch=genai_types.GoogleSearch())]
                # grounded responses must not enforce a JSON mime type (model rejects it)
                config_kwargs.pop("response_mime_type", None)

            try:
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(**config_kwargs)
                )
                text = response.text or ""
                return re.sub(r"```json|```", "", text).strip()
            except Exception as e:
                last_error = e
                message = str(e).lower()
                if any(token in message for token in ("quota", "429", "403", "resource_exhausted")):
                    self.gemini_keys.mark_exhausted(api_key)
                    continue
                break

        print(f"[Gemini] Error: {last_error}")
        return ""

    def _parse_json(self, text: str, expected: str):
        """Parse Gemini JSON and tolerate common almost-JSON responses."""
        cleaned = re.sub(r"```json|```", "", text or "").strip()
        if not cleaned:
            raise ValueError("Empty Gemini response")

        if expected == "object":
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        else:
            match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        candidate = match.group() if match else cleaned

        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return ast.literal_eval(candidate)

    def _salvage_string_array(self, text: str) -> list[str]:
        """Recover useful strings from an incomplete JSON array."""
        cleaned = re.sub(r"```json|```", "", text or "").strip()
        strings = re.findall(r'"([^"\n\r]+)"|\'([^\'\n\r]+)\'', cleaned)
        return [(double or single).strip() for double, single in strings if (double or single).strip()]

    def _log_parse_error(self, label: str, error: Exception, text: str) -> None:
        snippet = re.sub(r"\s+", " ", text or "").strip()[:300]
        print(f"[AIService] {label} error: {error}")
        if snippet:
            print(f"[AIService] {label} raw response: {snippet}")

    def analyze_brief(self, brief: str) -> dict:
        """Stage 1: Deep campaign brief analysis."""
        text = ""
        try:
            text = self._generate(build_analysis_prompt(brief), temperature=0.1)
            parsed = self._parse_json(text, "object")
            return apply_gender_intent(parsed, brief)
        except Exception as e:
            self._log_parse_error("Brief analysis", e, text)
            return apply_gender_intent({
                "niche": "lifestyle", "secondary_niche": None,
                "language": None, "city": None, "state": None,
                "gender": "ANY", "creator_tier": "micro",
                "min_followers": 10_000, "max_followers": 500_000,
                "confidence": "low", "reasoning": "Parse error, using defaults"
            }, brief)

    def generate_hashtags_raw(self, intent: dict, brief: str) -> list[str]:
        """Generate candidate hashtags (unverified)."""
        text = ""
        try:
            text = self._generate(build_hashtag_prompt(intent, brief), temperature=0.3)
            tags = self._parse_json(text, "array")
        except Exception as e:
            self._log_parse_error("Hashtag generation", e, text)
            tags = self._salvage_string_array(text)

        try:
            result = []
            for t in tags:
                t = str(t).strip()
                if not t.startswith("#"):
                    t = "#" + t
                t = "#" + t[1:].replace(" ", "").lower()
                if 2 < len(t) <= 40:
                    result.append(t)
            return list(dict.fromkeys(result))
        except Exception as e:
            self._log_parse_error("Hashtag normalization", e, text)
            return []

    def generate_yt_queries(self, intent: dict, brief: str) -> list[str]:
        """Generate YouTube search queries."""
        text = ""
        try:
            text = self._generate(build_yt_prompt(intent, brief), temperature=0.4)
        except Exception as e:
            self._log_parse_error("YT query generation", e, text)
            queries = self._salvage_string_array(text)

        try:
            queries = self._parse_json(text, "array")
        except Exception:
            queries = self._salvage_string_array(text)

        try:
            return [str(q).strip() for q in queries if q and str(q).strip()][:MAX_YT_QUERIES]
        except Exception as e:
            self._log_parse_error("YT query normalization", e, text)
            return []

    def generate_grounded_yt_search_plan(
        self,
        intent: dict,
        brief: str,
        user_search_terms: list[str],
        exclude_terms: list[str],
    ) -> list[dict]:
        """Use Gemini Google Search grounding for a current YouTube search-pack plan."""
        text = ""
        try:
            text = self._generate(
                build_yt_search_plan_prompt(intent, brief, user_search_terms, exclude_terms, "grounded_ai"),
                temperature=0.2,
                response_mime_type=None,
                grounded=True,
            )
            parsed = self._parse_json(text, "array")
            return normalize_yt_search_plan(parsed, intent, "grounded_ai")
        except Exception as e:
            self._log_parse_error("Grounded YT search plan", e, text)
            return []

    def generate_strategic_yt_search_plan(
        self,
        intent: dict,
        brief: str,
        user_search_terms: list[str],
        exclude_terms: list[str],
    ) -> list[dict]:
        """Use Gemini as a strategist for diverse query planning without web grounding."""
        text = ""
        try:
            text = self._generate(
                build_yt_search_plan_prompt(intent, brief, user_search_terms, exclude_terms, "strategist_ai"),
                temperature=0.45,
            )
            parsed = self._parse_json(text, "array")
            return normalize_yt_search_plan(parsed, intent, "strategist_ai")
        except Exception as e:
            self._log_parse_error("Strategic YT search plan", e, text)
            return []

    def generate_yt_search_plan(
        self,
        intent: dict,
        brief: str,
        user_search_terms: str | list[str] | tuple[str, ...] | None = None,
        exclude_terms: str | list[str] | tuple[str, ...] | None = None,
        use_grounding: bool = True,
    ) -> list[dict]:
        """Build the richer YouTube search plan from user, deterministic, hashtag, and grounded sources."""
        user_terms = normalize_user_search_terms(user_search_terms)
        excludes = normalize_user_search_terms(exclude_terms)
        user_plan = build_user_yt_search_plan(intent, brief, user_terms)
        strategist = self.generate_strategic_yt_search_plan(intent, brief, user_terms, excludes)
        deterministic = build_deterministic_yt_search_plan(intent, brief)
        hashtag_plan = build_yt_hashtag_search_plan(intent, brief)
        grounded = (
            self.generate_grounded_yt_search_plan(intent, brief, user_terms, excludes)
            if use_grounding and False  # Grounded search has very low quota; disabled to avoid 429s
            else []
        )
        return merge_yt_search_plans(user_plan, strategist, deterministic, hashtag_plan, grounded)

    def generate_ig_keywords(self, intent: dict, brief: str) -> list[str]:
        """Generate Instagram keyword/search phrases, not hashtags."""
        text = ""
        try:
            text = self._generate(build_ig_keyword_prompt(intent, brief), temperature=0.2)
            phrases = self._parse_json(text, "array")
        except Exception as e:
            self._log_parse_error("IG keyword generation", e, text)
            phrases = self._salvage_string_array(text)

        result = []
        for phrase in phrases:
            clean = re.sub(r"\s+", " ", str(phrase).replace("#", " ").strip().lower())
            if 4 <= len(clean) <= 80 and clean not in result:
                result.append(clean)
        return result[:MAX_IG_KEYWORDS]

    def score_instagram_post(self, brief: str, post: dict) -> dict:
        """Score one Instagram post before extracting/promoting its owner."""
        username = post.get("username") or post.get("ownerUsername") or ""
        caption = str(post.get("caption") or "")[:1200]
        hashtags = post.get("hashtags") or []
        likes = post.get("likesCount") or post.get("likes") or 0
        comments = post.get("commentsCount") or post.get("comments") or 0

        prompt = f"""You are an expert influencer discovery evaluator.

Your task is to determine whether an Instagram POST belongs to a REAL influencer/creator relevant to the campaign.

Campaign:
"{brief}"

Evaluate this Instagram post:

Username:
{username}

Caption:
{caption}

Hashtags:
{hashtags}

Post Stats:

Likes: {likes}
Comments: {comments}

Return a STRICT JSON response:

{{
"relevance_score": 0-100,
"is_creator_content": true/false,
"is_business_or_store": true/false,
"is_relevant_to_niche": true/false,
"gender_match": true/false,
"location_match": true/false,
"creator_confidence": "high | medium | low",
"reason": "short explanation"
}}

Scoring Rules:

HIGH score:
personal creator content
routines
reviews
tutorials
reels-style captions
storytelling
creator personality
influencer behavior
LOW score:
stores
distributors
clinics
wholesale
product-only pages
spam
repost pages
meme pages
educational institutions

Very Important:
A real creator/influencer should FEEL like a person creating content regularly.

Return ONLY valid JSON."""

        text = ""
        try:
            text = self._generate(prompt, temperature=0.05)
            parsed = self._parse_json(text, "object")
            parsed["relevance_score"] = int(parsed.get("relevance_score", 0))
            return parsed
        except Exception as e:
            self._log_parse_error("Post relevance scoring", e, text)
            return {
                "relevance_score": 0,
                "is_creator_content": False,
                "is_business_or_store": True,
                "is_relevant_to_niche": False,
                "gender_match": False,
                "location_match": False,
                "creator_confidence": "low",
                "reason": "AI scoring failed",
            }

    def score_instagram_profile(self, brief: str, creator: dict) -> dict:
        """Final score for an enriched Instagram creator profile."""
        recent_captions = creator.get("recent_captions") or creator.get("caption_sample") or ""
        prompt = f"""You are an expert influencer marketing analyst for an Indian agency.

Evaluate this Instagram account against the campaign brief.

Campaign Brief: "{brief}"

Profile Data:
- Username: {creator.get("username", "")}
- Full Name: {creator.get("full_name", "")}
- Bio: {creator.get("bio", "") or "(empty)"}
- Business Category: {creator.get("business_category", "") or "none"}
- Followers: {creator.get("followers", 0)}
- External URL: {creator.get("external_url", "") or "none"}
- Recent Captions: {str(recent_captions)[:1200] or "(none available)"}

=== CRITICAL CONTEXT ABOUT INDIAN CREATORS ===
Most Indian nano/micro creators have SHORT English bios with NO city or country mentioned.
This is completely NORMAL for Indian creators. Empty or location-free bios do NOT mean non-Indian.
Indian creators often use Hinglish in captions: yaar, bhai, dost, bilkul, achha, ekdum.
Indian brands in captions = strong India signal: Minimalist, Mamaearth, Nykaa, mCaffeine,
Dot & Key, The Derma Co, WOW, Plum, Beardo, Bombay Shaving Company, Man Matters, Ustraa.
Indian male skincare creators rarely state pronouns — don't penalize for missing "he/him".

=== SCORING CRITERIA (0–100) ===

1. Is this a REAL PERSON creating content? (0–30 points)
   HIGH: personal bio tone, "content creator", "blogger", "sharing my journey",
         collab inquiries, reels mentions, authentic captions with opinions/reviews.
   LOW: store, distributor, brand page, wholesale, clinic, no human presence.

2. Is this person LIKELY INDIAN? (0–30 points)
   +25: bio mentions Indian city (Mumbai, Delhi, Bangalore, Pune, etc.)
   +20: Indian brand names in captions (Minimalist, Mamaearth, Nykaa, mCaffeine, etc.)
   +20: Hinglish in captions (yaar, bhai, dost, achha, bilkul, kya, abhi, mast)
   +15: .in or .co.in in external URL
   +10: Indian name patterns (common Indian first/last names)
   +10: rupee symbol ₹ or Indian pricing in captions
   +5: no signals but also no counter-signals (benefit of the doubt)
   -20: bio explicitly says non-Indian city/country (NYC, London, Dubai, Singapore, etc.)
   
   DO NOT require explicit "India" text. Absence of location text ≠ not Indian.

3. Does this match the campaign NICHE? (0–25 points)
   Be generous: lifestyle creator who occasionally posts skincare = 12–15 points.
   Dedicated niche creator = 20–25 points.

4. Does this match the campaign GENDER? (0–15 points)
   If campaign wants male creators: look for male niche content (beard, grooming, menskincare),
   male pronouns, or general lifestyle with no female signals. Ambiguous = give partial credit.
   Indian male creators rarely write "he/him" — absence of pronouns is not penalized.

=== THRESHOLDS ===
70–100: Strong match → accept
50–69: Possible match → flag for manual review
0–49:  Reject

Return ONLY valid JSON (no markdown, no explanation):
{{
  "final_score": 0-100,
  "is_real_creator": true/false,
  "india_confidence": "high | medium | low | unknown",
  "niche_match": true/false,
  "gender_match": true/false,
  "is_business": true/false,
  "creator_tier": "nano | micro | mid | macro",
  "reason": "one sentence explanation"
}}"""

        text = ""
        try:
            text = self._generate(prompt, temperature=0.05)
            parsed = self._parse_json(text, "object")
            parsed["final_score"] = int(parsed.get("final_score", 0))
            return parsed
        except Exception as e:
            self._log_parse_error("Final profile scoring", e, text)
            return {
                "final_score": 0,
                "is_real_creator": False,
                "niche_match": False,
                "gender_match": False,
                "location_match": False,
                "is_business": True,
                "creator_tier": "nano",
                "confidence": "low",
                "reason": "AI scoring failed",
            }

    async def verify_hashtag_apify(self, session: aiohttp.ClientSession, tag: str) -> tuple[str, int]:
        clean_tag = tag.lstrip("#")
        url = "https://api.apify.com/v2/acts/apify~instagram-hashtag-scraper/run-sync-get-dataset-items"
        payload = {
            "hashtags": [clean_tag],
            "resultsLimit": 1,
        }
        params = {"token": self.apify_api_key}
        try:
            async with session.post(url, json=payload, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    if data and len(data) > 0:
                        item = data[0]
                        count = (
                            item.get("postsCount") or
                            item.get("topPostsCount") or
                            item.get("mediaCount") or
                            item.get("edge_hashtag_to_media", {}).get("count") or
                            -1
                        )
                        return (tag, int(count) if count and count != -1 else -1)
        except Exception as e:
            print(f"[Apify] Error verifying {tag}: {e}")
        return (tag, -1)

    async def verify_hashtags_batch(self, tags: list[str]) -> list[dict]:
        if not tags:
            return []

        print(f"[AIService] Verifying {len(tags)} hashtags via Apify...")

        async with aiohttp.ClientSession() as session:
            tasks = [self.verify_hashtag_apify(session, tag) for tag in tags]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        verified = []
        for res in results:
            if isinstance(res, Exception):
                continue
            tag, count = res
            verified.append({
                "tag": tag,
                "post_count": count,
                "verified": count >= MIN_HASHTAG_POSTS if count != -1 else False,
                "count_display": (
                    f"{count/1_000_000:.1f}M" if count >= 1_000_000
                    else f"{count/1_000:.0f}K" if count >= 1_000
                    else str(count) if count != -1
                    else "unverified"
                )
            })

        verified.sort(key=lambda x: (0 if x["verified"] else 1, -x["post_count"]))
        return verified

    def score_creators_batch(self, creators: list[dict], intent: dict) -> list[dict]:
        """
        Final Gemini scoring for enriched creator profiles.
        Adds AI ranking and updates match_status.
        Borderline candidates are kept for manual review instead of hidden.
        """
        if not creators:
            return []

        brief = intent.get("_brief") or intent.get("brief") or (
            f"Find {intent.get('gender', 'ANY')} {intent.get('niche', 'lifestyle')} creators "
            f"in {intent.get('city') or intent.get('state') or intent.get('language') or 'India'}"
        )

        def compact_profile(creator: dict) -> dict:
            return {
                "username": creator.get("username", ""),
                "full_name": creator.get("full_name", ""),
                "bio": creator.get("bio", ""),
                "followers": creator.get("followers", 0),
                "business_category": creator.get("business_category", ""),
                "external_url": creator.get("external_url", ""),
                "source_hashtag": creator.get("source_hashtag", ""),
                "local_match_score": creator.get("local_match_score", 0),
                "niche_confidence": creator.get("niche_confidence", 0),
                "india_confidence": creator.get("india_confidence", 0),
                "gender_confidence": creator.get("gender_confidence", 0),
                "creator_confidence": creator.get("creator_confidence", 0),
                "business_risk": creator.get("business_risk", 0),
                "evidence": creator.get("evidence", ""),
                "recent_captions": str(creator.get("recent_captions", ""))[:700],
            }

        def score_chunk(chunk: list[dict]) -> dict[str, dict]:
            prompt = f"""You are an Indian influencer marketing talent analyst.

Campaign Brief:
"{brief}"

Evaluate these Instagram profiles. Use local evidence scores as strong signals,
but correct obvious mistakes. Do not require explicit "India" text; Indian names,
Indian brands, Hinglish, +91, .in links, India/city hashtags, and Indian-language
signals all count. Empty short bios are common for Indian micro creators.

Return ONLY a JSON array, one object per input profile:
[
  {{
    "username": "handle",
    "final_score": 0-100,
    "is_real_creator": true,
    "india_confidence": "high|medium|low|unknown",
    "niche_match": true,
    "gender_match": true,
    "is_business": false,
    "creator_tier": "nano|micro|mid|macro",
    "reason": "short evidence-based reason"
  }}
]

Profiles:
{json.dumps([compact_profile(c) for c in chunk], ensure_ascii=False)}
"""
            text = ""
            try:
                text = self._generate(prompt, temperature=0.05)
                parsed = self._parse_json(text, "array")
                output = {}
                for row in parsed:
                    if isinstance(row, dict) and row.get("username"):
                        output[str(row["username"]).lower()] = row
                return output
            except Exception as e:
                self._log_parse_error("Batch profile scoring", e, text)
                return {}

        scored_map: dict[str, dict] = {}
        scoreable = [c for c in creators if c.get("match_status") != "rejected"]
        for start in range(0, len(scoreable), 8):
            scored_map.update(score_chunk(scoreable[start:start + 8]))

        for creator in creators:
            if creator.get("match_status") == "rejected":
                creator.setdefault("ai_final_score", 0)
                creator.setdefault("ai_score", 0)
                creator.setdefault("ai_reason", creator.get("reject_reason", "Rejected by local filters"))
                creator["ai_reject"] = True
                creator["ai_review_needed"] = False
                continue

            scored = scored_map.get(str(creator.get("username", "")).lower())
            if not scored:
                scored = self.score_instagram_profile(brief, creator)
            final_score = int(scored.get("final_score", 0))
            creator["ai_final_score"] = final_score
            creator["ai_score"] = round(final_score / 10, 1)
            is_real = bool(scored.get("is_real_creator", False))
            is_business = bool(scored.get("is_business", False))
            local_score = float(creator.get("local_match_score") or 0)
            strong_ai = final_score >= 70 and is_real and not is_business
            strong_local = local_score >= 75 and creator.get("match_status") == "high"

            if strong_ai or (strong_local and final_score >= 50 and not is_business):
                creator["match_status"] = "high"
                creator["review_reason"] = ""
                creator["ai_reject"] = False
            elif is_business and local_score < 70:
                creator["match_status"] = "rejected"
                creator["reject_reason"] = "AI marked as business/store"
                creator["ai_reject"] = True
            elif final_score < 40 and local_score < 65:
                creator["match_status"] = "rejected"
                creator["reject_reason"] = "weak AI and local confidence"
                creator["ai_reject"] = True
            else:
                creator["match_status"] = "review"
                creator["review_reason"] = "AI/local confidence borderline"
                creator["ai_reject"] = False

            creator["ai_review_needed"] = creator.get("match_status") == "review"
            creator["ai_reason"] = scored.get("reason", "")
            creator["creator_tier"] = scored.get("creator_tier", creator.get("creator_tier", ""))
            creator["ai_confidence"] = scored.get("india_confidence", scored.get("confidence", ""))

        print(
            f"[AIService] Final scored {len(creators)} creators. "
            f"High: {sum(1 for c in creators if c.get('match_status') == 'high')}, "
            f"Review: {sum(1 for c in creators if c.get('match_status') == 'review')}, "
            f"Rejected: {sum(1 for c in creators if c.get('match_status') == 'rejected')}"
        )
        return creators

    def score_youtube_creators_batch(self, creators: list[dict], intent: dict) -> list[dict]:
        """
        Final Gemini scoring for YouTube creator candidates.
        Local filters get candidates into the funnel; AI decides high/review/rejected.
        """
        if not creators:
            return []

        brief = intent.get("_brief") or intent.get("brief") or (
            f"Find {intent.get('gender', 'ANY')} {intent.get('niche', 'lifestyle')} creators "
            f"in {intent.get('city') or intent.get('state') or intent.get('language') or 'India'}"
        )

        def compact_creator(creator: dict) -> dict:
            return {
                "channel_id": creator.get("channel_id", ""),
                "channel_name": creator.get("channel_name", ""),
                "handle": creator.get("handle", ""),
                "description": str(creator.get("description", ""))[:700],
                "subscribers": creator.get("subscribers", 0),
                "country": creator.get("country", ""),
                "video_title": creator.get("video_title", ""),
                "search_query": creator.get("_search_query", ""),
                "search_type": creator.get("_search_type", ""),
                "local_quality_score": creator.get("_quality_score", 0),
                "creator_evidence_score": creator.get("_creator_evidence_score", 0),
                "india_score": creator.get("_india_score", 0),
                "gender_score": creator.get("_gender_score", 0),
                "female_score": creator.get("_female_score", 0),
                "inferred_gender": creator.get("_gender_label", "unknown"),
                "niche_score": creator.get("_niche_score", 0),
                "local_reason": creator.get("review_reason") or creator.get("reject_reason", ""),
            }

        campaign_gender = str(intent.get("gender") or "ANY").upper()
        campaign_gender_mode = _gender_mode(intent)
        if campaign_gender == "M":
            gender_criteria = "- male creator/grooming/men-content match (beard, shaving, grooming, men skincare, men fashion, etc.)"
            gender_reject_note = "Reject female-focused channels. Accept male or neutral lifestyle creators."
            gender_accept_note = "named Indian male creators who post men's grooming, hair color, skincare, fashion, or lifestyle videos"
            gender_match_rule = "gender_match: true if creator is male or covers male-oriented content"
        elif campaign_gender == "F":
            gender_criteria = "- female creator/beauty/women-content match (skincare, beauty, fashion, women lifestyle, etc.)"
            gender_reject_note = "Reject male-only grooming channels. Accept female or neutral lifestyle creators."
            gender_accept_note = "named Indian female creators who post beauty, skincare, fashion, or women lifestyle videos"
            gender_match_rule = "gender_match: true if creator is female or covers female-oriented content"
        else:  # ANY
            gender_criteria = "- real creator-led channel covering any gender (male, female, or mixed audience is fine)"
            gender_reject_note = "Accept both male and female creators. Do not prefer male by default. Reject only brands, stores, clinics, or non-creator channels."
            gender_accept_note = "any real Indian creators — male OR female — who post skincare, beauty, grooming, fashion, or lifestyle content"
            gender_match_rule = "gender_match: true for any real individual creator regardless of gender"

        def score_chunk(chunk: list[dict]) -> dict[str, dict]:
            prompt = f"""You are a strict YouTube influencer discovery analyst for an Indian agency.

Campaign Brief:
"{brief}"

Gender mode: {campaign_gender_mode}

Evaluate these YouTube channels. The goal is real Indian creator-led channels, not brands,
stores, salons, clinics, product companies, media channels, or random unrelated channels.

High Match requires all of:
- real person or creator-led channel
- likely Indian or India-focused
- {gender_criteria}
- relevant to the campaign niche or adjacent content
- not a brand/business/product channel

{gender_reject_note}

Return ONLY a JSON array with one object per input:
[
  {{
    "channel_id": "UC...",
    "final_score": 0-100,
    "match_status": "high|review|rejected",
    "is_real_creator": true,
    "india_confidence": "high|medium|low|unknown",
    "niche_match": true,
    "gender_match": true,
    "is_business": false,
    "reason": "short evidence-based reason"
  }}
]

Note on gender_match: {gender_match_rule}

Reject examples: brand product channels, stores, salons, product brands,
craft/random channels, international channels with no India evidence.
Accept/review examples: {gender_accept_note}.
For mixed/any gender briefs, preserve variety. A female creator and male creator with similar campaign fit should score similarly.

Profiles:
{json.dumps([compact_creator(c) for c in chunk], ensure_ascii=False)}
"""
            text = ""
            try:
                text = self._generate(prompt, temperature=0.05)
                parsed = self._parse_json(text, "array")
                output = {}
                for row in parsed:
                    if isinstance(row, dict) and row.get("channel_id"):
                        output[str(row["channel_id"])] = row
                return output
            except Exception as e:
                self._log_parse_error("Batch YouTube scoring", e, text)
                return {}

        scored_map: dict[str, dict] = {}
        for start in range(0, len(creators), 8):
            scored_map.update(score_chunk(creators[start:start + 8]))

        def as_bool(value, default: bool = False) -> bool:
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"true", "yes", "1", "high"}
            return bool(value)

        for creator in creators:
            cid = str(creator.get("channel_id", ""))
            scored = scored_map.get(cid, {})
            local_score = int(creator.get("_quality_score") or 0)
            final_score = int(scored.get("final_score", local_score))
            status = str(scored.get("match_status") or "").lower()
            is_real = as_bool(scored.get("is_real_creator"), creator.get("_creator_evidence_score", 0) >= 1)
            is_business = as_bool(scored.get("is_business"), False)
            if campaign_gender == "M":
                default_gender_match = creator.get("_gender_score", 0) > 0
            elif campaign_gender == "F":
                default_gender_match = creator.get("_female_score", 0) > 0
            else:
                default_gender_match = True
            gender_match = as_bool(scored.get("gender_match"), default_gender_match)
            niche_match = as_bool(scored.get("niche_match"), creator.get("_niche_score", 0) > 0)
            india_conf = str(scored.get("india_confidence") or creator.get("_india_confidence") or "unknown").lower()

            if status not in {"high", "review", "rejected"}:
                if is_business or not is_real or final_score < 40:
                    status = "rejected"
                elif final_score >= 65 and gender_match and india_conf in {"high", "medium"}:
                    status = "high"
                else:
                    status = "review"

            # Downgrade high → review if key signals are missing (but only reject for hard failures)
            if status == "high" and (is_business or not is_real):
                status = "rejected"
            elif status == "high" and india_conf in {"low", "unknown"}:
                status = "review"
            elif status == "high" and campaign_gender != "ANY" and not gender_match:
                # Only gate on gender_match when campaign has a specific gender requirement
                status = "review"

            creator["match_status"] = status
            creator["ai_final_score"] = final_score
            creator["ai_score"] = round(final_score / 10, 1)
            creator["ai_reason"] = scored.get("reason", creator.get("review_reason", "Local YouTube scoring used"))
            creator["ai_confidence"] = india_conf
            creator["ai_reject"] = status == "rejected"
            creator["ai_review_needed"] = status == "review"
            if status == "rejected":
                creator["reject_reason"] = creator["ai_reason"]
                creator["review_reason"] = ""
            elif status == "review":
                creator["review_reason"] = creator["ai_reason"]
                creator["reject_reason"] = ""
            else:
                creator["review_reason"] = ""
                creator["reject_reason"] = ""

        print(
            f"[AIService] Final scored {len(creators)} YouTube creators. "
            f"High: {sum(1 for c in creators if c.get('match_status') == 'high')}, "
            f"Review: {sum(1 for c in creators if c.get('match_status') == 'review')}, "
            f"Rejected: {sum(1 for c in creators if c.get('match_status') == 'rejected')}"
        )
        return creators

    def run_full_analysis(
        self,
        brief: str,
        verify_hashtags: bool = True,
        user_search_terms: str | list[str] | tuple[str, ...] | None = None,
        exclude_terms: str | list[str] | tuple[str, ...] | None = None,
        progress_callback=None,
        platforms: list[str] | None = None,
    ) -> dict:
        """
        Main entry point. Returns complete analysis.

        platforms — list of active platforms e.g. ["YouTube"], ["Instagram"], or
                    ["YouTube", "Instagram"]. Passing None means both.
        """
        def log(message: str) -> None:
            print(message)
            if progress_callback:
                try:
                    progress_callback(message)
                except Exception:
                    pass

        do_ig = platforms is None or "Instagram" in platforms
        do_yt = platforms is None or "YouTube" in platforms

        user_terms = normalize_user_search_terms(user_search_terms)
        excludes = normalize_user_search_terms(exclude_terms)

        # Stage 1: Understand the brief
        log("[AIService] Brief parsing...")
        intent = self.analyze_brief(brief)
        log(f"[AIService] Intent: {intent.get('niche')} | {intent.get('city') or intent.get('language') or 'India'} | {intent.get('gender_mode') or intent.get('gender')}")

        ig_keywords: list[str] = []
        final_tags: list[str] = []
        hashtags_verified: list[dict] = []
        hashtag_search_terms: list[str] = []
        yt_search_plan: list[dict] = []
        yt_queries: list[str] = []

        # ── Instagram path ─────────────────────────────────────────────────────
        if do_ig:
            log("[AIService] Generating Instagram discovery keywords...")
            ig_keywords = self.generate_ig_keywords(intent, brief)
            for term in user_terms:
                if term not in ig_keywords:
                    ig_keywords.append(term)
            ig_keywords = ig_keywords[:MAX_IG_KEYWORDS]
            log(f"[AIService] Generated {len(ig_keywords)} IG keyword phrases")

            log("[AIService] Planning verified Instagram hashtags...")
            planned = plan_hashtags(
                intent=intent,
                ig_keywords=ig_keywords,
                brief=brief,
                api_keys=self.apify_api_keys,
                verify=verify_hashtags and bool(self.apify_api_keys),
                progress_callback=progress_callback,
            )
            final_tags = planned.get("hashtags_final", [])[:MAX_FINAL_HASHTAGS]
            hashtags_verified = planned.get("hashtags_verified", [])
            hashtag_search_terms = planned.get("hashtag_search_terms", [])
            log(f"[AIService] Selected {len(final_tags)} IG hashtags: {final_tags[:8]}")
        else:
            log("[AIService] Instagram skipped (platform not selected)")

        # ── YouTube path ───────────────────────────────────────────────────────
        if do_yt:
            log("[AIService] Strategic YouTube search planning...")
            yt_search_plan = self.generate_yt_search_plan(
                intent,
                brief,
                user_search_terms=user_terms,
                exclude_terms=excludes,
                use_grounding=True,
            )
            yt_queries = [item["query"] for item in yt_search_plan]
            video_count = sum(1 for item in yt_search_plan if item.get("search_type") == "video")
            channel_count = sum(1 for item in yt_search_plan if item.get("search_type") == "channel")
            hashtag_count = sum(1 for item in yt_search_plan if item.get("source") == "hashtag")
            log(f"[AIService] Query pack ready: {video_count} video + {channel_count} channel + {hashtag_count} hashtag searches")
        else:
            log("[AIService] YouTube skipped (platform not selected)")

        return {
            "intent": intent,
            "hashtags_verified": hashtags_verified,
            "hashtags_final": final_tags,
            "hashtag_search_terms": hashtag_search_terms,
            "ig_keywords": ig_keywords,
            "yt_search_plan": yt_search_plan,
            "yt_queries": yt_queries,
            "user_search_terms": user_terms,
            "exclude_terms": excludes,
        }
