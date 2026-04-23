from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Dict, List

import requests

from vc_agent.profile import UserProfile, UserProfilePatch
from vc_agent.settings import Settings
from vc_agent.utils.text import normalize_text


LOGGER = logging.getLogger(__name__)

TOPIC_ALIASES = {
    "AI": ["ai", "llm", "agent", "模型", "多模态", "infra", "inference", "reasoning", "算力"],
    "芯片": ["芯片", "半导体", "chip", "gpu", "hbm", "semiconductor", "先进制程", "封装"],
    "机器人": ["机器人", "具身", "humanoid", "robot", "robotics", "automation", "人形机器人"],
}


@dataclass
class CompiledPreference:
    patch: UserProfilePatch
    mode: str


class PreferenceCompiler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()

    def compile(
        self,
        text: str,
        current_profile: UserProfile,
        available_topics: List[str],
        available_sources: List[str],
    ) -> CompiledPreference:
        if self.settings.has_openai:
            try:
                patch = self._compile_with_llm(text, current_profile, available_topics, available_sources)
                return CompiledPreference(patch=patch, mode="llm")
            except Exception as exc:
                LOGGER.warning("自然语言偏好解析失败，降级到启发式规则: %s", exc)
        patch = self._compile_with_heuristics(text, available_topics, available_sources)
        return CompiledPreference(patch=patch, mode="heuristic")

    def _compile_with_llm(
        self,
        text: str,
        current_profile: UserProfile,
        available_topics: List[str],
        available_sources: List[str],
    ) -> UserProfilePatch:
        url = self.settings.openai_base_url.rstrip("/") + "/chat/completions"
        prompt = (
            "你是推荐系统的偏好编译器。把用户的自然语言偏好翻译成 JSON patch。"
            "只输出 JSON。字段必须使用："
            "add_focus_topics, remove_focus_topics, add_blocked_topics, remove_blocked_topics, "
            "add_preferred_sources, remove_preferred_sources, add_blocked_sources, remove_blocked_sources, "
            "add_blocked_keywords, remove_blocked_keywords, topic_weight_overrides, source_weight_overrides, "
            "keyword_weight_overrides, max_brief_items, exploration_slots, rationale。"
            "topic/source 权重范围 -0.2 到 0.2，正数表示提升，负数表示降权。"
            "只有在用户明确表达‘不要看/屏蔽’时才使用 blocked_*；"
            "‘多关注/少给我’优先翻译成 focus/preferred 或 weight_overrides。"
            "max_brief_items 只在用户明确提到条数时填写；exploration_slots 只在用户明确提到探索位时填写。"
            "优先使用给定的 canonical topic/source 名称。"
        )
        content = {
            "user_text": text,
            "available_topics": available_topics,
            "available_sources": available_sources,
            "current_profile": {
                "focus_topics": current_profile.focus_topics,
                "blocked_topics": current_profile.blocked_topics,
                "preferred_sources": current_profile.preferred_sources,
                "blocked_sources": current_profile.blocked_sources,
                "blocked_keywords": current_profile.blocked_keywords,
                "topic_weight_overrides": current_profile.topic_weight_overrides,
                "source_weight_overrides": current_profile.source_weight_overrides,
                "keyword_weight_overrides": current_profile.keyword_weight_overrides,
                "max_brief_items": current_profile.max_brief_items,
                "exploration_slots": current_profile.exploration_slots,
            },
        }
        response = self.session.post(
            url,
            headers={
                "Authorization": "Bearer {0}".format(self.settings.openai_api_key),
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.openai_model,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(content, ensure_ascii=False)},
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        raw_content = payload["choices"][0]["message"]["content"]
        return _sanitize_patch(json.loads(raw_content), available_topics, available_sources)

    def _compile_with_heuristics(
        self,
        text: str,
        available_topics: List[str],
        available_sources: List[str],
    ) -> UserProfilePatch:
        normalized = normalize_text(text)
        patch = UserProfilePatch(rationale="使用启发式规则解析自然语言偏好。")

        for topic in available_topics:
            aliases = TOPIC_ALIASES.get(topic, [topic])
            if any(alias in normalized for alias in [normalize_text(value) for value in aliases]):
                patch.add_focus_topics.append(topic)
                patch.topic_weight_overrides[topic] = 0.08

        source_lookup = {normalize_text(source): source for source in available_sources}
        for normalized_source, source in source_lookup.items():
            if normalized_source and normalized_source in normalized:
                if any(marker in normalized for marker in ("不要", "屏蔽", "不想看", "拉黑")):
                    patch.add_blocked_sources.append(source)
                else:
                    patch.add_preferred_sources.append(source)
                    patch.source_weight_overrides[source] = 0.1

        for raw_chunk in _extract_keyword_chunks(text, ("多给我", "更关注", "优先", "多看")):
            for keyword in _split_keywords(raw_chunk):
                patch.keyword_weight_overrides[keyword] = 0.08

        for raw_chunk in _extract_keyword_chunks(text, ("少给我", "少看", "降低", "弱化")):
            for keyword in _split_keywords(raw_chunk):
                patch.keyword_weight_overrides[keyword] = -0.08

        for raw_chunk in _extract_keyword_chunks(text, ("不要看", "屏蔽", "过滤掉")):
            for keyword in _split_keywords(raw_chunk):
                patch.add_blocked_keywords.append(keyword)

        count_match = re.search(r"(\d+)\s*条", text)
        if count_match:
            patch.max_brief_items = int(count_match.group(1))

        explore_match = re.search(r"(\d+)\s*个探索", text)
        if explore_match:
            patch.exploration_slots = int(explore_match.group(1))

        return _sanitize_patch(patch.__dict__, available_topics, available_sources)


def render_patch_summary(compiled: CompiledPreference) -> str:
    patch = compiled.patch
    lines = ["解析方式: {0}".format(compiled.mode)]
    if patch.rationale:
        lines.append("解释: {0}".format(patch.rationale))
    for label, values in (
        ("新增 focus_topics", patch.add_focus_topics),
        ("移除 focus_topics", patch.remove_focus_topics),
        ("新增 preferred_sources", patch.add_preferred_sources),
        ("新增 blocked_sources", patch.add_blocked_sources),
        ("新增 blocked_keywords", patch.add_blocked_keywords),
    ):
        if values:
            lines.append("{0}: {1}".format(label, ", ".join(values)))
    if patch.topic_weight_overrides:
        lines.append("topic_weight_overrides: {0}".format(json.dumps(patch.topic_weight_overrides, ensure_ascii=False)))
    if patch.source_weight_overrides:
        lines.append("source_weight_overrides: {0}".format(json.dumps(patch.source_weight_overrides, ensure_ascii=False)))
    if patch.keyword_weight_overrides:
        lines.append("keyword_weight_overrides: {0}".format(json.dumps(patch.keyword_weight_overrides, ensure_ascii=False)))
    if patch.max_brief_items is not None:
        lines.append("max_brief_items: {0}".format(patch.max_brief_items))
    if patch.exploration_slots is not None:
        lines.append("exploration_slots: {0}".format(patch.exploration_slots))
    return "\n".join(lines)


def _sanitize_patch(payload: Dict[str, object], available_topics: List[str], available_sources: List[str]) -> UserProfilePatch:
    topic_lookup = {normalize_text(topic): topic for topic in available_topics}
    source_lookup = {normalize_text(source): source for source in available_sources}
    patch = UserProfilePatch(
        add_focus_topics=_map_labels(payload.get("add_focus_topics"), topic_lookup),
        remove_focus_topics=_map_labels(payload.get("remove_focus_topics"), topic_lookup),
        add_blocked_topics=_map_labels(payload.get("add_blocked_topics"), topic_lookup),
        remove_blocked_topics=_map_labels(payload.get("remove_blocked_topics"), topic_lookup),
        add_preferred_sources=_map_labels(payload.get("add_preferred_sources"), source_lookup),
        remove_preferred_sources=_map_labels(payload.get("remove_preferred_sources"), source_lookup),
        add_blocked_sources=_map_labels(payload.get("add_blocked_sources"), source_lookup),
        remove_blocked_sources=_map_labels(payload.get("remove_blocked_sources"), source_lookup),
        add_blocked_keywords=_coerce_str_list(payload.get("add_blocked_keywords")),
        remove_blocked_keywords=_coerce_str_list(payload.get("remove_blocked_keywords")),
        topic_weight_overrides=_sanitize_weight_map(payload.get("topic_weight_overrides"), topic_lookup),
        source_weight_overrides=_sanitize_weight_map(payload.get("source_weight_overrides"), source_lookup),
        keyword_weight_overrides=_sanitize_free_weight_map(payload.get("keyword_weight_overrides")),
        rationale=str(payload.get("rationale") or "").strip(),
    )
    if payload.get("max_brief_items") not in (None, ""):
        patch.max_brief_items = max(3, min(int(payload["max_brief_items"]), 10))
    if payload.get("exploration_slots") not in (None, ""):
        patch.exploration_slots = max(0, min(int(payload["exploration_slots"]), 3))
    return patch


def _map_labels(raw_value: object, lookup: Dict[str, str]) -> List[str]:
    values = []
    for item in _coerce_str_list(raw_value):
        mapped = lookup.get(normalize_text(item))
        if mapped and mapped not in values:
            values.append(mapped)
    return values


def _coerce_str_list(raw_value: object) -> List[str]:
    if not isinstance(raw_value, list):
        return []
    values = []
    for item in raw_value:
        text = str(item).strip()
        if text and text not in values:
            values.append(text)
    return values


def _sanitize_weight_map(raw_value: object, lookup: Dict[str, str]) -> Dict[str, float]:
    if not isinstance(raw_value, dict):
        return {}
    cleaned: Dict[str, float] = {}
    for key, value in raw_value.items():
        mapped = lookup.get(normalize_text(str(key)))
        if mapped is None:
            continue
        clipped = _clip_weight(value)
        if clipped:
            cleaned[mapped] = clipped
    return cleaned


def _sanitize_free_weight_map(raw_value: object) -> Dict[str, float]:
    if not isinstance(raw_value, dict):
        return {}
    cleaned: Dict[str, float] = {}
    for key, value in raw_value.items():
        label = str(key).strip()
        if not label:
            continue
        clipped = _clip_weight(value)
        if clipped:
            cleaned[label] = clipped
    return cleaned


def _clip_weight(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    numeric = max(min(numeric, 0.2), -0.2)
    return round(numeric, 3)


def _extract_keyword_chunks(text: str, markers: tuple[str, ...]) -> List[str]:
    chunks: List[str] = []
    for marker in markers:
        for match in re.finditer(re.escape(marker) + r"([^。！!？?\n]+)", text):
            chunks.append(match.group(1))
    return chunks


def _split_keywords(raw: str) -> List[str]:
    values = []
    for part in re.split(r"[、/,，；;和及 ]+", raw):
        text = part.strip()
        if len(text) >= 2 and text not in values:
            values.append(text)
    return values[:5]
