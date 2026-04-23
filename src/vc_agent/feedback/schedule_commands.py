from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests

from vc_agent.delivery_preferences import (
    DAY_CODES,
    WEEKEND_CODES,
    WORKDAY_CODES,
    DeliverySchedule,
    DeliveryPreferences,
    OneOffDeliveryRun,
    load_delivery_preferences,
    render_delivery_preferences,
    save_delivery_preferences,
)
from vc_agent.settings import Settings
from vc_agent.utils.time import utcnow
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
    schedules: list[DeliverySchedule] = field(default_factory=list)
    one_off_runs: list[OneOffDeliveryRun] = field(default_factory=list)
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

    if compiled.schedules or compiled.one_off_runs or compiled.enabled is True:
        preferences.enabled = True if compiled.enabled is None else compiled.enabled
        if compiled.schedules:
            preferences.schedules = compiled.schedules
            preferences.daily_time = compiled.schedules[0].time
        if compiled.one_off_runs:
            preferences.one_off_runs = _merge_one_off_runs(preferences.one_off_runs, compiled.one_off_runs)
        preferences.timezone = settings.timezone
        if chat_id:
            preferences.target_type = "chat_id"
            preferences.target_id = chat_id
        save_delivery_preferences(settings.delivery_preferences_path, preferences)
        return ScheduleMessageResult(
            handled=True,
            reply_text="{0} 之后你继续用自然语言改内容偏好就行，比如“更关注机器人，日报控制在 5 条”。".format(
                render_delivery_preferences(preferences).replace("当前已设置为", "好，我已经把自动推送改成")
            ),
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
    if _looks_like_schedule_request(text):
        return False
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


def _looks_like_schedule_request(text: str) -> bool:
    lowered = normalize_text(text)
    schedule_markers = [
        "今天",
        "明天",
        "后天",
        "这周",
        "本周",
        "下周",
        "每天",
        "每日",
        "工作日",
        "周末",
        "周一",
        "周二",
        "周三",
        "周四",
        "周五",
        "周六",
        "周日",
        "星期",
        "礼拜",
        "早上",
        "上午",
        "中午",
        "下午",
        "晚上",
        "傍晚",
        "推送",
        "固定住",
    ]
    if any(marker in lowered for marker in schedule_markers):
        return True
    return bool(re.search(r"(\d{1,2})\s*(点|:|：)", lowered))


def _parse_daily_time(text: str) -> Optional[str]:
    lowered = normalize_text(text)
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


def _parse_one_off_runs(text: str, timezone_name: str) -> list[OneOffDeliveryRun]:
    lowered = normalize_text(text)
    if not any(marker in lowered for marker in ["推送", "日报", "晨报", "晚报", "发", "固定住"]):
        return []

    runs: list[OneOffDeliveryRun] = []
    base_date = utcnow().astimezone(ZoneInfo(timezone_name)).date()
    segments = [segment.strip() for segment in re.split(r"[，,。；;]\s*", text) if segment.strip()]
    if not segments:
        segments = [text]

    for segment in segments:
        run = _parse_one_off_run_segment(segment, base_date)
        if run and not _one_off_run_exists(runs, run):
            runs.append(run)

    return runs


def _parse_schedules(text: str) -> list[DeliverySchedule]:
    lowered = normalize_text(text)
    if not any(marker in lowered for marker in ["推送", "日报", "晨报", "晚报", "发", "固定住"]):
        return []
    contains_one_off_segment = any(_looks_like_one_off_segment(segment) for segment in re.split(r"[，,。；;]\s*", text) if segment.strip())

    schedules: list[DeliverySchedule] = []
    segments = [segment.strip() for segment in re.split(r"[，,。；;]\s*", text) if segment.strip()]
    if not segments:
        segments = [text]

    for segment in segments:
        schedule = _parse_schedule_segment(segment)
        if schedule and not _schedule_exists(schedules, schedule):
            schedules.append(schedule)

    if schedules:
        return schedules

    if contains_one_off_segment:
        return []

    fallback_time = _parse_daily_time(text)
    if fallback_time:
        return [DeliverySchedule(days=list(DAY_CODES), time=fallback_time)]
    return []


def _parse_one_off_run_segment(text: str, base_date) -> Optional[OneOffDeliveryRun]:
    if not _looks_like_one_off_segment(text):
        return None
    schedule_time = _parse_daily_time(text)
    schedule_date = _parse_one_off_date(text, base_date)
    if not schedule_time or not schedule_date:
        return None
    return OneOffDeliveryRun(date=schedule_date.isoformat(), time=schedule_time)


def _parse_schedule_segment(text: str) -> Optional[DeliverySchedule]:
    if _looks_like_one_off_segment(text):
        return None
    schedule_time = _parse_daily_time(text)
    if not schedule_time:
        return None
    days = _parse_days(text)
    return DeliverySchedule(days=days or list(DAY_CODES), time=schedule_time)


def _parse_days(text: str) -> list[str]:
    lowered = normalize_text(text)
    if any(marker in lowered for marker in ["工作日", "周一到周五", "周一至周五", "星期一到星期五", "weekday", "weekdays"]):
        return list(WORKDAY_CODES)
    if any(marker in lowered for marker in ["周末", "双休日", "星期六日", "星期六和星期日", "weekend", "weekends"]):
        return list(WEEKEND_CODES)
    if any(marker in lowered for marker in ["每天", "每日", "天天", "每天都", "每日都"]):
        return list(DAY_CODES)

    day_markers = [
        ("mon", ["周一", "星期一", "礼拜一"]),
        ("tue", ["周二", "星期二", "礼拜二"]),
        ("wed", ["周三", "星期三", "礼拜三"]),
        ("thu", ["周四", "星期四", "礼拜四"]),
        ("fri", ["周五", "星期五", "礼拜五"]),
        ("sat", ["周六", "星期六", "礼拜六"]),
        ("sun", ["周日", "周天", "星期日", "星期天", "礼拜天", "礼拜日"]),
    ]
    days: list[str] = []
    for code, markers in day_markers:
        if any(marker in lowered for marker in markers):
            days.append(code)
    return days


def _parse_one_off_date(text: str, base_date):
    lowered = normalize_text(text)
    if "明天" in lowered:
        return base_date + timedelta(days=1)
    if "后天" in lowered:
        return base_date + timedelta(days=2)
    if any(marker in lowered for marker in ["今天", "今日"]):
        return base_date

    weekday_index = _extract_weekday_index(lowered)
    if weekday_index is None:
        return None
    base_weekday = base_date.weekday()
    if any(marker in lowered for marker in ["下周", "下星期", "下礼拜"]):
        return base_date + timedelta(days=(7 - base_weekday) + weekday_index)
    if any(marker in lowered for marker in ["这周", "本周", "这星期", "本星期", "这礼拜", "本礼拜"]):
        delta = weekday_index - base_weekday
        if delta < 0:
            delta += 7
        return base_date + timedelta(days=delta)
    return None


def _extract_weekday_index(text: str) -> Optional[int]:
    day_markers = [
        (0, ["周一", "星期一", "礼拜一"]),
        (1, ["周二", "星期二", "礼拜二"]),
        (2, ["周三", "星期三", "礼拜三"]),
        (3, ["周四", "星期四", "礼拜四"]),
        (4, ["周五", "星期五", "礼拜五"]),
        (5, ["周六", "星期六", "礼拜六"]),
        (6, ["周日", "周天", "星期日", "星期天", "礼拜日", "礼拜天"]),
    ]
    for index, markers in day_markers:
        if any(marker in text for marker in markers):
            return index
    return None


def _looks_like_one_off_segment(text: str) -> bool:
    lowered = normalize_text(text)
    one_off_markers = [
        "今天",
        "今日",
        "明天",
        "后天",
        "这周",
        "本周",
        "下周",
        "这星期",
        "本星期",
        "下星期",
        "这礼拜",
        "本礼拜",
        "下礼拜",
        "一次性",
        "单次",
        "只发一次",
        "就这一次",
        "仅此一次",
    ]
    return any(marker in lowered for marker in one_off_markers)


def _schedule_exists(schedules: list[DeliverySchedule], candidate: DeliverySchedule) -> bool:
    for schedule in schedules:
        if schedule.time == candidate.time and schedule.days == candidate.days:
            return True
    return False


def _one_off_run_exists(runs: list[OneOffDeliveryRun], candidate: OneOffDeliveryRun) -> bool:
    return any(run.date == candidate.date and run.time == candidate.time for run in runs)


def _merge_one_off_runs(existing: list[OneOffDeliveryRun], incoming: list[OneOffDeliveryRun]) -> list[OneOffDeliveryRun]:
    merged = list(existing)
    for run in incoming:
        if not _one_off_run_exists(merged, run):
            merged.append(run)
    return sorted(merged, key=lambda run: (run.date, run.time))


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
    one_off_runs = _parse_one_off_runs(text, settings.timezone)
    schedules = _parse_schedules(text)
    if one_off_runs or schedules:
        rationale_parts = []
        if schedules:
            rationale_parts.append("命中周期时间解析规则")
        if one_off_runs:
            rationale_parts.append("命中单次推送时间解析规则")
        return CompiledDeliveryRequest(
            enabled=True,
            schedules=schedules,
            one_off_runs=one_off_runs,
            rationale="；".join(rationale_parts) + "。",
        )
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
        "只输出 JSON，字段只能使用：generate_now, show_schedule, enabled, schedules, one_off_runs, rationale。"
        "generate_now/show_schedule 必须是布尔值。enabled 只能是 true/false/null。"
        "schedules 必须是数组，元素字段只能是 days 和 time。"
        "one_off_runs 必须是数组，元素字段只能是 date 和 time；date 使用 YYYY-MM-DD。"
        "days 只能使用 mon,tue,wed,thu,fri,sat,sun；time 只能是 HH:MM。"
        "如果用户说的是今天、明天、后天、本周几、下周几或只发一次，请优先写入 one_off_runs，不要写 schedules。"
        "如果用户只是想立刻生成一版日报，不要修改 enabled、schedules 和 one_off_runs。"
        "如果用户只是想查看当前推送设置，不要修改 enabled、schedules 和 one_off_runs。"
        "如果用户没有明确表达调度诉求，就把所有字段置为空或 false。"
    )
    payload = {
        "user_text": text,
        "current_delivery_preferences": {
            "enabled": preferences.enabled,
                "daily_time": preferences.daily_time,
                "schedules": [{"days": schedule.days, "time": schedule.time} for schedule in preferences.schedules],
                "one_off_runs": [{"date": run.date, "time": run.time} for run in preferences.one_off_runs],
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
        schedules=_coerce_schedules(raw.get("schedules")),
        one_off_runs=_coerce_one_off_runs(raw.get("one_off_runs")),
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


def _coerce_schedules(value: object) -> list[DeliverySchedule]:
    if not isinstance(value, list):
        return []
    schedules: list[DeliverySchedule] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        time = _coerce_time_string(item.get("time"))
        days = _coerce_days(item.get("days"))
        if time and days and not _schedule_exists(schedules, DeliverySchedule(days=days, time=time)):
            schedules.append(DeliverySchedule(days=days, time=time))
    return schedules


def _coerce_one_off_runs(value: object) -> list[OneOffDeliveryRun]:
    if not isinstance(value, list):
        return []
    runs: list[OneOffDeliveryRun] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        date = str(item.get("date") or "").strip()
        time = _coerce_time_string(item.get("time"))
        if not _looks_like_iso_date(date) or not time:
            continue
        candidate = OneOffDeliveryRun(date=date, time=time)
        if not _one_off_run_exists(runs, candidate):
            runs.append(candidate)
    return sorted(runs, key=lambda run: (run.date, run.time))


def _coerce_days(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    days: list[str] = []
    for item in value:
        label = normalize_text(str(item))
        if label in DAY_CODES and label not in days:
            days.append(label)
    return days


def _looks_like_iso_date(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))


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
