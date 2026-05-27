"""
debug_logger.py — Pre-filter debug dump utility
Writes raw channels/profiles to JSON before any filtering, so you can see
what's being dropped and why.

Usage:
  from debug_logger import log_yt_raw, log_ig_raw
  log_yt_raw(all_channels)         # call in yt_scraper.py after batch_fetch
  log_ig_raw(all_posts, candidates) # call in ig_scraper.py after pre_filter
"""

from __future__ import annotations
import json
import os
from datetime import datetime
from typing import Any

DEBUG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_logs")


def _ensure_dir() -> str:
    os.makedirs(DEBUG_DIR, exist_ok=True)
    return DEBUG_DIR


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def log_yt_raw(all_channels: dict[str, Any], channel_matches: dict[str, Any] | None = None) -> str:
    """
    Log every YT channel retrieved BEFORE subscriber range filter + normalize_channel filter.
    Includes the match context (which query found it) for each channel.
    Returns path of the log file.
    """
    _ensure_dir()
    path = os.path.join(DEBUG_DIR, f"yt_raw_{_ts()}.json")
    rows = []
    for cid, ch in all_channels.items():
        sn = ch.get("snippet", {})
        st = ch.get("statistics", {})
        match_ctx = (channel_matches or {}).get(cid, {})
        rows.append({
            "channel_id":   cid,
            "channel_name": sn.get("title", ""),
            "handle":       sn.get("customUrl", ""),
            "country":      sn.get("country", ""),
            "subscribers":  int(st.get("subscriberCount", 0) or 0),
            "video_count":  int(st.get("videoCount", 0) or 0),
            "total_views":  int(st.get("viewCount", 0) or 0),
            "description":  (sn.get("description", "") or "")[:300],
            "channel_url":  f"https://www.youtube.com/channel/{cid}",
            "_search_query": match_ctx.get("query", ""),
            "_search_type":  match_ctx.get("search_type", ""),
            "_source":       match_ctx.get("source", ""),
        })
    rows.sort(key=lambda r: -r["subscribers"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"total": len(rows), "channels": rows}, f, ensure_ascii=False, indent=2)
    print(f"[DEBUG] YT raw log: {len(rows)} channels → {path}")
    return path


def log_ig_raw(all_posts: list[Any], candidates_after_prefilter: list[Any] | None = None) -> str:
    """
    Log every IG post/username BEFORE enrich + local scoring filter.
    Also logs pre-filter candidates so you can compare.
    Returns path of the log file.
    """
    _ensure_dir()
    path = os.path.join(DEBUG_DIR, f"ig_raw_{_ts()}.json")
    seen: dict[str, dict] = {}
    for post in all_posts:
        uname = str(post.get("username") or post.get("ownerUsername") or "").strip().lower()
        if not uname:
            continue
        if uname not in seen:
            seen[uname] = {
                "username":       uname,
                "full_name":      post.get("ownerFullName") or post.get("full_name") or "",
                "followers":      post.get("ownerFollowersCount") or post.get("followers") or 0,
                "bio":            (post.get("bio") or "")[:200],
                "is_private":     post.get("ownerIsPrivate") or post.get("is_private") or False,
                "is_business":    post.get("is_business") or False,
                "caption_sample": (str(post.get("caption") or ""))[:200],
                "source_hashtag": post.get("source_hashtag") or "",
                "profile_url":    f"https://www.instagram.com/{uname}/",
                "posts_seen":     1,
            }
        else:
            seen[uname]["posts_seen"] = seen[uname].get("posts_seen", 0) + 1

    rows = sorted(seen.values(), key=lambda r: -int(r.get("followers") or 0))
    prefilter_names = {c.get("username", "") for c in (candidates_after_prefilter or [])}
    for row in rows:
        row["passed_prefilter"] = row["username"] in prefilter_names

    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "total_posts":         len(all_posts),
            "unique_usernames":    len(rows),
            "passed_prefilter":    len(prefilter_names),
            "dropped_prefilter":   len(rows) - len(prefilter_names),
            "profiles":            rows,
        }, f, ensure_ascii=False, indent=2)
    print(f"[DEBUG] IG raw log: {len(all_posts)} posts → {len(rows)} unique users → {len(prefilter_names)} passed pre-filter → {path}")
    return path
