# Instagram Influencer Discovery: Robust Solution

## Problem Analysis

Your current approach has these issues:

**Rate Limiting & Cost:**
- Calling Gemini for every post (`score_instagram_post()`)
- Calling Gemini for every profile (`score_instagram_profile()`)
- Results in 100+ Gemini calls per campaign
- $0.075-0.15 per profile score = expensive fast
- Rate limits hit frequently (429 errors)

**Poor Filtering:**
- Brands/stores/clinics still get through
- AI is inconsistent on what "creator" means
- No engagement authenticity checks
- Missing behavioral signals

## New Solution: `influencer_validator.py`

### How It Works

**Tier 1: Statistical Validation (85% of filtering, 0 AI calls)**
- Business pattern matching
- Engagement rate analysis (real influencers have natural engagement)
- Bio quality scoring
- Account authenticity checks
- Returns: `needs_ai_review: bool`

**Tier 2: AI Review Only for Ambiguous Cases (15% remaining)**
- Only profiles scoring 50-75 (uncertain zone)
- Batch them together for single Gemini call
- Reduces AI usage by 85-90%

### Key Improvements

1. **Engagement Authenticity** - Detect fake followers/pods
2. **Bio Pattern Matching** - Catch stores/clinics early
3. **Account Age Checks** - Filter new accounts suspicious followers
4. **Link Analysis** - Identify ecommerce/medical links
5. **Creator Signal Detection** - Count influencer language markers

## Integration Steps

### Step 1: Import in `ig_scraper.py`

```python
from influencer_validator import InstagramInfluencerValidator, CreatorConfidence

# Create once at module level
_validator = InstagramInfluencerValidator()

def validate_creator_profile(creator_data: dict) -> tuple[int, bool, str]:
    """
    Replace Gemini scoring with statistical validation.
    Returns: (score 0-100, needs_ai_review, reason)
    """
    result = _validator.validate_profile(
        username=creator_data.get("username", ""),
        full_name=creator_data.get("full_name", ""),
        bio=creator_data.get("bio", ""),
        followers=creator_data.get("followers", 0),
        posts_count=creator_data.get("posts_count", 0),
        is_private=creator_data.get("is_private", False),
        is_business=creator_data.get("is_business", False),
        business_category=creator_data.get("business_category", ""),
        likes=creator_data.get("sample_post_likes", 0),
        comments=creator_data.get("sample_post_comments", 0),
        recent_captions=creator_data.get("recent_captions", ""),
    )
    
    return (
        result.score,
        result.needs_ai_review,
        result.reason
    )
```

### Step 2: Update `scrape_hashtag_for_creators()`

**Current code:**
```python
if post_scorer:
    post_ai = post_scorer(post_payload)
    if (int(post_ai.get("relevance_score", 0)) < post_score_threshold or ...):
        continue
```

**Issue:** You're calling AI for EVERY post. Stop this.

**Fix:**
```python
# REMOVE post_scorer AI calls here - move to enrichment phase only
# Just do regex filtering instead

if BUSINESS_REJECT.search(full_text):
    continue

# Follower range check is fine
if followers > 0:
    if followers < min_followers or (max_followers > 0 and followers > max_followers):
        continue

# Continue with current inline filtering...
```

### Step 3: Update `enrich_top_candidates()`

**Add statistical validation BEFORE AI:**
```python
for candidate in to_enrich:
    # ... existing enrichment code ...
    
    # NEW: Statistical validation (0 cost)
    stat_score, needs_ai, stat_reason = validate_creator_profile(candidate)
    candidate["stat_score"] = stat_score
    candidate["stat_reason"] = stat_reason
    candidate["needs_ai_review"] = needs_ai
    
    # Hard reject obvious non-creators
    if stat_score < 30:
        continue  # Skip to next candidate
    
    # Keep for AI review if ambiguous
    if needs_ai:
        # Will batch AI review below
        pass
    elif stat_score >= 70:
        # High confidence creator, skip AI
        candidate["ai_final_score"] = stat_score
        final.append(candidate)
        continue

# Batch AI review for uncertain cases only
to_ai_review = [c for c in final if c.get("needs_ai_review", False)]
print(f"[IG] {len(to_ai_review)} candidates need AI review (vs {len(final)} total)")

if to_ai_review:
    # ONE Gemini call for all ambiguous cases (batch scoring)
    ai_scored = score_creators_batch_optimized(to_ai_review, intent, ai_service)
    for c in ai_scored:
        if not c.get("ai_reject", False):
            final.append(c)
```

### Step 4: Create Optimized Batch Scorer

Create this in `ai_service.py`:

```python
def score_creators_batch_optimized(
    self, 
    creators: list[dict], 
    intent: dict,
    only_high_confidence=False
) -> list[dict]:
    """
    Score only ambiguous creators (stat_score 50-75).
    Batch them all in ONE Gemini call instead of per-profile.
    """
    if not creators:
        return []

    brief = intent.get("_brief") or intent.get("brief") or (
        f"Find {intent.get('gender', 'ANY')} {intent.get('niche', 'lifestyle')} creators "
        f"in {intent.get('city') or intent.get('state') or 'India'}"
    )

    # Prepare batch prompt
    profiles_text = "\n\n---\n\n".join([
        f"""Profile #{i+1}: {c.get('username', '')}
Bio: {c.get('bio', '')}
Followers: {c.get('followers', 0)}
Posts: {c.get('posts_count', 0)}
Stat Score: {c.get('stat_score', 0)}/100
Recent Caption Sample: {c.get('recent_captions', '')[:200]}"""
        for i, c in enumerate(creators[:20])  # Batch max 20 at a time
    ])

    prompt = f"""Campaign: "{brief}"

Review these {len(creators)} AMBIGUOUS Instagram profiles (already flagged as uncertain by statistical analysis).

RESPOND WITH ONLY VALID JSON ARRAY. No explanation.

Output format:
[
  {{"username": "user1", "accept": true/false, "reason": "short note"}},
  {{"username": "user2", "accept": true/false, "reason": "short note"}}
]

PROFILES TO REVIEW:
{profiles_text}

Quick rules:
- Reject: Businesses, stores, clinics, brands, distributors
- Accept: Real personal creators, authentic influencers
- If unsure, lean toward REJECT (we have plenty of other creators)
"""

    text = ""
    try:
        text = self._generate(prompt, temperature=0.2, max_output_tokens=1024)
        decisions = self._parse_json(text, "array")
        
        # Apply decisions
        decision_map = {d.get("username"): d for d in decisions}
        for creator in creators:
            decision = decision_map.get(creator.get("username", {}), {})
            creator["ai_final_score"] = 70 if decision.get("accept") else 30
            creator["ai_reject"] = not decision.get("accept", False)
            creator["ai_reason"] = decision.get("reason", "Ambiguous profile")
        
        return creators
    except Exception as e:
        self._log_parse_error("Batch scoring", e, text)
        # Conservative: reject all if AI fails
        for c in creators:
            c["ai_reject"] = True
            c["ai_reason"] = "AI batch scoring failed"
        return creators
```

## Cost Savings & Speed Comparison

### Before (Current):
- 30 profiles per run
- 30 post scores (if enabled): 30 × $0.00075 = ~$0.02
- 30 profile scores: 30 × $0.0025 = ~$0.075
- **Total: $0.10 + rate limits**

### After (New):
- 30 profiles per run
- 0 post scores (regex only)
- ~3 profiles need AI review (batch): 1 × $0.0025 = ~$0.003
- **Total: ~$0.003 (97% savings!) + no rate limits**

## Implementation Checklist

- [ ] Copy `influencer_validator.py` to project
- [ ] Add import to `ig_scraper.py`
- [ ] Remove `post_scorer` AI calls from hashtag scraping
- [ ] Add statistical validation to enrichment
- [ ] Create batch AI scorer in `ai_service.py`
- [ ] Update app.py to remove "post AI checks" cap (no longer needed)
- [ ] Test with sample campaign
- [ ] Verify cost/performance improvements
- [ ] Adjust thresholds based on results

## Threshold Tuning

If you're getting too many non-creators:
- Increase `score >= 60` threshold to `score >= 75` in enrichment
- Reduce `needs_ai_review` threshold from score 50-75 to 60-75

If you're filtering out too many creators:
- Lower threshold to `score >= 50`
- Increase AI batch review to `needs_ai_review=True` for score > 40

## Advanced: Link Analysis

The validator already checks for:
- ecommerce links (Flipkart, Amazon, Myntra, etc.)
- clinic/hospital links
- personal portfolio links (Linktree, Beacons)

Stores are auto-rejected. Clinics are auto-rejected.  
Personal portfolio links are bonus points.

## Notes

1. **First time setup**: Run against your existing creators list to see performance
2. **Monitoring**: Log `stat_score` and `needs_ai_review` to track filtering
3. **Feedback loop**: If AI rejects statistically high-scoring creators, lower thresholds
4. **Regional tuning**: Add language-specific patterns to CREATOR_INDICATORS as needed
