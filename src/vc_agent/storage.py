from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from vc_agent.domain import Item, PreferenceState, RawItem
from vc_agent.utils.time import parse_datetime, utcnow


class Repository:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS raw_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    platform_item_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    author TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    UNIQUE(platform, platform_item_id)
                );

                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    raw_item_id INTEGER NOT NULL UNIQUE,
                    platform TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    platform_item_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    normalized_title TEXT NOT NULL,
                    normalized_text TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    seed_weight REAL NOT NULL DEFAULT 1.0,
                    score REAL NOT NULL DEFAULT 0.0,
                    reasons_json TEXT NOT NULL DEFAULT '[]',
                    summary TEXT NOT NULL DEFAULT '',
                    why_it_matters TEXT NOT NULL DEFAULT '',
                    duplicate_of TEXT,
                    selected_for_brief INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(raw_item_id) REFERENCES raw_items(id)
                );

                CREATE TABLE IF NOT EXISTS briefs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brief_date TEXT NOT NULL UNIQUE,
                    markdown_path TEXT NOT NULL,
                    html_path TEXT,
                    sent_via TEXT,
                    sent_status TEXT NOT NULL,
                    message_id TEXT,
                    item_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    source TEXT NOT NULL,
                    user_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(item_id) REFERENCES items(id)
                );

                CREATE TABLE IF NOT EXISTS preference_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    source_weights_json TEXT NOT NULL,
                    topic_weights_json TEXT NOT NULL,
                    phrase_weights_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_raw_items_published_at ON raw_items(published_at);
                CREATE INDEX IF NOT EXISTS idx_items_published_at ON items(published_at);
                CREATE INDEX IF NOT EXISTS idx_feedback_item_id ON feedback(item_id);
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO preference_state
                (id, source_weights_json, topic_weights_json, phrase_weights_json, updated_at)
                VALUES (1, '{}', '{}', '{}', ?)
                """,
                (utcnow().isoformat(),),
            )

    def upsert_raw_item(self, item: RawItem) -> int:
        payload = (
            item.platform,
            item.source_key,
            item.source_name,
            item.platform_item_id,
            item.url,
            item.title,
            item.description,
            item.author,
            item.published_at.isoformat(),
            utcnow().isoformat(),
            json.dumps(item.raw_payload, ensure_ascii=False),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO raw_items
                (platform, source_key, source_name, platform_item_id, url, title, description, author, published_at, fetched_at, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, platform_item_id) DO UPDATE SET
                    source_key=excluded.source_key,
                    source_name=excluded.source_name,
                    url=excluded.url,
                    title=excluded.title,
                    description=excluded.description,
                    author=excluded.author,
                    published_at=excluded.published_at,
                    fetched_at=excluded.fetched_at,
                    raw_json=excluded.raw_json
                """,
                payload,
            )
            row = conn.execute(
                "SELECT id FROM raw_items WHERE platform = ? AND platform_item_id = ?",
                (item.platform, item.platform_item_id),
            ).fetchone()
            return int(row["id"])

    def upsert_item(self, item: Item) -> int:
        payload = (
            item.raw_item_id,
            item.platform,
            item.source_key,
            item.source_name,
            item.platform_item_id,
            item.url,
            item.title,
            item.description,
            item.normalized_title,
            item.normalized_text,
            item.published_at.isoformat(),
            item.topic,
            json.dumps(item.tags, ensure_ascii=False),
            item.seed_weight,
            item.score,
            json.dumps(item.reasons, ensure_ascii=False),
            item.summary,
            item.why_it_matters,
            item.duplicate_of,
            1 if item.selected_for_brief else 0,
            utcnow().isoformat(),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO items
                (raw_item_id, platform, source_key, source_name, platform_item_id, url, title, description,
                 normalized_title, normalized_text, published_at, topic, tags_json, seed_weight,
                 score, reasons_json, summary, why_it_matters, duplicate_of, selected_for_brief, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(raw_item_id) DO UPDATE SET
                    platform=excluded.platform,
                    source_key=excluded.source_key,
                    source_name=excluded.source_name,
                    platform_item_id=excluded.platform_item_id,
                    url=excluded.url,
                    title=excluded.title,
                    description=excluded.description,
                    normalized_title=excluded.normalized_title,
                    normalized_text=excluded.normalized_text,
                    published_at=excluded.published_at,
                    topic=excluded.topic,
                    tags_json=excluded.tags_json,
                    seed_weight=excluded.seed_weight,
                    score=excluded.score,
                    reasons_json=excluded.reasons_json,
                    summary=excluded.summary,
                    why_it_matters=excluded.why_it_matters,
                    duplicate_of=excluded.duplicate_of,
                    selected_for_brief=excluded.selected_for_brief,
                    updated_at=excluded.updated_at
                """,
                payload,
            )
            row = conn.execute("SELECT id FROM items WHERE raw_item_id = ?", (item.raw_item_id,)).fetchone()
            return int(row["id"])

    def list_items_since(self, since_iso: str) -> List[Item]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM items
                WHERE published_at >= ?
                ORDER BY published_at DESC
                """,
                (since_iso,),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def get_item(self, item_id: int) -> Optional[Item]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_item(row)

    def load_preference_state(self) -> PreferenceState:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM preference_state WHERE id = 1").fetchone()
        return PreferenceState(
            source_weights=json.loads(row["source_weights_json"]),
            topic_weights=json.loads(row["topic_weights_json"]),
            phrase_weights=json.loads(row["phrase_weights_json"]),
        )

    def save_preference_state(self, state: PreferenceState) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE preference_state
                SET source_weights_json = ?, topic_weights_json = ?, phrase_weights_json = ?, updated_at = ?
                WHERE id = 1
                """,
                (
                    json.dumps(state.source_weights, ensure_ascii=False),
                    json.dumps(state.topic_weights, ensure_ascii=False),
                    json.dumps(state.phrase_weights, ensure_ascii=False),
                    utcnow().isoformat(),
                ),
            )

    def record_feedback(
        self,
        item_id: int,
        label: str,
        source: str,
        user_id: Optional[str],
        metadata: Optional[dict],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO feedback (item_id, label, source, user_id, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    label,
                    source,
                    user_id,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    utcnow().isoformat(),
                ),
            )

    def save_brief(
        self,
        brief_date: str,
        markdown_path: str,
        item_ids: Iterable[int],
        sent_via: Optional[str],
        sent_status: str,
        message_id: Optional[str],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO briefs
                (brief_date, markdown_path, html_path, sent_via, sent_status, message_id, item_ids_json, created_at)
                VALUES (?, ?, NULL, ?, ?, ?, ?, ?)
                ON CONFLICT(brief_date) DO UPDATE SET
                    markdown_path=excluded.markdown_path,
                    sent_via=excluded.sent_via,
                    sent_status=excluded.sent_status,
                    message_id=excluded.message_id,
                    item_ids_json=excluded.item_ids_json,
                    created_at=excluded.created_at
                """,
                (
                    brief_date,
                    markdown_path,
                    sent_via,
                    sent_status,
                    message_id,
                    json.dumps(list(item_ids), ensure_ascii=False),
                    utcnow().isoformat(),
                ),
            )

    def get_latest_brief_before(self, brief_date: str) -> Optional[Tuple[str, List[int]]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT brief_date, item_ids_json
                FROM briefs
                WHERE brief_date < ?
                ORDER BY brief_date DESC
                LIMIT 1
                """,
                (brief_date,),
            ).fetchone()
        if row is None:
            return None
        return row["brief_date"], [int(value) for value in json.loads(row["item_ids_json"])]

    def get_items_by_ids(self, item_ids: Iterable[int]) -> List[Item]:
        ids = [int(value) for value in item_ids if value is not None]
        if not ids:
            return []
        placeholders = ", ".join(["?"] * len(ids))
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM items WHERE id IN ({0})".format(placeholders),
                ids,
            ).fetchall()
        items = [self._row_to_item(row) for row in rows]
        return sorted(items, key=lambda item: item.score, reverse=True)

    def _row_to_item(self, row: sqlite3.Row) -> Item:
        return Item(
            item_id=int(row["id"]),
            raw_item_id=int(row["raw_item_id"]),
            platform=row["platform"],
            source_key=row["source_key"],
            source_name=row["source_name"],
            platform_item_id=row["platform_item_id"],
            url=row["url"],
            title=row["title"],
            description=row["description"],
            normalized_title=row["normalized_title"],
            normalized_text=row["normalized_text"],
            published_at=parse_datetime(row["published_at"]),
            topic=row["topic"],
            tags=json.loads(row["tags_json"]),
            seed_weight=float(row["seed_weight"]),
            score=float(row["score"]),
            reasons=json.loads(row["reasons_json"]),
            summary=row["summary"],
            why_it_matters=row["why_it_matters"],
            duplicate_of=row["duplicate_of"],
            selected_for_brief=bool(row["selected_for_brief"]),
        )
