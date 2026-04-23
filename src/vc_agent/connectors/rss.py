from __future__ import annotations

import hashlib
import html
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

import feedparser
import requests

from vc_agent.domain import RawItem, SourceConfig
from vc_agent.utils.time import parse_datetime


LOGGER = logging.getLogger(__name__)

TAG_RE = re.compile(r"<[^>]+>")


class RSSConnector:
    def __init__(self, max_fetch_per_source: int = 10):
        self.max_fetch_per_source = max_fetch_per_source
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "vc-agent-solution/0.1 (+https://github.com/huachabobo/vc-daily-brief-agent)"
            }
        )

    def fetch_since(self, sources: List[SourceConfig], since_iso: str) -> List[RawItem]:
        since_dt = parse_datetime(since_iso)
        collected: List[RawItem] = []
        active_sources = [source for source in sources if source.active]

        for source in active_sources:
            if not source.feed_url:
                raise ValueError("RSS source 缺少 feed_url: {0}".format(source.name))
            try:
                response = self.session.get(source.feed_url, timeout=30)
                response.raise_for_status()
                parsed = feedparser.parse(response.content)
            except Exception as exc:  # pragma: no cover - 网络错误靠集成验证覆盖
                LOGGER.warning("rss source=%s skipped because of fetch error: %s", source.name, exc)
                continue

            if getattr(parsed, "bozo", 0):
                exc_name = type(getattr(parsed, "bozo_exception", None)).__name__
                LOGGER.warning("rss source=%s reported bozo feed=%s", source.name, exc_name)

            items = self._convert_entries(source, parsed)
            new_items = [item for item in items if item.published_at >= since_dt]
            LOGGER.info("source=%s fetched=%s kept=%s", source.name, len(items), len(new_items))
            collected.extend(new_items)

        return collected

    def _convert_entries(self, source: SourceConfig, parsed_feed) -> List[RawItem]:
        feed_meta = getattr(parsed_feed, "feed", {})
        feed_title = self._clean_text(feed_meta.get("title") or source.name) or source.name
        feed_link = feed_meta.get("link") or source.feed_url or ""
        items: List[RawItem] = []

        for entry in getattr(parsed_feed, "entries", []):
            published_at = self._resolve_published_at(entry)
            if published_at is None:
                continue

            title = self._clean_text(entry.get("title") or "")
            description = self._extract_description(entry)
            url = (entry.get("link") or feed_link or source.feed_url or "").strip()
            author = self._clean_text(entry.get("author") or feed_title or source.name) or source.name

            entry_key = entry.get("id") or entry.get("guid") or url or title
            if not entry_key:
                continue

            platform_item_id = hashlib.sha1(
                "{0}|{1}".format(source.name, entry_key).encode("utf-8")
            ).hexdigest()

            items.append(
                RawItem(
                    platform="rss",
                    source_key=source.name,
                    source_name=source.name,
                    platform_item_id=platform_item_id,
                    url=url or source.feed_url or "",
                    title=title or "Untitled feed entry",
                    description=description,
                    author=author,
                    published_at=published_at,
                    raw_payload={
                        "feed": {"title": feed_title, "link": feed_link},
                        "entry": {
                            "id": str(entry_key),
                            "link": url,
                            "title": title,
                            "summary": description,
                            "author": author,
                            "published_at": published_at.isoformat(),
                        },
                    },
                )
            )
            if len(items) >= self.max_fetch_per_source:
                break

        return items

    def _resolve_published_at(self, entry) -> Optional[datetime]:
        for field_name in ("published_parsed", "updated_parsed", "created_parsed"):
            parsed_value = entry.get(field_name)
            if parsed_value:
                return datetime(*parsed_value[:6], tzinfo=timezone.utc)

        for field_name in ("published", "updated", "created"):
            raw_value = entry.get(field_name)
            if not raw_value:
                continue
            try:
                return parse_datetime(str(raw_value))
            except ValueError:
                continue

        return None

    def _extract_description(self, entry) -> str:
        candidates = []
        for field_name in ("summary", "description"):
            value = entry.get(field_name)
            if value:
                candidates.append(value)

        for block in entry.get("content", []) or []:
            value = block.get("value") if isinstance(block, dict) else None
            if value:
                candidates.append(value)

        for candidate in candidates:
            cleaned = self._clean_text(candidate)
            if cleaned:
                return cleaned
        return ""

    def _clean_text(self, value: str) -> str:
        text = html.unescape(value or "")
        text = TAG_RE.sub(" ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
