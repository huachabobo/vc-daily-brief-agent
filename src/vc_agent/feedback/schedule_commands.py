from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from vc_agent.delivery_preferences import (
    DeliveryPreferences,
    load_delivery_preferences,
    render_delivery_preferences,
    save_delivery_preferences,
)
from vc_agent.settings import Settings
from vc_agent.utils.text import normalize_text


@dataclass
class ScheduleMessageResult:
    handled: bool
    reply_text: str = ""


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

    if _is_show_schedule_request(text):
        return ScheduleMessageResult(handled=True, reply_text=render_delivery_preferences(preferences))

    if _is_disable_schedule_request(text):
        preferences.enabled = False
        save_delivery_preferences(settings.delivery_preferences_path, preferences)
        return ScheduleMessageResult(
            handled=True,
            reply_text="好的，我先暂停每日自动推送。之后如果你想恢复，直接发“每天早上 8 点推送日报”之类的话就行。",
        )

    schedule_time = _parse_daily_time(text)
    if schedule_time:
        preferences.enabled = True
        preferences.daily_time = schedule_time
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
            ).format(schedule_time),
        )

    if _is_enable_schedule_request(text):
        preferences.enabled = True
        preferences.timezone = settings.timezone
        if chat_id:
            preferences.target_type = "chat_id"
            preferences.target_id = chat_id
        save_delivery_preferences(settings.delivery_preferences_path, preferences)
        return ScheduleMessageResult(
            handled=True,
            reply_text="好的，我已经恢复每日自动推送，当前时间是每天 {0}。".format(preferences.daily_time),
        )

    return ScheduleMessageResult(handled=False)


def looks_like_generate_now_request(body: dict[str, Any]) -> bool:
    if _extract_sender_type(body) != "user":
        return False
    if _extract_chat_type(body) not in {"", "p2p"}:
        return False
    if _extract_message_type(body) != "text":
        return False
    text = normalize_text(_extract_text_message(body))
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
