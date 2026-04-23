from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import requests

from vc_agent.feedback.message_preferences import handle_preference_message, looks_like_preference_message
from vc_agent.feedback.schedule_commands import (
    handle_schedule_message,
    looks_like_generate_now_message,
    looks_like_schedule_message,
)
from vc_agent.settings import Settings
from vc_agent.utils.text import compact_sentence, normalize_text


LOGGER = logging.getLogger(__name__)

ALLOWED_TOOLS = {"schedule", "preference", "generate_now"}


@dataclass
class IntentAgentExecution:
    handled: bool = False
    reply_texts: list[str] = field(default_factory=list)
    reply_card: dict | None = None
    trigger_generate_now: bool = False


def handle_message_with_intent_agent(settings: Settings, body: dict[str, Any]) -> IntentAgentExecution:
    text = _extract_text_message(body)
    if not text:
        return IntentAgentExecution()

    planned_tools = _plan_tools(settings, text)
    if not planned_tools:
        chat_reply = _reply_to_general_chat(settings, text)
        if chat_reply:
            return IntentAgentExecution(handled=True, reply_texts=[chat_reply])
        return IntentAgentExecution()

    execution = IntentAgentExecution(handled=True)
    notes: list[str] = []

    for tool_name in planned_tools:
        if tool_name == "schedule":
            result = handle_schedule_message(settings, body)
            if not result.handled:
                continue
            if result.reply_text:
                notes.append("schedule: {0}".format(result.reply_text))
                execution.reply_texts.append(result.reply_text)
            if result.trigger_generate_now:
                execution.trigger_generate_now = True
            continue

        if tool_name == "preference":
            result = handle_preference_message(settings, body)
            if not result.should_reply:
                continue
            if result.reply_text:
                notes.append("preference: {0}".format(result.reply_text))
            if result.reply_card:
                execution.reply_card = result.reply_card
            elif result.reply_text:
                execution.reply_texts.append(result.reply_text)
            continue

        if tool_name == "generate_now":
            execution.trigger_generate_now = True
            notes.append("generate_now: 立即生成并发送一版最新日报。")

    if not notes and not execution.reply_card and not execution.trigger_generate_now:
        return IntentAgentExecution()

    if settings.has_openai and len(notes) > 1:
        summary = _summarize_execution(settings, text, notes)
        if summary:
            execution.reply_texts = [summary] + execution.reply_texts

    if execution.trigger_generate_now and not any("开始生成" in text for text in execution.reply_texts):
        execution.reply_texts.append("收到，我会按你的意思继续处理，生成完成后再把结果汇总给你。")

    return execution


def _plan_tools(settings: Settings, text: str) -> list[str]:
    heuristic_tools = _plan_tools_with_heuristics(text)
    if heuristic_tools:
        return heuristic_tools
    if settings.has_openai:
        try:
            tools = _plan_tools_with_llm(settings, text)
            if tools:
                return tools
        except Exception as exc:
            LOGGER.warning("意图调度器规划失败，降级到传统路由: %s", exc)
    return []


def _plan_tools_with_heuristics(text: str) -> list[str]:
    tools: list[str] = []
    if looks_like_schedule_message(text):
        tools.append("schedule")
    if looks_like_preference_message(text):
        tools.append("preference")
    if looks_like_generate_now_message(text):
        tools.append("generate_now")
    return tools


def _plan_tools_with_llm(settings: Settings, text: str) -> list[str]:
    session = requests.Session()
    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    prompt = (
        "你是一个消息意图调度器。请根据用户消息，决定要按什么顺序调用内部工具。"
        "只输出 JSON，字段只能是 tools。"
        "tools 必须是数组，元素只能从 schedule, preference, generate_now 里选。"
        "schedule: 调整/查看/暂停/恢复每日推送或按周规则。"
        "preference: 调整简报条数、关注主题、来源偏好、查看偏好、撤销偏好、确认/取消偏好。"
        "generate_now: 立即生成并发送一版最新日报。"
        "如果一句话同时涉及多件事，可以返回多个工具，按执行顺序排列。"
        "如果只是闲聊或没有明确操作意图，返回空数组。"
    )
    response = session.post(
        url,
        headers={
            "Authorization": "Bearer {0}".format(settings.openai_api_key),
            "Content-Type": "application/json",
        },
        json={
            "model": settings.openai_model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps({"user_text": text}, ensure_ascii=False)},
            ],
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    content = json.loads(payload["choices"][0]["message"]["content"])
    raw_tools = content.get("tools")
    if not isinstance(raw_tools, list):
        return []
    tools: list[str] = []
    for item in raw_tools:
        label = normalize_text(str(item))
        if label in ALLOWED_TOOLS and label not in tools:
            tools.append(label)
    return tools


def _summarize_execution(settings: Settings, user_text: str, notes: list[str]) -> str:
    fallback = "；".join(notes)
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
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是飞书里的 VC Agent。请把内部工具执行结果汇总成一段中文回复。"
                        "要求：100字以内，说明已经做了什么、接下来会发生什么。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"user_text": user_text, "notes": notes, "fallback": fallback}, ensure_ascii=False),
                },
            ],
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    message = payload["choices"][0]["message"]["content"].strip()
    return compact_sentence(message or fallback, limit=120)


def _reply_to_general_chat(settings: Settings, text: str) -> str:
    fallback = _fallback_chat_reply(text)
    if not settings.has_openai:
        return fallback
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
            "temperature": 0.4,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是飞书里的 VC Daily Brief Agent。"
                        "当用户只是聊天、问你是谁、问你能做什么时，请自然地用中文回复。"
                        "语气友好、简洁，80字以内；如果合适，顺带说明你能帮他调推送时间、改内容偏好、立即生成日报。"
                    ),
                },
                {"role": "user", "content": text},
            ],
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    message = payload["choices"][0]["message"]["content"].strip()
    return compact_sentence(message or fallback, limit=120)


def _fallback_chat_reply(text: str) -> str:
    lowered = normalize_text(text)
    if any(marker in lowered for marker in ["你是谁", "你是什么", "what are you", "who are you"]):
        return "我是你的 VC Daily Brief 助手，能帮你调推送时间、改内容偏好，也能立刻生成一版日报。"
    if any(marker in lowered for marker in ["能做什么", "可以做什么", "help", "帮助"]):
        return "我可以帮你改日报推送时间、调整关注方向和条数，还能马上生成并发送一版最新日报。"
    return "我在，除了聊天，也能帮你改推送时间、调内容偏好，或者现在就生成一版日报。"


def _extract_text_message(body: dict[str, Any]) -> str:
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
