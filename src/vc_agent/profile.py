from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from vc_agent.domain import Item
from vc_agent.utils.text import normalize_text


@dataclass
class UserProfile:
    focus_topics: List[str] = field(default_factory=list)
    blocked_topics: List[str] = field(default_factory=list)
    preferred_sources: List[str] = field(default_factory=list)
    blocked_sources: List[str] = field(default_factory=list)
    blocked_keywords: List[str] = field(default_factory=list)
    max_brief_items: int | None = None
    exploration_slots: int | None = None


def load_user_profile(path: Path) -> UserProfile:
    if not path.exists():
        return UserProfile()
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    digest = payload.get("digest") or {}
    return UserProfile(
        focus_topics=list(payload.get("focus_topics") or []),
        blocked_topics=list(payload.get("blocked_topics") or []),
        preferred_sources=list(payload.get("preferred_sources") or []),
        blocked_sources=list(payload.get("blocked_sources") or []),
        blocked_keywords=list(payload.get("blocked_keywords") or []),
        max_brief_items=_optional_int(digest.get("max_items")),
        exploration_slots=_optional_int(digest.get("exploration_slots")),
    )


def item_allowed(item: Item, profile: UserProfile) -> bool:
    if item.source_name in profile.blocked_sources:
        return False
    if item.topic in profile.blocked_topics:
        return False
    if not profile.blocked_keywords:
        return True
    text = item.normalized_text or normalize_text("{0} {1}".format(item.title, item.description))
    for keyword in profile.blocked_keywords:
        normalized_keyword = normalize_text(keyword)
        if normalized_keyword and normalized_keyword in text:
            return False
    return True


def apply_profile_adjustments(item: Item, profile: UserProfile) -> Item:
    delta, reasons = score_profile_adjustments(item, profile)
    if delta:
        item.score = max(item.score + delta, 0.0)
        item.reasons.extend(reasons)
    return item


def score_profile_adjustments(item: Item, profile: UserProfile) -> Tuple[float, List[str]]:
    delta = 0.0
    reasons: List[str] = []

    if item.topic in profile.focus_topics:
        delta += 0.08
        reasons.append("用户重点关注赛道")

    if item.source_name in profile.preferred_sources:
        delta += 0.1
        reasons.append("用户偏好来源")

    return delta, reasons


def resolve_digest_settings(default_max_items: int, default_exploration_slots: int, profile: UserProfile) -> Dict[str, int]:
    return {
        "max_items": profile.max_brief_items or default_max_items,
        "exploration_slots": profile.exploration_slots if profile.exploration_slots is not None else default_exploration_slots,
    }


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
