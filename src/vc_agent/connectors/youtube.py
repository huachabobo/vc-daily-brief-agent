from __future__ import annotations

import logging
from typing import Dict, List

import requests

from vc_agent.domain import RawItem, SourceConfig
from vc_agent.utils.time import parse_datetime


LOGGER = logging.getLogger(__name__)


class YouTubeConnector:
    api_root = "https://www.googleapis.com/youtube/v3"

    def __init__(self, api_key: str, max_fetch_per_source: int = 10):
        self.api_key = api_key
        self.max_fetch_per_source = max_fetch_per_source
        self.session = requests.Session()

    def fetch_since(self, sources: List[SourceConfig], since_iso: str) -> List[RawItem]:
        if not self.api_key:
            raise ValueError("YOUTUBE_API_KEY 未配置，无法抓取真实 YouTube 数据。")

        since_dt = parse_datetime(since_iso)
        collected: List[RawItem] = []
        active_sources = [source for source in sources if source.active]
        if not active_sources:
            raise ValueError("config/sources.yaml 中没有 active=true 的 YouTube 频道。")

        for source in active_sources:
            metadata = self._fetch_channel_metadata(source.channel_id)
            playlist_id = metadata["contentDetails"]["relatedPlaylists"]["uploads"]
            source_name = metadata["snippet"]["title"]
            items = self._fetch_playlist_items(playlist_id, source, source_name)
            new_items = [item for item in items if item.published_at >= since_dt]
            LOGGER.info("source=%s fetched=%s kept=%s", source.name, len(items), len(new_items))
            collected.extend(new_items)

        return collected

    def _fetch_channel_metadata(self, channel_id: str) -> Dict:
        response = self.session.get(
            f"{self.api_root}/channels",
            params={
                "part": "snippet,contentDetails,statistics",
                "id": channel_id,
                "key": self.api_key,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])
        if not items:
            raise ValueError("无法通过 channel_id 找到频道: {0}".format(channel_id))
        return items[0]

    def _fetch_playlist_items(
        self,
        playlist_id: str,
        source: SourceConfig,
        source_name: str,
    ) -> List[RawItem]:
        items: List[RawItem] = []
        next_page_token = None

        while len(items) < self.max_fetch_per_source:
            response = self.session.get(
                f"{self.api_root}/playlistItems",
                params={
                    "part": "snippet,contentDetails",
                    "playlistId": playlist_id,
                    "maxResults": min(self.max_fetch_per_source, 50),
                    "pageToken": next_page_token,
                    "key": self.api_key,
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()

            for entry in payload.get("items", []):
                snippet = entry.get("snippet", {})
                content_details = entry.get("contentDetails", {})
                if snippet.get("title") == "Deleted video":
                    continue
                video_id = content_details.get("videoId")
                if not video_id:
                    continue
                items.append(
                    RawItem(
                        platform="youtube",
                        source_key=source.name,
                        source_name=source_name,
                        platform_item_id=video_id,
                        url="https://www.youtube.com/watch?v={0}".format(video_id),
                        title=snippet.get("title", "").strip(),
                        description=snippet.get("description", "").strip(),
                        author=snippet.get("videoOwnerChannelTitle") or source_name,
                        published_at=parse_datetime(snippet["publishedAt"]),
                        raw_payload=entry,
                    )
                )
                if len(items) >= self.max_fetch_per_source:
                    break

            next_page_token = payload.get("nextPageToken")
            if not next_page_token:
                break

        return items
