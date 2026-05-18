"""
ai_service.py — Gemini Influencer Marketing Genius
====================================================
Two-stage approach:
  Stage 1: Gemini deeply understands the campaign brief (niche, region, gender,
           creator tier, language, intent signals) and generates candidate
           hashtags + YT queries thinking like an influencer marketing expert.
  Stage 2: Hashtags are verified against real Instagram post counts via Apify.
           Only tags with proven usage (>= MIN_POST_COUNT) are kept.

This completely solves the "trash hashtag" problem from the GAS system.
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
MAX_IG_KEYWORDS = 18


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
  "creator_tier": "nano (1K-10K) | micro (10K-100K) | mid (100K-500K) | macro (500K+) | any",
  "min_followers": integer,
  "max_followers": integer,
  "content_formats": ["reels", "posts", "stories", "shorts", "long_form"] - whichever apply,
  "campaign_type": "awareness | product_review | haul | tutorial | lifestyle | ugc",
  "age_target": "teen | young_adult | adult | any",
  "confidence": "high | medium | low",
  "reasoning": "1-2 sentence explanation of your interpretation"
}}

For follower ranges use these defaults if not specified:
- nano: 1000-10000, micro: 5000-150000, mid: 100000-600000, macro: 500000-5000000, any: 1000-1000000"""


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
            config_kwargs = {
                "system_instruction": system,
                "temperature": temperature,
                "max_output_tokens": 2048,
            }
            if response_mime_type:
                config_kwargs["response_mime_type"] = response_mime_type

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
            # Handles responses that use single quotes or Python-style None/True.
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
            return self._parse_json(text, "object")
        except Exception as e:
            self._log_parse_error("Brief analysis", e, text)
            return {
                "niche": "lifestyle", "secondary_niche": None,
                "language": None, "city": None, "state": None,
                "gender": "ANY", "creator_tier": "micro",
                "min_followers": 5000, "max_followers": 150000,
                "confidence": "low", "reasoning": "Parse error, using defaults"
            }

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
        """
        Verify a single hashtag via Apify Instagram Hashtag Scraper.
        Returns (tag, post_count). post_count = -1 if verification failed.
        """
        clean_tag = tag.lstrip("#")
        url = "https://api.apify.com/v2/acts/apify~instagram-hashtag-scraper/run-sync-get-dataset-items"
        payload = {
            "hashtags": [clean_tag],
            "resultsLimit": 1,  # We only need the count, not actual posts
        }
        params = {"token": self.apify_api_key}
        try:
            async with session.post(url, json=payload, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    if data and len(data) > 0:
                        item = data[0]
                        # Apify hashtag scraper returns topPostsCount or postsCount
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
        """
        Verify all candidate hashtags in parallel via Apify.
        Returns list of {tag, post_count, verified} sorted by post_count desc.
        """
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

        # Sort: verified tags first by post count, then unverified
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

    def run_full_analysis(self, brief: str, verify_hashtags: bool = True) -> dict:
        """
        Main entry point. Returns complete analysis:
        - intent: parsed campaign brief
        - hashtags_verified: list with post counts
        - hashtags_final: top verified tags ready to use
        - yt_queries: YouTube search queries
        """
        # Stage 1: Understand the brief
        print("[AIService] Analyzing campaign brief...")
        intent = self.analyze_brief(brief)
        print(f"[AIService] Intent: {intent.get('niche')} | {intent.get('city') or intent.get('language') or 'India'} | {intent.get('gender')}")

        # Stage 2: Generate creator-intent discovery keywords. Hashtags are discovered
        # from these keywords via Apify during IG search, instead of asking Gemini to
        # hallucinate hashtags.
        print("[AIService] Generating Instagram discovery keywords...")
        ig_keywords = self.generate_ig_keywords(intent, brief)
        print(f"[AIService] Generated {len(ig_keywords)} IG keyword phrases")

        print("[AIService] Generating YouTube queries...")
        yt_queries = self.generate_yt_queries(intent, brief)
        print(f"[AIService] Generated {len(yt_queries)} YT queries")

        # Generate hashtags from Gemini — these are the seed tags for ig_scraper
        print("[AIService] Planning verified Instagram hashtags...")
        planned = plan_hashtags(
            intent=intent,
            ig_keywords=ig_keywords,
            brief=brief,
            api_keys=self.apify_api_keys,
            verify=verify_hashtags and bool(self.apify_api_keys),
        )
        final_tags = planned.get("hashtags_final", [])[:MAX_FINAL_HASHTAGS]
        print(f"[AIService] Selected {len(final_tags)} IG hashtags: {final_tags[:8]}")

        return {
            "intent": intent,
            "hashtags_verified": planned.get("hashtags_verified", []),
            "hashtags_final": final_tags,
            "hashtag_search_terms": planned.get("hashtag_search_terms", []),
            "ig_keywords": ig_keywords,
            "yt_queries": yt_queries,
        }
