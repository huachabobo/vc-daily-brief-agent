from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SourceConfig:
    name: str
    platform: str = "youtube"
    channel_id: Optional[str] = None
    feed_url: Optional[str] = None
    seed_weight: float = 1.0
    topics: List[str] = field(default_factory=list)
    active: bool = True


@dataclass
class RawItem:
    platform: str
    source_key: str
    source_name: str
    platform_item_id: str
    url: str
    title: str
    description: str
    author: str
    published_at: datetime
    raw_payload: Dict[str, Any]


@dataclass
class PreferenceState:
    source_weights: Dict[str, float] = field(default_factory=dict)
    topic_weights: Dict[str, float] = field(default_factory=dict)
    phrase_weights: Dict[str, float] = field(default_factory=dict)


@dataclass
class Item:
    item_id: Optional[int]
    raw_item_id: int
    platform: str
    source_key: str
    source_name: str
    platform_item_id: str
    url: str
    title: str
    description: str
    normalized_title: str
    normalized_text: str
    published_at: datetime
    topic: str
    tags: List[str] = field(default_factory=list)
    seed_weight: float = 1.0
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    summary: str = ""
    why_it_matters: str = ""
    duplicate_of: Optional[str] = None
    selected_for_brief: bool = False


@dataclass
class BriefEntry:
    item_id: int
    title: str
    summary: str
    why_it_matters: str
    why_selected: str
    source_name: str
    source_url: str
    topic: str
    tags: List[str]
    score: float


@dataclass
class DailyBrief:
    brief_date: str
    highlights: List[str]
    shifts: List[str]
    grouped_entries: Dict[str, List[BriefEntry]]
    markdown: str
