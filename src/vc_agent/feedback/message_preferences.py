from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from vc_agent.feedback.preference_assistant_state import (
    PendingPreferenceUpdate,
    PreferenceAssistantStateStore,
    PreferenceHistoryEntry,
)
from vc_agent.pipeline.run_once import load_sources
from vc_agent.profile import UserProfile, load_user_profile, merge_profile_patch, save_user_profile
from vc_agent.profile_nlp import CompiledPreference, PreferenceCompiler
from vc_agent.ranking.rules import TOPIC_KEYWORDS
from vc_agent.settings import Settings
from vc_agent.utils.text import compact_sentence, normalize_text


LOGGER = logging.getLogger(__name__)


@dataclass
class PreferenceMessageResult:
    should_reply: bool
    reply_text: str
    updated: bool = False
    reply_card: Optional[dict] = None


@dataclass
class PreferenceCardActionResult:
    toast_content: str
    reply_text: Optional[str] = None


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

    user_key = _extract_user_key(body) or _extract_chat_id(body) or "default"
    state_store = PreferenceAssistantStateStore(_assistant_state_path(settings))

    if _is_help_request(text):
        return PreferenceMessageResult(should_reply=True, reply_text=_help_text())

    if _is_show_profile_request(text):
        profile = load_user_profile(settings.user_profile_config)
        pending = state_store.get_pending(user_key)
        return PreferenceMessageResult(
            should_reply=True,
            reply_text=compose_profile_summary_reply(settings, profile, pending=pending),
        )

    if _is_undo_request(text):
        history = state_store.pop_history(user_key)
        if history is None:
            return PreferenceMessageResult(
                should_reply=True,
                reply_text="还没有可撤销的偏好修改。你可以先发一条新的偏好描述，我会先给你预览，再等你确认。",
            )
        save_user_profile(settings.user_profile_config, history.previous_profile)
        state_store.clear_pending(user_key)
        return PreferenceMessageResult(
            should_reply=True,
            updated=True,
            reply_text=compose_undo_reply(settings, history.previous_profile),
        )

    if _is_cancel_request(text):
        pending = state_store.get_pending(user_key)
        if pending is None:
            return PreferenceMessageResult(
                should_reply=True,
                reply_text="当前没有待确认的偏好修改。你可以直接发新的偏好描述，或者发“查看当前偏好”。",
            )
        state_store.clear_pending(user_key)
        return PreferenceMessageResult(
            should_reply=True,
            reply_text="好的，这次预览我先取消，不会改你的推荐偏好。想继续的话，随时再发一条新的偏好描述就行。",
        )

    if _is_confirm_request(text):
        pending = state_store.get_pending(user_key)
        if pending is None:
            return PreferenceMessageResult(
                should_reply=True,
                reply_text="我这边没有待确认的偏好修改。你可以先发一条偏好描述，我会先解释我的理解，再等你确认应用。",
            )
        current_profile = load_user_profile(settings.user_profile_config)
        state_store.append_history(
            user_key,
            PreferenceHistoryEntry(
                previous_profile=current_profile,
                user_text=pending.user_text,
                mode=pending.mode,
            ),
        )
        updated_profile = merge_profile_patch(current_profile, pending.patch)
        save_user_profile(settings.user_profile_config, updated_profile)
        state_store.clear_pending(user_key)
        return PreferenceMessageResult(
            should_reply=True,
            updated=True,
            reply_text=compose_update_reply(
                settings,
                pending.user_text,
                CompiledPreference(mode=pending.mode, patch=pending.patch),
                updated_profile,
            ),
        )

    if not _looks_like_preference(text):
        return PreferenceMessageResult(
            should_reply=True,
            reply_text=(
                "我现在支持三类偏好操作：直接描述偏好、查看当前偏好、撤销上一次偏好修改。"
                "例如你可以发：更关注 AI infra 和机器人商业化落地，优先 NVIDIA，日报控制在 5 条。"
            ),
        )

    current_profile = load_user_profile(settings.user_profile_config)
    available_sources = [source.name for source in load_sources(settings.sources_config) if source.active]
    available_topics = list(TOPIC_KEYWORDS.keys())
    compiler = PreferenceCompiler(settings)
    compiled = compiler.compile(text, current_profile, available_topics, available_sources)
    if not _patch_has_effect(compiled.patch):
        return PreferenceMessageResult(
            should_reply=True,
            reply_text="我这次还没解析出明确的偏好改动。你可以试着更具体一点，比如：优先 NVIDIA，少给我 benchmark，日报控制在 5 条。",
        )

    state_store.set_pending(
        PendingPreferenceUpdate(
            user_key=user_key,
            user_text=text,
            mode=compiled.mode,
            patch=compiled.patch,
        )
    )
    preview_text = compose_preview_reply(settings, text, compiled, current_profile)
    return PreferenceMessageResult(
        should_reply=True,
        reply_text=preview_text,
        reply_card=build_preview_card(preview_text),
    )


def handle_preference_card_action(settings: Settings, body: Dict[str, Any]) -> PreferenceCardActionResult:
    action = _extract_card_action(body)
    operator_open_id = _extract_operator_open_id(body)
    if not operator_open_id:
        return PreferenceCardActionResult(toast_content="没有识别到当前操作者，暂时无法执行。")

    state_store = PreferenceAssistantStateStore(_assistant_state_path(settings))

    if action == "confirm_pending":
        pending = state_store.get_pending(operator_open_id)
        if pending is None:
            return PreferenceCardActionResult(
                toast_content="当前没有待确认的偏好修改。",
                reply_text="我这边没有待确认的偏好修改。你可以先发一条新的偏好描述，我会先给你预览。",
            )
        current_profile = load_user_profile(settings.user_profile_config)
        state_store.append_history(
            operator_open_id,
            PreferenceHistoryEntry(
                previous_profile=current_profile,
                user_text=pending.user_text,
                mode=pending.mode,
            ),
        )
        updated_profile = merge_profile_patch(current_profile, pending.patch)
        save_user_profile(settings.user_profile_config, updated_profile)
        state_store.clear_pending(operator_open_id)
        return PreferenceCardActionResult(
            toast_content="偏好已更新",
            reply_text=compose_update_reply(
                settings,
                pending.user_text,
                CompiledPreference(mode=pending.mode, patch=pending.patch),
                updated_profile,
            ),
        )

    if action == "cancel_pending":
        pending = state_store.get_pending(operator_open_id)
        if pending is None:
            return PreferenceCardActionResult(
                toast_content="没有待取消的修改。",
                reply_text="当前没有待确认的偏好修改。你可以直接发新的偏好描述，或者发“查看当前偏好”。",
            )
        state_store.clear_pending(operator_open_id)
        return PreferenceCardActionResult(
            toast_content="已取消这次修改",
            reply_text="好的，这次预览我先取消，不会改你的推荐偏好。想继续的话，随时再发一条新的偏好描述就行。",
        )

    if action == "show_profile":
        profile = load_user_profile(settings.user_profile_config)
        pending = state_store.get_pending(operator_open_id)
        return PreferenceCardActionResult(
            toast_content="已发送当前偏好",
            reply_text=compose_profile_summary_reply(settings, profile, pending=pending),
        )

    return PreferenceCardActionResult(toast_content="暂不支持这个按钮动作。")


def compose_update_reply(settings: Settings, user_text: str, compiled: CompiledPreference, updated_profile: UserProfile) -> str:
    fallback = _render_update_reply(compiled.mode, compiled.patch, updated_profile)
    prompt = (
        "你是 VC 信息 Agent 的飞书机器人。"
        "请根据用户刚刚的偏好描述和系统解析结果，回复一段自然语言中文确认消息。"
        "要求：100 字以内，语气自然、简洁，不要使用 markdown 列表，不要编造未发生的改动，"
        "要明确说明已更新偏好并且会影响下一次日报。"
    )
    content = {
        "user_text": user_text,
        "mode": compiled.mode,
        "patch": _compiled_patch_payload(compiled.patch),
        "updated_profile": _profile_summary_payload(updated_profile),
        "fallback": fallback,
    }
    return _generate_reply_with_llm(settings, prompt, content, fallback=fallback, limit=120)


def compose_preview_reply(settings: Settings, user_text: str, compiled: CompiledPreference, current_profile: UserProfile) -> str:
    fallback = _render_preview_reply(compiled.mode, compiled.patch, current_profile)
    prompt = (
        "你是 VC 信息 Agent 的飞书机器人。"
        "请先用自然语言复述你对用户偏好的理解，再提醒对方回复“确认应用”或“取消”。"
        "要求：120 字以内，语气自然、清晰，不要编造未解析出来的偏好。"
    )
    content = {
        "user_text": user_text,
        "mode": compiled.mode,
        "patch": _compiled_patch_payload(compiled.patch),
        "current_profile": _profile_summary_payload(current_profile),
        "fallback": fallback,
    }
    return _generate_reply_with_llm(settings, prompt, content, fallback=fallback, limit=150)


def compose_profile_summary_reply(
    settings: Settings,
    profile: UserProfile,
    pending: Optional[PendingPreferenceUpdate] = None,
) -> str:
    fallback = _render_profile_summary_reply(profile, pending)
    prompt = (
        "你是 VC 信息 Agent 的飞书机器人。"
        "请把用户当前偏好总结成一段自然语言中文。"
        "要求：120 字以内，说明重点赛道、优先来源、屏蔽项和日报设置；"
        "如果有待确认修改，也顺带提醒用户回复“确认应用”或“取消”。"
    )
    content = {
        "profile": _profile_summary_payload(profile),
        "pending": None
        if pending is None
        else {
            "mode": pending.mode,
            "user_text": pending.user_text,
            "patch": _compiled_patch_payload(pending.patch),
        },
        "fallback": fallback,
    }
    return _generate_reply_with_llm(settings, prompt, content, fallback=fallback, limit=150)


def compose_undo_reply(settings: Settings, restored_profile: UserProfile) -> str:
    fallback = _render_undo_reply(restored_profile)
    prompt = (
        "你是 VC 信息 Agent 的飞书机器人。"
        "请告诉用户你已经撤销了上一次偏好修改，并简短说明当前恢复后的偏好状态。"
        "要求：100 字以内，中文，自然、不使用列表。"
    )
    content = {
        "restored_profile": _profile_summary_payload(restored_profile),
        "fallback": fallback,
    }
    return _generate_reply_with_llm(settings, prompt, content, fallback=fallback, limit=120)


def _generate_reply_with_llm(settings: Settings, prompt: str, content: dict, fallback: str, limit: int) -> str:
    if not settings.has_openai:
        return fallback
    try:
        session = requests.Session()
        url = settings.openai_base_url.rstrip("/") + "/chat/completions"
        response = session.post(
            url,
            headers={
                "Authorization": "Bearer {0}".format(settings.openai_api_key),
                "Content-Type": "application/json",
            },
            json={
                "model": settings.openai_model,
                "temperature": 0.3,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(content, ensure_ascii=False)},
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        message = payload["choices"][0]["message"]["content"].strip()
        if not message:
            raise ValueError("LLM reply is empty")
        return compact_sentence(message, limit=limit)
    except Exception as exc:
        LOGGER.warning("自然语言偏好回复生成失败，降级到模板回复: %s", exc)
        return fallback


def _render_update_reply(mode: str, patch, updated_profile: UserProfile) -> str:
    lines = ["已更新偏好，下次日报会按新画像排序。", "解析方式: {0}".format(mode)]
    if patch.add_focus_topics:
        lines.append("关注赛道: {0}".format("、".join(patch.add_focus_topics)))
    if patch.add_preferred_sources:
        lines.append("优先来源: {0}".format("、".join(patch.add_preferred_sources)))
    if patch.add_preferred_keywords:
        lines.append("偏好关键词: {0}".format("、".join(patch.add_preferred_keywords)))
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


def _render_preview_reply(mode: str, patch, current_profile: UserProfile) -> str:
    lines = ["我先确认一下我的理解："]
    if patch.add_focus_topics:
        lines.append("你想更关注 {0}。".format("、".join(patch.add_focus_topics)))
    if patch.add_preferred_sources:
        lines.append("你想优先看 {0}。".format("、".join(patch.add_preferred_sources)))
    if patch.add_preferred_keywords:
        lines.append("你尤其想多看 {0}。".format("、".join(patch.add_preferred_keywords)))
    if patch.add_blocked_sources:
        lines.append("你想屏蔽 {0}。".format("、".join(patch.add_blocked_sources)))
    lowered = [key for key, value in patch.keyword_weight_overrides.items() if value < 0]
    raised = [key for key, value in patch.keyword_weight_overrides.items() if value > 0]
    if raised:
        lines.append("我会提高 {0} 相关内容权重。".format("、".join(raised)))
    if lowered:
        lines.append("我会降低 {0} 相关内容权重。".format("、".join(lowered)))
    if patch.max_brief_items is not None:
        lines.append("日报条数会调整到 {0} 条。".format(patch.max_brief_items))
    if patch.exploration_slots is not None:
        lines.append("探索位会设为 {0} 个。".format(patch.exploration_slots))
    if len(lines) == 1:
        lines.append("我解析到你想调整推荐偏好。")
    lines.append("如果没问题，回复“确认应用”；如果想放弃这次修改，回复“取消”。")
    lines.append("当前重点来源: {0}".format("、".join(current_profile.preferred_sources) or "未设置"))
    lines.append("解析方式: {0}".format(mode))
    return "\n".join(lines)


def _render_profile_summary_reply(profile: UserProfile, pending: Optional[PendingPreferenceUpdate]) -> str:
    lines = ["当前你的偏好大致是这样："]
    lines.append("重点赛道: {0}".format("、".join(profile.focus_topics) or "未设置"))
    lines.append("优先来源: {0}".format("、".join(profile.preferred_sources) or "未设置"))
    if profile.preferred_keywords:
        lines.append("偏好关键词: {0}".format("、".join(profile.preferred_keywords)))
    if profile.blocked_sources:
        lines.append("屏蔽来源: {0}".format("、".join(profile.blocked_sources)))
    if profile.blocked_keywords:
        lines.append("屏蔽关键词: {0}".format("、".join(profile.blocked_keywords)))
    lines.append("日报条数: {0}".format(profile.max_brief_items or "默认"))
    lines.append("探索位: {0}".format(profile.exploration_slots if profile.exploration_slots is not None else "默认"))
    if pending is not None:
        lines.append("你还有一条待确认的偏好修改，回复“确认应用”或“取消”都可以。")
    return "\n".join(lines)


def _render_undo_reply(restored_profile: UserProfile) -> str:
    return "\n".join(
        [
            "已撤销上一次偏好修改，后续推荐会回到之前的画像设置。",
            "当前重点赛道: {0}".format("、".join(restored_profile.focus_topics) or "未设置"),
            "当前重点来源: {0}".format("、".join(restored_profile.preferred_sources) or "未设置"),
            "当前偏好关键词: {0}".format("、".join(restored_profile.preferred_keywords) or "未设置"),
        ]
    )


def build_preview_card(preview_text: str) -> dict:
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "wathet",
            "title": {"tag": "plain_text", "content": "偏好更新预览"},
        },
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": preview_text.replace("\n", "\n\n")},
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "确认应用"},
                        "type": "primary",
                        "value": {"assistant_action": "confirm_pending"},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "取消"},
                        "type": "default",
                        "value": {"assistant_action": "cancel_pending"},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "查看当前偏好"},
                        "type": "default",
                        "value": {"assistant_action": "show_profile"},
                    },
                ],
            },
        ],
    }


def _compiled_patch_payload(patch) -> dict:
    return {
        "add_focus_topics": patch.add_focus_topics,
        "add_preferred_sources": patch.add_preferred_sources,
        "add_preferred_keywords": patch.add_preferred_keywords,
        "add_blocked_sources": patch.add_blocked_sources,
        "add_blocked_keywords": patch.add_blocked_keywords,
        "topic_weight_overrides": patch.topic_weight_overrides,
        "source_weight_overrides": patch.source_weight_overrides,
        "keyword_weight_overrides": patch.keyword_weight_overrides,
        "max_brief_items": patch.max_brief_items,
        "exploration_slots": patch.exploration_slots,
        "rationale": patch.rationale,
    }


def _profile_summary_payload(profile: UserProfile) -> dict:
    return {
        "focus_topics": profile.focus_topics,
        "blocked_topics": profile.blocked_topics,
        "preferred_sources": profile.preferred_sources,
        "preferred_keywords": profile.preferred_keywords,
        "blocked_sources": profile.blocked_sources,
        "blocked_keywords": profile.blocked_keywords,
        "topic_weight_overrides": profile.topic_weight_overrides,
        "source_weight_overrides": profile.source_weight_overrides,
        "keyword_weight_overrides": profile.keyword_weight_overrides,
        "max_brief_items": profile.max_brief_items,
        "exploration_slots": profile.exploration_slots,
    }


def _extract_sender_type(body: Dict[str, Any]) -> str:
    return str(body.get("event", {}).get("sender", {}).get("sender_type") or "")


def _extract_chat_type(body: Dict[str, Any]) -> str:
    return str(body.get("event", {}).get("message", {}).get("chat_type") or "")


def _extract_message_type(body: Dict[str, Any]) -> str:
    return str(body.get("event", {}).get("message", {}).get("message_type") or "")


def _extract_chat_id(body: Dict[str, Any]) -> str:
    return str(body.get("event", {}).get("message", {}).get("chat_id") or "")


def _extract_user_key(body: Dict[str, Any]) -> str:
    sender_id = body.get("event", {}).get("sender", {}).get("sender_id", {})
    for key in ("open_id", "user_id", "union_id"):
        value = sender_id.get(key)
        if value:
            return str(value)
    return ""


def _extract_operator_open_id(body: Dict[str, Any]) -> str:
    return str(body.get("event", {}).get("operator", {}).get("open_id") or "")


def _extract_card_action(body: Dict[str, Any]) -> str:
    value = body.get("event", {}).get("action", {}).get("value", {})
    if not isinstance(value, dict):
        return ""
    return str(value.get("assistant_action") or "")


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


def _assistant_state_path(settings: Settings) -> Path:
    return settings.repo_root / "data" / "preference_assistant_state.json"


def _is_help_request(text: str) -> bool:
    lowered = normalize_text(text)
    return lowered in {"help", "帮助", "怎么用", "使用说明", "说明"} or "帮助" in lowered


def _is_show_profile_request(text: str) -> bool:
    lowered = normalize_text(text)
    markers = ["当前偏好", "我的偏好", "查看偏好", "看偏好", "show profile", "profile", "现在偏好"]
    return any(marker in lowered for marker in markers)


def _is_undo_request(text: str) -> bool:
    lowered = normalize_text(text)
    markers = ["撤销上一次偏好", "撤销上次偏好", "撤销上一次修改", "撤销上次修改", "undo", "回退上次偏好"]
    return any(marker in lowered for marker in markers)


def _is_confirm_request(text: str) -> bool:
    lowered = normalize_text(text)
    markers = {"确认", "确认应用", "应用", "就这样", "可以", "可以应用", "确认修改", "行", "好"}
    return lowered in markers


def _is_cancel_request(text: str) -> bool:
    lowered = normalize_text(text)
    markers = {"取消", "算了", "不用了", "别改了", "先别改"}
    return lowered in markers


def _looks_like_preference(text: str) -> bool:
    lowered = normalize_text(text)
    if re.search(r"(\d+)\s*条", lowered):
        return True
    markers = [
        "关注",
        "喜欢看",
        "想看",
        "多来点",
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


def _patch_has_effect(patch) -> bool:
    return any(
        [
            patch.add_focus_topics,
            patch.remove_focus_topics,
            patch.add_blocked_topics,
            patch.remove_blocked_topics,
            patch.add_preferred_sources,
            patch.remove_preferred_sources,
            patch.add_preferred_keywords,
            patch.remove_preferred_keywords,
            patch.add_blocked_sources,
            patch.remove_blocked_sources,
            patch.add_blocked_keywords,
            patch.remove_blocked_keywords,
            patch.topic_weight_overrides,
            patch.source_weight_overrides,
            patch.keyword_weight_overrides,
            patch.max_brief_items is not None,
            patch.exploration_slots is not None,
        ]
    )


def _help_text() -> str:
    return (
        "你可以像和助手聊天一样直接描述偏好，我会先复述理解，再等你回复“确认应用”或“取消”。\n"
        "另外也支持“查看当前偏好”和“撤销上一次偏好修改”。"
    )
