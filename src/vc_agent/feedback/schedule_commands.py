from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import requests

from vc_agent.delivery_preferences import (
    DeliveryPreferences,
    load_delivery_preferences,
    render_delivery_preferences,
    save_delivery_preferences,
)
from vc_agent.settings import Settings
from vc_agent.utils.text import normalize_text


LOGGER = logging.getLogger(__name__)


@dataclass
class ScheduleMessageResult:
    handled: bool
    reply_text: str = ""
    trigger_generate_now: bool = False


@dataclass
class CompiledDeliveryRequest:
    generate_now: bool = False
    show_schedule: bool = False
    enabled: Optional[bool] = None
    daily_time: Optional[str] = None
    rationale: str = ""


def handle_schedule_message(settings: Settings, body: dict[str, Any]) -> ScheduleMessageResult:
    if _extract_sender_type(body) != "user":
        return ScheduleMessageResult(handled=False)

    chat_type = _extract_chat_type(body)
    if chat_type and chat_type != "p2p":
        return ScheduleMessageResult(handled=False)

    if _extract_message_type(body) != "text":
        return ScheduleMessageResult(handled=False)

    text = _extract_text_message(body)
    if not text:
        return ScheduleMessageResult(handled=False)

    preferences = load_delivery_preferences(settings.delivery_preferences_path, settings.timezone)
    chat_id = _extract_chat_id(body)

    compiled = _compile_delivery_request(settings, text, preferences)
    if compiled.show_schedule:
        return ScheduleMessageResult(handled=True, reply_text=render_delivery_preferences(preferences))

    if compiled.generate_now:
        return ScheduleMessageResult(handled=True, trigger_generate_now=True)

    if compiled.enabled is False:
        preferences.enabled = False
        save_delivery_preferences(settings.delivery_preferences_path, preferences)
        return ScheduleMessageResult(
            handled=True,
            reply_text="好的，我先暂停每日自动推送。之后如果你想恢复，直接发“每天早上 8 点推送日报”之类的话就行。",
        )

    if compiled.daily_time or compiled.enabled is True:
        preferences.enabled = True if compiled.enabled is None else compiled.enabled
        if compiled.daily_time:
            preferences.daily_time = compiled.daily_time
        preferences.timezone = settings.timezone
        if chat_id:
            preferences.target_type = "chat_id"
            preferences.target_id = chat_id
        save_delivery_preferences(settings.delivery_preferences_path, preferences)
        return ScheduleMessageResult(
            handled=True,
            reply_text=(
                "好，我已经把每日自动推送改成每天 {0}，并绑定到当前会话。"
                "之后你继续用自然语言改内容偏好就行，比如“更关注机器人，日报控制在 5 条”。"
            ).format(preferences.daily_time),
        )

    return ScheduleMessageResult(handled=False)


def looks_like_generate_now_request(settings: Settings, body: dict[str, Any]) -> bool:
    if _extract_sender_type(body) != "user":
        return False
    if _extract_chat_type(body) not in {"", "p2p"}:
        return False
    if _extract_message_type(body) != "text":
        return False
    text = normalize_text(_extract_text_message(body))
    if _looks_like_generate_now_text(text):
        return True
    if not settings.has_openai:
        return False
    compiled = _compile_delivery_request_with_llm(
        settings,
        text,
        load_delivery_preferences(settings.delivery_preferences_path, settings.timezone),
    )
    return compiled.generate_now


def looks_like_preference_followup(text: str) -> bool:
    lowered = normalize_text(text)
    if re.search(r"(\d+)\s*条", lowered):
        return True
    markers = [
        "关注",
        "优先",
        "少给我",
        "少看",
        "不要看",
        "屏蔽",
        "不想看",
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


def _is_show_schedule_request(text: str) -> bool:
    lowered = normalize_text(text)
    markers = ["推送时间", "推送设置", "自动推送", "什么时候推送", "查看推送", "当前推送"]
    return any(marker in lowered for marker in markers) and "生成" not in lowered


def _is_disable_schedule_request(text: str) -> bool:
    lowered = normalize_text(text)
    markers = ["停止每日推送", "暂停每日推送", "关闭日报推送", "先别推送", "暂停推送"]
    return any(marker in lowered for marker in markers)


def _is_enable_schedule_request(text: str) -> bool:
    lowered = normalize_text(text)
    markers = ["恢复每日推送", "开启每日推送", "恢复推送", "继续推送"]
    return any(marker in lowered for marker in markers)


def _looks_like_generate_now_text(text: str) -> bool:
    explicit_markers = [
        "立即生成日报",
        "立刻生成日报",
        "马上生成日报",
        "现在生成日报",
        "来一版日报",
        "再来一版日报",
        "重新生成日报",
        "重新来一版日报",
        "给我今天的日报",
        "现在发日报",
        "生成今天的日报",
    ]
    if any(marker in text for marker in explicit_markers):
        return True
    return "日报" in text and any(marker in text for marker in ["生成", "重新", "再来", "来一版", "发我", "给我", "帮我"])


def _parse_daily_time(text: str) -> Optional[str]:
    lowered = normalize_text(text)
    if not any(marker in lowered for marker in ["每天", "每日", "推送", "日报"]):
        return None

    match = re.search(r"(\d{1,2})\s*[:：]\s*(\d{1,2})", lowered)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        return _format_time(hour, minute)

    match = re.search(r"(\d{1,2})\s*[点时](半|(\d{1,2})分?)?", lowered)
    if not match:
        return None

    hour = int(match.group(1))
    minute = 0
    suffix = match.group(2) or ""
    if "半" in suffix:
        minute = 30
    elif match.group(3):
        minute = int(match.group(3))

    if any(marker in lowered for marker in ["下午", "晚上", "傍晚"]):
        if hour < 12:
            hour += 12
    elif "中午" in lowered:
        if 1 <= hour < 11:
            hour += 12
    elif "凌晨" in lowered and hour == 12:
        hour = 0

    return _format_time(hour, minute)


def _format_time(hour: int, minute: int) -> Optional[str]:
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return "{0:02d}:{1:02d}".format(hour, minute)


def _compile_delivery_request(
    settings: Settings,
    text: str,
    preferences: DeliveryPreferences,
) -> CompiledDeliveryRequest:
    if _is_show_schedule_request(text):
        return CompiledDeliveryRequest(show_schedule=True, rationale="命中查看推送设置规则。")
    if _looks_like_generate_now_text(normalize_text(text)):
        return CompiledDeliveryRequest(generate_now=True, rationale="命中立即生成日报规则。")
    if _is_disable_schedule_request(text):
        return CompiledDeliveryRequest(enabled=False, rationale="命中暂停推送规则。")
    schedule_time = _parse_daily_time(text)
    if schedule_time:
        return CompiledDeliveryRequest(enabled=True, daily_time=schedule_time, rationale="命中时间解析规则。")
    if _is_enable_schedule_request(text):
        return CompiledDeliveryRequest(enabled=True, rationale="命中恢复推送规则。")
    if settings.has_openai:
        try:
            return _compile_delivery_request_with_llm(settings, text, preferences)
        except Exception as exc:
            LOGGER.warning("自然语言调度解析失败，降级到规则判断: %s", exc)
    return CompiledDeliveryRequest()


def _compile_delivery_request_with_llm(
    settings: Settings,
    text: str,
    preferences: DeliveryPreferences,
) -> CompiledDeliveryRequest:
    session = requests.Session()
    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    prompt = (
        "你是 Agent 运行配置编译器。把用户的自然语言需求翻译成 JSON。"
        "只输出 JSON，字段只能使用：generate_now, show_schedule, enabled, daily_time, rationale。"
        "generate_now/show_schedule 必须是布尔值。enabled 只能是 true/false/null。"
        "daily_time 只能是 HH:MM 或 null，按 24 小时制输出。"
        "如果用户只是想立刻生成一版日报，不要修改 enabled 和 daily_time。"
        "如果用户只是想查看当前推送设置，不要修改 enabled 和 daily_time。"
        "如果用户没有明确表达调度诉求，就把所有字段置为空或 false。"
    )
    payload = {
        "user_text": text,
        "current_delivery_preferences": {
            "enabled": preferences.enabled,
            "daily_time": preferences.daily_time,
            "timezone": preferences.timezone,
        },
        "timezone": settings.timezone,
    }
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
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        },
        timeout=60,
    )
    response.raise_for_status()
    result = response.json()
    raw = json.loads(result["choices"][0]["message"]["content"])
    return CompiledDeliveryRequest(
        generate_now=bool(raw.get("generate_now", False)),
        show_schedule=bool(raw.get("show_schedule", False)),
        enabled=_coerce_optional_bool(raw.get("enabled")),
        daily_time=_coerce_time_string(raw.get("daily_time")),
        rationale=str(raw.get("rationale") or "").strip(),
    )


def _coerce_optional_bool(value: object) -> Optional[bool]:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = normalize_text(str(value))
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def _coerce_time_string(value: object) -> Optional[str]:
    if value in (None, ""):
        return None
    text = normalize_text(str(value)).replace("：", ":")
    match = re.search(r"(\d{1,2}):(\d{1,2})", text)
    if not match:
        return None
    return _format_time(int(match.group(1)), int(match.group(2)))


def _extract_sender_type(body: dict[str, Any]) -> str:
    return str(body.get("event", {}).get("sender", {}).get("sender_type") or "")


def _extract_chat_type(body: dict[str, Any]) -> str:
    return str(body.get("event", {}).get("message", {}).get("chat_type") or "")


def _extract_message_type(body: dict[str, Any]) -> str:
    return str(body.get("event", {}).get("message", {}).get("message_type") or "")


def _extract_chat_id(body: dict[str, Any]) -> str:
    return str(body.get("event", {}).get("message", {}).get("chat_id") or "")


def _extract_text_message(body: dict[str, Any]) -> str:
    raw = body.get("event", {}).get("message", {}).get("content")
    if not raw:
        return ""
    if isinstance(raw, dict):
        return str(raw.get("text") or "").strip()
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return str(parsed.get("text") or "").strip()
        except Exception:
            pass
    return str(raw).strip()
