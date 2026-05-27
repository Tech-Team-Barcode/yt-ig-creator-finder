#creator_history.py
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable


DB_PATH = Path(__file__).with_name("creator_history.db")
USED_STATUS = "used"


def init_db(db_path: str | Path = DB_PATH) -> None:
    """Create the creator history table if it does not already exist."""
    path = Path(db_path)
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS creators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                username TEXT NOT NULL,
                handle TEXT,
                channel_name TEXT,
                followers_subs INTEGER,
                profile_url TEXT,
                campaign_brief TEXT,
                search_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'new',
                notes TEXT,
                full_creator_data TEXT,
                UNIQUE(platform, username, campaign_brief)
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_creators_campaign_status ON creators(campaign_brief, status)")
        con.commit()


def campaign_scope(campaign_name: str | None, brief: str | None) -> str:
    """Use campaign name when present, otherwise fall back to the current brief."""
    scope = (campaign_name or "").strip() or (brief or "").strip()
    return scope[:500] or "default"


def _clean_identifier(value) -> str:
    value = str(value or "").strip().lower()
    value = value.rstrip("/")
    return value


def creator_identity_candidates(creator: dict) -> set[tuple[str, str]]:
    """Return all stable identifiers that can represent a creator."""
    platform = _clean_identifier(creator.get("platform"))
    if platform not in {"instagram", "youtube"}:
        platform = "youtube" if creator.get("channel_id") or creator.get("channel_name") else "instagram"

    values: list[str] = []
    if platform == "instagram":
        values.extend([creator.get("username"), creator.get("handle")])
    else:
        values.extend([
            creator.get("handle"),
            creator.get("channel_id"),
            creator.get("channel_name"),
            creator.get("channel_url"),
            creator.get("handle_url"),
        ])

    output: set[tuple[str, str]] = set()
    for value in values:
        clean = _clean_identifier(value)
        if not clean:
            continue
        if platform == "instagram":
            clean = clean.lstrip("@")
        output.add((platform, clean))
    return output


def primary_creator_identity(creator: dict) -> tuple[str, str]:
    platform = _clean_identifier(creator.get("platform"))
    if platform == "instagram":
        username = _clean_identifier(creator.get("username") or creator.get("handle")).lstrip("@")
        return "instagram", username
    handle = _clean_identifier(creator.get("handle"))
    if handle:
        return "youtube", handle
    channel_id = _clean_identifier(creator.get("channel_id"))
    if channel_id:
        return "youtube", channel_id
    return "youtube", _clean_identifier(creator.get("channel_name"))


def _row_to_used_keys(row: sqlite3.Row) -> set[tuple[str, str]]:
    platform = _clean_identifier(row["platform"])
    keys = {(platform, _clean_identifier(row["username"]))}
    raw = row["full_creator_data"] or ""
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    if isinstance(data, dict):
        keys.update(creator_identity_candidates(data))
    return {(p, v) for p, v in keys if p and v}


def load_used_creator_keys(campaign: str, db_path: str | Path = DB_PATH) -> set[tuple[str, str]]:
    """Load creators marked as used for one campaign scope."""
    init_db(db_path)
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT platform, username, full_creator_data
            FROM creators
            WHERE campaign_brief = ? AND status = ?
            """,
            (campaign, USED_STATUS),
        ).fetchall()

    keys: set[tuple[str, str]] = set()
    for row in rows:
        keys.update(_row_to_used_keys(row))
    return keys


def is_creator_used(creator: dict, used_keys: set[tuple[str, str]]) -> bool:
    return bool(creator_identity_candidates(creator) & used_keys)


def annotate_used_creators(creators: Iterable[dict], campaign: str) -> list[dict]:
    used_keys = load_used_creator_keys(campaign)
    output = []
    for creator in creators:
        row = dict(creator)
        row["_history_used"] = is_creator_used(row, used_keys)
        output.append(row)
    return output


def filter_used_creators(creators: Iterable[dict], campaign: str, allow_repeats: bool) -> tuple[list[dict], list[dict]]:
    """Return kept and skipped creators, annotating kept rows with _history_used."""
    used_keys = load_used_creator_keys(campaign)
    kept: list[dict] = []
    skipped: list[dict] = []
    for creator in creators:
        row = dict(creator)
        row["_history_used"] = is_creator_used(row, used_keys)
        if row["_history_used"] and not allow_repeats:
            skipped.append(row)
        else:
            kept.append(row)
    return kept, skipped


def _followers_or_subs(creator: dict) -> int:
    for key in ("followers", "subscribers"):
        try:
            return int(creator.get(key) or 0)
        except Exception:
            pass
    return 0


def _profile_url(creator: dict) -> str:
    return (
        creator.get("profile_url")
        or creator.get("handle_url")
        or creator.get("channel_url")
        or ""
    )


def mark_creators_used(creators: Iterable[dict], campaign: str, notes: str = "") -> int:
    """Mark selected creators as used for this campaign."""
    init_db()
    rows = []
    for creator in creators:
        platform, username = primary_creator_identity(creator)
        if not platform or not username:
            continue
        rows.append((
            platform,
            username,
            _clean_identifier(creator.get("handle")),
            str(creator.get("channel_name") or creator.get("full_name") or ""),
            _followers_or_subs(creator),
            _profile_url(creator),
            campaign,
            USED_STATUS,
            notes,
            json.dumps(creator, ensure_ascii=False, default=str),
        ))

    if not rows:
        return 0

    with sqlite3.connect(DB_PATH) as con:
        con.executemany(
            """
            INSERT INTO creators (
                platform, username, handle, channel_name, followers_subs,
                profile_url, campaign_brief, status, notes, full_creator_data
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, username, campaign_brief) DO UPDATE SET
                handle = excluded.handle,
                channel_name = excluded.channel_name,
                followers_subs = excluded.followers_subs,
                profile_url = excluded.profile_url,
                status = excluded.status,
                notes = excluded.notes,
                full_creator_data = excluded.full_creator_data,
                search_date = CURRENT_TIMESTAMP
            """,
            rows,
        )
        con.commit()
    return len(rows)


def history_stats(campaign: str) -> dict[str, int]:
    init_db()
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            """
            SELECT status, COUNT(*)
            FROM creators
            WHERE campaign_brief = ?
            GROUP BY status
            """,
            (campaign,),
        ).fetchall()
    stats = {str(status or "new"): int(count) for status, count in rows}
    stats.setdefault(USED_STATUS, 0)
    stats["total"] = sum(stats.values())
    return stats


def clear_used_creators(campaign: str) -> int:
    init_db()
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "DELETE FROM creators WHERE campaign_brief = ? AND status = ?",
            (campaign, USED_STATUS),
        )
        con.commit()
        return int(cur.rowcount or 0)
