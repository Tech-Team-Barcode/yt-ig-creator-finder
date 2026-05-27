# """Influencer Finder Pro."""

# from __future__ import annotations

# import asyncio
# import html
# import re
# from datetime import datetime
# from io import BytesIO

# import pandas as pd
# import streamlit as st

# from ai_service import AIService, normalize_user_search_terms
# from backend_keys import backend_key_counts, env_keys, first_non_empty, parse_keys
# from creator_history import (
#     annotate_used_creators,
#     campaign_scope,
#     clear_used_creators,
#     creator_identity_candidates,
#     filter_used_creators,
#     history_stats,
#     mark_creators_used,
# )
# from ui_table import render_creator_table
# from ig_scraper import run_ig_search
# from yt_scraper import run_yt_search
# from scrapingbee_scraper import run_scrapingbee_search


# st.set_page_config(
#     page_title="Influencer Finder Pro",
#     page_icon="IF",
#     layout="wide",
#     initial_sidebar_state="expanded",
# )

# st.markdown(
#     """
# <style>
#   @import url('https://fonts.googleapis.com/css2?family=League+Spartan:wght@300;400;500;600;700;800;900&display=swap');
#   html, body, [class*="css"] { font-family: 'League Spartan', sans-serif !important; }
#   .stApp { background: #ffffff !important; color: #0a0a0a !important; }
#   section[data-testid="stSidebar"] { background: #f5f5f5 !important; border-right: 1px solid #e0e0e0 !important; }
#   .section-title { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: #777; margin: 20px 0 8px; padding-bottom: 6px; border-bottom: 1px solid #e0e0e0; }
#   .soft-panel { background: #f5f5f5; border: 1px solid #e0e0e0; border-radius: 6px; padding: 12px 14px; font-family: 'League Spartan', sans-serif; font-size: 0.72rem; color: #444; line-height: 1.7; }
#   .chip { display: inline-block; padding: 3px 9px; margin: 3px; border-radius: 4px; font-family: 'League Spartan', sans-serif; font-size: 0.72rem; font-weight: 600; border: 1px solid #ccc; color: #444; background: #f5f5f5; letter-spacing: 0.02em; }
#   .chip.good { border-color: #1a7a3a; color: #1a7a3a; background: rgba(26,122,58,.07); }
#   .chip.warn { border-color: #7a4a00; color: #7a4a00; background: rgba(122,74,0,.07); }
#   .chip.bad  { border-color: #8a0000; color: #8a0000; background: rgba(138,0,0,.07); }
#   .creator-card { background: #f5f5f5; border: 1px solid #e0e0e0; border-radius: 6px; padding: 14px; margin-bottom: 10px; }
#   .creator-title { font-weight: 800; color: #0a0a0a; font-family: 'League Spartan', sans-serif; }
#   .muted { color: #777777; font-size: .86rem; }
#   .metric-box { background: #f5f5f5; border: 1px solid #e0e0e0; border-radius: 6px; padding: 16px; text-align: center; }
#   .metric-box .num { font-size: 1.8rem; font-weight: 900; color: #0a0a0a; font-family: 'League Spartan', sans-serif; }
#   .metric-box .label { color: #777; font-size: .82rem; }
# </style>
# """,
#     unsafe_allow_html=True,
# )

# # Map internal match_status → display label and chip class
# _STATUS_LABEL = {"high": "High", "review": "Mid", "rejected": "Low", "mid": "Mid", "low": "Low"}
# _STATUS_CLS   = {"high": "good", "review": "warn", "rejected": "bad",  "mid": "warn", "low": "bad"}
# CREATOR_TIER_RANGES = {
#     "Nano": (1_000, 10_000),
#     "Micro": (10_000, 100_000),
#     "Mid": (100_000, 500_000),
#     "Macro": (500_000, 5_000_000),
#     "Any": (10_000, 500_000),
# }
# CREATOR_TIER_OPTIONS = ["Auto", "Any", "Nano", "Micro", "Mid", "Macro", "Custom range"]


# def _status_label(status: str) -> str:
#     return _STATUS_LABEL.get(status, status.title())


# def _status_cls(status: str) -> str:
#     return _STATUS_CLS.get(status, "")


# def _normalize_status(status: str) -> str:
#     """Normalise raw match_status to high / mid / low for export."""
#     return {"high": "high", "review": "mid", "rejected": "low",
#             "mid": "mid", "low": "low"}.get(status, status)


# def init_state() -> None:
#     defaults = {
#         "analysis_result": None,
#         "ig_results": [],
#         "yt_results": [],
#         "ig_debug": {},
#         "search_complete": False,
#         "last_brief": "",
#         "last_platforms": [],
#         "history_notice": "",
#         "ai_filter_version": 0,
#         "review_queries": [],
#         "review_hashtags": [],
#         "review_brand_tags": [],
#         "review_trending_tags": [],
#         "user_extra_keywords": "",
#         "reference_creators": "",
#         "show_review_panel": False,
#         "ai_suggested_min": 10000,
#         "ai_suggested_max": 500000,
#         "ai_suggested_gender": "Auto",
#         "ai_suggested_tier": "Auto",
#         "ai_suggested_locations": [],
#         "selected_review_tags": [],
#     }
#     for key, value in defaults.items():
#         if key not in st.session_state:
#             st.session_state[key] = value


# def run_async(coro):
#     loop = asyncio.new_event_loop()
#     try:
#         return loop.run_until_complete(coro)
#     finally:
#         loop.close()


# def fmt_num(value) -> str:
#     try:
#         n = int(value)
#     except Exception:
#         return str(value)
#     if n >= 1_000_000:
#         return f"{n / 1_000_000:.1f}M"
#     if n >= 1_000:
#         return f"{n / 1_000:.1f}K"
#     return str(n)


# def chip(label: str, cls: str = "") -> str:
#     return f'<span class="chip {cls}">{html.escape(label)}</span>'


# def yt_plan_from_queries(queries: list[str], source: str = "user") -> list[dict]:
#     return [
#         {
#             "query": query,
#             "search_type": "video",
#             "source": source,
#             "intent_terms": [],
#             "negative_terms": [],
#             "paginate": True,
#         }
#         for query in queries
#         if query
#     ]


# def get_key_config(overrides: dict[str, str]) -> dict[str, list[str]]:
#     gemini = first_non_empty(parse_keys(overrides.get("gemini")), env_keys("GEMINI_API_KEYS"), env_keys("GEMINI_API_KEY"))
#     apify_discovery = first_non_empty(
#         parse_keys(overrides.get("apify_discovery")),
#         env_keys("APIFY_DISCOVERY_KEYS"),
#         env_keys("APIFY_API_KEYS"),
#         env_keys("APIFY_API_KEY"),
#     )
#     apify_profile = first_non_empty(
#         parse_keys(overrides.get("apify_profile")),
#         env_keys("APIFY_PROFILE_KEYS"),
#         apify_discovery,
#     )
#     youtube = first_non_empty(parse_keys(overrides.get("youtube")), env_keys("YOUTUBE_API_KEYS"), env_keys("YOUTUBE_API_KEY"))
#     scrapingbee = first_non_empty(
#         parse_keys(overrides.get("scrapingbee")),
#         env_keys("SCRAPINGBEE_KEYS"),
#         env_keys("SCRAPINGBEE_API_KEY"),
#     )
#     return {
#         "gemini": gemini,
#         "apify_discovery": apify_discovery,
#         "apify_profile": apify_profile,
#         "youtube": youtube,
#         "scrapingbee": scrapingbee,
#     }


# def creators_to_df(creators: list[dict]) -> pd.DataFrame:
#     rows = []
#     for c in creators:
#         if c.get("platform") == "instagram":
#             rows.append({
#                 "Platform": "Instagram",
#                 "Status": _normalize_status(c.get("match_status", "")),
#                 "Username/Handle": c.get("username", ""),
#                 "Full Name": c.get("full_name", ""),
#                 "Followers": c.get("followers", 0),
#                 "Profile URL": c.get("profile_url", ""),
#                 "Bio": c.get("bio", ""),
#                 "Source Hashtag": "#" + c.get("source_hashtag", "") if c.get("source_hashtag") else "",
#                 "Sample Post": c.get("sample_post_url", ""),
#                 "Email": c.get("email", ""),
#                 "Phone": c.get("phone", ""),
#                 "Website": c.get("external_url", ""),
#                 "Used Before": "Yes" if c.get("_history_used") else "",
#                 "AI Score": c.get("ai_score", ""),
#                 "Niche Confidence": c.get("niche_confidence", 0),
#                 "India Confidence": c.get("india_confidence", 0),
#                 "Gender Confidence": c.get("gender_confidence", 0),
#                 "Creator Confidence": c.get("creator_confidence", 0),
#                 "Evidence": c.get("evidence", ""),
#                 "Reason": c.get("reject_reason") or c.get("review_reason") or c.get("ai_reason", ""),
#             })
#         else:
#             rows.append({
#                 "Platform": "YouTube",
#                 "Status": _normalize_status(c.get("match_status", "mid")),
#                 "Username/Handle": c.get("handle", "") or c.get("channel_name", ""),
#                 "Full Name": c.get("channel_name", ""),
#                 "Followers": c.get("subscribers", 0),
#                 "Profile URL": c.get("handle_url") or c.get("channel_url", ""),
#                 "Bio": c.get("description", ""),
#                 "Source Hashtag": "",
#                 "Sample Post": c.get("video_url", ""),
#                 "Email": c.get("email", ""),
#                 "Phone": c.get("phone", ""),
#                 "Website": c.get("website") or c.get("aggregator_url", ""),
#                 "Used Before": "Yes" if c.get("_history_used") else "",
#                 "AI Score": c.get("ai_score", ""),
#                 "Niche Confidence": c.get("_niche_score", ""),
#                 "India Confidence": c.get("_india_confidence", c.get("_location_score", "")),
#                 "Gender Confidence": c.get("_gender_score", ""),
#                 "Creator Confidence": c.get("_quality_score", 0),
#                 "Evidence": c.get("video_title", "") or c.get("_search_query", ""),
#                 "Reason": c.get("reject_reason") or c.get("review_reason") or c.get("ai_reason", ""),
#             })
#     return pd.DataFrame(rows)


# def df_to_excel(df: pd.DataFrame) -> bytes:
#     output = BytesIO()
#     with pd.ExcelWriter(output, engine="openpyxl") as writer:
#         df.to_excel(writer, index=False, sheet_name="Creators")
#         ws = writer.sheets["Creators"]
#         for col in ws.columns:
#             max_len = max(len(str(cell.value or "")) for cell in col)
#             ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 60)
#     return output.getvalue()


# def render_creator_card(creator: dict, selection_key: str | None = None) -> None:
#     platform = creator.get("platform", "")
#     if platform == "instagram":
#         name = html.escape(str(creator.get("full_name") or creator.get("username", "")))
#         handle = html.escape("@" + str(creator.get("username", "")))
#         url = html.escape(str(creator.get("profile_url", "")), quote=True)
#         followers = creator.get("followers", 0)
#         bio = html.escape(str(creator.get("bio", ""))[:220])
#         status = creator.get("match_status", "review")
#         reason = html.escape(str(creator.get("reject_reason") or creator.get("review_reason") or creator.get("ai_reason") or ""))
#         chips = [
#             chip(_status_label(status), _status_cls(status)),
#             chip(f"{fmt_num(followers)} followers"),
#         ]
#         if creator.get("_history_used"):
#             chips.append(chip("Used before", "bad"))
#         if creator.get("ai_score") not in (None, ""):
#             chips.append(chip(f"AI {creator.get('ai_score')}/10"))
#         if creator.get("source_hashtag"):
#             chips.append(chip("#" + str(creator.get("source_hashtag")), "warn"))
#         evidence = html.escape(str(creator.get("evidence", ""))[:260])
#     else:
#         name = html.escape(str(creator.get("channel_name", "")))
#         handle = html.escape(str(creator.get("handle", "")))
#         url = html.escape(str(creator.get("handle_url") or creator.get("channel_url") or ""), quote=True)
#         followers = creator.get("subscribers", 0)
#         bio = html.escape(str(creator.get("description", ""))[:220])
#         status = creator.get("match_status", "review")
#         reason = html.escape(str(creator.get("reject_reason") or creator.get("review_reason") or creator.get("ai_reason") or ""))
#         chips = [
#             chip(_status_label(status), _status_cls(status)),
#             chip(f"{fmt_num(followers)} subscribers"),
#         ]
#         if creator.get("_history_used"):
#             chips.append(chip("Used before", "bad"))
#         if creator.get("ai_score") not in (None, ""):
#             chips.append(chip(f"AI {creator.get('ai_score')}/10"))
#         if creator.get("_source"):
#             chips.append(chip(str(creator.get("_source")), "warn"))
#         evidence_text = creator.get("video_title") or ("Query: " + str(creator.get("_search_query", "")))
#         evidence = html.escape(str(evidence_text)[:260])

#     st.markdown(
#         f"""
# <div class="creator-card">
#   <div class="creator-title">{name} <span class="muted">{handle}</span></div>
#   <div>{''.join(chips)}</div>
#   <div class="muted" style="margin-top:6px">{bio}</div>
#   <div class="muted" style="margin-top:6px">{evidence}</div>
#   {'<div class="muted" style="margin-top:6px">Reason: ' + reason + '</div>' if reason else ''}
#   {'<a href="' + url + '" target="_blank">Open profile</a>' if url else ''}
# </div>
# """,
#         unsafe_allow_html=True,
#     )
#     if selection_key:
#         st.checkbox("Mark as used", key=selection_key)


# def render_cards(items: list[dict], selectable: bool = False) -> list[tuple[str, dict]]:
#     if not items:
#         st.info("No creators in this bucket.")
#         return []
#     selection_rows: list[tuple[str, dict]] = []
#     cols_per_row = 2
#     for start in range(0, len(items), cols_per_row):
#         cols = st.columns(cols_per_row)
#         for offset, col in enumerate(cols):
#             index = start + offset
#             if index < len(items):
#                 with col:
#                     selection_key = None
#                     if selectable:
#                         ids = sorted(value for _, value in creator_identity_candidates(items[index]))
#                         identity = re.sub(r"[^a-zA-Z0-9_]+", "_", ids[0] if ids else str(index))
#                         selection_key = f"used_select_{index}_{identity}"
#                         selection_rows.append((selection_key, items[index]))
#                     render_creator_card(items[index], selection_key=selection_key)
#     return selection_rows


# def show_hashtag_plan(result: dict) -> None:
#     hashtags_verified = result.get("hashtags_verified", [])
#     hashtags_final = result.get("hashtags_final", [])

#     st.markdown('<div class="sec-label">Instagram Hashtags</div>', unsafe_allow_html=True)
#     if hashtags_final:
#         st.markdown("".join(chip(tag, "good") for tag in hashtags_final), unsafe_allow_html=True)
#         st.code(" ".join(hashtags_final), language=None)
#     else:
#         st.warning("No usable Instagram hashtags selected.")

#     if hashtags_verified:
#         selected_count = sum(1 for h in hashtags_verified if h.get("selected"))
#         st.caption(f"{selected_count}/{len(hashtags_verified)} tags selected after quality gate")
#         rows = []
#         for h in hashtags_verified:
#             cls = "good" if h.get("selected") else "bad"
#             label = f"{h.get('tag')} | {h.get('count_display', 'unverified')} | {h.get('reason', '')}"
#             rows.append(chip(label, cls))
#         st.markdown("".join(rows[:60]), unsafe_allow_html=True)

#     search_terms = result.get("hashtag_search_terms", [])
#     if search_terms:
#         with st.expander("Hashtag search terms"):
#             st.write(search_terms)


# init_state()

# if st.query_params.get("reset"):
#     for key in (
#         "analysis_result", "ig_results", "yt_results", "ig_debug", "search_complete",
#         "last_brief", "last_platforms", "history_notice", "ai_suggested_min",
#         "ai_suggested_max", "ai_suggested_gender", "ai_suggested_tier",
#     ):
#         if key in st.session_state:
#             del st.session_state[key]
#     st.query_params.clear()
#     st.rerun()

# st.markdown(
#     """
# <style>
# @import url('https://fonts.googleapis.com/css2?family=League+Spartan:wght@300;400;500;600;700;800;900&display=swap');

# /* Reset Streamlit defaults */
# html, body, [class*="css"], [class*="st-"] {
#   font-family: 'League Spartan', sans-serif !important;
# }
# .stApp { background: #ffffff !important; color: #0a0a0a !important; }
# .block-container { padding: 0 !important; max-width: 100% !important; }
# #MainMenu, header[data-testid="stHeader"], footer { display: none !important; }

# /* Topbar */
# #ciq-topbar {
#   display: flex; align-items: center; gap: 20px;
#   padding: 12px 24px; background: #ffffff;
#   border-bottom: 2px solid #0a0a0a; position: sticky; top: 0; z-index: 999;
# }
# #ciq-topbar .topbar-right { margin-left: auto; display: flex; align-items: center; gap: 16px; }

# /* Logo */
# .logo-wrap { display:flex; align-items:center; gap:10px; }
# .logo-bar { font-family:'League Spartan',sans-serif; font-weight:800; font-size:1rem; letter-spacing:.5px; color:#111; }
# .logo-bar-bg { background:#111; color:#fff; padding:1px 5px; border-radius:2px; margin-right:1px; }
# .logo-divider { color:#999; font-size:1.2rem; font-weight:300; margin:0 4px; }
# .logo-ykone { font-family:'Georgia','Times New Roman',serif; font-style:italic; font-size:1.1rem; color:#111; font-weight:400; }

# /* Quota bar */
# .quota-wrap { display: flex; align-items: center; gap: 12px; }
# .quota-item { display: flex; align-items: center; gap: 6px; }
# .quota-label { font-family: 'League Spartan', sans-serif; font-size: 0.65rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #777; white-space: nowrap; }
# .quota-bar { width: 56px; height: 4px; background: #e0e0e0; border-radius: 99px; overflow: hidden; }
# .quota-bar-fill { height: 100%; background: #0a0a0a; border-radius: 99px; }
# .quota-pct { font-family: 'League Spartan', sans-serif; color: #777; font-size: 0.65rem; min-width: 24px; }

# /* Reset link */
# .reset-link {
#   font-family: 'League Spartan', sans-serif; font-size: 0.72rem; font-weight: 700;
#   letter-spacing: 0.06em; text-transform: uppercase; color: #0a0a0a;
#   text-decoration: none; padding: 5px 12px; border: 1px solid #0a0a0a; border-radius: 4px;
# }
# .reset-link:hover { background: #0a0a0a; color: #fff; }

# /* Sidebar */
# section[data-testid="stSidebar"] {
#   background: #f5f5f5 !important; border-right: 1px solid #e0e0e0 !important;
#   min-width: 320px !important; max-width: 320px !important; padding: 0 !important;
# }
# section[data-testid="stSidebar"] > div { padding: 0 !important; }
# section[data-testid="stSidebar"] * { font-family: 'League Spartan', sans-serif !important; }
# section[data-testid="stSidebar"] label {
#   color: #444 !important; font-size: 0.75rem !important;
#   font-weight: 600 !important; letter-spacing: 0.05em !important; text-transform: uppercase !important;
# }
# section[data-testid="stSidebar"] input,
# section[data-testid="stSidebar"] textarea,
# section[data-testid="stSidebar"] select {
#   background: #ffffff !important; border: 1px solid #cccccc !important;
#   color: #0a0a0a !important; border-radius: 4px !important;
#   font-family: 'League Spartan', sans-serif !important;
# }
# section[data-testid="stSidebar"] input:focus,
# section[data-testid="stSidebar"] textarea:focus {
#   border-color: #0a0a0a !important; box-shadow: none !important; outline: none !important;
# }
# .sidebar-inner { padding: 0 16px 80px 16px; }

# /* AI Panel */
# .ai-panel { background: #f5f5f5; border: 1px solid #e0e0e0; border-radius: 6px; margin: 12px 0; padding: 14px 16px; }
# .ai-panel-title { font-family: 'League Spartan', sans-serif; font-size: 0.72rem; font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase; color: #0a0a0a; margin-bottom: 10px; }
# .ai-confidence { display:flex; gap:8px; align-items:center; margin-bottom:6px; flex-wrap: wrap; }
# .conf-high { background:#0a0a0a; color:#fff; padding:2px 8px; border-radius:3px; font-size:0.68rem; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; }
# .conf-mid  { background:#444; color:#fff; padding:2px 8px; border-radius:3px; font-size:0.68rem; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; }
# .conf-low  { background:#fff; color:#999; border:1px solid #ccc; padding:2px 8px; border-radius:3px; font-size:0.68rem; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; }
# .ai-suggest-row { font-family: 'League Spartan', sans-serif; font-size: 0.72rem; color: #555; margin-bottom: 6px; }
# .ai-suggest-row strong { color: #0a0a0a; font-weight: 700; }

# /* Section labels */
# .sec-label {
#   font-family: 'League Spartan', sans-serif; font-size: 0.68rem; font-weight: 700;
#   letter-spacing: 0.1em; text-transform: uppercase; color: #777;
#   margin: 20px 0 8px; padding-bottom: 6px; border-bottom: 1px solid #e0e0e0;
# }
# .kw-section-label { color: #777; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; margin: 8px 0 4px; text-transform: uppercase; font-family: 'League Spartan', sans-serif; }

# /* Keyword chips */
# .kw-chip {
#   display: inline-flex; align-items: center; gap: 4px; background: #fff;
#   border: 1px solid #ccc; border-radius: 4px; color: #0a0a0a;
#   font-family: 'League Spartan', sans-serif; font-size: 0.72rem; font-weight: 600;
#   padding: 3px 9px; margin: 3px; letter-spacing: 0.01em;
# }
# .kw-chip .plus { color: #0a0a0a; font-weight: 800; }

# /* Streamlit buttons */
# .stButton > button {
#   font-family: 'League Spartan', sans-serif !important; font-weight: 700 !important;
#   letter-spacing: 0.03em !important; border-radius: 4px !important; font-size: 0.82rem !important;
# }
# .stButton > button[kind="primary"],
# .stButton > button:not([kind]) {
#   background: #0a0a0a !important; color: #ffffff !important; border: 1px solid #0a0a0a !important;
# }
# .stButton > button:hover { background: #333 !important; border-color: #333 !important; }

# /* Download button */
# .stDownloadButton > button {
#   font-family: 'League Spartan', sans-serif !important; background: #fff !important;
#   border: 1px solid #0a0a0a !important; color: #0a0a0a !important; font-weight: 700 !important;
#   border-radius: 4px !important; font-size: 0.78rem !important; letter-spacing: 0.04em !important;
# }
# .stDownloadButton > button:hover { background: #0a0a0a !important; color: #fff !important; }

# /* Tabs */
# .stTabs [data-baseweb="tab-list"] {
#   background: #ffffff !important; border-bottom: 2px solid #e0e0e0 !important; gap: 0 !important;
# }
# .stTabs [data-baseweb="tab"] {
#   color: #777 !important; font-family: 'League Spartan', sans-serif !important;
#   font-size: 0.85rem !important; font-weight: 700 !important; letter-spacing: 0.04em !important;
#   text-transform: uppercase !important; padding: 10px 28px !important;
#   border-bottom: 2px solid transparent !important; border-radius: 0 !important;
# }
# .stTabs [aria-selected="true"] {
#   color: #0a0a0a !important; border-bottom: 2px solid #0a0a0a !important; background: transparent !important;
# }

# /* Expanders */
# .streamlit-expanderHeader {
#   font-family: 'League Spartan', sans-serif !important; font-weight: 700 !important;
#   font-size: 0.8rem !important; letter-spacing: 0.06em !important; text-transform: uppercase !important;
#   color: #444 !important; background: #f5f5f5 !important;
#   border: 1px solid #e0e0e0 !important; border-radius: 4px !important;
# }
# .streamlit-expanderContent {
#   border: 1px solid #e0e0e0 !important; border-top: none !important;
#   border-radius: 0 0 4px 4px !important; background: #fff !important;
# }

# /* Metrics */
# [data-testid="stMetric"] {
#   background: #f5f5f5; border: 1px solid #e0e0e0; border-radius: 6px; padding: 16px !important;
# }
# [data-testid="stMetricValue"] {
#   font-family: 'League Spartan', sans-serif !important; font-size: 1.8rem !important;
#   font-weight: 900 !important; color: #0a0a0a !important;
# }
# [data-testid="stMetricLabel"] {
#   font-family: 'League Spartan', sans-serif !important; color: #777 !important;
#   font-size: 0.7rem !important; font-weight: 600 !important;
#   text-transform: uppercase !important; letter-spacing: 0.07em !important;
# }

# /* Select boxes */
# .stSelectbox > div > div {
#   background: #fff !important; border: 1px solid #ccc !important;
#   border-radius: 4px !important; font-family: 'League Spartan', sans-serif !important; color: #0a0a0a !important;
# }

# /* Progress bar */
# .stProgress > div > div > div { background: #0a0a0a !important; }

# /* Spinner */
# .stSpinner > div { border-top-color: #0a0a0a !important; }

# /* Captions / info */
# .stCaption { font-family: 'League Spartan', sans-serif !important; color: #777 !important; font-size: 0.75rem !important; }
# .stAlert { border-radius: 4px !important; font-family: 'League Spartan', sans-serif !important; }

# /* Layout */
# .main-area { padding: 20px 28px 40px; }
# .empty-state { text-align: center; padding: 80px 0; }
# .empty-state .icon { font-size: 2rem; font-weight: 900; color: #ccc; margin-bottom: 16px; font-family: 'League Spartan', sans-serif; }
# .empty-state h3 { font-family: 'League Spartan', sans-serif; font-size: 1.1rem; font-weight: 800; color: #0a0a0a; margin-bottom: 8px; }
# .empty-state p { font-family: 'League Spartan', sans-serif; font-size: 0.82rem; color: #777; line-height: 1.7; }
# .empty-tip { font-family: 'League Spartan', sans-serif; font-size: 0.72rem; color: #aaa; margin-top: 4px; }
# .metric-row { display: flex; gap: 14px; margin: 16px 0; }
# .metric-box { flex: 1; background: #f5f5f5; border: 1px solid #e0e0e0; border-radius: 6px; padding: 16px; text-align: center; }
# .metric-box .num { font-family: 'League Spartan', sans-serif; font-size: 1.6rem; font-weight: 900; color: #0a0a0a; }
# .metric-box .lbl { font-family: 'League Spartan', sans-serif; font-size: 0.65rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #777; margin-top: 4px; }
# .results-header { font-family: 'League Spartan', sans-serif; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: #777; margin: 20px 0 10px; }

# /* Soft panel log */
# .soft-panel { background: #f5f5f5; border: 1px solid #e0e0e0; border-radius: 6px; padding: 12px 14px; font-family: 'League Spartan', sans-serif; font-size: 0.72rem; color: #444; line-height: 1.7; }
# </style>
# """,
#     unsafe_allow_html=True,
# )

# counts = backend_key_counts()
# yt_total = len(env_keys("YOUTUBE_API_KEYS") or env_keys("YOUTUBE_API_KEY") or [])
# gem_total = len(env_keys("GEMINI_API_KEYS") or env_keys("GEMINI_API_KEY") or [])
# quota_html = "".join(
#     f'<div class="quota-item"><span class="quota-label">S{i + 1}</span>'
#     f'<div class="quota-bar"><div class="quota-bar-fill" style="width:0%"></div></div>'
#     f'<span class="quota-pct">—</span></div>'
#     for i in range(min(yt_total, 4))
# ) or '<span class="quota-pct" style="color:#aaa">No YT keys</span>'
# gem_html = "".join(
#     f'<div class="quota-item"><span class="quota-label">G{i + 1}</span>'
#     f'<div class="quota-bar"><div class="quota-bar-fill" style="width:0%"></div></div>'
#     f'<span class="quota-pct">—</span></div>'
#     for i in range(min(gem_total, 3))
# )
# st.markdown(
#     f"""
# <div id="ciq-topbar">
#   <div class="logo-wrap">
#     <span class="logo-bar"><span class="logo-bar-bg">BAR</span>CODE</span>
#     <span class="logo-divider">|</span>
#     <span class="logo-ykone">Ykone</span>
#   </div>
#   <div class="quota-wrap">
#     <span class="quota-label">API Quota</span>
#     {quota_html}{gem_html}
#   </div>
#   <div class="topbar-right">
#     <a href="?reset=1" class="reset-link">&#8635; Reset</a>
#   </div>
# </div>
# """,
#     unsafe_allow_html=True,
# )

# filter_version = int(st.session_state.get("ai_filter_version", 0))

# with st.sidebar:
#     st.markdown('<div class="sidebar-inner">', unsafe_allow_html=True)
#     st.markdown('<div class="ai-panel">', unsafe_allow_html=True)
#     st.markdown('<div class="ai-panel-title">AI Assist</div>', unsafe_allow_html=True)

#     brief = st.text_area(
#         "",
#         placeholder="Describe your campaign, creator type, location, gender, and follower range...",
#         height=90,
#         key="brief_input",
#         label_visibility="collapsed",
#     )

#     with st.expander("Advanced API key override", expanded=False):
#         override_gemini = st.text_area("Gemini keys", height=60, key="ovr_gem")
#         override_apify_discovery = st.text_area("Apify discovery keys", height=60, key="ovr_apd")
#         override_apify_profile = st.text_area("Apify profile keys", height=60, key="ovr_app")
#         override_youtube = st.text_area("YouTube keys", height=60, key="ovr_yt")
#         override_scrapingbee = st.text_area("ScrapingBee keys", height=60, key="ovr_sb")

#     keys = get_key_config({
#         "gemini": st.session_state.get("ovr_gem", ""),
#         "apify_discovery": st.session_state.get("ovr_apd", ""),
#         "apify_profile": st.session_state.get("ovr_app", ""),
#         "youtube": st.session_state.get("ovr_yt", ""),
#         "scrapingbee": st.session_state.get("ovr_sb", ""),
#     })

#     analyze_ready = bool(brief and keys["gemini"])
#     get_kw_btn = st.button("Get Keywords", disabled=not analyze_ready, use_container_width=True)

#     if st.session_state.analysis_result:
#         result = st.session_state.analysis_result
#         intent = result.get("intent", {})
#         conf = str(intent.get("confidence", "medium")).upper()
#         badge_cls = {"HIGH": "conf-high", "MEDIUM": "conf-mid", "LOW": "conf-low"}.get(conf, "conf-mid")
#         gender_label = "Male" if intent.get("gender") == "M" else "Female" if intent.get("gender") == "F" else "Any"
#         niche_label = str(intent.get("niche") or "creator")
#         ai_min = fmt_num(intent.get("min_followers", 10000))
#         ai_max = fmt_num(intent.get("max_followers", 500000))
#         st.markdown(
#             f"""
# <div class="ai-confidence">
#   <span class="{badge_cls}">Confidence: {html.escape(conf)}</span>
#   <span style="color:#777;font-size:.78rem">{html.escape(niche_label)} / {html.escape(gender_label)}</span>
# </div>
# <div class="ai-suggest-row">AI suggests: <strong>{ai_min} - {ai_max}</strong> followers</div>
# """,
#             unsafe_allow_html=True,
#         )
#         yt_queries = result.get("yt_queries", [])
#         if yt_queries:
#             st.markdown('<div class="kw-section-label">YouTube Keywords</div>', unsafe_allow_html=True)
#             st.markdown(
#                 "".join(
#                     f'<span class="kw-chip">{html.escape(str(q)[:40])} <span class="plus">+</span></span>'
#                     for q in yt_queries[:8]
#                 ),
#                 unsafe_allow_html=True,
#             )
#         hashtags = result.get("hashtags_final", [])
#         if hashtags:
#             st.markdown('<div class="kw-section-label">Instagram Hashtags</div>', unsafe_allow_html=True)
#             st.markdown(
#                 "".join(
#                     f'<span class="kw-chip">{html.escape(str(tag))} <span class="plus">+</span></span>'
#                     for tag in hashtags[:12]
#                 ),
#                 unsafe_allow_html=True,
#             )
#         cross = result.get("ig_keywords", [])
#         if cross:
#             st.markdown('<div class="kw-section-label">Cross-Platform</div>', unsafe_allow_html=True)
#             st.markdown(
#                 "".join(
#                     f'<span class="kw-chip">{html.escape(str(k))} <span class="plus">+</span></span>'
#                     for k in cross[:4]
#                 ),
#                 unsafe_allow_html=True,
#             )

#     st.markdown('</div>', unsafe_allow_html=True)

#     st.markdown('<div class="sec-label">Campaign Name <span style="color:#777;font-weight:400;text-transform:none">(track used creators)</span></div>', unsafe_allow_html=True)
#     campaign_name = st.text_input("", placeholder="e.g. Meesho May 2026", key="campaign_name", label_visibility="collapsed")

#     c1, c2 = st.columns([1, 1])
#     with c1:
#         block_repeats = st.toggle("Block repeats", value=True, key="block_repeats")
#         allow_repeats = not block_repeats
#     with c2:
#         if st.button("History", key="hist_btn"):
#             st.session_state["show_history"] = not st.session_state.get("show_history", False)
#     if st.session_state.get("show_history"):
#         stats = history_stats(campaign_scope(campaign_name, st.session_state.last_brief))
#         st.caption(f"Used in this campaign: {stats.get('used', 0)}")
#         if stats.get("used", 0) and st.button("Clear used history", key="clear_hist_btn"):
#             cleared = clear_used_creators(campaign_scope(campaign_name, st.session_state.last_brief))
#             st.session_state.history_notice = f"Cleared {cleared} used creators for this campaign."
#             st.rerun()

#     st.markdown('<div class="sec-label">Keywords / Hashtags <span style="color:#777;font-weight:400;text-transform:none">(comma-separated)</span></div>', unsafe_allow_html=True)
#     known_search_terms = st.text_input("", placeholder="Type keyword / #hashtag...", key="known_kw", label_visibility="collapsed")
#     if known_search_terms:
#         chips_added = "".join(
#             f'<span class="kw-chip">{html.escape(t.strip())}</span>'
#             for t in re.split(r"[,;]+", known_search_terms)
#             if t.strip()
#         )
#         st.markdown(chips_added, unsafe_allow_html=True)
#     st.button("Quick Suggest", key="quick_suggest", use_container_width=False)

#     st.markdown('<div class="sec-label">Location</div>', unsafe_allow_html=True)
#     loc1, loc2, loc3 = st.columns([1.2, 1, 1])
#     with loc1:
#         region = st.selectbox("Country", ["IN India", "US", "GB", "AU", "CA", "SG", "AE"], index=0, key="region_sel")
#         region_code = region.split()[0]
#     with loc2:
#         state_input = st.text_input("State (opt)", placeholder="State", key="state_input")
#     with loc3:
#         city_input = st.text_input("City (opt)", placeholder="City", key="city_input")

#     st.markdown('<div class="sec-label">Audience Size</div>', unsafe_allow_html=True)
#     sz1, sz2, sz3 = st.columns(3)
#     with sz1:
#         min_followers = st.number_input(
#             "Min Subs",
#             value=int(st.session_state.get("ai_suggested_min", 10000)),
#             step=1000,
#             format="%d",
#             key=f"min_subs_{filter_version}",
#         )
#     with sz2:
#         max_followers = st.number_input(
#             "Max Subs",
#             value=int(st.session_state.get("ai_suggested_max", 500000)),
#             step=5000,
#             format="%d",
#             key=f"max_subs_{filter_version}",
#         )
#     with sz3:
#         results_per_yt_query = st.number_input("Fetch", value=50, step=10, min_value=10, max_value=50, key="fetch_count")

#     st.markdown('<div class="sec-label">Targeting</div>', unsafe_allow_html=True)
#     t1, t2 = st.columns([1.05, 1])
#     with t1:
#         _gender_options = ["Auto", "Any", "Male only", "Female only"]
#         _ai_gender = st.session_state.get("ai_suggested_gender", "Auto")
#         _gender_idx = _gender_options.index(_ai_gender) if _ai_gender in _gender_options else 0
#         gender_override = st.selectbox("Gender", _gender_options, index=_gender_idx, key=f"gender_sel_{filter_version}")
#         gender_map = {"Auto": None, "Any": "ANY", "Male only": "M", "Female only": "F"}
#     with t2:
#         _ai_tier = st.session_state.get("ai_suggested_tier", "Auto")
#         _tier_idx = CREATOR_TIER_OPTIONS.index(_ai_tier) if _ai_tier in CREATOR_TIER_OPTIONS else 0
#         creator_tier_override = st.selectbox("Creator tier", CREATOR_TIER_OPTIONS, index=_tier_idx, key=f"tier_sel_{filter_version}")
#     strict_mode = st.toggle("Relaxed matching", value=True, key="strictness_toggle")

#     with st.expander("More options", expanded=False):
#         exclude_terms_raw = st.text_area("Exclude brands/channels", height=60, placeholder="Garnier, Just For Men...", key="exclude_terms")
#         allow_international = st.checkbox("Allow international creators", value=False, key="allow_intl")
#         posts_per_tag = st.slider("IG rows per hashtag", 10, 30, 30, step=5, key="posts_per_tag")
#         deep_yt_search = st.checkbox("YouTube deep search (page 2)", value=True, key="deep_yt")
#         verify_hashtags = st.checkbox("Verify hashtag counts", value=True, key="verify_htag")

#     search_ready = bool(brief and st.session_state.analysis_result)
#     search_btn = st.button("Search", use_container_width=True, disabled=not search_ready, key="main_search_btn")
#     st.markdown('</div>', unsafe_allow_html=True)

# yt_tab, ig_tab = st.tabs(["YouTube", "Instagram"])
# do_ig = True
# do_yt = True

# if st.session_state.history_notice:
#     st.success(st.session_state.history_notice)
#     st.session_state.history_notice = ""

# if brief and not keys["gemini"]:
#     st.warning("No Gemini keys configured. Set GEMINI_API_KEYS or use the advanced override.")

# if get_kw_btn and brief:
#     with st.spinner("Analyzing brief..."):
#         ai = AIService(keys["gemini"], keys["apify_discovery"])
#         result = ai.run_full_analysis(
#             brief,
#             verify_hashtags=st.session_state.get("verify_htag", True),
#             user_search_terms=st.session_state.get("known_kw", ""),
#             exclude_terms=st.session_state.get("exclude_terms", ""),
#             progress_callback=lambda _message: None,
#             platforms=["YouTube", "Instagram"],
#         )
#         intent = result.get("intent", {})
#         if intent:
#             st.session_state["ai_suggested_min"] = int(intent.get("min_followers") or 10000)
#             st.session_state["ai_suggested_max"] = int(intent.get("max_followers") or 500000)
#             _gmap = {"M": "Male only", "F": "Female only", "ANY": "Any"}
#             st.session_state["ai_suggested_gender"] = _gmap.get(str(intent.get("gender") or "ANY").upper(), "Auto")
#             st.session_state["ai_suggested_locations"] = intent.get("locations_list", []) or []
#             _tier_map = {"nano": "Nano", "micro": "Micro", "mid": "Mid", "mid-tier": "Mid", "macro": "Macro", "any": "Any"}
#             _ai_min = int(intent.get("min_followers") or 10000)
#             _ai_max = int(intent.get("max_followers") or 500000)
#             _exact_tier = next((label for label, bounds in CREATOR_TIER_RANGES.items() if bounds == (_ai_min, _ai_max)), None)
#             if _exact_tier:
#                 st.session_state["ai_suggested_tier"] = _exact_tier
#             elif re.search(r"\b\d+\s*[kKmM]?\s*(?:to|-)\s*\d+\s*[kKmM]?\b", brief or ""):
#                 st.session_state["ai_suggested_tier"] = "Custom range"
#             else:
#                 st.session_state["ai_suggested_tier"] = _tier_map.get(
#                     str(intent.get("creator_tier") or "any").lower().split()[0],
#                     "Auto",
#                 )
#             st.session_state["ai_filter_version"] = int(st.session_state.get("ai_filter_version", 0)) + 1
#         st.session_state.analysis_result = result
#         st.session_state["review_queries"] = [item.get("query", "") for item in result.get("yt_search_plan", []) if item.get("query")]
#         st.session_state["review_hashtags"] = result.get("hashtags_final", [])
#         st.session_state["review_brand_tags"] = result.get("brand_campaign_tags", [])
#         st.session_state["review_trending_tags"] = result.get("trending_creator_tags", [])
#         st.session_state["selected_queries_widget"] = list(st.session_state["review_queries"])
#         tag_labels = (
#             [f"{tag} [AI]" for tag in st.session_state["review_hashtags"]] +
#             [f"{tag} [Brand]" for tag in st.session_state["review_brand_tags"]] +
#             [f"{tag} [Trending]" for tag in st.session_state["review_trending_tags"]]
#         )
#         st.session_state["selected_hashtags_widget"] = tag_labels
#         st.session_state["show_review_panel"] = True
#         st.session_state.last_brief = brief
#         st.session_state.last_platforms = ["YouTube", "Instagram"]
#         st.session_state.search_complete = False
#     st.rerun()

# if st.session_state.get("show_review_panel"):
#     with yt_tab:
#         st.markdown('<div class="main-area">', unsafe_allow_html=True)
#         st.markdown('<div class="results-header">Review & Edit Search Plan</div>', unsafe_allow_html=True)
#         st.caption("Deselect anything you do not want to search. Add extra keywords or reference creators before pressing Search.")

#         current_queries = st.session_state.get("review_queries", [])
#         if current_queries:
#             st.multiselect(
#                 "AI YouTube queries",
#                 options=current_queries,
#                 default=st.session_state.get("selected_queries_widget", current_queries),
#                 key="selected_queries_widget",
#             )
#         else:
#             st.caption("No AI YouTube queries yet.")

#         tag_options = (
#             [(tag, "AI") for tag in st.session_state.get("review_hashtags", [])] +
#             [(tag, "Brand") for tag in st.session_state.get("review_brand_tags", [])] +
#             [(tag, "Trending") for tag in st.session_state.get("review_trending_tags", [])]
#         )
#         tag_labels = [f"{tag} [{source}]" for tag, source in tag_options]
#         if tag_labels:
#             st.multiselect(
#                 "Instagram hashtags",
#                 options=tag_labels,
#                 default=st.session_state.get("selected_hashtags_widget", tag_labels),
#                 key="selected_hashtags_widget",
#             )
#         else:
#             st.caption("No Instagram hashtags yet.")

#         st.text_area(
#             "Extra keywords or hashtags",
#             key="user_extra_keywords",
#             height=70,
#             placeholder="#myhashtag, men hair color review, grooming creator delhi",
#         )
#         st.text_area(
#             "Reference creators for similar search",
#             key="reference_creators",
#             height=60,
#             placeholder="https://youtube.com/@SomeCreator\n@AnotherCreator",
#         )
#         ai_locs = st.session_state.get("ai_suggested_locations", [])
#         if ai_locs:
#             st.info(f"AI detected locations: {', '.join(str(loc) for loc in ai_locs)}")
#         if st.button("Clear Review Panel", use_container_width=True):
#             st.session_state["show_review_panel"] = False
#             st.session_state["review_queries"] = []
#             st.session_state["review_hashtags"] = []
#             st.session_state["review_brand_tags"] = []
#             st.session_state["review_trending_tags"] = []
#             st.rerun()
#         st.markdown('</div>', unsafe_allow_html=True)

# if search_btn and st.session_state.analysis_result:
#     result = st.session_state.analysis_result
#     intent = dict(result.get("intent", {}))
#     effective_gender = gender_map.get(gender_override) or intent.get("gender", "ANY")
#     if effective_gender is None:
#         effective_gender = intent.get("gender", "ANY")
#     if creator_tier_override in CREATOR_TIER_RANGES:
#         effective_min, effective_max = CREATOR_TIER_RANGES[creator_tier_override]
#     else:
#         effective_min = int(min_followers)
#         effective_max = int(max_followers)

#     history_campaign = campaign_scope(campaign_name, brief)
#     _locs_list = intent.get("locations_list") or []
#     if _locs_list:
#         location_hints = [str(loc).lower().strip() for loc in _locs_list if loc]
#         if intent.get("language") and str(intent["language"]).lower() not in location_hints:
#             location_hints.append(str(intent["language"]).lower())
#     else:
#         location_hints = [str(intent.get(k)) for k in ("city", "state", "language") if intent.get(k)]
#     for manual_location in (state_input, city_input):
#         clean_location = str(manual_location or "").strip().lower()
#         if clean_location and clean_location not in location_hints:
#             location_hints.append(clean_location)

#     lang_code_map = {
#         "kannada": "kn", "tamil": "ta", "telugu": "te", "malayalam": "ml",
#         "marathi": "mr", "punjabi": "pa", "gujarati": "gu", "bengali": "bn",
#         "hindi": "hi", "assamese": "as",
#     }
#     lang_code = lang_code_map.get(str(intent.get("language") or "").lower())

#     logs: list[str] = []
#     with yt_tab:
#         log_box_yt = st.empty()
#         progress_yt = st.progress(0)
#     with ig_tab:
#         log_box_ig = st.empty()

#     def add_log(message: str) -> None:
#         safe = html.escape(str(message))
#         logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {safe}")
#         log_box_yt.markdown(
#             '<div class="soft-panel" style="max-height:200px;overflow:auto">'
#             + "<br>".join(logs[-18:]) + "</div>",
#             unsafe_allow_html=True,
#         )

#     ig_results: list[dict] = []
#     yt_results: list[dict] = []
#     ai_svc = AIService(keys["gemini"], keys["apify_discovery"]) if keys["gemini"] else None

#     base_plan = result.get("yt_search_plan") or yt_plan_from_queries(result.get("yt_queries", []), source="legacy")
#     selected_queries = st.session_state.get("selected_queries_widget") or [item.get("query", "") for item in base_plan]
#     selected_query_set = {str(query).strip().lower() for query in selected_queries if str(query).strip()}
#     yt_plan = [item for item in base_plan if str(item.get("query", "")).strip().lower() in selected_query_set]

#     user_extra_terms = normalize_user_search_terms(st.session_state.get("user_extra_keywords", ""))
#     for term in user_extra_terms:
#         if term.startswith("#"):
#             query = term
#         else:
#             query = term
#         if query and query.lower() not in selected_query_set:
#             yt_plan.append({
#                 "query": query,
#                 "search_type": "video",
#                 "source": "user_extra",
#                 "intent_terms": [str(intent.get("niche", "")), query],
#                 "negative_terms": [],
#                 "paginate": True,
#             })
#             selected_query_set.add(query.lower())

#     selected_tag_labels = st.session_state.get("selected_hashtags_widget", [])
#     selected_tags = [str(label).split(" [", 1)[0] for label in selected_tag_labels if str(label).strip()]
#     selected_tags = list(dict.fromkeys(selected_tags))
#     for tag in selected_tags:
#         clean_tag = "#" + re.sub(r"[^a-zA-Z0-9]", "", str(tag).lstrip("#")).lower()
#         if len(clean_tag) > 2 and clean_tag.lower() not in selected_query_set:
#             yt_plan.append({
#                 "query": clean_tag,
#                 "search_type": "video",
#                 "source": "review_hashtag",
#                 "intent_terms": [clean_tag.lstrip("#"), str(intent.get("niche", ""))],
#                 "negative_terms": [],
#                 "paginate": False,
#             })
#             selected_query_set.add(clean_tag.lower())

#     ref_creator_text = st.session_state.get("reference_creators", "")
#     ref_creators = [line.strip() for line in re.split(r"[\n,;]+", ref_creator_text) if line.strip()]
#     if ref_creators and ai_svc:
#         add_log(f"Generating similar-creator queries for {len(ref_creators)} reference creator(s)...")
#         similar_plan = ai_svc.generate_similar_creator_queries(ref_creators, intent, brief)
#         if similar_plan:
#             yt_plan.extend(similar_plan)
#             add_log(f"Added {len(similar_plan)} similar-creator queries")

#     raw_extra_tokens = [
#         token.strip()
#         for token in re.split(r"[\n,;]+", st.session_state.get("user_extra_keywords", ""))
#         if token.strip()
#     ]
#     extra_hashtags = [
#         "#" + re.sub(r"[^a-zA-Z0-9]", "", token.lstrip("#")).lower()
#         for token in raw_extra_tokens
#         if token.startswith("#") and len(token.strip("#")) > 1
#     ]
#     ig_hashtags_to_search = list(dict.fromkeys((selected_tags or result.get("hashtags_final", [])) + extra_hashtags))

#     if yt_plan and (keys["youtube"] or keys["scrapingbee"]):
#         progress_yt.progress(10)
#         add_log(f"YouTube: running {len(yt_plan)} queries...")
#         try:
#             async def _run_all_yt() -> tuple[list[dict], list[dict]]:
#                 yt_task = None
#                 if keys["youtube"]:
#                     yt_task = run_yt_search(
#                         api_keys=keys["youtube"],
#                         queries=[],
#                         min_subs=effective_min,
#                         max_subs=effective_max,
#                         gender_filter=effective_gender,
#                         location_hints=location_hints,
#                         lang_hints=[intent.get("language", "")] if intent.get("language") else [],
#                         lang_code=lang_code,
#                         region=region_code,
#                         results_per_query=int(results_per_yt_query),
#                         progress_callback=add_log,
#                         search_plan=yt_plan,
#                         exclude_terms=result.get("exclude_terms") or normalize_user_search_terms(st.session_state.get("exclude_terms", "")),
#                         allow_international=st.session_state.get("allow_intl", False),
#                         deep_search=st.session_state.get("deep_yt", True),
#                     )
#                 sb_task = None
#                 if keys["scrapingbee"]:
#                     sb_task = run_scrapingbee_search(
#                         api_keys=keys["scrapingbee"],
#                         search_plan=yt_plan,
#                         min_subs=effective_min,
#                         max_subs=effective_max,
#                         progress_callback=add_log,
#                     )
#                 if yt_task and sb_task:
#                     yt_api_results, sb_results = await asyncio.gather(yt_task, sb_task)
#                     return yt_api_results, sb_results
#                 if yt_task:
#                     return await yt_task, []
#                 if sb_task:
#                     return [], await sb_task
#                 return [], []

#             yt_api_results, sb_results = run_async(_run_all_yt())
#             seen_cids = {
#                 row.get("channel_id", "")
#                 for row in yt_api_results
#                 if row.get("channel_id") and not str(row.get("channel_id", "")).startswith("sb_")
#             }
#             seen_names = {
#                 str(row.get("channel_name", "")).lower()
#                 for row in yt_api_results
#                 if row.get("channel_name")
#             }
#             sb_unique: list[dict] = []
#             for row in sb_results:
#                 cid = str(row.get("channel_id", ""))
#                 cname = str(row.get("channel_name", "")).lower()
#                 if cid and cid in seen_cids:
#                     continue
#                 if cname and cname in seen_names:
#                     continue
#                 seen_cids.add(cid)
#                 seen_names.add(cname)
#                 sb_unique.append(row)
#             yt_results = yt_api_results + sb_unique
#             if sb_unique:
#                 add_log(f"Merged: {len(yt_api_results)} YT API + {len(sb_unique)} unique ScrapingBee = {len(yt_results)} total")
#             yt_results, skipped = filter_used_creators(yt_results, history_campaign, allow_repeats)
#             if skipped:
#                 add_log(f"Skipped {len(skipped)} previously used creators")
#             progress_yt.progress(75)
#             if yt_results and ai_svc:
#                 add_log(f"Gemini: ranking {len(yt_results)} YouTube candidates...")
#                 scoring_intent = dict(intent)
#                 scoring_intent["_brief"] = brief
#                 yt_results = ai_svc.score_youtube_creators_batch(yt_results, scoring_intent)
#             progress_yt.progress(100)
#             add_log(
#                 f"Done: {sum(1 for c in yt_results if c.get('match_status') == 'high')} high, "
#                 f"{sum(1 for c in yt_results if c.get('match_status') in ('review', 'mid'))} mid, "
#                 f"{sum(1 for c in yt_results if c.get('match_status') in ('rejected', 'low'))} low"
#             )
#         except Exception as exc:
#             add_log(f"YouTube error: {exc}")
#     elif yt_plan:
#         with yt_tab:
#             st.warning("YouTube skipped: missing YOUTUBE_API_KEYS and SCRAPINGBEE_KEYS")

#     if ig_hashtags_to_search and keys["apify_discovery"] and keys["apify_profile"]:
#         try:
#             ig_results = run_async(run_ig_search(
#                 api_key=keys["apify_discovery"],
#                 profile_api_keys=keys["apify_profile"],
#                 hashtags=ig_hashtags_to_search,
#                 min_followers=effective_min,
#                 max_followers=effective_max,
#                 location_hints=location_hints,
#                 posts_per_tag=st.session_state.get("posts_per_tag", 30),
#                 gender_filter=effective_gender,
#                 niche=intent.get("niche", ""),
#                 progress_callback=lambda _message: None,
#                 debug_state={},
#             ))
#             ig_results, _ = filter_used_creators(ig_results, history_campaign, allow_repeats)
#             if ig_results and ai_svc:
#                 scoring_intent = dict(intent)
#                 scoring_intent["_brief"] = brief
#                 ig_results = ai_svc.score_creators_batch(ig_results, scoring_intent)
#         except Exception as exc:
#             with ig_tab:
#                 log_box_ig.error(f"Instagram error: {exc}")

#     st.session_state.ig_results = ig_results
#     st.session_state.yt_results = yt_results
#     st.session_state.analysis_result = result
#     st.session_state.search_complete = True
#     st.rerun()

# ig_results = st.session_state.ig_results
# yt_results = st.session_state.yt_results
# display_campaign = campaign_scope(campaign_name, brief or st.session_state.last_brief)
# yt_display = annotate_used_creators(yt_results, display_campaign)
# ig_display = annotate_used_creators(ig_results, display_campaign)
# if not allow_repeats:
#     yt_display = [c for c in yt_display if not c.get("_history_used")]
#     ig_display = [c for c in ig_display if not c.get("_history_used")]

# def sort_key(c):
#     score = c.get("ai_score")
#     try:
#         return float(score) if score is not None else 0
#     except Exception:
#         return 0

# def _render_results_panel(items: list[dict], label: str) -> None:
#     if not items and not st.session_state.search_complete:
#         st.markdown(
#             f"""
# <div class="empty-state">
#   <div class="icon">IF</div>
#   <h3>Find Real {html.escape(label)} Creators</h3>
#   <p>Name your campaign, add keywords, and search.<br>Mark used creators to avoid repeats.</p>
#   <div class="empty-tip">Multiple hashtags = combined search</div>
#   <div class="empty-tip">Mark Used = never repeat in the same campaign</div>
#   <div class="empty-tip">Download Excel for records</div>
# </div>
# """,
#             unsafe_allow_html=True,
#         )
#         return

#     sorted_items = sorted(items, key=sort_key, reverse=True)
#     total = len(sorted_items)
#     with_email = sum(1 for c in sorted_items if c.get("email"))
#     avg_score = sum(sort_key(c) for c in sorted_items) / total if total else 0
#     st.markdown(
#         f"""
# <div class="metric-row">
#   <div class="metric-box"><div class="num">{total}</div><div class="lbl">Creators Found</div></div>
#   <div class="metric-box"><div class="num">{with_email}</div><div class="lbl">With Email</div></div>
#   <div class="metric-box"><div class="num">{avg_score:.1f}</div><div class="lbl">Avg AI Score</div></div>
# </div>
# """,
#         unsafe_allow_html=True,
#     )
#     df = creators_to_df(sorted_items)
#     if not df.empty:
#         st.download_button(
#             "Download Excel",
#             data=df_to_excel(df),
#             file_name=f"creators_{label.lower()}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
#             mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#             key=f"dl_{label}",
#         )
#     st.markdown(f'<div class="results-header">{html.escape(label)} Creators - sorted by AI Score</div>', unsafe_allow_html=True)
#     render_creator_table(sorted_items, height=680)

# with yt_tab:
#     st.markdown('<div class="main-area">', unsafe_allow_html=True)
#     _render_results_panel(yt_display, "YouTube")
#     st.markdown('</div>', unsafe_allow_html=True)

# with ig_tab:
#     st.markdown('<div class="main-area">', unsafe_allow_html=True)
#     _render_results_panel(ig_display, "Instagram")
#     st.markdown('</div>', unsafe_allow_html=True)

# st.stop()

# with st.sidebar:
#     st.markdown("## Influencer Finder Pro")
#     counts = backend_key_counts()
#     st.markdown("### Backend Keys")
#     st.caption(
#         f"Gemini: {counts['gemini']} | Apify discovery: {counts['apify_discovery']} | "
#         f"Apify profile: {counts['apify_profile']} | YouTube: {counts['youtube']}"
#     )

#     with st.expander("Advanced API key override"):
#         override_gemini = st.text_area("Gemini keys", height=70)
#         override_apify_discovery = st.text_area("Apify discovery keys", height=70)
#         override_apify_profile = st.text_area("Apify profile keys", height=70)
#         override_youtube = st.text_area("YouTube keys", height=70)

#     keys = get_key_config({
#         "gemini": override_gemini,
#         "apify_discovery": override_apify_discovery,
#         "apify_profile": override_apify_profile,
#         "youtube": override_youtube,
#     })

#     st.markdown("### Search Filters")
#     platform_choice = st.multiselect("Platforms", ["Instagram", "YouTube"], default=["Instagram", "YouTube"])
#     col_a, col_b = st.columns(2)
#     with col_a:
#         min_followers = st.number_input(
#             "Min followers/subscribers",
#             value=int(st.session_state.get("ai_suggested_min", 10000)),
#             step=1000,
#             format="%d",
#         )
#     with col_b:
#         max_followers = st.number_input(
#             "Max followers/subscribers",
#             value=int(st.session_state.get("ai_suggested_max", 500000)),
#             step=5000,
#             format="%d",
#         )

#     _gender_options = ["Auto", "Any", "Male only", "Female only"]
#     _ai_gender = st.session_state.get("ai_suggested_gender", "Auto")
#     _gender_idx = _gender_options.index(_ai_gender) if _ai_gender in _gender_options else 0
#     gender_override = st.selectbox("Gender override", _gender_options, index=_gender_idx)
#     gender_map = {"Auto": None, "Any": "ANY", "Male only": "M", "Female only": "F"}
#     _ai_tier = st.session_state.get("ai_suggested_tier", "Auto")
#     _tier_idx = CREATOR_TIER_OPTIONS.index(_ai_tier) if _ai_tier in CREATOR_TIER_OPTIONS else 0
#     creator_tier_override = st.selectbox(
#         "Creator tier",
#         CREATOR_TIER_OPTIONS,
#         index=_tier_idx,
#         key=f"creator_tier_override_{st.session_state.get('ai_filter_version', 0)}",
#     )
#     region = st.selectbox("YouTube region", ["IN", "US", "GB", "AU", "CA", "SG", "AE"], index=0)

#     st.markdown("### Creator History")
#     campaign_name = st.text_input(
#         "Campaign name",
#         placeholder="Optional, used for repeat blocking",
#         help="Creators marked as used are blocked only inside this campaign scope. If blank, the brief text is used.",
#     )
#     allow_repeats = st.checkbox(
#         "Allow repeated creators",
#         value=False,
#         help="When off, creators marked as used in this campaign are skipped from new results.",
#     )
#     current_history_scope = campaign_scope(campaign_name, st.session_state.last_brief)
#     stats = history_stats(current_history_scope)
#     st.caption(f"Used in this campaign: {stats.get('used', 0)}")
#     if stats.get("used", 0):
#         if st.button("Clear used history for campaign"):
#             cleared = clear_used_creators(current_history_scope)
#             st.session_state.history_notice = f"Cleared {cleared} used creators for this campaign."
#             st.rerun()

#     st.markdown("### Advanced")
#     known_search_terms = st.text_area(
#         "Known hashtags / search phrases",
#         height=80,
#         placeholder="#haircolor, #mensgrooming, Mumbai male grooming",
#     )
#     exclude_terms_raw = st.text_area(
#         "Exclude brands/channels",
#         height=70,
#         placeholder="Garnier Men India, Just For Men, SIMPLER Hair Color",
#     )
#     allow_international = st.checkbox("Allow international creators", value=False,
#                                        help="When on, channels from non-IN countries are kept as Mid instead of filtered out")
#     posts_per_tag = st.slider("Instagram rows per hashtag", 10, 30, 30, step=5)
#     results_per_yt_query = st.slider("YouTube results per query", 10, 50, 50, step=10)
#     deep_yt_search = st.checkbox("YouTube deep search (page 2)", value=True,
#                                   help="Fetches a second page of results for video queries; doubles candidates, uses ~2x quota")
#     verify_hashtags = st.checkbox("Verify hashtag counts with Apify analytics", value=True)


# st.title("Influencer Finder Pro")
# st.caption("Platform-aware creator discovery: Instagram hashtag search + YouTube deep search. Keys from .env.")

# brief = st.text_area(
#     "Campaign brief",
#     placeholder='Example: "Find male skincare creators in India, 5K-50K followers, Hindi or English content"',
#     height=110,
# )

# do_ig = "Instagram" in platform_choice
# do_yt = "YouTube" in platform_choice

# # Determine if analysis result is still valid for current platform selection
# analysis = st.session_state.analysis_result
# hashtags_ready = bool(analysis and analysis.get("hashtags_final"))
# yt_plan_ready = bool(analysis and (analysis.get("yt_search_plan") or analysis.get("yt_queries")))

# ig_search_ready = do_ig and bool(keys["apify_discovery"]) and bool(keys["apify_profile"]) and hashtags_ready
# yt_search_ready = do_yt and bool(keys["youtube"]) and yt_plan_ready

# analyze_ready = bool(brief and keys["gemini"])
# search_ready = bool(brief and analysis and (ig_search_ready or yt_search_ready))

# col_analyze, col_search, col_clear = st.columns([1, 1, 4])
# with col_analyze:
#     analyze_btn = st.button("Analyze Brief", disabled=not analyze_ready)
# with col_search:
#     search_btn = st.button("Start Search", disabled=not search_ready)
# with col_clear:
#     if st.button("Clear Results"):
#         st.session_state.analysis_result = None
#         st.session_state.ig_results = []
#         st.session_state.yt_results = []
#         st.session_state.ig_debug = {}
#         st.session_state.search_complete = False
#         st.rerun()

# if brief and not keys["gemini"]:
#     st.warning("No Gemini keys configured. Set GEMINI_API_KEYS or use the advanced override.")

# if not platform_choice:
#     st.warning("Select at least one platform (Instagram or YouTube) in the sidebar.")

# if st.session_state.history_notice:
#     st.success(st.session_state.history_notice)
#     st.session_state.history_notice = ""

# if analyze_btn:
#     analysis_logs: list[str] = []
#     analysis_box = st.empty()

#     def add_analysis_log(message: str) -> None:
#         safe = html.escape(str(message))
#         analysis_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {safe}")
#         analysis_box.markdown('<div class="soft-panel muted">' + "<br>".join(analysis_logs[-18:]) + "</div>", unsafe_allow_html=True)

#     with st.spinner("Analyzing brief and planning creator search packs..."):
#         ai = AIService(keys["gemini"], keys["apify_discovery"])
#         result = ai.run_full_analysis(
#             brief,
#             verify_hashtags=verify_hashtags,
#             user_search_terms=known_search_terms,
#             exclude_terms=exclude_terms_raw,
#             progress_callback=add_analysis_log,
#             platforms=platform_choice,
#         )
#         intent = result.get("intent", {})
#         if intent:
#             st.session_state["ai_suggested_min"] = int(intent.get("min_followers") or 10000)
#             st.session_state["ai_suggested_max"] = int(intent.get("max_followers") or 500000)
#             _gmap = {"M": "Male only", "F": "Female only", "ANY": "Any"}
#             st.session_state["ai_suggested_gender"] = _gmap.get(
#                 str(intent.get("gender") or "ANY").upper(),
#                 "Auto",
#             )
#             _tier_map = {
#                 "nano": "Nano",
#                 "micro": "Micro",
#                 "mid": "Mid",
#                 "mid-tier": "Mid",
#                 "macro": "Macro",
#                 "any": "Any",
#             }
#             _ai_min = int(intent.get("min_followers") or 10000)
#             _ai_max = int(intent.get("max_followers") or 500000)
#             _exact_tier = next(
#                 (label for label, bounds in CREATOR_TIER_RANGES.items() if bounds == (_ai_min, _ai_max)),
#                 None,
#             )
#             if _exact_tier:
#                 st.session_state["ai_suggested_tier"] = _exact_tier
#             elif re.search(r"\b\d+\s*[kKmM]?\s*(?:to|-)\s*\d+\s*[kKmM]?\b", brief or ""):
#                 st.session_state["ai_suggested_tier"] = "Custom range"
#             else:
#                 st.session_state["ai_suggested_tier"] = _tier_map.get(
#                     str(intent.get("creator_tier") or "any").lower().split()[0],
#                     "Auto",
#                 )
#             st.session_state["ai_filter_version"] = int(st.session_state.get("ai_filter_version", 0)) + 1
#         st.session_state.analysis_result = result
#         st.session_state.last_brief = brief
#         st.session_state.last_platforms = list(platform_choice)
#         st.session_state.search_complete = False
#     st.rerun()


# if st.session_state.analysis_result:
#     result = st.session_state.analysis_result
#     intent = result.get("intent", {})

#     st.markdown('<div class="section-title">Campaign Brief Analysis</div>', unsafe_allow_html=True)
#     badges = []
#     for key in ("niche", "secondary_niche", "city", "state", "language", "creator_tier", "confidence"):
#         if intent.get(key):
#             badges.append(chip(f"{key}: {intent[key]}"))
#     if intent.get("gender_mode"):
#         badges.append(chip("gender mode: " + str(intent["gender_mode"]).replace("_", " ")))
#     if intent.get("gender") and intent.get("gender") != "ANY":
#         badges.append(chip("gender: " + ("male" if intent["gender"] == "M" else "female")))
#     st.markdown("".join(badges), unsafe_allow_html=True)
#     if intent.get("reasoning"):
#         st.caption(intent["reasoning"])
#     st.caption(
#         f"Follower range: {fmt_num(intent.get('min_followers', min_followers))} - "
#         f"{fmt_num(intent.get('max_followers', max_followers))}"
#     )

#     # ── Platform-aware analysis display ───────────────────────────────────────
#     show_ig_section = do_ig
#     show_yt_section = do_yt

#     if show_ig_section and show_yt_section:
#         col_tags, col_queries = st.columns(2)
#     elif show_ig_section:
#         col_tags = st.container()
#         col_queries = None
#     elif show_yt_section:
#         col_tags = None
#         col_queries = st.container()
#     else:
#         col_tags = col_queries = None

#     if show_ig_section and col_tags is not None:
#         with col_tags:
#             show_hashtag_plan(result)
#             st.markdown('<div class="section-title">Instagram Discovery Phrases</div>', unsafe_allow_html=True)
#             for i, query in enumerate(result.get("ig_keywords", [])[:12], 1):
#                 st.markdown(f"{i}. `{query}`")

#     if show_yt_section and col_queries is not None:
#         with col_queries:
#             st.markdown('<div class="section-title">YouTube Queries</div>', unsafe_allow_html=True)
#             yt_plan = result.get("yt_search_plan") or yt_plan_from_queries(result.get("yt_queries", []), source="legacy")
#             for i, item in enumerate(yt_plan, 1):
#                 query = item.get("query", "")
#                 source = item.get("source", "")
#                 stype = item.get("search_type", "video")
#                 source_label = f"{stype} | {source}"
#                 st.markdown(f"{i}. `{query}` <span class=\"muted\">{html.escape(source_label)}</span>", unsafe_allow_html=True)

#     with st.expander("Edit hashtags and queries"):
#         if show_ig_section:
#             edited_tags = st.text_area("Instagram hashtags, one per line", value="\n".join(result.get("hashtags_final", [])), height=140)
#             edited_ig_phrases = st.text_area("Instagram discovery phrases, one per line", value="\n".join(result.get("ig_keywords", [])), height=100)
#         if show_yt_section:
#             edited_yt = st.text_area("YouTube queries, one per line", value="\n".join(result.get("yt_queries", [])), height=140)
#         if st.button("Save edits"):
#             if show_ig_section:
#                 result["hashtags_final"] = [line.strip() for line in edited_tags.splitlines() if line.strip()]
#                 result["ig_keywords"] = [line.strip() for line in edited_ig_phrases.splitlines() if line.strip()]
#             if show_yt_section:
#                 result["yt_queries"] = [line.strip() for line in edited_yt.splitlines() if line.strip()]
#                 result["yt_search_plan"] = yt_plan_from_queries(result["yt_queries"], source="user")
#             st.session_state.analysis_result = result
#             st.rerun()


# if search_btn and st.session_state.analysis_result:
#     result = st.session_state.analysis_result
#     intent = dict(result.get("intent", {}))
#     effective_gender = gender_map.get(gender_override) or intent.get("gender", "ANY")
#     if effective_gender is None:
#         effective_gender = intent.get("gender", "ANY")
#     if creator_tier_override in CREATOR_TIER_RANGES:
#         effective_min, effective_max = CREATOR_TIER_RANGES[creator_tier_override]
#     else:
#         effective_min = int(min_followers)
#         effective_max = int(max_followers)
#     history_campaign = campaign_scope(campaign_name, brief)
#     _locs_list = intent.get("locations_list") or []
#     if _locs_list:
#         location_hints = [str(loc).lower().strip() for loc in _locs_list if loc]
#         if intent.get("language") and str(intent["language"]).lower() not in location_hints:
#             location_hints.append(str(intent["language"]).lower())
#     else:
#         location_hints = [str(intent.get(k)) for k in ("city", "state", "language") if intent.get(k)]
#     lang_code_map = {
#         "kannada": "kn", "tamil": "ta", "telugu": "te", "malayalam": "ml",
#         "marathi": "mr", "punjabi": "pa", "gujarati": "gu", "bengali": "bn",
#         "hindi": "hi", "assamese": "as",
#     }
#     lang_code = lang_code_map.get(str(intent.get("language") or "").lower())

#     logs: list[str] = []
#     log_box = st.empty()
#     progress = st.progress(0)

#     def add_log(message: str) -> None:
#         safe = html.escape(str(message))
#         logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {safe}")
#         log_box.markdown('<div class="soft-panel muted">' + "<br>".join(logs[-22:]) + "</div>", unsafe_allow_html=True)

#     ig_results: list[dict] = []
#     yt_results: list[dict] = []

#     # ── Instagram search ───────────────────────────────────────────────────────
#     if do_ig and result.get("hashtags_final"):
#         if not (keys["apify_discovery"] and keys["apify_profile"]):
#             add_log("Instagram skipped: missing Apify discovery/profile keys")
#         else:
#             progress.progress(10)
#             add_log(f"Instagram: scraping {len(result['hashtags_final'])} verified hashtags")
#             ig_debug: dict = {}
#             try:
#                 ig_results = run_async(run_ig_search(
#                     api_key=keys["apify_discovery"],
#                     profile_api_keys=keys["apify_profile"],
#                     hashtags=result["hashtags_final"],
#                     min_followers=effective_min,
#                     max_followers=effective_max,
#                     location_hints=location_hints,
#                     posts_per_tag=posts_per_tag,
#                     gender_filter=effective_gender,
#                     niche=intent.get("niche", ""),
#                     progress_callback=add_log,
#                     debug_state=ig_debug,
#                 ))
#                 ig_results, skipped_used = filter_used_creators(ig_results, history_campaign, allow_repeats)
#                 if skipped_used:
#                     add_log(f"Creator history: skipped {len(skipped_used)} previously used Instagram creators")
#                 elif allow_repeats and ig_results:
#                     used_count = sum(1 for c in ig_results if c.get("_history_used"))
#                     if used_count:
#                         add_log(f"Creator history: included {used_count} previously used Instagram creators")
#                 st.session_state.ig_debug = ig_debug
#                 result["ig_debug"] = ig_debug
#                 progress.progress(45)
#                 if ig_results and keys["gemini"]:
#                     add_log(f"Gemini: ranking {len(ig_results)} Instagram candidates")
#                     scorer = AIService(keys["gemini"], keys["apify_discovery"])
#                     scoring_intent = dict(intent)
#                     scoring_intent["_brief"] = brief
#                     ig_results = scorer.score_creators_batch(ig_results, scoring_intent)
#                 add_log(
#                     "Instagram done: "
#                     f"{sum(1 for c in ig_results if c.get('match_status') == 'high')} high, "
#                     f"{sum(1 for c in ig_results if c.get('match_status') in ('review', 'mid'))} mid, "
#                     f"{sum(1 for c in ig_results if c.get('match_status') in ('rejected', 'low'))} low"
#                 )
#             except Exception as exc:
#                 add_log(f"Instagram error: {exc}")
#     elif do_ig:
#         add_log("Instagram: no hashtags from analysis — run Analyze Brief first or add known hashtags")

#     # ── YouTube search ─────────────────────────────────────────────────────────
#     yt_plan = result.get("yt_search_plan") or yt_plan_from_queries(result.get("yt_queries", []), source="legacy")
#     if do_yt and yt_plan:
#         if not keys["youtube"]:
#             add_log("YouTube skipped: missing YOUTUBE_API_KEYS")
#         else:
#             progress.progress(60)
#             video_count = sum(1 for item in yt_plan if item.get("search_type") == "video")
#             channel_count = sum(1 for item in yt_plan if item.get("search_type") == "channel")
#             hashtag_count = sum(1 for item in yt_plan if item.get("source") == "hashtag")
#             add_log(f"YouTube: {video_count} video + {channel_count} channel + {hashtag_count} hashtag queries")
#             add_log(f"YouTube deep search: {'enabled (page 2)' if deep_yt_search else 'disabled'}")
#             try:
#                 yt_results = run_async(run_yt_search(
#                     api_keys=keys["youtube"],
#                     queries=result.get("yt_queries", []),
#                     min_subs=effective_min,
#                     max_subs=effective_max,
#                     gender_filter=effective_gender,
#                     location_hints=location_hints,
#                     lang_hints=[intent.get("language", "")] if intent.get("language") else [],
#                     lang_code=lang_code,
#                     region=region,
#                     results_per_query=results_per_yt_query,
#                     progress_callback=add_log,
#                     search_plan=yt_plan,
#                     exclude_terms=result.get("exclude_terms") or normalize_user_search_terms(exclude_terms_raw),
#                     allow_international=allow_international,
#                     deep_search=deep_yt_search,
#                 ))
#                 yt_results, skipped_used = filter_used_creators(yt_results, history_campaign, allow_repeats)
#                 if skipped_used:
#                     add_log(f"Creator history: skipped {len(skipped_used)} previously used YouTube creators")
#                 elif allow_repeats and yt_results:
#                     used_count = sum(1 for c in yt_results if c.get("_history_used"))
#                     if used_count:
#                         add_log(f"Creator history: included {used_count} previously used YouTube creators")
#                 progress.progress(78)
#                 if yt_results and keys["gemini"]:
#                     add_log(f"Gemini: ranking {len(yt_results)} YouTube candidates")
#                     scorer = AIService(keys["gemini"], keys["apify_discovery"])
#                     scoring_intent = dict(intent)
#                     scoring_intent["_brief"] = brief
#                     yt_results = scorer.score_youtube_creators_batch(yt_results, scoring_intent)
#                 add_log(
#                     "YouTube done: "
#                     f"{sum(1 for c in yt_results if c.get('match_status') == 'high')} high, "
#                     f"{sum(1 for c in yt_results if c.get('match_status') in ('review', 'mid'))} mid, "
#                     f"{sum(1 for c in yt_results if c.get('match_status') in ('rejected', 'low'))} low"
#                 )
#             except Exception as exc:
#                 add_log(f"YouTube error: {exc}")

#             # ── ScrapingBee parallel search ─────────────────────────────────
#             if keys.get("scrapingbee"):
#                 add_log("ScrapingBee: starting parallel YouTube discovery...")
#                 try:
#                     sb_results = run_async(run_scrapingbee_search(
#                         api_keys=keys["scrapingbee"],
#                         search_plan=yt_plan,
#                         min_subs=effective_min,
#                         max_subs=effective_max,
#                         progress_callback=add_log,
#                         yt_api_keys=keys["youtube"],
#                         gender_filter=effective_gender,
#                         location_hints=location_hints,
#                         lang_hints=[intent.get("language", "")] if intent.get("language") else [],
#                         exclude_terms=result.get("exclude_terms") or normalize_user_search_terms(exclude_terms_raw),
#                         allow_international=allow_international,
#                     ))
#                     # Deduplicate: only add channels not already found by YT API
#                     existing_ids = {c.get("channel_id") for c in yt_results}
#                     new_sb = [c for c in sb_results if c.get("channel_id") not in existing_ids]
#                     if new_sb:
#                         # Run through Gemini scorer for new SB-only results
#                         if keys["gemini"]:
#                             scorer2 = AIService(keys["gemini"], keys["apify_discovery"])
#                             scoring_intent2 = dict(intent)
#                             scoring_intent2["_brief"] = brief
#                             new_sb = scorer2.score_youtube_creators_batch(new_sb, scoring_intent2)
#                         yt_results.extend(new_sb)
#                         add_log(f"ScrapingBee: added {len(new_sb)} unique creators not found by YouTube API")
#                     else:
#                         add_log("ScrapingBee: no new unique creators beyond YouTube API results")
#                 except Exception as exc:
#                     add_log(f"ScrapingBee error: {exc}")
#             else:
#                 add_log("ScrapingBee: skipped (no SCRAPINGBEE_KEYS configured)")

#     elif do_yt:
#         add_log("YouTube: no search plan — run Analyze Brief first")

#     progress.progress(100)
#     st.session_state.ig_results = ig_results
#     # Sort YT results by AI score now, then apply the fetch cap so the user
#     # sees only the top N they asked for (not all raw candidates).
#     def _ai_sort_key(c: dict) -> float:
#         score = c.get("ai_score")
#         try:
#             return float(score) if score is not None else 0.0
#         except Exception:
#             return 0.0
#     yt_results.sort(key=_ai_sort_key, reverse=True)
#     fetch_cap = int(results_per_yt_query) if results_per_yt_query else 50
#     if fetch_cap < 50 and len(yt_results) > fetch_cap:
#         add_log(f"Fetch cap: keeping top {fetch_cap} of {len(yt_results)} YouTube creators")
#         yt_results = yt_results[:fetch_cap]
#     st.session_state.yt_results = yt_results
#     st.session_state.analysis_result = result
#     st.session_state.search_complete = True
#     st.rerun()


# ig_results = st.session_state.ig_results
# yt_results = st.session_state.yt_results
# display_history_campaign = campaign_scope(campaign_name, brief or st.session_state.last_brief)
# all_results = annotate_used_creators(ig_results + yt_results, display_history_campaign)
# if not allow_repeats:
#     all_results = [c for c in all_results if not c.get("_history_used")]

# if all_results or st.session_state.search_complete:
#     # Sort all creators by AI score descending
#     def sort_key(c):
#         score = c.get("ai_score")
#         if isinstance(score, str):
#             try:
#                 score = float(score)
#             except Exception:
#                 score = 0
#         return score if score is not None else 0

#     sorted_results = sorted(all_results, key=sort_key, reverse=True)

#     m1, m2, m3 = st.columns(3)
#     with m1:
#         st.metric("Total Creators", len(sorted_results))
#     with m2:
#         st.metric("With Email", sum(1 for c in sorted_results if c.get("email")))
#     with m3:
#         avg = sum(sort_key(c) for c in sorted_results) / len(sorted_results) if sorted_results else 0
#         st.metric("Avg AI Score", f"{avg:.1f}")

#     df = creators_to_df(sorted_results)
#     if not df.empty:
#         st.download_button(
#             "Download Excel",
#             data=df_to_excel(df),
#             file_name=f"influencers_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
#             mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#         )

#     st.markdown('<div class="sec-label">All Creators — sorted by AI Score</div>', unsafe_allow_html=True)
#     render_creator_table(sorted_results, height=700)
#     # NOTE: selection/mark-as-used moved below table; CSV now inside the HTML component
#     selection_rows: list[tuple[str, dict]] = []
#     selected_creators: list[dict] = []
#     mark_col, info_col = st.columns([1, 3])
#     with mark_col:
#         if st.button("Mark selected as used", disabled=not selected_creators):
#             marked = mark_creators_used(selected_creators, display_history_campaign, notes="Marked from Streamlit results")
#             selected_keys = set()
#             for creator in selected_creators:
#                 selected_keys.update(creator_identity_candidates(creator))

#             def keep_unselected(row: dict) -> bool:
#                 return not (creator_identity_candidates(row) & selected_keys)

#             if not allow_repeats:
#                 st.session_state.ig_results = [c for c in st.session_state.ig_results if keep_unselected(c)]
#                 st.session_state.yt_results = [c for c in st.session_state.yt_results if keep_unselected(c)]
#             for key, _ in selection_rows:
#                 st.session_state[key] = False
#             st.session_state.history_notice = f"Marked {marked} creator(s) as used for this campaign."
#             st.rerun()
#     with info_col:
#         st.caption(
#             "Tick creators you used, then mark them. With repeated creators blocked, they will be skipped in future searches for this campaign."
#         )

# elif not st.session_state.analysis_result:
#     st.info("Enter a campaign brief and analyze it to begin.")

"""Influencer Finder Pro."""

from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from ai_service import AIService, normalize_user_search_terms
from backend_keys import backend_key_counts, env_keys, first_non_empty, parse_keys
from creator_history import (
    annotate_used_creators,
    campaign_scope,
    clear_used_creators,
    creator_identity_candidates,
    filter_used_creators,
    history_stats,
    mark_creators_used,
)
from ui_table import render_creator_table
from ig_scraper import merge_instagram_creators, run_ig_related_search_from_youtube, run_ig_reels_discovery, run_ig_search
from yt_scraper import run_yt_search
from scrapingbee_scraper import run_scrapingbee_search


st.set_page_config(
    page_title="Influencer Radar",
    page_icon="IF",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
  
  html, body, [class*="css"] { font-family: 'League Spartan', sans-serif !important; }
</style>
""",
    unsafe_allow_html=True,
)

# Map internal match_status → display label and chip class
_STATUS_LABEL = {"high": "High", "review": "Mid", "rejected": "Low", "mid": "Mid", "low": "Low"}
_STATUS_CLS   = {"high": "good", "review": "warn", "rejected": "bad",  "mid": "warn", "low": "bad"}
CREATOR_TIER_RANGES = {
    "Nano": (1_000, 10_000),
    "Micro": (10_000, 100_000),
    "Mid": (100_000, 500_000),
    "Macro": (500_000, 5_000_000),
    "Any": (10_000, 500_000),
}
CREATOR_TIER_OPTIONS = ["Auto", "Any", "Nano", "Micro", "Mid", "Macro", "Custom range"]


def _status_label(status: str) -> str:
    return _STATUS_LABEL.get(status, status.title())


def _status_cls(status: str) -> str:
    return _STATUS_CLS.get(status, "")


def _normalize_status(status: str) -> str:
    """Normalise raw match_status to high / mid / low for export."""
    return {"high": "high", "review": "mid", "rejected": "low",
            "mid": "mid", "low": "low"}.get(status, status)


def init_state() -> None:
    defaults = {
        "analysis_result": None,
        "ig_results": [],
        "yt_results": [],
        "ig_debug": {},
        "search_complete": False,
        "last_brief": "",
        "last_platforms": [],
        "history_notice": "",
        "ai_filter_version": 0,
        "review_queries": [],
        "review_hashtags": [],
        "review_brand_tags": [],
        "review_trending_tags": [],
        "user_extra_keywords": "",
        "reference_creators": "",
        "show_review_panel": False,
        "ai_suggested_min": 10000,
        "ai_suggested_max": 500000,
        "ai_suggested_gender": "Auto",
        "ai_suggested_tier": "Auto",
        "ai_suggested_locations": [],
        "selected_review_tags": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def fmt_num(value) -> str:
    try:
        n = int(value)
    except Exception:
        return str(value)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def chip(label: str, cls: str = "") -> str:
    return f'<span class="chip {cls}">{html.escape(label)}</span>'


def yt_plan_from_queries(queries: list[str], source: str = "user") -> list[dict]:
    return [
        {
            "query": query,
            "search_type": "video",
            "source": source,
            "intent_terms": [],
            "negative_terms": [],
            "paginate": True,
        }
        for query in queries
        if query
    ]


def _compact_ig_hashtag(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", str(value or "").replace("#", "")).lower()


def build_instagram_reels_terms(
    result: dict,
    intent: dict,
    brief: str,
    user_terms: list[str],
    ai_svc: AIService | None,
) -> tuple[list[str], list[str]]:
    """Build Instagram keyword and hashtag searches from the same campaign brief."""
    keyword_terms: list[str] = []
    hashtag_terms: list[str] = []

    def add_keyword(term: object) -> None:
        clean = re.sub(r"\s+", " ", str(term or "").replace("#", " ").strip().lower())
        if 4 <= len(clean) <= 80 and clean not in keyword_terms:
            keyword_terms.append(clean)

    def add_hashtag(term: object) -> None:
        clean = _compact_ig_hashtag(str(term or ""))
        if 3 <= len(clean) <= 40 and clean not in hashtag_terms:
            hashtag_terms.append(clean)

    for term in result.get("ig_keywords") or []:
        add_keyword(term)
    if ai_svc and not keyword_terms:
        try:
            for term in ai_svc.generate_ig_keywords(intent, brief):
                add_keyword(term)
        except Exception:
            pass

    for term in user_terms:
        if str(term).strip().startswith("#"):
            add_hashtag(term)
        else:
            add_keyword(term)

    niche = str(intent.get("niche") or "").strip().lower()
    secondary = str(intent.get("secondary_niche") or "").strip().lower()
    gender = str(intent.get("gender") or "ANY").upper()
    locations = [str(x).strip().lower() for x in (intent.get("locations_list") or []) if str(x).strip()]
    if not locations:
        locations = [
            str(intent.get(key) or "").strip().lower()
            for key in ("city", "state", "language")
            if str(intent.get(key) or "").strip()
        ]
    if "india" not in locations:
        locations.append("india")

    base_topics = [topic for topic in (niche, secondary) if topic]
    if not base_topics:
        base_topics = ["lifestyle creator"]

    for topic in base_topics[:3]:
        add_keyword(f"{topic} india")
        add_keyword(f"{topic} creator india")
        add_keyword(f"{topic} review")
        add_keyword(f"{topic} routine")
        add_keyword(f"{topic} reels")
        for loc in locations[:4]:
            add_keyword(f"{topic} {loc} creator")
        if gender == "M":
            add_keyword(f"men {topic} india")
            add_keyword(f"male {topic} creator")
        elif gender == "F":
            add_keyword(f"women {topic} india")
            add_keyword(f"female {topic} creator")

    for tag in (
        result.get("hashtags_final") or []
    ) + (
        result.get("brand_campaign_tags") or []
    ) + (
        result.get("trending_creator_tags") or []
    ):
        add_hashtag(tag)

    for topic in base_topics[:3]:
        compact_topic = _compact_ig_hashtag(topic)
        if compact_topic:
            add_hashtag(compact_topic)
            add_hashtag(f"{compact_topic}india")
            add_hashtag(f"indian{compact_topic}")
            add_hashtag(f"{compact_topic}reels")
            add_hashtag(f"{compact_topic}review")
        for loc in locations[:4]:
            compact_loc = _compact_ig_hashtag(loc)
            if compact_topic and compact_loc:
                add_hashtag(f"{compact_topic}{compact_loc}")
    if gender == "M":
        add_hashtag("mensgroomingindia")
        add_hashtag("indianmenstyle")
    elif gender == "F":
        add_hashtag("indianbeautyblogger")
        add_hashtag("indianwomenfashion")

    return keyword_terms[:18], hashtag_terms[:18]


def get_key_config(overrides: dict[str, str]) -> dict[str, list[str]]:
    gemini = first_non_empty(parse_keys(overrides.get("gemini")), env_keys("GEMINI_API_KEYS"), env_keys("GEMINI_API_KEY"))
    apify_discovery = first_non_empty(
        parse_keys(overrides.get("apify_discovery")),
        env_keys("APIFY_DISCOVERY_KEYS"),
        env_keys("APIFY_API_KEYS"),
        env_keys("APIFY_API_KEY"),
    )
    apify_profile = first_non_empty(
        parse_keys(overrides.get("apify_profile")),
        env_keys("APIFY_PROFILE_KEYS"),
        apify_discovery,
    )
    apify_ig_related = first_non_empty(
        parse_keys(overrides.get("apify_ig_related")),
        env_keys("APIFY_IG_RELATED_KEYS"),
    )
    youtube = first_non_empty(parse_keys(overrides.get("youtube")), env_keys("YOUTUBE_API_KEYS"), env_keys("YOUTUBE_API_KEY"))
    scrapingbee = first_non_empty(
        parse_keys(overrides.get("scrapingbee")),
        env_keys("SCRAPINGBEE_KEYS"),
        env_keys("SCRAPINGBEE_API_KEY"),
    )
    return {
        "gemini": gemini,
        "apify_discovery": apify_discovery,
        "apify_profile": apify_profile,
        "apify_ig_related": apify_ig_related,
        "youtube": youtube,
        "scrapingbee": scrapingbee,
    }


def creators_to_df(creators: list[dict]) -> pd.DataFrame:
    rows = []
    for c in creators:
        if c.get("platform") == "instagram":
            rows.append({
                "Platform": "Instagram",
                "Status": _normalize_status(c.get("match_status", "")),
                "Username/Handle": c.get("username", ""),
                "Full Name": c.get("full_name", ""),
                "Followers": c.get("followers", 0),
                "Profile URL": c.get("profile_url", ""),
                "Bio": c.get("bio", ""),
                "Source Hashtag": "#" + c.get("source_hashtag", "") if c.get("source_hashtag") else "",
                "Sample Post": c.get("sample_post_url", ""),
                "Email": c.get("email", ""),
                "Phone": c.get("phone", ""),
                "Website": c.get("external_url", ""),
                "Used Before": "Yes" if c.get("_history_used") else "",
                "AI Score": c.get("ai_score", ""),
                "Niche Confidence": c.get("niche_confidence", 0),
                "India Confidence": c.get("india_confidence", 0),
                "Gender Confidence": c.get("gender_confidence", 0),
                "Creator Confidence": c.get("creator_confidence", 0),
                "Evidence": c.get("evidence", ""),
                "Reason": c.get("reject_reason") or c.get("review_reason") or c.get("ai_reason", ""),
            })
        else:
            rows.append({
                "Platform": "YouTube",
                "Status": _normalize_status(c.get("match_status", "mid")),
                "Username/Handle": c.get("handle", "") or c.get("channel_name", ""),
                "Full Name": c.get("channel_name", ""),
                "Followers": c.get("subscribers", 0),
                "Profile URL": c.get("handle_url") or c.get("channel_url", ""),
                "Bio": c.get("description", ""),
                "Source Hashtag": "",
                "Sample Post": c.get("video_url", ""),
                "Email": c.get("email", ""),
                "Phone": c.get("phone", ""),
                "Website": c.get("website") or c.get("aggregator_url", ""),
                "Used Before": "Yes" if c.get("_history_used") else "",
                "AI Score": c.get("ai_score", ""),
                "Niche Confidence": c.get("_niche_score", ""),
                "India Confidence": c.get("_india_confidence", c.get("_location_score", "")),
                "Gender Confidence": c.get("_gender_score", ""),
                "Creator Confidence": c.get("_quality_score", 0),
                "Evidence": c.get("video_title", "") or c.get("_search_query", ""),
                "Reason": c.get("reject_reason") or c.get("review_reason") or c.get("ai_reason", ""),
            })
    return pd.DataFrame(rows)


def df_to_excel(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Creators")
        ws = writer.sheets["Creators"]
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 60)
    return output.getvalue()


def render_creator_card(creator: dict, selection_key: str | None = None) -> None:
    platform = creator.get("platform", "")
    if platform == "instagram":
        name = html.escape(str(creator.get("full_name") or creator.get("username", "")))
        handle = html.escape("@" + str(creator.get("username", "")))
        url = html.escape(str(creator.get("profile_url", "")), quote=True)
        followers = creator.get("followers", 0)
        bio = html.escape(str(creator.get("bio", ""))[:220])
        status = creator.get("match_status", "review")
        reason = html.escape(str(creator.get("reject_reason") or creator.get("review_reason") or creator.get("ai_reason") or ""))
        chips = [
            chip(_status_label(status), _status_cls(status)),
            chip(f"{fmt_num(followers)} followers"),
        ]
        if creator.get("_history_used"):
            chips.append(chip("Used before", "bad"))
        if creator.get("ai_score") not in (None, ""):
            chips.append(chip(f"AI {creator.get('ai_score')}/10"))
        if creator.get("source_hashtag"):
            chips.append(chip("#" + str(creator.get("source_hashtag")), "warn"))
        evidence = html.escape(str(creator.get("evidence", ""))[:260])
    else:
        name = html.escape(str(creator.get("channel_name", "")))
        handle = html.escape(str(creator.get("handle", "")))
        url = html.escape(str(creator.get("handle_url") or creator.get("channel_url") or ""), quote=True)
        followers = creator.get("subscribers", 0)
        bio = html.escape(str(creator.get("description", ""))[:220])
        status = creator.get("match_status", "review")
        reason = html.escape(str(creator.get("reject_reason") or creator.get("review_reason") or creator.get("ai_reason") or ""))
        chips = [
            chip(_status_label(status), _status_cls(status)),
            chip(f"{fmt_num(followers)} subscribers"),
        ]
        if creator.get("_history_used"):
            chips.append(chip("Used before", "bad"))
        if creator.get("ai_score") not in (None, ""):
            chips.append(chip(f"AI {creator.get('ai_score')}/10"))
        if creator.get("_source"):
            chips.append(chip(str(creator.get("_source")), "warn"))
        evidence_text = creator.get("video_title") or ("Query: " + str(creator.get("_search_query", "")))
        evidence = html.escape(str(evidence_text)[:260])

    st.markdown(
        f"""
<div class="creator-card">
  <div class="creator-title">{name} <span class="muted">{handle}</span></div>
  <div>{''.join(chips)}</div>
  <div class="muted" style="margin-top:6px">{bio}</div>
  <div class="muted" style="margin-top:6px">{evidence}</div>
  {'<div class="muted" style="margin-top:6px">Reason: ' + reason + '</div>' if reason else ''}
  {'<a href="' + url + '" target="_blank">Open profile</a>' if url else ''}
</div>
""",
        unsafe_allow_html=True,
    )
    if selection_key:
        st.checkbox("Mark as used", key=selection_key)


def render_cards(items: list[dict], selectable: bool = False) -> list[tuple[str, dict]]:
    if not items:
        st.info("No creators in this bucket.")
        return []
    selection_rows: list[tuple[str, dict]] = []
    cols_per_row = 2
    for start in range(0, len(items), cols_per_row):
        cols = st.columns(cols_per_row)
        for offset, col in enumerate(cols):
            index = start + offset
            if index < len(items):
                with col:
                    selection_key = None
                    if selectable:
                        ids = sorted(value for _, value in creator_identity_candidates(items[index]))
                        identity = re.sub(r"[^a-zA-Z0-9_]+", "_", ids[0] if ids else str(index))
                        selection_key = f"used_select_{index}_{identity}"
                        selection_rows.append((selection_key, items[index]))
                    render_creator_card(items[index], selection_key=selection_key)
    return selection_rows


def show_hashtag_plan(result: dict) -> None:
    hashtags_verified = result.get("hashtags_verified", [])
    hashtags_final = result.get("hashtags_final", [])

    st.markdown('<div class="sec-label"><span>Instagram Hashtags</span></div>', unsafe_allow_html=True)
    if hashtags_final:
        st.markdown("".join(chip(tag, "good") for tag in hashtags_final), unsafe_allow_html=True)
        st.code(" ".join(hashtags_final), language=None)
    else:
        st.warning("No usable Instagram hashtags selected.")

    if hashtags_verified:
        selected_count = sum(1 for h in hashtags_verified if h.get("selected"))
        st.caption(f"{selected_count}/{len(hashtags_verified)} tags selected after quality gate")
        rows = []
        for h in hashtags_verified:
            cls = "good" if h.get("selected") else "bad"
            label = f"{h.get('tag')} | {h.get('count_display', 'unverified')} | {h.get('reason', '')}"
            rows.append(chip(label, cls))
        st.markdown("".join(rows[:60]), unsafe_allow_html=True)

    search_terms = result.get("hashtag_search_terms", [])
    if search_terms:
        with st.expander("Hashtag search terms"):
            st.write(search_terms)


init_state()

if st.query_params.get("reset"):
    for key in (
        "analysis_result", "ig_results", "yt_results", "ig_debug", "search_complete",
        "last_brief", "last_platforms", "history_notice", "ai_suggested_min",
        "ai_suggested_max", "ai_suggested_gender", "ai_suggested_tier",
    ):
        if key in st.session_state:
            del st.session_state[key]
    st.query_params.clear()
    st.rerun()

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=League+Spartan:wght@300;400;500;600;700;800;900&display=swap');

/* ── Global Reset ── */
html, body, [class*="css"] {
  font-family: 'League Spartan', sans-serif !important;
}
.stApp { background: #f9f9f8 !important; color: #111 !important; }
.block-container { padding: 0 !important; max-width: 100% !important; }
#MainMenu, footer { display: none !important; }
/* The workbench uses a fixed filter rail; remove Streamlit's header/toggle gutter. */
header[data-testid="stHeader"] { display: none !important; height: 0 !important; }
button[data-testid="baseButton-headerNoPadding"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"] { display: none !important; }

/* ── Topbar ── */
#ciq-topbar-anchor {
  position: sticky; top: 0; z-index: 100;
  background: #fff; border-bottom: 1.5px solid #e8e8e8;
}
#ciq-topbar {
  display: flex; align-items: center; gap: 18px;
  padding: 10px 28px; background: #fff;
  height: 52px;
}
#ciq-topbar .topbar-right { margin-left: auto; display: flex; align-items: center; gap: 12px; }

/* ── Logo ── */
.logo-wrap { display:flex; align-items:center; gap:8px; user-select:none; }
.logo-bar { font-family:'League Spartan', sans-serif; font-weight:900; font-size:0.92rem; letter-spacing:0.04em; color:#111; }
.logo-bar-bg { background:#111; color:#fff; padding:2px 6px; border-radius:3px; margin-right:2px; letter-spacing:0.06em; }
.logo-divider { color:#555; font-size:1.1rem; font-weight:200; margin:0 2px; }
.logo-ykone { font-family:'League Spartan', sans-serif; font-style:italic; font-size:1rem; color:#111; font-weight:700; letter-spacing:-0.01em; }
.logo-product-name {
  font-family:'League Spartan', sans-serif; font-weight:700; font-size:0.78rem;
  letter-spacing:0.18em; text-transform:uppercase; color:#444;
  padding-left: 10px; border-left: 1.5px solid #e0e0e0; margin-left: 4px;
}

/* ── Quota bar ── */
.quota-wrap { display: flex; align-items: center; gap: 10px; }
.quota-item { display: flex; align-items: center; gap: 5px; }
.quota-label { font-family: 'League Spartan', sans-serif; font-size: 0.6rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #444; white-space: nowrap; }
.quota-bar { width: 48px; height: 3px; background: #ebebeb; border-radius: 99px; overflow: hidden; }
.quota-bar-fill { height: 100%; background: #111; border-radius: 99px; }
.quota-pct { font-family: 'League Spartan', sans-serif; color: #444; font-size: 0.6rem; min-width: 20px; }

/* ── Reset link ── */
.reset-link {
  font-family: 'League Spartan', sans-serif; font-size: 0.7rem; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase; color: #555;
  text-decoration: none; padding: 5px 12px; border: 1px solid #ddd; border-radius: 5px;
  transition: all .15s;
}
.reset-link:hover { background: #111; color: #fff; border-color: #111; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
  background: #fff !important;
  border-right: 1.5px solid #ebebeb !important;
  width: 392px !important;
  min-width: 392px !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
  padding: 12px 18px 24px !important;
}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] textarea,
section[data-testid="stSidebar"] button {
  font-family: 'League Spartan', sans-serif !important;
}

/* Sidebar input labels */
section[data-testid="stSidebar"] label {
  color: #333 !important; font-size: 0.7rem !important;
  font-weight: 600 !important; letter-spacing: 0.07em !important;
  text-transform: uppercase !important;
}

/* Toggle copy stays readable without changing Streamlit's internal layout. */
[data-testid="stToggle"] p { color: #303030 !important; font-size: 0.75rem !important; font-family: 'League Spartan', sans-serif !important; font-weight: 500 !important; margin: 0 !important; }

/* Placeholder text global fix */
input::placeholder, textarea::placeholder { color: #5b5b5b !important; opacity: 1 !important; }

/* Number input label */
[data-testid="stNumberInput"] label { color: #333 !important; font-size: 0.68rem !important; font-weight: 700 !important; letter-spacing: 0.08em !important; text-transform: uppercase !important; }
[data-testid="stSelectbox"] label { color: #333 !important; font-size: 0.68rem !important; font-weight: 700 !important; letter-spacing: 0.08em !important; text-transform: uppercase !important; }
[data-testid="stTextInput"] label { color: #333 !important; font-size: 0.68rem !important; font-weight: 700 !important; letter-spacing: 0.08em !important; text-transform: uppercase !important; }

/* Multiselect tags clean styling */
[data-baseweb="multi-select"] { background: #fafafa !important; border: 1.5px solid #e8e8e8 !important; border-radius: 6px !important; }
[data-baseweb="multi-select"] input::placeholder { color: #5b5b5b !important; font-size: 0.78rem !important; }

section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] textarea {
  background: #fafafa !important; border: 1.5px solid #e8e8e8 !important;
  color: #111 !important; border-radius: 6px !important;
  font-family: 'League Spartan', sans-serif !important; font-size: 0.82rem !important;
}
section[data-testid="stSidebar"] input:focus,
section[data-testid="stSidebar"] textarea:focus {
  border-color: #111 !important; box-shadow: 0 0 0 3px rgba(0,0,0,0.06) !important;
  outline: none !important;
}
.sidebar-inner { padding: 0; }

/* ── Section labels ── */
.sec-label {
  font-family: 'League Spartan', sans-serif; font-size: 0.62rem; font-weight: 700;
  letter-spacing: 0.12em; text-transform: uppercase; color: #3a3a3a;
  margin: 16px 0 8px; display: flex; align-items: center; gap: 8px;
}
.sec-label::after { content: ''; flex: 1; height: 1px; background: #ebebeb; }
.sec-label span { white-space: nowrap; }

/* ── AI Panel ── */
.ai-panel-title {
  font-family: 'League Spartan', sans-serif; font-size: 0.62rem; font-weight: 800;
  letter-spacing: 0.14em; text-transform: uppercase; color: #303030;
  margin: 0 0 10px;
}
.ai-confidence { display:flex; gap:6px; align-items:center; margin-bottom:6px; flex-wrap: wrap; }
.conf-high { background:#111; color:#fff; padding:2px 8px; border-radius:4px; font-size:0.62rem; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; }
.conf-mid  { background:#555; color:#fff; padding:2px 8px; border-radius:4px; font-size:0.62rem; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; }
.conf-low  { background:#fff; color:#3f3f3f; border:1px solid #bdbdbd; padding:2px 8px; border-radius:4px; font-size:0.62rem; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; }
.ai-suggest-row { font-family: 'League Spartan', sans-serif; font-size: 0.75rem; color: #3f3f3f; margin-bottom: 4px; }
.ai-suggest-row strong { color: #111; font-weight: 700; }
.kw-section-label { color: #3f3f3f; font-size: 0.6rem; font-weight: 700; letter-spacing: 0.1em; margin: 10px 0 4px; text-transform: uppercase; }

/* ── Keyword chips ── */
.kw-chip {
  display: inline-flex; align-items: center; gap: 4px;
  background: #f3f3f3; border: 1px solid #e0e0e0; border-radius: 5px;
  color: #333; font-family: 'League Spartan', sans-serif; font-size: 0.7rem;
  font-weight: 600; padding: 3px 9px; margin: 2px 3px 2px 0; letter-spacing: 0.01em;
}
.kw-chip .plus { color: #333; font-weight: 700; margin-left: 2px; }

/* ── Buttons ── */
.stButton > button {
  font-family: 'League Spartan', sans-serif !important; font-weight: 600 !important;
  letter-spacing: 0.04em !important; border-radius: 6px !important;
  font-size: 0.78rem !important; transition: all .15s !important;
  background: #fff !important; color: #111 !important;
  border: 1.5px solid #202020 !important; padding: 6px 16px !important;
}
.stButton > button:hover:not(:disabled) { background: #f4f4f4 !important; border-color: #111 !important; }
.stButton > button:disabled { background: #f6f6f6 !important; color: #111 !important; border-color: #c9c9c9 !important; cursor: not-allowed !important; opacity: 1 !important; }
.stButton > button[kind="primary"]:not(:disabled),
.stButton > button[data-testid="stBaseButton-primary"]:not(:disabled) {
  background: #111 !important; color: #fff !important; border-color: #111 !important;
}
.stButton > button[kind="primary"]:hover:not(:disabled),
.stButton > button[data-testid="stBaseButton-primary"]:hover:not(:disabled) {
  background: #303030 !important; color: #fff !important; border-color: #303030 !important;
}

/* Secondary/ghost buttons — History, Quick Suggest */
.stButton[data-key="hist_btn"] > button,
.stButton[data-key="quick_suggest"] > button {
  background: #fff !important; color: #333 !important;
  border: 1.5px solid #ddd !important;
}
.stButton[data-key="hist_btn"] > button:hover,
.stButton[data-key="quick_suggest"] > button:hover {
  background: #f3f3f3 !important; border-color: #bbb !important; color: #111 !important;
}

/* Download button */
.stDownloadButton > button {
  font-family: 'League Spartan', sans-serif !important; background: #fff !important;
  border: 1.5px solid #ddd !important; color: #333 !important; font-weight: 600 !important;
  border-radius: 6px !important; font-size: 0.75rem !important;
}
.stDownloadButton > button:hover { background: #111 !important; color: #fff !important; border-color: #111 !important; }

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
  background: #fff !important; border-bottom: 1.5px solid #ebebeb !important; gap: 0 !important;
  padding: 0 24px !important;
}
.stTabs [data-baseweb="tab"] {
  color: #3d3d3d !important; font-family: 'League Spartan', sans-serif !important;
  font-size: 0.78rem !important; font-weight: 700 !important; letter-spacing: 0.06em !important;
  text-transform: uppercase !important; padding: 12px 24px !important;
  border-bottom: 2px solid transparent !important; border-radius: 0 !important;
  margin-bottom: -1.5px !important;
  display: inline-flex !important; align-items: center !important; gap: 8px !important;
}
.stTabs [data-baseweb="tab"]::before {
  content: "";
  width: 18px;
  height: 18px;
  display: inline-block;
  flex: 0 0 18px;
  background-size: contain;
  background-repeat: no-repeat;
  background-position: center;
}
.stTabs [data-baseweb="tab"]:nth-of-type(1)::before {
  background-image: url("data:image/svg+xml,%3Csvg width='18' height='18' viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Crect x='2' y='5' width='20' height='14' rx='4' fill='%23FF0000'/%3E%3Cpath d='M10 8.5v7l6-3.5-6-3.5z' fill='white'/%3E%3C/svg%3E");
}
.stTabs [data-baseweb="tab"]:nth-of-type(2)::before {
  background-image: url("data:image/svg+xml,%3Csvg width='18' height='18' viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='2' y1='22' x2='22' y2='2' gradientUnits='userSpaceOnUse'%3E%3Cstop stop-color='%23FEDA75'/%3E%3Cstop offset='.28' stop-color='%23FA7E1E'/%3E%3Cstop offset='.55' stop-color='%23D62976'/%3E%3Cstop offset='.78' stop-color='%239624FB'/%3E%3Cstop offset='1' stop-color='%234F5BD5'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect x='3' y='3' width='18' height='18' rx='5' fill='url(%23g)'/%3E%3Ccircle cx='12' cy='12' r='4' fill='none' stroke='white' stroke-width='2'/%3E%3Ccircle cx='16.8' cy='7.2' r='1.4' fill='white'/%3E%3C/svg%3E");
}
.stTabs [aria-selected="true"] {
  color: #111 !important; border-bottom: 2px solid #111 !important; background: transparent !important;
}

/* ── Expanders ── */
details > summary {
  font-family: 'League Spartan', sans-serif !important; font-weight: 600 !important;
  font-size: 0.75rem !important; letter-spacing: 0.04em !important;
  color: #242424 !important; background: #fff !important;
  border: 1.5px solid #d2d2d2 !important; border-radius: 6px !important;
  padding: 9px 12px !important; list-style: none !important; cursor: pointer;
  display: flex !important; align-items: center !important; gap: 8px !important;
}
details[open] > summary { border-radius: 6px 6px 0 0 !important; border-bottom: none !important; }
details > div { border: 1.5px solid #ebebeb !important; border-top: none !important; border-radius: 0 0 6px 6px !important; background: #fff !important; }
/* Fallback for streamlit expander class names */
[data-testid="stExpander"] > details > summary { list-style: none; }
[data-testid="stExpander"] summary::-webkit-details-marker { display: none; }
.streamlit-expanderHeader {
  font-family: 'League Spartan', sans-serif !important; font-weight: 600 !important;
  font-size: 0.75rem !important; color: #242424 !important; background: #fff !important;
  border: 1.5px solid #d2d2d2 !important; border-radius: 6px !important;
}
[data-testid="stExpander"] summary svg { color: #111 !important; }

/* ── Metrics ── */
[data-testid="stMetric"] {
  background: #fff; border: 1.5px solid #ebebeb; border-radius: 10px; padding: 18px 20px !important;
}
[data-testid="stMetricValue"] {
  font-family: 'League Spartan', sans-serif !important; font-size: 2rem !important;
  font-weight: 900 !important; color: #111 !important;
}
[data-testid="stMetricLabel"] {
  font-family: 'League Spartan', sans-serif !important; color: #444 !important;
  font-size: 0.62rem !important; font-weight: 700 !important;
  text-transform: uppercase !important; letter-spacing: 0.1em !important;
}

/* ── Selectboxes ── */
.stSelectbox > div > div {
  background: #fafafa !important; border: 1.5px solid #e8e8e8 !important;
  border-radius: 6px !important; font-family: 'League Spartan', sans-serif !important;
  color: #111 !important; font-size: 0.8rem !important;
}

/* ── Number inputs ── */
.stNumberInput > div > div > input {
  background: #fafafa !important; border: 1.5px solid #e8e8e8 !important;
  color: #111 !important; border-radius: 6px !important;
  font-family: 'League Spartan', sans-serif !important; font-size: 0.8rem !important;
}

/* ── Toggle ── */
.stToggle > label > div[data-checked="true"] { background: #111 !important; }
.stToggle > label { font-family: 'League Spartan', sans-serif !important; font-size: 0.75rem !important; color: #303030 !important; font-weight: 500 !important; }
/* Toggle label text fix */
[data-testid="stToggle"] span[data-testid="stToggleLabel"] { color: #303030 !important; font-size: 0.75rem !important; font-weight: 500 !important; font-family: 'League Spartan', sans-serif !important; }

/* ── Progress / Spinner ── */
.stProgress > div > div > div { background: #111 !important; }
.stSpinner > div { border-top-color: #111 !important; }

/* ── Caption / Alert ── */
.stCaption { font-family: 'League Spartan', sans-serif !important; color: #444 !important; font-size: 0.72rem !important; }
.stAlert { border-radius: 8px !important; font-family: 'League Spartan', sans-serif !important; font-size: 0.8rem !important; }
div[data-testid="stAlert"] { border-radius: 8px !important; }

/* ── Multiselect (review panel) ── */
[data-baseweb="tag"] {
  background: #f3f3f3 !important; border: 1px solid #e0e0e0 !important;
  border-radius: 5px !important; color: #333 !important;
  font-family: 'League Spartan', sans-serif !important; font-size: 0.72rem !important;
  font-weight: 600 !important;
}
[data-baseweb="tag"] span { color: #333 !important; }
[data-baseweb="tag"] [role="button"] { color: #444 !important; }
[data-baseweb="tag"] [role="button"]:hover { color: #111 !important; background: transparent !important; }

/* ── Layout ── */
.main-area { padding: 20px 28px 40px; }
.metric-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(150px, 210px));
  gap: 12px;
  margin: 14px 0;
}
.metric-box {
  background: #fff;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  padding: 14px 16px 12px;
  min-height: 84px;
}
.metric-box .num {
  font-family: 'League Spartan', sans-serif;
  font-size: 1.55rem;
  font-weight: 700;
  line-height: 1.05;
  color: #111;
}
.metric-box .lbl {
  margin-top: 7px;
  font-family: 'League Spartan', sans-serif;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #333;
}
.empty-state { text-align: center; padding: 80px 0; }
.empty-state .icon { font-size: 2.5rem; font-weight: 900; color: #555; margin-bottom: 20px; font-family: 'League Spartan', sans-serif; }
.empty-state h3 { font-family: 'League Spartan', sans-serif; font-size: 1rem; font-weight: 800; color: #111; margin-bottom: 10px; letter-spacing: -0.01em; }
.empty-state p { font-family: 'League Spartan', sans-serif; font-size: 0.8rem; color: #444; line-height: 1.8; }
.empty-tip { font-family: 'League Spartan', sans-serif; font-size: 0.7rem; color: #444; margin-top: 6px; }
.results-header { font-family: 'League Spartan', sans-serif; font-size: 0.62rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: #444; margin: 20px 0 10px; }
.soft-panel { background: #fafafa; border: 1.5px solid #ebebeb; border-radius: 8px; padding: 12px 14px; font-family: 'League Spartan', sans-serif; font-size: 0.72rem; color: #555; line-height: 1.7; }

/* ── Review panel ── */
.review-panel {
  background: #fff; border: 1.5px solid #ebebeb; border-radius: 10px;
  padding: 20px 24px; margin: 12px 0;
}
.review-panel-title {
  font-family: 'League Spartan', sans-serif; font-size: 0.62rem; font-weight: 800;
  letter-spacing: 0.14em; text-transform: uppercase; color: #444; margin-bottom: 4px;
}
.review-panel-sub {
  font-family: 'League Spartan', sans-serif; font-size: 0.78rem; color: #111; margin-bottom: 16px;
}
.review-note {
  margin: 10px 0 12px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  font-family: 'League Spartan', sans-serif;
  font-size: 0.76rem;
  color: #111;
}
.st-key-selected_queries_widget [data-baseweb="select"] > div,
.st-key-selected_queries_widget [data-baseweb="multi-select"],
.st-key-user_extra_keywords [data-baseweb="textarea"],
.st-key-reference_creators [data-baseweb="textarea"] {
  background: #fff !important;
  border: 1px solid #cfcfcf !important;
  border-radius: 6px !important;
  box-shadow: none !important;
}
.st-key-selected_queries_widget [data-baseweb="tag"] {
  background: #f7f7f7 !important;
  border: 1px solid #d5d5d5 !important;
  color: #111 !important;
}
.st-key-user_extra_keywords textarea,
.st-key-reference_creators textarea,
.st-key-selected_queries_widget input {
  color: #111 !important;
  background: #fff !important;
}
.st-key-selected_queries_widget label *,
.st-key-user_extra_keywords label *,
.st-key-reference_creators label * {
  color: #111 !important;
  opacity: 1 !important;
}
.st-key-user_extra_keywords textarea::placeholder,
.st-key-reference_creators textarea::placeholder {
  color: #444 !important;
  opacity: 1 !important;
}
.st-key-clear_review_btn button {
  color: #111 !important;
  background: #fff !important;
  border-color: #cfcfcf !important;
}

/* ── Material Icons font (prevents icon names from rendering as raw text) ── */
@font-face {
  font-family: 'Material Icons';
  font-style: normal;
  font-weight: 400;
  src: url(https://fonts.gstatic.com/s/materialicons/v142/flUhRq6tzZclQEJ-Vdg-IuiaDsNcIhQ8tQ.woff2) format('woff2');
}
.material-icons {
  font-family: 'Material Icons' !important;
  font-size: 18px !important;
  line-height: 1 !important;
  letter-spacing: 0 !important;
  text-transform: none !important;
  display: inline-block !important;
  white-space: nowrap !important;
  word-wrap: normal !important;
  direction: ltr !important;
  -webkit-font-feature-settings: 'liga' !important;
  font-feature-settings: 'liga' !important;
  -webkit-font-smoothing: antialiased !important;
}

/* ── Sidebar: remove top gap from hidden header ── */
section[data-testid="stSidebar"] > div:first-child {
  padding-top: 0 !important;
  margin-top: 0 !important;
}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlock"]:first-child {
  padding-top: 8px !important;
}

/* ── Number input stepper buttons: white, not black ── */
[data-testid="stNumberInput"] button {
  background: #fafafa !important;
  color: #555 !important;
  border: 1px solid #e0e0e0 !important;
  border-radius: 5px !important;
  min-height: 36px !important;
  min-width: 32px !important;
}
[data-testid="stNumberInput"] button:hover {
  background: #f0f0f0 !important;
  color: #111 !important;
  border-color: #aaa !important;
}
[data-testid="stNumberInput"] button svg {
  fill: #555 !important;
}
[data-testid="stNumberInput"] button:hover svg {
  fill: #111 !important;
}

/* ── Textarea: remove red error ring, use clean black focus ── */
section[data-testid="stSidebar"] [data-baseweb="textarea"],
section[data-testid="stSidebar"] [data-baseweb="base-input"] {
  border-color: #e8e8e8 !important;
  box-shadow: none !important;
}
section[data-testid="stSidebar"] [data-baseweb="textarea"]:focus-within,
section[data-testid="stSidebar"] [data-baseweb="base-input"]:focus-within {
  border-color: #111 !important;
  box-shadow: 0 0 0 2px rgba(0,0,0,0.07) !important;
}

/* ── Multiselect dropdown list: white bg, not dark ── */
[data-baseweb="popover"] > div,
[data-baseweb="menu"],
[role="listbox"] {
  background: #fff !important;
  border: 1.5px solid #e8e8e8 !important;
  border-radius: 8px !important;
  box-shadow: 0 4px 16px rgba(0,0,0,0.08) !important;
}
[data-baseweb="option"] {
  background: #fff !important;
  color: #111 !important;
  font-family: 'League Spartan', sans-serif !important;
  font-size: 0.8rem !important;
  font-weight: 500 !important;
}
[data-baseweb="option"]:hover,
[data-baseweb="option"][aria-selected="true"] {
  background: #f5f5f5 !important;
  color: #111 !important;
}

/* ── Ctrl+Enter hint below brief textarea ── */
.ctrl-hint {
  font-family: 'League Spartan', sans-serif;
  font-size: 0.66rem;
  color: #333;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-align: right;
  margin-top: 2px;
  margin-bottom: 8px;
  padding-right: 2px;
  text-transform: uppercase;
}

/* ── Toggle row: prevent label from overlapping ── */
section[data-testid="stSidebar"] [data-testid="stToggle"] {
  min-height: 36px !important;
}
section[data-testid="stSidebar"] [data-testid="stToggle"] label {
  color: #303030 !important;
  white-space: normal !important;
}

/* ── Search button: make it visually prominent ── */
.st-key-main_search_btn {
  margin-top: 10px;
}

/* ── Expander arrow icon: ensure Material Icons font renders ── */
[data-testid="stExpander"] summary svg,
[data-testid="stExpander"] summary [data-testid="stIconMaterial"] {
  display: none !important;
}
[data-testid="stExpander"] summary::after {
  content: "";
  width: 7px;
  height: 7px;
  border-right: 2px solid #111;
  border-bottom: 2px solid #111;
  margin-left: auto;
  transform: rotate(45deg);
  transition: transform .12s ease;
  flex-shrink: 0;
}
[data-testid="stExpander"] details[open] > summary::after {
  transform: rotate(225deg);
}

/* ── Sidebar inner section label spacing cleanup ── */
.sidebar-inner > div:first-child .sec-label {
  margin-top: 0 !important;
}

/* ── Column gap tighten in sidebar ── */
section[data-testid="stSidebar"] [data-testid="column"] {
  padding-left: 5px !important;
  padding-right: 5px !important;
}

/* High-contrast sidebar: no light text may sit on a white surface. */
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] label *,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] *,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] *,
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] *,
section[data-testid="stSidebar"] [data-testid="stCheckbox"] *,
section[data-testid="stSidebar"] [data-testid="stToggle"] *,
section[data-testid="stSidebar"] [data-testid="stSlider"] p,
section[data-testid="stSidebar"] details summary *,
section[data-testid="stSidebar"] [data-baseweb="select"] * {
  color: #111 !important;
  opacity: 1 !important;
}
section[data-testid="stSidebar"] input::placeholder,
section[data-testid="stSidebar"] textarea::placeholder {
  color: #111 !important;
  opacity: 1 !important;
}
section[data-testid="stSidebar"] [data-testid="stCheckbox"],
section[data-testid="stSidebar"] [data-testid="stToggle"],
section[data-testid="stSidebar"] [aria-disabled="true"] {
  opacity: 1 !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="primary"]:not(:disabled),
section[data-testid="stSidebar"] .stButton > button[kind="primary"]:not(:disabled) *,
section[data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-primary"]:not(:disabled),
section[data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-primary"]:not(:disabled) * {
  color: #fff !important;
}
</style>
""",
    unsafe_allow_html=True,
)

counts = backend_key_counts()
yt_total = len(env_keys("YOUTUBE_API_KEYS") or env_keys("YOUTUBE_API_KEY") or [])
gem_total = len(env_keys("GEMINI_API_KEYS") or env_keys("GEMINI_API_KEY") or [])
quota_html = "".join(
    f'<div class="quota-item"><span class="quota-label">S{i + 1}</span>'
    f'<div class="quota-bar"><div class="quota-bar-fill" style="width:0%"></div></div>'
    f'<span class="quota-pct">—</span></div>'
    for i in range(min(yt_total, 4))
) or '<span class="quota-pct" style="color:#444">No YT keys</span>'
gem_html = "".join(
    f'<div class="quota-item"><span class="quota-label">G{i + 1}</span>'
    f'<div class="quota-bar"><div class="quota-bar-fill" style="width:0%"></div></div>'
    f'<span class="quota-pct">—</span></div>'
    for i in range(min(gem_total, 3))
)
st.markdown(
    f"""
<div id="ciq-topbar-anchor">
<div id="ciq-topbar">
  <div class="logo-wrap">
    <span class="logo-bar"><span class="logo-bar-bg">BAR</span>CODE</span>
    <span class="logo-divider">|</span>
    <span class="logo-ykone">Ykone</span>
    <span class="logo-product-name">Influencer Radar</span>
  </div>
  <div class="quota-wrap">
    <span class="quota-label">API Quota</span>
    {quota_html}{gem_html}
  </div>
  <div class="topbar-right">
    <a href="?reset=1" class="reset-link">&#8635; Reset</a>
  </div>
</div>
</div>
""",
    unsafe_allow_html=True,
)

filter_version = int(st.session_state.get("ai_filter_version", 0))

with st.sidebar:
    st.markdown('<div class="ai-panel-title">AI Assist</div>', unsafe_allow_html=True)

    brief = st.text_area(
        "",
        placeholder="Explain your campaign and what type of creators you want...",
        height=90,
        key="brief_input",
        label_visibility="collapsed",
    )
    st.markdown('<div class="ctrl-hint">Ctrl + Enter to apply</div>', unsafe_allow_html=True)

    with st.expander("Advanced API key override", expanded=False):
        override_gemini = st.text_area("Gemini keys", height=60, key="ovr_gem")
        override_apify_discovery = st.text_area("Apify discovery keys", height=60, key="ovr_apd")
        override_apify_profile = st.text_area("Apify profile keys", height=60, key="ovr_app")
        override_apify_ig_related = st.text_area("Instagram graph actor keys", height=60, key="ovr_igr")
        override_youtube = st.text_area("YouTube keys", height=60, key="ovr_yt")
        override_scrapingbee = st.text_area("ScrapingBee keys", height=60, key="ovr_sb")

    keys = get_key_config({
        "gemini": st.session_state.get("ovr_gem", ""),
        "apify_discovery": st.session_state.get("ovr_apd", ""),
        "apify_profile": st.session_state.get("ovr_app", ""),
        "apify_ig_related": st.session_state.get("ovr_igr", ""),
        "youtube": st.session_state.get("ovr_yt", ""),
        "scrapingbee": st.session_state.get("ovr_sb", ""),
    })

    analyze_ready = bool(brief and keys["gemini"])
    get_kw_btn = st.button(
        "Get Keywords",
        disabled=not analyze_ready,
        use_container_width=True,
        key="get_keywords_btn",
        type="primary",
    )

    quick_search_btn = False
    if st.session_state.analysis_result:
        result = st.session_state.analysis_result
        intent = result.get("intent", {})
        conf = str(intent.get("confidence", "medium")).upper()
        badge_cls = {"HIGH": "conf-high", "MEDIUM": "conf-mid", "LOW": "conf-low"}.get(conf, "conf-mid")
        gender_label = "Male" if intent.get("gender") == "M" else "Female" if intent.get("gender") == "F" else "Any"
        niche_label = str(intent.get("niche") or "creator")
        ai_min = fmt_num(intent.get("min_followers", 10000))
        ai_max = fmt_num(intent.get("max_followers", 500000))
        st.markdown(
            f"""
<div class="ai-confidence">
  <span class="{badge_cls}">Confidence: {html.escape(conf)}</span>
  <span style="color:#444;font-size:.78rem">{html.escape(niche_label)} / {html.escape(gender_label)}</span>
</div>
<div class="ai-suggest-row">AI suggests: <strong>{ai_min} - {ai_max}</strong> followers</div>
""",
            unsafe_allow_html=True,
        )
        yt_queries = result.get("yt_queries", [])
        if yt_queries:
            st.markdown('<div class="kw-section-label">YouTube Keywords</div>', unsafe_allow_html=True)
            st.markdown(
                "".join(
                    f'<span class="kw-chip">{html.escape(str(q)[:40])} <span class="plus">+</span></span>'
                    for q in yt_queries[:8]
                ),
                unsafe_allow_html=True,
            )
        hashtags = result.get("hashtags_final", [])
        if hashtags:
            st.markdown('<div class="kw-section-label">Instagram Hashtags</div>', unsafe_allow_html=True)
            st.markdown(
                "".join(
                    f'<span class="kw-chip">{html.escape(str(tag))} <span class="plus">+</span></span>'
                    for tag in hashtags[:12]
                ),
                unsafe_allow_html=True,
            )
        cross = result.get("ig_keywords", [])
        if cross:
            st.markdown('<div class="kw-section-label">Cross-Platform</div>', unsafe_allow_html=True)
            st.markdown(
                "".join(
                    f'<span class="kw-chip">{html.escape(str(k))} <span class="plus">+</span></span>'
                    for k in cross[:4]
                ),
                unsafe_allow_html=True,
            )
        quick_search_btn = st.button(
            "Search Creators",
            use_container_width=True,
            disabled=not bool(brief),
            key="quick_search_btn",
            type="primary",
        )

    st.markdown('<div class="sec-label"><span>Campaign Name <span style="color:#444;font-weight:400;text-transform:none">(track used creators)</span></span></div>', unsafe_allow_html=True)
    campaign_name = st.text_input("", placeholder="e.g. Meesho May 2026", key="campaign_name", label_visibility="collapsed")

    c1, c2 = st.columns([3, 2])
    with c1:
        block_repeats = st.toggle("Block repeats", value=True, key="block_repeats")
        allow_repeats = not block_repeats
    with c2:
        if st.button("History", key="hist_btn"):
            st.session_state["show_history"] = not st.session_state.get("show_history", False)
    if st.session_state.get("show_history"):
        stats = history_stats(campaign_scope(campaign_name, st.session_state.last_brief))
        st.caption(f"Used in this campaign: {stats.get('used', 0)}")
        if stats.get("used", 0) and st.button("Clear used history", key="clear_hist_btn"):
            cleared = clear_used_creators(campaign_scope(campaign_name, st.session_state.last_brief))
            st.session_state.history_notice = f"Cleared {cleared} used creators for this campaign."
            st.rerun()

    st.markdown('<div class="sec-label"><span>Keywords / Hashtags <span style="color:#444;font-weight:400;text-transform:none">(comma-separated)</span></span></div>', unsafe_allow_html=True)
    known_search_terms = st.text_input("", placeholder="Type keyword / #hashtag...", key="known_kw", label_visibility="collapsed")
    if known_search_terms:
        chips_added = "".join(
            f'<span class="kw-chip">{html.escape(t.strip())}</span>'
            for t in re.split(r"[,;]+", known_search_terms)
            if t.strip()
        )
        st.markdown(chips_added, unsafe_allow_html=True)
    st.button("Quick Suggest", key="quick_suggest", use_container_width=False)

    st.markdown('<div class="sec-label"><span>Location</span></div>', unsafe_allow_html=True)
    region = st.selectbox("Country", ["IN India", "US", "GB", "AU", "CA", "SG", "AE"], index=0, key="region_sel")
    region_code = region.split()[0]
    loc2, loc3 = st.columns(2)
    with loc2:
        state_input = st.text_input("State (opt)", placeholder="State", key="state_input")
    with loc3:
        city_input = st.text_input("City (opt)", placeholder="City", key="city_input")

    st.markdown('<div class="sec-label"><span>Audience Size</span></div>', unsafe_allow_html=True)
    sz1, sz2 = st.columns(2)
    with sz1:
        min_followers = st.number_input(
            "Min Subs",
            value=int(st.session_state.get("ai_suggested_min", 10000)),
            step=1000,
            format="%d",
            key=f"min_subs_{filter_version}",
        )
    with sz2:
        max_followers = st.number_input(
            "Max Subs",
            value=int(st.session_state.get("ai_suggested_max", 500000)),
            step=5000,
            format="%d",
            key=f"max_subs_{filter_version}",
        )
    results_per_yt_query = 50  # fixed default, no longer user-configurable

    st.markdown('<div class="sec-label"><span>Targeting</span></div>', unsafe_allow_html=True)
    t1, t2 = st.columns([1.05, 1])
    with t1:
        _gender_options = ["Auto", "Any", "Male only", "Female only"]
        _ai_gender = st.session_state.get("ai_suggested_gender", "Auto")
        _gender_idx = _gender_options.index(_ai_gender) if _ai_gender in _gender_options else 0
        gender_override = st.selectbox("Gender", _gender_options, index=_gender_idx, key=f"gender_sel_{filter_version}")
        gender_map = {"Auto": None, "Any": "ANY", "Male only": "M", "Female only": "F"}
    with t2:
        _ai_tier = st.session_state.get("ai_suggested_tier", "Auto")
        _tier_idx = CREATOR_TIER_OPTIONS.index(_ai_tier) if _ai_tier in CREATOR_TIER_OPTIONS else 0
        creator_tier_override = st.selectbox("Creator tier", CREATOR_TIER_OPTIONS, index=_tier_idx, key=f"tier_sel_{filter_version}")
    strict_mode = st.toggle("Relaxed matching", value=True, key="strictness_toggle")

    with st.expander("More options", expanded=False):
        exclude_terms_raw = st.text_area("Exclude brands/channels", height=60, placeholder="Garnier, Just For Men...", key="exclude_terms")
        allow_international = st.checkbox("Allow international creators", value=False, key="allow_intl")
        deep_yt_search = st.checkbox("YouTube deep search (page 2)", value=True, key="deep_yt")

    search_ready = bool(brief and st.session_state.analysis_result)
    bottom_search_btn = st.button(
        "Search Creators",
        use_container_width=True,
        disabled=not search_ready,
        key="main_search_btn",
        type="primary",
    )
    search_btn = quick_search_btn or bottom_search_btn

yt_tab, ig_tab = st.tabs(["YouTube", "Instagram"])
do_ig = True
do_yt = True

if st.session_state.history_notice:
    st.success(st.session_state.history_notice)
    st.session_state.history_notice = ""

if brief and not keys["gemini"]:
    st.warning("No Gemini keys configured. Set GEMINI_API_KEYS or use the advanced override.")

if get_kw_btn and brief:
    with st.spinner("Analyzing brief..."):
        ai = AIService(keys["gemini"], keys["apify_discovery"])
        result = ai.run_full_analysis(
            brief,
            verify_hashtags=st.session_state.get("verify_htag", True),
            user_search_terms=st.session_state.get("known_kw", ""),
            exclude_terms=st.session_state.get("exclude_terms", ""),
            progress_callback=lambda _message: None,
            platforms=["YouTube"],
        )
        intent = result.get("intent", {})
        if intent:
            st.session_state["ai_suggested_min"] = int(intent.get("min_followers") or 10000)
            st.session_state["ai_suggested_max"] = int(intent.get("max_followers") or 500000)
            _gmap = {"M": "Male only", "F": "Female only", "ANY": "Any"}
            st.session_state["ai_suggested_gender"] = _gmap.get(str(intent.get("gender") or "ANY").upper(), "Auto")
            st.session_state["ai_suggested_locations"] = intent.get("locations_list", []) or []
            _tier_map = {"nano": "Nano", "micro": "Micro", "mid": "Mid", "mid-tier": "Mid", "macro": "Macro", "any": "Any"}
            _ai_min = int(intent.get("min_followers") or 10000)
            _ai_max = int(intent.get("max_followers") or 500000)
            _exact_tier = next((label for label, bounds in CREATOR_TIER_RANGES.items() if bounds == (_ai_min, _ai_max)), None)
            if _exact_tier:
                st.session_state["ai_suggested_tier"] = _exact_tier
            elif re.search(r"\b\d+\s*[kKmM]?\s*(?:to|-)\s*\d+\s*[kKmM]?\b", brief or ""):
                st.session_state["ai_suggested_tier"] = "Custom range"
            else:
                st.session_state["ai_suggested_tier"] = _tier_map.get(
                    str(intent.get("creator_tier") or "any").lower().split()[0],
                    "Auto",
                )
            st.session_state["ai_filter_version"] = int(st.session_state.get("ai_filter_version", 0)) + 1
        st.session_state.analysis_result = result
        st.session_state["review_queries"] = [item.get("query", "") for item in result.get("yt_search_plan", []) if item.get("query")]
        st.session_state["review_hashtags"] = result.get("hashtags_final", [])
        st.session_state["review_brand_tags"] = result.get("brand_campaign_tags", [])
        st.session_state["review_trending_tags"] = result.get("trending_creator_tags", [])
        st.session_state["selected_queries_widget"] = list(st.session_state["review_queries"])
        tag_labels = (
            [f"{tag} [AI]" for tag in st.session_state["review_hashtags"]] +
            [f"{tag} [Brand]" for tag in st.session_state["review_brand_tags"]] +
            [f"{tag} [Trending]" for tag in st.session_state["review_trending_tags"]]
        )
        st.session_state["selected_hashtags_widget"] = tag_labels
        st.session_state["show_review_panel"] = True
        st.session_state.last_brief = brief
        st.session_state.last_platforms = ["YouTube", "Instagram"]
        st.session_state.search_complete = False
    st.rerun()

if st.session_state.get("show_review_panel"):
    with yt_tab:
        st.markdown("""
<div class="review-panel">
  <div class="review-panel-title">Review &amp; Edit Search Plan</div>
  <div class="review-panel-sub">Deselect anything you do not want to search. Add extra keywords or reference creators before pressing Search.</div>
</div>
""", unsafe_allow_html=True)

        current_queries = st.session_state.get("review_queries", [])
        if current_queries:
            st.multiselect(
                "YouTube search queries",
                options=current_queries,
                default=st.session_state.get("selected_queries_widget", current_queries),
                key="selected_queries_widget",
            )
        else:
            st.caption("No AI YouTube queries yet.")

        st.text_area(
            "Extra YouTube search keywords",
            key="user_extra_keywords",
            height=70,
            placeholder="men hair color review, grooming creator delhi",
        )
        st.text_area(
            "Reference creators for similar search",
            key="reference_creators",
            height=60,
            placeholder="https://youtube.com/@SomeCreator\n@AnotherCreator",
        )
        ai_locs = st.session_state.get("ai_suggested_locations", [])
        if ai_locs:
            st.markdown(
                f'<div class="review-note">AI detected locations: {html.escape(", ".join(str(loc) for loc in ai_locs))}</div>',
                unsafe_allow_html=True,
            )
        if st.button("Clear Review Panel", use_container_width=True, key="clear_review_btn"):
            st.session_state["show_review_panel"] = False
            st.session_state["review_queries"] = []
            st.session_state["review_hashtags"] = []
            st.session_state["review_brand_tags"] = []
            st.session_state["review_trending_tags"] = []
            st.rerun()

if search_btn and st.session_state.analysis_result:
    result = st.session_state.analysis_result
    intent = dict(result.get("intent", {}))
    effective_gender = gender_map.get(gender_override) or intent.get("gender", "ANY")
    if effective_gender is None:
        effective_gender = intent.get("gender", "ANY")
    if creator_tier_override in CREATOR_TIER_RANGES:
        effective_min, effective_max = CREATOR_TIER_RANGES[creator_tier_override]
    else:
        effective_min = int(min_followers)
        effective_max = int(max_followers)

    history_campaign = campaign_scope(campaign_name, brief)
    _locs_list = intent.get("locations_list") or []
    if _locs_list:
        location_hints = [str(loc).lower().strip() for loc in _locs_list if loc]
        if intent.get("language") and str(intent["language"]).lower() not in location_hints:
            location_hints.append(str(intent["language"]).lower())
    else:
        location_hints = [str(intent.get(k)) for k in ("city", "state", "language") if intent.get(k)]
    for manual_location in (state_input, city_input):
        clean_location = str(manual_location or "").strip().lower()
        if clean_location and clean_location not in location_hints:
            location_hints.append(clean_location)
    if region_code == "IN" and "india" not in location_hints:
        location_hints.append("india")

    lang_code_map = {
        "kannada": "kn", "tamil": "ta", "telugu": "te", "malayalam": "ml",
        "marathi": "mr", "punjabi": "pa", "gujarati": "gu", "bengali": "bn",
        "hindi": "hi", "assamese": "as",
    }
    lang_code = lang_code_map.get(str(intent.get("language") or "").lower())

    logs: list[str] = []
    with yt_tab:
        log_box_yt = st.empty()
        progress_yt = st.progress(0)
    with ig_tab:
        log_box_ig = st.empty()

    def add_log(message: str) -> None:
        safe = html.escape(str(message))
        logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {safe}")
        log_box_yt.markdown(
            '<div class="soft-panel" style="max-height:200px;overflow:auto">'
            + "<br>".join(logs[-18:]) + "</div>",
            unsafe_allow_html=True,
        )

    ig_results: list[dict] = []
    yt_results: list[dict] = []
    ai_svc = AIService(keys["gemini"], keys["apify_discovery"]) if keys["gemini"] else None

    base_plan = result.get("yt_search_plan") or yt_plan_from_queries(result.get("yt_queries", []), source="legacy")
    selected_queries = st.session_state.get("selected_queries_widget") or [item.get("query", "") for item in base_plan]
    selected_query_set = {str(query).strip().lower() for query in selected_queries if str(query).strip()}
    yt_plan = [item for item in base_plan if str(item.get("query", "")).strip().lower() in selected_query_set]

    user_extra_terms = normalize_user_search_terms(st.session_state.get("user_extra_keywords", ""))
    for term in user_extra_terms:
        if term.startswith("#"):
            query = term
        else:
            query = term
        if query and query.lower() not in selected_query_set:
            yt_plan.append({
                "query": query,
                "search_type": "video",
                "source": "user_extra",
                "intent_terms": [str(intent.get("niche", "")), query],
                "negative_terms": [],
                "paginate": True,
            })
            selected_query_set.add(query.lower())

    selected_tag_labels = st.session_state.get("selected_hashtags_widget", [])
    selected_tags = [str(label).split(" [", 1)[0] for label in selected_tag_labels if str(label).strip()]
    selected_tags = list(dict.fromkeys(selected_tags))
    for tag in selected_tags:
        clean_tag = "#" + re.sub(r"[^a-zA-Z0-9]", "", str(tag).lstrip("#")).lower()
        if len(clean_tag) > 2 and clean_tag.lower() not in selected_query_set:
            yt_plan.append({
                "query": clean_tag,
                "search_type": "video",
                "source": "review_hashtag",
                "intent_terms": [clean_tag.lstrip("#"), str(intent.get("niche", ""))],
                "negative_terms": [],
                "paginate": False,
            })
            selected_query_set.add(clean_tag.lower())

    ref_creator_text = st.session_state.get("reference_creators", "")
    ref_creators = [line.strip() for line in re.split(r"[\n,;]+", ref_creator_text) if line.strip()]
    if ref_creators and ai_svc:
        add_log(f"Generating similar-creator queries for {len(ref_creators)} reference creator(s)...")
        similar_plan = ai_svc.generate_similar_creator_queries(ref_creators, intent, brief)
        if similar_plan:
            yt_plan.extend(similar_plan)
            add_log(f"Added {len(similar_plan)} similar-creator queries")

    if yt_plan and (keys["youtube"] or keys["scrapingbee"]):
        progress_yt.progress(10)
        add_log(f"YouTube: running {len(yt_plan)} queries...")
        try:
            async def _run_all_yt() -> tuple[list[dict], list[dict]]:
                yt_task = None
                if keys["youtube"]:
                    yt_task = run_yt_search(
                        api_keys=keys["youtube"],
                        queries=[],
                        min_subs=effective_min,
                        max_subs=effective_max,
                        gender_filter=effective_gender,
                        location_hints=location_hints,
                        lang_hints=[intent.get("language", "")] if intent.get("language") else [],
                        lang_code=lang_code,
                        region=region_code,
                        results_per_query=int(results_per_yt_query),
                        progress_callback=add_log,
                        search_plan=yt_plan,
                        exclude_terms=result.get("exclude_terms") or normalize_user_search_terms(st.session_state.get("exclude_terms", "")),
                        allow_international=st.session_state.get("allow_intl", False),
                        deep_search=st.session_state.get("deep_yt", True),
                    )
                sb_task = None
                if keys["scrapingbee"]:
                    sb_task = run_scrapingbee_search(
                        api_keys=keys["scrapingbee"],
                        search_plan=yt_plan,
                        min_subs=effective_min,
                        max_subs=effective_max,
                        progress_callback=add_log,
                    )
                if yt_task and sb_task:
                    yt_api_results, sb_results = await asyncio.gather(yt_task, sb_task)
                    return yt_api_results, sb_results
                if yt_task:
                    return await yt_task, []
                if sb_task:
                    return [], await sb_task
                return [], []

            yt_api_results, sb_results = run_async(_run_all_yt())
            seen_cids = {
                row.get("channel_id", "")
                for row in yt_api_results
                if row.get("channel_id") and not str(row.get("channel_id", "")).startswith("sb_")
            }
            seen_names = {
                str(row.get("channel_name", "")).lower()
                for row in yt_api_results
                if row.get("channel_name")
            }
            sb_unique: list[dict] = []
            for row in sb_results:
                cid = str(row.get("channel_id", ""))
                cname = str(row.get("channel_name", "")).lower()
                if cid and cid in seen_cids:
                    continue
                if cname and cname in seen_names:
                    continue
                seen_cids.add(cid)
                seen_names.add(cname)
                sb_unique.append(row)
            yt_results = yt_api_results + sb_unique
            if sb_unique:
                add_log(f"Merged: {len(yt_api_results)} YT API + {len(sb_unique)} unique ScrapingBee = {len(yt_results)} total")
            yt_results, skipped = filter_used_creators(yt_results, history_campaign, allow_repeats)
            if skipped:
                add_log(f"Skipped {len(skipped)} previously used creators")
            progress_yt.progress(75)
            if yt_results and ai_svc:
                add_log(f"Gemini: ranking {len(yt_results)} YouTube candidates...")
                scoring_intent = dict(intent)
                scoring_intent["_brief"] = brief
                yt_results = ai_svc.score_youtube_creators_batch(yt_results, scoring_intent)
            progress_yt.progress(100)
            add_log(
                f"Done: {sum(1 for c in yt_results if c.get('match_status') == 'high')} high, "
                f"{sum(1 for c in yt_results if c.get('match_status') in ('review', 'mid'))} mid, "
                f"{sum(1 for c in yt_results if c.get('match_status') in ('rejected', 'low'))} low"
            )
        except Exception as exc:
            add_log(f"YouTube error: {exc}")
    elif yt_plan:
        with yt_tab:
            st.warning("YouTube skipped: missing YOUTUBE_API_KEYS and SCRAPINGBEE_KEYS")

    ig_debug: dict = {"reels": {}, "youtube_graph": {}}
    ig_reels_results: list[dict] = []
    ig_graph_results: list[dict] = []
    ig_content_keys = first_non_empty(keys["apify_discovery"], keys["apify_ig_related"])
    ig_profile_keys = first_non_empty(keys["apify_ig_related"], keys["apify_profile"], keys["apify_discovery"])

    if ig_content_keys and ig_profile_keys:
        try:
            ig_keyword_terms, ig_hashtag_terms = build_instagram_reels_terms(
                result,
                intent,
                brief,
                user_extra_terms,
                ai_svc,
            )
            add_log(
                "Instagram reels: "
                f"{len(ig_keyword_terms)} keyword search(es), {len(ig_hashtag_terms)} hashtag search(es)"
            )
            ig_reels_results = run_async(run_ig_reels_discovery(
                api_key=ig_content_keys,
                profile_api_keys=ig_profile_keys,
                keyword_terms=ig_keyword_terms,
                hashtag_terms=ig_hashtag_terms,
                min_followers=effective_min,
                max_followers=effective_max,
                location_hints=location_hints,
                gender_filter=effective_gender,
                niche=intent.get("niche", ""),
                posts_per_term=25,
                include_rejected=False,
                progress_callback=add_log,
                debug_state=ig_debug["reels"],
            ))
        except Exception as exc:
            with ig_tab:
                log_box_ig.error(f"Instagram reels error: {exc}")
    else:
        add_log("Instagram reels skipped: missing Apify discovery/profile keys")

    if keys["apify_ig_related"]:
        try:
            ig_graph_results = run_async(run_ig_related_search_from_youtube(
                yt_creators=yt_results,
                profile_api_keys=keys["apify_ig_related"],
                min_followers=effective_min,
                max_followers=effective_max,
                location_hints=location_hints,
                gender_filter=effective_gender,
                niche=intent.get("niche", ""),
                related_depth=1,
                max_related_per_profile=35,
                max_related_per_hop=400,
                include_rejected=False,
                progress_callback=add_log,
                debug_state=ig_debug["youtube_graph"],
            ))
        except Exception as exc:
            with ig_tab:
                log_box_ig.error(f"Instagram graph error: {exc}")
    else:
        add_log("Instagram graph skipped: missing APIFY_IG_RELATED_KEYS")

    ig_results = merge_instagram_creators(ig_reels_results, ig_graph_results)
    st.session_state.ig_debug = ig_debug
    result["ig_debug"] = ig_debug
    if ig_results:
        add_log(f"Instagram merged: {len(ig_results)} creator profile(s) before history/AI ranking")
        ig_results, _ = filter_used_creators(ig_results, history_campaign, allow_repeats)
        if ig_results and ai_svc:
            add_log(f"Gemini: ranking {len(ig_results)} Instagram candidates...")
            scoring_intent = dict(intent)
            scoring_intent["_brief"] = brief
            ig_results = ai_svc.score_creators_batch(ig_results, scoring_intent)

    st.session_state.ig_results = ig_results
    st.session_state.yt_results = yt_results
    st.session_state.analysis_result = result
    st.session_state.search_complete = True
    st.rerun()

ig_results = st.session_state.ig_results
yt_results = st.session_state.yt_results
display_campaign = campaign_scope(campaign_name, brief or st.session_state.last_brief)
yt_display = annotate_used_creators(yt_results, display_campaign)
ig_display = annotate_used_creators(ig_results, display_campaign)
if not allow_repeats:
    yt_display = [c for c in yt_display if not c.get("_history_used")]
    ig_display = [c for c in ig_display if not c.get("_history_used")]

def sort_key(c):
    score = c.get("ai_score")
    try:
        return float(score) if score is not None else 0
    except Exception:
        return 0

def _render_results_panel(items: list[dict], label: str) -> None:
    if not items:
        if st.session_state.search_complete and label == "Instagram":
            st.markdown(
                """
<div class="empty-state">
  <h3>No Instagram creator profiles returned</h3>
  <p>Instagram discovery runs from the Instagram profiles found in completed YouTube results.<br>Check the graph actor key status in the activity log, then run Search again.</p>
</div>
""",
                unsafe_allow_html=True,
            )
            return
        if st.session_state.search_complete:
            st.markdown(
                f'<div class="empty-state"><h3>No {html.escape(label)} creators returned</h3></div>',
                unsafe_allow_html=True,
            )
            return
        st.markdown(
            f"""
<div class="empty-state">
  <h3>Find Real Influencers</h3>
  <p>Explain your campaign, add any must-have keywords, and search.<br>It will find matching YouTube and Instagram creators.</p>
  <div class="empty-tip">Mark Used = avoid repeats in the same campaign</div>
  <div class="empty-tip">Download Excel for your final shortlist</div>
</div>
""",
            unsafe_allow_html=True,
        )
        return

    sorted_items = sorted(items, key=sort_key, reverse=True)
    total = len(sorted_items)
    with_email = sum(1 for c in sorted_items if c.get("email"))
    avg_score = sum(sort_key(c) for c in sorted_items) / total if total else 0
    st.markdown(
        f"""
<div class="metric-row">
  <div class="metric-box"><div class="num">{total}</div><div class="lbl">Creators Found</div></div>
  <div class="metric-box"><div class="num">{with_email}</div><div class="lbl">With Email</div></div>
  <div class="metric-box"><div class="num">{avg_score:.1f}</div><div class="lbl">Avg AI Score</div></div>
</div>
""",
        unsafe_allow_html=True,
    )
    df = creators_to_df(sorted_items)
    if not df.empty:
        st.download_button(
            "Download Excel",
            data=df_to_excel(df),
            file_name=f"creators_{label.lower()}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"dl_{label}",
        )
    st.markdown(f'<div class="results-header">{html.escape(label)} Creators - sorted by AI Score</div>', unsafe_allow_html=True)
    render_creator_table(sorted_items, height=680)

with yt_tab:
    st.markdown('<div class="main-area">', unsafe_allow_html=True)
    _render_results_panel(yt_display, "YouTube")
    st.markdown('</div>', unsafe_allow_html=True)

with ig_tab:
    st.markdown('<div class="main-area">', unsafe_allow_html=True)
    _render_results_panel(ig_display, "Instagram")
    st.markdown('</div>', unsafe_allow_html=True)

st.stop()

with st.sidebar:
    st.markdown("## Influencer Finder Pro")
    counts = backend_key_counts()
    st.markdown("### Backend Keys")
    st.caption(
        f"Gemini: {counts['gemini']} | Apify discovery: {counts['apify_discovery']} | "
        f"Apify profile: {counts['apify_profile']} | YouTube: {counts['youtube']}"
    )

    with st.expander("Advanced API key override"):
        override_gemini = st.text_area("Gemini keys", height=70)
        override_apify_discovery = st.text_area("Apify discovery keys", height=70)
        override_apify_profile = st.text_area("Apify profile keys", height=70)
        override_youtube = st.text_area("YouTube keys", height=70)

    keys = get_key_config({
        "gemini": override_gemini,
        "apify_discovery": override_apify_discovery,
        "apify_profile": override_apify_profile,
        "youtube": override_youtube,
    })

    st.markdown("### Search Filters")
    platform_choice = st.multiselect("Platforms", ["Instagram", "YouTube"], default=["Instagram", "YouTube"])
    col_a, col_b = st.columns(2)
    with col_a:
        min_followers = st.number_input(
            "Min followers/subscribers",
            value=int(st.session_state.get("ai_suggested_min", 10000)),
            step=1000,
            format="%d",
        )
    with col_b:
        max_followers = st.number_input(
            "Max followers/subscribers",
            value=int(st.session_state.get("ai_suggested_max", 500000)),
            step=5000,
            format="%d",
        )

    _gender_options = ["Auto", "Any", "Male only", "Female only"]
    _ai_gender = st.session_state.get("ai_suggested_gender", "Auto")
    _gender_idx = _gender_options.index(_ai_gender) if _ai_gender in _gender_options else 0
    gender_override = st.selectbox("Gender override", _gender_options, index=_gender_idx)
    gender_map = {"Auto": None, "Any": "ANY", "Male only": "M", "Female only": "F"}
    _ai_tier = st.session_state.get("ai_suggested_tier", "Auto")
    _tier_idx = CREATOR_TIER_OPTIONS.index(_ai_tier) if _ai_tier in CREATOR_TIER_OPTIONS else 0
    creator_tier_override = st.selectbox(
        "Creator tier",
        CREATOR_TIER_OPTIONS,
        index=_tier_idx,
        key=f"creator_tier_override_{st.session_state.get('ai_filter_version', 0)}",
    )
    region = st.selectbox("YouTube region", ["IN", "US", "GB", "AU", "CA", "SG", "AE"], index=0)

    st.markdown("### Creator History")
    campaign_name = st.text_input(
        "Campaign name",
        placeholder="Optional, used for repeat blocking",
        help="Creators marked as used are blocked only inside this campaign scope. If blank, the brief text is used.",
    )
    allow_repeats = st.checkbox(
        "Allow repeated creators",
        value=False,
        help="When off, creators marked as used in this campaign are skipped from new results.",
    )
    current_history_scope = campaign_scope(campaign_name, st.session_state.last_brief)
    stats = history_stats(current_history_scope)
    st.caption(f"Used in this campaign: {stats.get('used', 0)}")
    if stats.get("used", 0):
        if st.button("Clear used history for campaign"):
            cleared = clear_used_creators(current_history_scope)
            st.session_state.history_notice = f"Cleared {cleared} used creators for this campaign."
            st.rerun()

    st.markdown("### Advanced")
    known_search_terms = st.text_area(
        "Known hashtags / search phrases",
        height=80,
        placeholder="#haircolor, #mensgrooming, Mumbai male grooming",
    )
    exclude_terms_raw = st.text_area(
        "Exclude brands/channels",
        height=70,
        placeholder="Garnier Men India, Just For Men, SIMPLER Hair Color",
    )
    allow_international = st.checkbox("Allow international creators", value=False,
                                       help="When on, channels from non-IN countries are kept as Mid instead of filtered out")
    posts_per_tag = st.slider("Instagram rows per hashtag", 10, 30, 30, step=5)
    results_per_yt_query = st.slider("YouTube results per query", 10, 50, 50, step=10)
    deep_yt_search = st.checkbox("YouTube deep search (page 2)", value=True,
                                  help="Fetches a second page of results for video queries; doubles candidates, uses ~2x quota")
    verify_hashtags = st.checkbox("Verify hashtag counts with Apify analytics", value=True)


st.title("Influencer Finder Pro")
st.caption("Platform-aware creator discovery: Instagram hashtag search + YouTube deep search. Keys from .env.")

brief = st.text_area(
    "Campaign brief",
    placeholder='Example: "Find male skincare creators in India, 5K-50K followers, Hindi or English content"',
    height=110,
)

do_ig = "Instagram" in platform_choice
do_yt = "YouTube" in platform_choice

# Determine if analysis result is still valid for current platform selection
analysis = st.session_state.analysis_result
hashtags_ready = bool(analysis and analysis.get("hashtags_final"))
yt_plan_ready = bool(analysis and (analysis.get("yt_search_plan") or analysis.get("yt_queries")))

ig_search_ready = do_ig and bool(keys["apify_discovery"]) and bool(keys["apify_profile"]) and hashtags_ready
yt_search_ready = do_yt and bool(keys["youtube"]) and yt_plan_ready

analyze_ready = bool(brief and keys["gemini"])
search_ready = bool(brief and analysis and (ig_search_ready or yt_search_ready))

col_analyze, col_search, col_clear = st.columns([1, 1, 4])
with col_analyze:
    analyze_btn = st.button("Analyze Brief", disabled=not analyze_ready)
with col_search:
    search_btn = st.button("Start Search", disabled=not search_ready)
with col_clear:
    if st.button("Clear Results"):
        st.session_state.analysis_result = None
        st.session_state.ig_results = []
        st.session_state.yt_results = []
        st.session_state.ig_debug = {}
        st.session_state.search_complete = False
        st.rerun()

if brief and not keys["gemini"]:
    st.warning("No Gemini keys configured. Set GEMINI_API_KEYS or use the advanced override.")

if not platform_choice:
    st.warning("Select at least one platform (Instagram or YouTube) in the sidebar.")

if st.session_state.history_notice:
    st.success(st.session_state.history_notice)
    st.session_state.history_notice = ""

if analyze_btn:
    analysis_logs: list[str] = []
    analysis_box = st.empty()

    def add_analysis_log(message: str) -> None:
        safe = html.escape(str(message))
        analysis_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {safe}")
        analysis_box.markdown('<div class="soft-panel muted">' + "<br>".join(analysis_logs[-18:]) + "</div>", unsafe_allow_html=True)

    with st.spinner("Analyzing brief and planning creator search packs..."):
        ai = AIService(keys["gemini"], keys["apify_discovery"])
        result = ai.run_full_analysis(
            brief,
            verify_hashtags=verify_hashtags,
            user_search_terms=known_search_terms,
            exclude_terms=exclude_terms_raw,
            progress_callback=add_analysis_log,
            platforms=platform_choice,
        )
        intent = result.get("intent", {})
        if intent:
            st.session_state["ai_suggested_min"] = int(intent.get("min_followers") or 10000)
            st.session_state["ai_suggested_max"] = int(intent.get("max_followers") or 500000)
            _gmap = {"M": "Male only", "F": "Female only", "ANY": "Any"}
            st.session_state["ai_suggested_gender"] = _gmap.get(
                str(intent.get("gender") or "ANY").upper(),
                "Auto",
            )
            _tier_map = {
                "nano": "Nano",
                "micro": "Micro",
                "mid": "Mid",
                "mid-tier": "Mid",
                "macro": "Macro",
                "any": "Any",
            }
            _ai_min = int(intent.get("min_followers") or 10000)
            _ai_max = int(intent.get("max_followers") or 500000)
            _exact_tier = next(
                (label for label, bounds in CREATOR_TIER_RANGES.items() if bounds == (_ai_min, _ai_max)),
                None,
            )
            if _exact_tier:
                st.session_state["ai_suggested_tier"] = _exact_tier
            elif re.search(r"\b\d+\s*[kKmM]?\s*(?:to|-)\s*\d+\s*[kKmM]?\b", brief or ""):
                st.session_state["ai_suggested_tier"] = "Custom range"
            else:
                st.session_state["ai_suggested_tier"] = _tier_map.get(
                    str(intent.get("creator_tier") or "any").lower().split()[0],
                    "Auto",
                )
            st.session_state["ai_filter_version"] = int(st.session_state.get("ai_filter_version", 0)) + 1
        st.session_state.analysis_result = result
        st.session_state.last_brief = brief
        st.session_state.last_platforms = list(platform_choice)
        st.session_state.search_complete = False
    st.rerun()


if st.session_state.analysis_result:
    result = st.session_state.analysis_result
    intent = result.get("intent", {})

    st.markdown('<div class="section-title">Campaign Brief Analysis</div>', unsafe_allow_html=True)
    badges = []
    for key in ("niche", "secondary_niche", "city", "state", "language", "creator_tier", "confidence"):
        if intent.get(key):
            badges.append(chip(f"{key}: {intent[key]}"))
    if intent.get("gender_mode"):
        badges.append(chip("gender mode: " + str(intent["gender_mode"]).replace("_", " ")))
    if intent.get("gender") and intent.get("gender") != "ANY":
        badges.append(chip("gender: " + ("male" if intent["gender"] == "M" else "female")))
    st.markdown("".join(badges), unsafe_allow_html=True)
    if intent.get("reasoning"):
        st.caption(intent["reasoning"])
    st.caption(
        f"Follower range: {fmt_num(intent.get('min_followers', min_followers))} - "
        f"{fmt_num(intent.get('max_followers', max_followers))}"
    )

    # ── Platform-aware analysis display ───────────────────────────────────────
    show_ig_section = do_ig
    show_yt_section = do_yt

    if show_ig_section and show_yt_section:
        col_tags, col_queries = st.columns(2)
    elif show_ig_section:
        col_tags = st.container()
        col_queries = None
    elif show_yt_section:
        col_tags = None
        col_queries = st.container()
    else:
        col_tags = col_queries = None

    if show_ig_section and col_tags is not None:
        with col_tags:
            show_hashtag_plan(result)
            st.markdown('<div class="section-title">Instagram Discovery Phrases</div>', unsafe_allow_html=True)
            for i, query in enumerate(result.get("ig_keywords", [])[:12], 1):
                st.markdown(f"{i}. `{query}`")

    if show_yt_section and col_queries is not None:
        with col_queries:
            st.markdown('<div class="section-title">YouTube Queries</div>', unsafe_allow_html=True)
            yt_plan = result.get("yt_search_plan") or yt_plan_from_queries(result.get("yt_queries", []), source="legacy")
            for i, item in enumerate(yt_plan, 1):
                query = item.get("query", "")
                source = item.get("source", "")
                stype = item.get("search_type", "video")
                source_label = f"{stype} | {source}"
                st.markdown(f"{i}. `{query}` <span class=\"muted\">{html.escape(source_label)}</span>", unsafe_allow_html=True)

    with st.expander("Edit hashtags and queries"):
        if show_ig_section:
            edited_tags = st.text_area("Instagram hashtags, one per line", value="\n".join(result.get("hashtags_final", [])), height=140)
            edited_ig_phrases = st.text_area("Instagram discovery phrases, one per line", value="\n".join(result.get("ig_keywords", [])), height=100)
        if show_yt_section:
            edited_yt = st.text_area("YouTube queries, one per line", value="\n".join(result.get("yt_queries", [])), height=140)
        if st.button("Save edits"):
            if show_ig_section:
                result["hashtags_final"] = [line.strip() for line in edited_tags.splitlines() if line.strip()]
                result["ig_keywords"] = [line.strip() for line in edited_ig_phrases.splitlines() if line.strip()]
            if show_yt_section:
                result["yt_queries"] = [line.strip() for line in edited_yt.splitlines() if line.strip()]
                result["yt_search_plan"] = yt_plan_from_queries(result["yt_queries"], source="user")
            st.session_state.analysis_result = result
            st.rerun()


if search_btn and st.session_state.analysis_result:
    result = st.session_state.analysis_result
    intent = dict(result.get("intent", {}))
    effective_gender = gender_map.get(gender_override) or intent.get("gender", "ANY")
    if effective_gender is None:
        effective_gender = intent.get("gender", "ANY")
    if creator_tier_override in CREATOR_TIER_RANGES:
        effective_min, effective_max = CREATOR_TIER_RANGES[creator_tier_override]
    else:
        effective_min = int(min_followers)
        effective_max = int(max_followers)
    history_campaign = campaign_scope(campaign_name, brief)
    _locs_list = intent.get("locations_list") or []
    if _locs_list:
        location_hints = [str(loc).lower().strip() for loc in _locs_list if loc]
        if intent.get("language") and str(intent["language"]).lower() not in location_hints:
            location_hints.append(str(intent["language"]).lower())
    else:
        location_hints = [str(intent.get(k)) for k in ("city", "state", "language") if intent.get(k)]
    lang_code_map = {
        "kannada": "kn", "tamil": "ta", "telugu": "te", "malayalam": "ml",
        "marathi": "mr", "punjabi": "pa", "gujarati": "gu", "bengali": "bn",
        "hindi": "hi", "assamese": "as",
    }
    lang_code = lang_code_map.get(str(intent.get("language") or "").lower())

    logs: list[str] = []
    log_box = st.empty()
    progress = st.progress(0)

    def add_log(message: str) -> None:
        safe = html.escape(str(message))
        logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {safe}")
        log_box.markdown('<div class="soft-panel muted">' + "<br>".join(logs[-22:]) + "</div>", unsafe_allow_html=True)

    ig_results: list[dict] = []
    yt_results: list[dict] = []

    # ── Instagram search ───────────────────────────────────────────────────────
    if do_ig and result.get("hashtags_final"):
        if not (keys["apify_discovery"] and keys["apify_profile"]):
            add_log("Instagram skipped: missing Apify discovery/profile keys")
        else:
            progress.progress(10)
            add_log(f"Instagram: scraping {len(result['hashtags_final'])} verified hashtags")
            ig_debug: dict = {}
            try:
                ig_results = run_async(run_ig_search(
                    api_key=keys["apify_discovery"],
                    profile_api_keys=keys["apify_profile"],
                    hashtags=result["hashtags_final"],
                    min_followers=effective_min,
                    max_followers=effective_max,
                    location_hints=location_hints,
                    posts_per_tag=posts_per_tag,
                    gender_filter=effective_gender,
                    niche=intent.get("niche", ""),
                    progress_callback=add_log,
                    debug_state=ig_debug,
                ))
                ig_results, skipped_used = filter_used_creators(ig_results, history_campaign, allow_repeats)
                if skipped_used:
                    add_log(f"Creator history: skipped {len(skipped_used)} previously used Instagram creators")
                elif allow_repeats and ig_results:
                    used_count = sum(1 for c in ig_results if c.get("_history_used"))
                    if used_count:
                        add_log(f"Creator history: included {used_count} previously used Instagram creators")
                st.session_state.ig_debug = ig_debug
                result["ig_debug"] = ig_debug
                progress.progress(45)
                if ig_results and keys["gemini"]:
                    add_log(f"Gemini: ranking {len(ig_results)} Instagram candidates")
                    scorer = AIService(keys["gemini"], keys["apify_discovery"])
                    scoring_intent = dict(intent)
                    scoring_intent["_brief"] = brief
                    ig_results = scorer.score_creators_batch(ig_results, scoring_intent)
                add_log(
                    "Instagram done: "
                    f"{sum(1 for c in ig_results if c.get('match_status') == 'high')} high, "
                    f"{sum(1 for c in ig_results if c.get('match_status') in ('review', 'mid'))} mid, "
                    f"{sum(1 for c in ig_results if c.get('match_status') in ('rejected', 'low'))} low"
                )
            except Exception as exc:
                add_log(f"Instagram error: {exc}")
    elif do_ig:
        add_log("Instagram: no hashtags from analysis — run Analyze Brief first or add known hashtags")

    # ── YouTube search ─────────────────────────────────────────────────────────
    yt_plan = result.get("yt_search_plan") or yt_plan_from_queries(result.get("yt_queries", []), source="legacy")
    if do_yt and yt_plan:
        if not keys["youtube"]:
            add_log("YouTube skipped: missing YOUTUBE_API_KEYS")
        else:
            progress.progress(60)
            video_count = sum(1 for item in yt_plan if item.get("search_type") == "video")
            channel_count = sum(1 for item in yt_plan if item.get("search_type") == "channel")
            hashtag_count = sum(1 for item in yt_plan if item.get("source") == "hashtag")
            add_log(f"YouTube: {video_count} video + {channel_count} channel + {hashtag_count} hashtag queries")
            add_log(f"YouTube deep search: {'enabled (page 2)' if deep_yt_search else 'disabled'}")
            try:
                yt_results = run_async(run_yt_search(
                    api_keys=keys["youtube"],
                    queries=result.get("yt_queries", []),
                    min_subs=effective_min,
                    max_subs=effective_max,
                    gender_filter=effective_gender,
                    location_hints=location_hints,
                    lang_hints=[intent.get("language", "")] if intent.get("language") else [],
                    lang_code=lang_code,
                    region=region,
                    results_per_query=results_per_yt_query,
                    progress_callback=add_log,
                    search_plan=yt_plan,
                    exclude_terms=result.get("exclude_terms") or normalize_user_search_terms(exclude_terms_raw),
                    allow_international=allow_international,
                    deep_search=deep_yt_search,
                ))
                yt_results, skipped_used = filter_used_creators(yt_results, history_campaign, allow_repeats)
                if skipped_used:
                    add_log(f"Creator history: skipped {len(skipped_used)} previously used YouTube creators")
                elif allow_repeats and yt_results:
                    used_count = sum(1 for c in yt_results if c.get("_history_used"))
                    if used_count:
                        add_log(f"Creator history: included {used_count} previously used YouTube creators")
                progress.progress(78)
                if yt_results and keys["gemini"]:
                    add_log(f"Gemini: ranking {len(yt_results)} YouTube candidates")
                    scorer = AIService(keys["gemini"], keys["apify_discovery"])
                    scoring_intent = dict(intent)
                    scoring_intent["_brief"] = brief
                    yt_results = scorer.score_youtube_creators_batch(yt_results, scoring_intent)
                add_log(
                    "YouTube done: "
                    f"{sum(1 for c in yt_results if c.get('match_status') == 'high')} high, "
                    f"{sum(1 for c in yt_results if c.get('match_status') in ('review', 'mid'))} mid, "
                    f"{sum(1 for c in yt_results if c.get('match_status') in ('rejected', 'low'))} low"
                )
            except Exception as exc:
                add_log(f"YouTube error: {exc}")

            # ── ScrapingBee parallel search ─────────────────────────────────
            if keys.get("scrapingbee"):
                add_log("ScrapingBee: starting parallel YouTube discovery...")
                try:
                    sb_results = run_async(run_scrapingbee_search(
                        api_keys=keys["scrapingbee"],
                        search_plan=yt_plan,
                        min_subs=effective_min,
                        max_subs=effective_max,
                        progress_callback=add_log,
                        yt_api_keys=keys["youtube"],
                        gender_filter=effective_gender,
                        location_hints=location_hints,
                        lang_hints=[intent.get("language", "")] if intent.get("language") else [],
                        exclude_terms=result.get("exclude_terms") or normalize_user_search_terms(exclude_terms_raw),
                        allow_international=allow_international,
                    ))
                    # Deduplicate: only add channels not already found by YT API
                    existing_ids = {c.get("channel_id") for c in yt_results}
                    new_sb = [c for c in sb_results if c.get("channel_id") not in existing_ids]
                    if new_sb:
                        # Run through Gemini scorer for new SB-only results
                        if keys["gemini"]:
                            scorer2 = AIService(keys["gemini"], keys["apify_discovery"])
                            scoring_intent2 = dict(intent)
                            scoring_intent2["_brief"] = brief
                            new_sb = scorer2.score_youtube_creators_batch(new_sb, scoring_intent2)
                        yt_results.extend(new_sb)
                        add_log(f"ScrapingBee: added {len(new_sb)} unique creators not found by YouTube API")
                    else:
                        add_log("ScrapingBee: no new unique creators beyond YouTube API results")
                except Exception as exc:
                    add_log(f"ScrapingBee error: {exc}")
            else:
                add_log("ScrapingBee: skipped (no SCRAPINGBEE_KEYS configured)")

    elif do_yt:
        add_log("YouTube: no search plan — run Analyze Brief first")

    progress.progress(100)
    st.session_state.ig_results = ig_results
    # Sort YT results by AI score now, then apply the fetch cap so the user
    # sees only the top N they asked for (not all raw candidates).
    def _ai_sort_key(c: dict) -> float:
        score = c.get("ai_score")
        try:
            return float(score) if score is not None else 0.0
        except Exception:
            return 0.0
    yt_results.sort(key=_ai_sort_key, reverse=True)
    fetch_cap = int(results_per_yt_query) if results_per_yt_query else 50
    if fetch_cap < 50 and len(yt_results) > fetch_cap:
        add_log(f"Fetch cap: keeping top {fetch_cap} of {len(yt_results)} YouTube creators")
        yt_results = yt_results[:fetch_cap]
    st.session_state.yt_results = yt_results
    st.session_state.analysis_result = result
    st.session_state.search_complete = True
    st.rerun()


ig_results = st.session_state.ig_results
yt_results = st.session_state.yt_results
display_history_campaign = campaign_scope(campaign_name, brief or st.session_state.last_brief)
all_results = annotate_used_creators(ig_results + yt_results, display_history_campaign)
if not allow_repeats:
    all_results = [c for c in all_results if not c.get("_history_used")]

if all_results or st.session_state.search_complete:
    # Sort all creators by AI score descending
    def sort_key(c):
        score = c.get("ai_score")
        if isinstance(score, str):
            try:
                score = float(score)
            except Exception:
                score = 0
        return score if score is not None else 0

    sorted_results = sorted(all_results, key=sort_key, reverse=True)

    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Total Creators", len(sorted_results))
    with m2:
        st.metric("With Email", sum(1 for c in sorted_results if c.get("email")))
    with m3:
        avg = sum(sort_key(c) for c in sorted_results) / len(sorted_results) if sorted_results else 0
        st.metric("Avg AI Score", f"{avg:.1f}")

    df = creators_to_df(sorted_results)
    if not df.empty:
        st.download_button(
            "Download Excel",
            data=df_to_excel(df),
            file_name=f"influencers_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    st.markdown('<div class="sec-label"><span>All Creators — sorted by AI Score</span></div>', unsafe_allow_html=True)
    render_creator_table(sorted_results, height=700)
    # NOTE: selection/mark-as-used moved below table; CSV now inside the HTML component
    selection_rows: list[tuple[str, dict]] = []
    selected_creators: list[dict] = []
    mark_col, info_col = st.columns([1, 3])
    with mark_col:
        if st.button("Mark selected as used", disabled=not selected_creators):
            marked = mark_creators_used(selected_creators, display_history_campaign, notes="Marked from Streamlit results")
            selected_keys = set()
            for creator in selected_creators:
                selected_keys.update(creator_identity_candidates(creator))

            def keep_unselected(row: dict) -> bool:
                return not (creator_identity_candidates(row) & selected_keys)

            if not allow_repeats:
                st.session_state.ig_results = [c for c in st.session_state.ig_results if keep_unselected(c)]
                st.session_state.yt_results = [c for c in st.session_state.yt_results if keep_unselected(c)]
            for key, _ in selection_rows:
                st.session_state[key] = False
            st.session_state.history_notice = f"Marked {marked} creator(s) as used for this campaign."
            st.rerun()
    with info_col:
        st.caption(
            "Tick creators you used, then mark them. With repeated creators blocked, they will be skipped in future searches for this campaign."
        )

elif not st.session_state.analysis_result:
    st.info("Enter a campaign brief and analyze it to begin.")
