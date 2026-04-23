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
    topic_weight_overrides: Dict[str, float] = field(default_factory=dict)
    source_weight_overrides: Dict[str, float] = field(default_factory=dict)
    keyword_weight_overrides: Dict[str, float] = field(default_factory=dict)
    max_brief_items: int | None = None
    exploration_slots: int | None = None


@dataclass
class UserProfilePatch:
    add_focus_topics: List[str] = field(default_factory=list)
    remove_focus_topics: List[str] = field(default_factory=list)
    add_blocked_topics: List[str] = field(default_factory=list)
    remove_blocked_topics: List[str] = field(default_factory=list)
    add_preferred_sources: List[str] = field(default_factory=list)
    remove_preferred_sources: List[str] = field(default_factory=list)
    add_blocked_sources: List[str] = field(default_factory=list)
    remove_blocked_sources: List[str] = field(default_factory=list)
    add_blocked_keywords: List[str] = field(default_factory=list)
    remove_blocked_keywords: List[str] = field(default_factory=list)
    topic_weight_overrides: Dict[str, float] = field(default_factory=dict)
    source_weight_overrides: Dict[str, float] = field(default_factory=dict)
    keyword_weight_overrides: Dict[str, float] = field(default_factory=dict)
    max_brief_items: int | None = None
    exploration_slots: int | None = None
    rationale: str = ""


def load_user_profile(path: Path) -> UserProfile:
    if not path.exists():
        return UserProfile()
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    digest = payload.get("digest") or {}
    weight_overrides = payload.get("weight_overrides") or {}
    return UserProfile(
        focus_topics=list(payload.get("focus_topics") or []),
        blocked_topics=list(payload.get("blocked_topics") or []),
        preferred_sources=list(payload.get("preferred_sources") or []),
        blocked_sources=list(payload.get("blocked_sources") or []),
        blocked_keywords=list(payload.get("blocked_keywords") or []),
        topic_weight_overrides=_coerce_weight_map(weight_overrides.get("topics")),
        source_weight_overrides=_coerce_weight_map(weight_overrides.get("sources")),
        keyword_weight_overrides=_coerce_weight_map(weight_overrides.get("keywords")),
        max_brief_items=_optional_int(digest.get("max_items")),
        exploration_slots=_optional_int(digest.get("exploration_slots")),
    )


def save_user_profile(path: Path, profile: UserProfile) -> None:
    payload = {
        "focus_topics": list(profile.focus_topics),
        "blocked_topics": list(profile.blocked_topics),
        "preferred_sources": list(profile.preferred_sources),
        "blocked_sources": list(profile.blocked_sources),
        "blocked_keywords": list(profile.blocked_keywords),
        "digest": {
            "max_items": profile.max_brief_items,
            "exploration_slots": profile.exploration_slots,
        },
    }
    weight_overrides = {
        "topics": _serialize_weight_map(profile.topic_weight_overrides),
        "sources": _serialize_weight_map(profile.source_weight_overrides),
        "keywords": _serialize_weight_map(profile.keyword_weight_overrides),
    }
    if any(weight_overrides.values()):
        payload["weight_overrides"] = {key: value for key, value in weight_overrides.items() if value}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def merge_profile_patch(profile: UserProfile, patch: UserProfilePatch) -> UserProfile:
    updated = UserProfile(
        focus_topics=_merge_list(profile.focus_topics, patch.add_focus_topics, patch.remove_focus_topics),
        blocked_topics=_merge_list(profile.blocked_topics, patch.add_blocked_topics, patch.remove_blocked_topics),
        preferred_sources=_merge_list(
            profile.preferred_sources,
            patch.add_preferred_sources,
            patch.remove_preferred_sources,
        ),
        blocked_sources=_merge_list(profile.blocked_sources, patch.add_blocked_sources, patch.remove_blocked_sources),
        blocked_keywords=_merge_list(
            profile.blocked_keywords,
            patch.add_blocked_keywords,
            patch.remove_blocked_keywords,
        ),
        topic_weight_overrides=_merge_weight_map(profile.topic_weight_overrides, patch.topic_weight_overrides),
        source_weight_overrides=_merge_weight_map(profile.source_weight_overrides, patch.source_weight_overrides),
        keyword_weight_overrides=_merge_weight_map(profile.keyword_weight_overrides, patch.keyword_weight_overrides),
        max_brief_items=profile.max_brief_items,
        exploration_slots=profile.exploration_slots,
    )
    if patch.max_brief_items is not None:
        updated.max_brief_items = max(3, min(int(patch.max_brief_items), 10))
    if patch.exploration_slots is not None:
        updated.exploration_slots = max(0, min(int(patch.exploration_slots), 3))
    return updated


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

    topic_weight = _clip_weight(profile.topic_weight_overrides.get(item.topic, 0.0))
    if topic_weight:
        delta += topic_weight
        reasons.append("用户主题权重 {0:+.2f}".format(topic_weight))

    source_weight = _clip_weight(profile.source_weight_overrides.get(item.source_name, 0.0))
    if source_weight:
        delta += source_weight
        reasons.append("用户来源权重 {0:+.2f}".format(source_weight))

    text = item.normalized_text or normalize_text("{0} {1}".format(item.title, item.description))
    keyword_total = 0.0
    for keyword, weight in profile.keyword_weight_overrides.items():
        normalized_keyword = normalize_text(keyword)
        if normalized_keyword and normalized_keyword in text:
            keyword_total += _clip_weight(weight)
    keyword_total = max(min(keyword_total, 0.25), -0.25)
    if keyword_total:
        delta += keyword_total
        reasons.append("用户关键词权重 {0:+.2f}".format(keyword_total))

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


def _coerce_weight_map(value: object) -> Dict[str, float]:
    if not isinstance(value, dict):
        return {}
    weights: Dict[str, float] = {}
    for key, raw in value.items():
        if key in (None, ""):
            continue
        weights[str(key)] = _clip_weight(raw)
    return {key: weight for key, weight in weights.items() if weight}


def _serialize_weight_map(value: Dict[str, float]) -> Dict[str, float]:
    return {key: round(_clip_weight(weight), 3) for key, weight in value.items() if _clip_weight(weight)}


def _merge_list(current: List[str], additions: List[str], removals: List[str]) -> List[str]:
    merged: List[str] = []
    removal_set = {value for value in removals if value}
    for value in current:
        if value and value not in removal_set and value not in merged:
            merged.append(value)
    for value in additions:
        if value and value not in removal_set and value not in merged:
            merged.append(value)
    return merged


def _merge_weight_map(current: Dict[str, float], patch: Dict[str, float]) -> Dict[str, float]:
    merged = {key: _clip_weight(value) for key, value in current.items() if _clip_weight(value)}
    for key, value in patch.items():
        clipped = _clip_weight(value)
        if key in (None, ""):
            continue
        if clipped:
            merged[str(key)] = clipped
        else:
            merged.pop(str(key), None)
    return merged


def _clip_weight(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    numeric = max(min(numeric, 0.2), -0.2)
    return round(numeric, 3)
