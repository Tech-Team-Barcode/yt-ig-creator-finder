# Influencer Finder Pro — Python Edition

A powerful, fast, AI-driven influencer discovery tool for Instagram and YouTube.

## What's different from the old GAS system

| Old GAS System | This System |
|---|---|
| RapidAPI IG (slow, unreliable) | **Apify actors** (fast, maintained) |
| AI generates hashtags blindly | **Hashtags verified** with real post counts via Apify |
| Sequential GAS calls | **Async parallel** requests |
| 6-min execution cap | **No limit** |
| Curated niche library (brittle) | **Gemini "genius" prompt** understands any brief |
| GAS-only, hard to extend | **Python modules**, easy to extend |

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Get API keys

**Gemini API key:**
- Go to https://aistudio.google.com/app/apikey
- Create a key (free tier works fine)

**Apify API key:**
- Go to https://console.apify.com/account/integrations
- Copy your Personal API Token
- Apify has a free tier; the actors used are:
  - `apify~instagram-hashtag-scraper` — hashtag post scraping
  - `apify~instagram-profile-scraper` — profile enrichment
  - Note: Apify charges per actor run, monitor usage

**YouTube Data API keys (for YT search):**
- Go to https://console.cloud.google.com
- Create a project → Enable YouTube Data API v3
- Create API credentials → Copy key
- Add multiple keys from different projects for more quota (100 units/search)

### 3. Run
```bash
streamlit run app.py
```

Opens at: http://localhost:8501

---

## How the AI hashtag verification works

1. **Brief Analysis** — Gemini deeply reads your campaign brief and extracts:
   - Niche (skincare, fashion, fitness, etc.)
   - Location (city, state, language)
   - Gender focus
   - Creator tier
   - Content format

2. **Hashtag Generation** — Gemini thinks like an influencer marketing expert and generates 30 candidate hashtags across 5 categories (broad discovery, niche-specific, regional/language, format, size tier)

3. **Verification** — Each hashtag is checked via Apify's Instagram Hashtag Scraper to get actual post counts. Tags with <10,000 posts are filtered out and marked as unverified.

4. **Final output** — Only hashtags with proven real usage are used for scraping. You see exact post counts.

This directly solves the problem of AI generating compound tags like `#mumbaimenskincareindian` that literally don't exist on Instagram.

---

## Architecture

```
app.py                  — Streamlit UI
├── ai_service.py       — Gemini analysis + hashtag verification
├── ig_scraper.py       — Apify-based Instagram scraper  
├── yt_scraper.py       — YouTube Data API scraper (async)
└── requirements.txt
```

---

## Tips

- **For best IG results:** Use 5-8 verified hashtags, 50-100 posts per tag
- **For best YT results:** Use 3-4 focused queries with location terms
- **Quota:** Each YT search.list call costs 100 quota units. With 1 key = 100 searches/day max. Add more keys from different GCP projects.
- **Apify costs:** Monitor your usage at console.apify.com. Profile scraping is the most expensive step.

---

## Extending

The modular design makes it easy to add:
- Telegram/LinkedIn scraping via other Apify actors
- Export to Google Sheets
- Campaign tracking / deduplication across runs
- Email verification via Hunter.io or similar
