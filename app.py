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
from ig_scraper import run_ig_search
from yt_scraper import run_yt_search


st.set_page_config(
    page_title="Influencer Finder Pro",
    page_icon="IF",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
  html, body, [class*="css"] { font-family: Inter, Segoe UI, sans-serif; }
  .stApp { background: #0b0d12; color: #f2f4f8; }
  section[data-testid="stSidebar"] { background: #11141c !important; border-right: 1px solid #252a36; }
  .section-title { font-size: 1.15rem; font-weight: 800; margin: 1rem 0 .6rem; }
  .soft-panel { background: #151923; border: 1px solid #272d3a; border-radius: 8px; padding: 12px; }
  .chip { display: inline-block; padding: 4px 9px; margin: 3px; border-radius: 999px; font-size: .78rem; border: 1px solid #343b4d; color: #cbd4e1; background: #171c27; }
  .chip.good { border-color: #2f8f83; color: #62d6c6; background: rgba(47,143,131,.14); }
  .chip.warn { border-color: #a76b24; color: #ffbd66; background: rgba(167,107,36,.14); }
  .chip.bad { border-color: #9b3d4e; color: #ff8095; background: rgba(155,61,78,.14); }
  .creator-card { background: #151923; border: 1px solid #272d3a; border-radius: 8px; padding: 14px; margin-bottom: 10px; }
  .creator-title { font-weight: 800; color: #f7f9fc; }
  .muted { color: #94a0b8; font-size: .86rem; }
  .metric-box { background: #151923; border: 1px solid #272d3a; border-radius: 8px; padding: 14px; text-align: center; }
  .metric-box .num { font-size: 1.8rem; font-weight: 900; color: #69a7ff; }
  .metric-box .label { color: #94a0b8; font-size: .82rem; }
</style>
""",
    unsafe_allow_html=True,
)

# Map internal match_status → display label and chip class
_STATUS_LABEL = {"high": "High", "review": "Mid", "rejected": "Low", "mid": "Mid", "low": "Low"}
_STATUS_CLS   = {"high": "good", "review": "warn", "rejected": "bad",  "mid": "warn", "low": "bad"}


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
    youtube = first_non_empty(parse_keys(overrides.get("youtube")), env_keys("YOUTUBE_API_KEYS"), env_keys("YOUTUBE_API_KEY"))
    return {
        "gemini": gemini,
        "apify_discovery": apify_discovery,
        "apify_profile": apify_profile,
        "youtube": youtube,
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

    st.markdown('<div class="section-title">Instagram Hashtags</div>', unsafe_allow_html=True)
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
        min_followers = st.number_input("Min followers/subscribers", value=10000, step=1000, format="%d")
    with col_b:
        max_followers = st.number_input("Max followers/subscribers", value=500000, step=5000, format="%d")

    gender_override = st.selectbox("Gender override", ["Auto", "Any", "Male only", "Female only"])
    gender_map = {"Auto": None, "Any": "ANY", "Male only": "M", "Female only": "F"}
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
    intent = result.get("intent", {})
    effective_gender = gender_map.get(gender_override) or intent.get("gender", "ANY")
    if effective_gender is None:
        effective_gender = intent.get("gender", "ANY")
    effective_min = int(min_followers)
    effective_max = int(max_followers)
    history_campaign = campaign_scope(campaign_name, brief)
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
    elif do_yt:
        add_log("YouTube: no search plan — run Analyze Brief first")

    progress.progress(100)
    st.session_state.ig_results = ig_results
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
            "📥 Download Excel",
            data=df_to_excel(df),
            file_name=f"influencers_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    st.markdown('<div class="section-title">All Creators — sorted by AI Score</div>', unsafe_allow_html=True)
    selection_rows = render_cards(sorted_results, selectable=True)
    selected_creators = [creator for key, creator in selection_rows if st.session_state.get(key)]
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