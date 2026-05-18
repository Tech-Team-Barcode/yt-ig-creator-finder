"""Influencer Finder Streamlit UI."""

from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from ai_service import AIService
from backend_keys import backend_key_counts, env_keys, first_non_empty, parse_keys
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


def init_state() -> None:
    defaults = {
        "analysis_result": None,
        "ig_results": [],
        "yt_results": [],
        "ig_debug": {},
        "search_complete": False,
        "last_brief": "",
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
                "Status": c.get("match_status", ""),
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
                "Local Score": c.get("local_match_score", 0),
                "AI Score": c.get("ai_score", ""),
                "Niche Confidence": c.get("niche_confidence", 0),
                "India Confidence": c.get("india_confidence", 0),
                "Gender Confidence": c.get("gender_confidence", 0),
                "Creator Confidence": c.get("creator_confidence", 0),
                "Business Risk": c.get("business_risk", 0),
                "Evidence": c.get("evidence", ""),
                "Reason": c.get("reject_reason") or c.get("review_reason") or c.get("ai_reason", ""),
            })
        else:
            rows.append({
                "Platform": "YouTube",
                "Status": "high",
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
                "Local Score": c.get("_quality_score", 0),
                "AI Score": "",
                "Niche Confidence": "",
                "India Confidence": c.get("_location_score", 0),
                "Gender Confidence": "",
                "Creator Confidence": c.get("_quality_score", 0),
                "Business Risk": "",
                "Evidence": c.get("video_title", ""),
                "Reason": "",
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


def render_creator_card(creator: dict) -> None:
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
            chip(status.title(), "good" if status == "high" else "warn" if status == "review" else "bad"),
            chip(f"{fmt_num(followers)} followers"),
            chip(f"Local {creator.get('local_match_score', 0)}"),
        ]
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
        reason = ""
        chips = [chip("High", "good"), chip(f"{fmt_num(followers)} subscribers")]
        evidence = html.escape(str(creator.get("video_title", ""))[:260])

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


def render_cards(items: list[dict]) -> None:
    if not items:
        st.info("No creators in this bucket.")
        return
    cols_per_row = 2
    for start in range(0, len(items), cols_per_row):
        cols = st.columns(cols_per_row)
        for offset, col in enumerate(cols):
            index = start + offset
            if index < len(items):
                with col:
                    render_creator_card(items[index])


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
        min_followers = st.number_input("Min followers", value=5000, step=1000, format="%d")
    with col_b:
        max_followers = st.number_input("Max followers", value=50000, step=5000, format="%d")

    gender_override = st.selectbox("Gender override", ["Auto", "Any", "Male only", "Female only"])
    gender_map = {"Auto": None, "Any": "ANY", "Male only": "M", "Female only": "F"}
    region = st.selectbox("YouTube region", ["IN", "US", "GB", "AU", "CA", "SG", "AE"], index=0)

    st.markdown("### Advanced")
    posts_per_tag = st.slider("Instagram rows per hashtag", 10, 30, 30, step=5)
    results_per_yt_query = st.slider("YouTube results per query", 10, 50, 30, step=10)
    verify_hashtags = st.checkbox("Verify hashtag counts with Apify analytics", value=True)


st.title("Influencer Finder Pro")
st.caption("Deterministic Instagram hashtag discovery plus YouTube search. Backend keys are read from environment variables by default.")

brief = st.text_area(
    "Campaign brief",
    placeholder='Example: "Find male skincare creators in India, 5K-50K followers, Hindi or English content"',
    height=110,
)

hashtags_ready = bool(st.session_state.analysis_result and st.session_state.analysis_result.get("hashtags_final"))
ig_ready = "Instagram" in platform_choice and bool(keys["apify_discovery"]) and bool(keys["apify_profile"]) and hashtags_ready
yt_ready = "YouTube" in platform_choice and bool(keys["youtube"]) and bool(st.session_state.analysis_result and st.session_state.analysis_result.get("yt_queries"))
analyze_ready = bool(brief and keys["gemini"])
search_ready = bool(brief and st.session_state.analysis_result and (ig_ready or yt_ready))

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

if analyze_btn:
    with st.spinner("Analyzing brief and planning Instagram hashtags..."):
        ai = AIService(keys["gemini"], keys["apify_discovery"])
        result = ai.run_full_analysis(brief, verify_hashtags=verify_hashtags)
        st.session_state.analysis_result = result
        st.session_state.last_brief = brief
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
    if intent.get("gender") and intent.get("gender") != "ANY":
        badges.append(chip("gender: " + ("male" if intent["gender"] == "M" else "female")))
    st.markdown("".join(badges), unsafe_allow_html=True)
    if intent.get("reasoning"):
        st.caption(intent["reasoning"])
    st.caption(
        f"Follower range: {fmt_num(intent.get('min_followers', min_followers))} - "
        f"{fmt_num(intent.get('max_followers', max_followers))}"
    )

    col_tags, col_queries = st.columns(2)
    with col_tags:
        show_hashtag_plan(result)
    with col_queries:
        st.markdown('<div class="section-title">YouTube Queries</div>', unsafe_allow_html=True)
        for i, query in enumerate(result.get("yt_queries", []), 1):
            st.markdown(f"{i}. `{query}`")
        st.markdown('<div class="section-title">Instagram Discovery Phrases</div>', unsafe_allow_html=True)
        for i, query in enumerate(result.get("ig_keywords", [])[:12], 1):
            st.markdown(f"{i}. `{query}`")

    with st.expander("Edit hashtags and queries"):
        edited_tags = st.text_area("Instagram hashtags, one per line", value="\n".join(result.get("hashtags_final", [])), height=140)
        edited_yt = st.text_area("YouTube queries, one per line", value="\n".join(result.get("yt_queries", [])), height=140)
        edited_ig_phrases = st.text_area("Instagram discovery phrases, one per line", value="\n".join(result.get("ig_keywords", [])), height=100)
        if st.button("Save edits"):
            result["hashtags_final"] = [line.strip() for line in edited_tags.splitlines() if line.strip()]
            result["yt_queries"] = [line.strip() for line in edited_yt.splitlines() if line.strip()]
            result["ig_keywords"] = [line.strip() for line in edited_ig_phrases.splitlines() if line.strip()]
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
        log_box.markdown('<div class="soft-panel muted">' + "<br>".join(logs[-18:]) + "</div>", unsafe_allow_html=True)

    ig_results: list[dict] = []
    yt_results: list[dict] = []

    if "Instagram" in platform_choice and result.get("hashtags_final"):
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
                    f"{sum(1 for c in ig_results if c.get('match_status') == 'review')} review, "
                    f"{sum(1 for c in ig_results if c.get('match_status') == 'rejected')} rejected"
                )
            except Exception as exc:
                add_log(f"Instagram error: {exc}")

    if "YouTube" in platform_choice and result.get("yt_queries"):
        if not keys["youtube"]:
            add_log("YouTube skipped: missing YOUTUBE_API_KEYS")
        else:
            progress.progress(60)
            add_log(f"YouTube: searching {len(result['yt_queries'])} queries")
            try:
                yt_results = run_async(run_yt_search(
                    api_keys=keys["youtube"],
                    queries=result["yt_queries"],
                    min_subs=effective_min,
                    max_subs=effective_max,
                    gender_filter=effective_gender,
                    location_hints=location_hints,
                    lang_hints=[intent.get("language", "")] if intent.get("language") else [],
                    lang_code=lang_code,
                    region=region,
                    results_per_query=results_per_yt_query,
                    progress_callback=add_log,
                ))
                add_log(f"YouTube done: {len(yt_results)} creators")
            except Exception as exc:
                add_log(f"YouTube error: {exc}")

    progress.progress(100)
    st.session_state.ig_results = ig_results
    st.session_state.yt_results = yt_results
    st.session_state.analysis_result = result
    st.session_state.search_complete = True
    st.rerun()


ig_results = st.session_state.ig_results
yt_results = st.session_state.yt_results
all_results = ig_results + yt_results

if all_results or st.session_state.search_complete:
    st.markdown('<div class="section-title">Results</div>', unsafe_allow_html=True)
    high_results = [c for c in ig_results if c.get("match_status") == "high"] + yt_results
    review_results = [c for c in ig_results if c.get("match_status") == "review"]
    rejected_results = [c for c in ig_results if c.get("match_status") == "rejected"]

    m1, m2, m3, m4 = st.columns(4)
    metrics = [
        (m1, len(high_results), "High Match"),
        (m2, len(review_results), "Needs Review"),
        (m3, len(rejected_results), "Rejected Debug"),
        (m4, sum(1 for c in all_results if c.get("email")), "Have Email"),
    ]
    for col, number, label in metrics:
        with col:
            st.markdown(f'<div class="metric-box"><div class="num">{number}</div><div class="label">{label}</div></div>', unsafe_allow_html=True)

    df = creators_to_df(all_results)
    if not df.empty:
        st.download_button(
            "Download Excel",
            data=df_to_excel(df),
            file_name=f"influencers_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    tab_high, tab_review, tab_rejected, tab_table, tab_debug = st.tabs([
        "High Match", "Needs Review", "Rejected Debug", "Data Table", "Funnel Debug"
    ])
    with tab_high:
        render_cards(high_results)
    with tab_review:
        render_cards(review_results)
    with tab_rejected:
        render_cards(rejected_results[:80])
    with tab_table:
        if df.empty:
            st.info("No rows to display.")
        else:
            st.dataframe(
                df,
                width="stretch",
                hide_index=True,
                column_config={
                    "Followers": st.column_config.NumberColumn("Followers", format="%d"),
                    "Profile URL": st.column_config.LinkColumn("Profile URL"),
                    "Sample Post": st.column_config.LinkColumn("Sample Post"),
                },
            )
    with tab_debug:
        debug = st.session_state.ig_debug or (st.session_state.analysis_result or {}).get("ig_debug", {})
        if debug:
            st.json(debug)
        else:
            st.info("No Instagram funnel debug available yet.")

elif not st.session_state.analysis_result:
    st.info("Enter a campaign brief and analyze it to begin.")
