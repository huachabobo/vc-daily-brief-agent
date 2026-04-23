from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from vc_agent.pipeline.run_once import load_sources
from vc_agent.profile import load_user_profile, merge_profile_patch, save_user_profile
from vc_agent.profile_nlp import PreferenceCompiler
from vc_agent.ranking.rules import TOPIC_KEYWORDS
from vc_agent.settings import Settings
from vc_agent.utils.text import normalize_text


@dataclass
class PreferenceMessageResult:
    should_reply: bool
    reply_text: str
    updated: bool = False


def handle_preference_message(settings: Settings, body: Dict[str, Any]) -> PreferenceMessageResult:
    if _extract_sender_type(body) != "user":
        return PreferenceMessageResult(should_reply=False, reply_text="")

    chat_type = _extract_chat_type(body)
    if chat_type and chat_type != "p2p":
        return PreferenceMessageResult(
            should_reply=True,
            reply_text="当前只支持私聊设置偏好。请在和机器人私聊时直接发送你的偏好描述。",
        )

    message_type = _extract_message_type(body)
    if message_type != "text":
        return PreferenceMessageResult(
            should_reply=True,
            reply_text="目前只支持文本消息设置偏好。你可以直接发：更关注 AI 和机器人，优先 NVIDIA，日报控制在 5 条。",
        )

    text = _extract_text_message(body)
    if not text:
        return PreferenceMessageResult(
            should_reply=True,
            reply_text="我没有读到有效的文本内容。你可以直接发：更关注芯片和机器人，少给我 benchmark。",
        )

    if _is_help_request(text):
        return PreferenceMessageResult(should_reply=True, reply_text=_help_text())

    if not _looks_like_preference(text):
        return PreferenceMessageResult(
            should_reply=True,
            reply_text=(
                "我现在支持用自然语言更新偏好。示例：\n"
                "更关注 AI infra 和机器人商业化落地，优先 NVIDIA、SemiEngineering，少给我纯学术 benchmark，日报控制在 5 条。"
            ),
        )

    current_profile = load_user_profile(settings.user_profile_config)
    available_sources = [source.name for source in load_sources(settings.sources_config) if source.active]
    available_topics = list(TOPIC_KEYWORDS.keys())
    compiler = PreferenceCompiler(settings)
    compiled = compiler.compile(text, current_profile, available_topics, available_sources)
    updated_profile = merge_profile_patch(current_profile, compiled.patch)
    save_user_profile(settings.user_profile_config, updated_profile)

    return PreferenceMessageResult(
        should_reply=True,
        updated=True,
        reply_text=_render_update_reply(compiled.mode, compiled.patch, updated_profile),
    )


def _extract_sender_type(body: Dict[str, Any]) -> str:
    return str(body.get("event", {}).get("sender", {}).get("sender_type") or "")


def _extract_chat_type(body: Dict[str, Any]) -> str:
    return str(body.get("event", {}).get("message", {}).get("chat_type") or "")


def _extract_message_type(body: Dict[str, Any]) -> str:
    return str(body.get("event", {}).get("message", {}).get("message_type") or "")


def _extract_text_message(body: Dict[str, Any]) -> str:
    raw = body.get("event", {}).get("message", {}).get("content")
    if not raw:
        return ""
    if isinstance(raw, dict):
        return str(raw.get("text") or "").strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return str(parsed.get("text") or "").strip()
    except Exception:
        pass
    return str(raw).strip()


def _is_help_request(text: str) -> bool:
    lowered = normalize_text(text)
    return lowered in {"help", "帮助", "怎么用", "使用说明", "说明"} or "帮助" in lowered


def _looks_like_preference(text: str) -> bool:
    lowered = normalize_text(text)
    markers = [
        "关注",
        "优先",
        "少给我",
        "少看",
        "不要看",
        "屏蔽",
        "不想看",
        "日报",
        "探索位",
        "benchmark",
        "ai",
        "机器人",
        "芯片",
        "nvidia",
        "asianometry",
        "semiengineering",
    ]
    return any(marker in lowered for marker in markers)


def _help_text() -> str:
    return (
        "可以直接发自然语言偏好，我会更新后续推荐。例如：\n"
        "1. 更关注 AI infra 和机器人商业化落地\n"
        "2. 优先 NVIDIA、SemiEngineering\n"
        "3. 少给我 benchmark，日报控制在 5 条\n"
        "更新后会写入画像配置，并在下一次日报生成时生效。"
    )


def _render_update_reply(mode: str, patch, updated_profile) -> str:
    lines: List[str] = ["已更新偏好，下次日报会按新画像排序。", "解析方式: {0}".format(mode)]
    if patch.add_focus_topics:
        lines.append("关注赛道: {0}".format("、".join(patch.add_focus_topics)))
    if patch.add_preferred_sources:
        lines.append("优先来源: {0}".format("、".join(patch.add_preferred_sources)))
    if patch.add_blocked_sources:
        lines.append("屏蔽来源: {0}".format("、".join(patch.add_blocked_sources)))
    if patch.add_blocked_keywords:
        lines.append("屏蔽关键词: {0}".format("、".join(patch.add_blocked_keywords)))
    if patch.keyword_weight_overrides:
        lowered = [key for key, value in patch.keyword_weight_overrides.items() if value < 0]
        raised = [key for key, value in patch.keyword_weight_overrides.items() if value > 0]
        if raised:
            lines.append("提升关键词: {0}".format("、".join(raised)))
        if lowered:
            lines.append("降低关键词: {0}".format("、".join(lowered)))
    if patch.max_brief_items is not None:
        lines.append("日报条数: {0}".format(patch.max_brief_items))
    if patch.exploration_slots is not None:
        lines.append("探索位: {0}".format(patch.exploration_slots))
    lines.append("当前重点来源: {0}".format("、".join(updated_profile.preferred_sources) or "未设置"))
    return "\n".join(lines)
