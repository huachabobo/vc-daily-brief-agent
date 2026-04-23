from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


DAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WORKDAY_CODES = ["mon", "tue", "wed", "thu", "fri"]
WEEKEND_CODES = ["sat", "sun"]


@dataclass
class DeliverySchedule:
    days: list[str]
    time: str


@dataclass
class OneOffDeliveryRun:
    date: str
    time: str


@dataclass
class DeliveryPreferences:
    enabled: bool = False
    daily_time: str = "08:00"
    schedules: list[DeliverySchedule] = field(default_factory=list)
    one_off_runs: list[OneOffDeliveryRun] = field(default_factory=list)
    timezone: str = "Asia/Shanghai"
    target_type: str = ""
    target_id: str = ""


def load_delivery_preferences(path: Path, default_timezone: str) -> DeliveryPreferences:
    if not path.exists():
        return DeliveryPreferences(timezone=default_timezone)
    payload = json.loads(path.read_text(encoding="utf-8"))
    schedules = _load_schedules(payload)
    daily_time = str(payload.get("daily_time") or (schedules[0].time if schedules else "08:00"))
    return DeliveryPreferences(
        enabled=bool(payload.get("enabled", False)),
        daily_time=daily_time,
        schedules=schedules,
        one_off_runs=_load_one_off_runs(payload),
        timezone=str(payload.get("timezone") or default_timezone),
        target_type=str(payload.get("target_type") or ""),
        target_id=str(payload.get("target_id") or ""),
    )


def save_delivery_preferences(path: Path, preferences: DeliveryPreferences) -> None:
    schedules = preferences.schedules
    payload = {
        "enabled": preferences.enabled,
        "daily_time": str(preferences.daily_time or (schedules[0].time if schedules else "08:00")),
        "schedules": [
            {"days": _normalize_days(schedule.days), "time": schedule.time}
            for schedule in schedules
        ],
        "one_off_runs": [
            {"date": run.date, "time": run.time}
            for run in _normalize_one_off_runs(preferences.one_off_runs)
        ],
        "timezone": preferences.timezone,
        "target_type": preferences.target_type,
        "target_id": preferences.target_id,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def render_delivery_preferences(preferences: DeliveryPreferences) -> str:
    if not preferences.enabled:
        return "当前还没有启用每日自动推送。你可以直接发：每天早上 8 点推送日报。"
    target = "当前会话" if preferences.target_type and preferences.target_id else "默认接收目标"
    parts: list[str] = []
    if preferences.schedules:
        parts.append("自动推送 {0}".format("，".join(_render_schedule(schedule) for schedule in preferences.schedules)))
    if preferences.one_off_runs:
        parts.append("单次推送 {0}".format("、".join(_render_one_off_run(run) for run in _normalize_one_off_runs(preferences.one_off_runs))))
    if not parts:
        return "当前还没有启用每日自动推送。你可以直接发：每天早上 8 点推送日报。"
    return "当前已设置为 {0} 到{1}。".format("，另有 ".join(parts), target)


def schedule_identity(schedule: DeliverySchedule) -> str:
    return "{0}@{1}".format(",".join(_normalize_days(schedule.days)), schedule.time)


def one_off_identity(run: OneOffDeliveryRun) -> str:
    return "{0}@{1}".format(run.date, run.time)


def _load_schedules(payload: dict) -> list[DeliverySchedule]:
    if "schedules" in payload:
        raw_schedules = payload.get("schedules")
        schedules: list[DeliverySchedule] = []
        if isinstance(raw_schedules, list):
            for entry in raw_schedules:
                if not isinstance(entry, dict):
                    continue
                time = str(entry.get("time") or "").strip()
                days = _normalize_days(entry.get("days") or [])
                if time and days:
                    schedules.append(DeliverySchedule(days=days, time=time))
        return schedules

    legacy_time = str(payload.get("daily_time") or "08:00")
    return [DeliverySchedule(days=list(DAY_CODES), time=legacy_time)]


def _load_one_off_runs(payload: dict) -> list[OneOffDeliveryRun]:
    raw_runs = payload.get("one_off_runs")
    runs: list[OneOffDeliveryRun] = []
    if not isinstance(raw_runs, list):
        return runs
    for entry in raw_runs:
        if not isinstance(entry, dict):
            continue
        date = str(entry.get("date") or "").strip()
        time = str(entry.get("time") or "").strip()
        if date and time:
            runs.append(OneOffDeliveryRun(date=date, time=time))
    return _normalize_one_off_runs(runs)


def _normalize_days(raw_days: object) -> list[str]:
    if not isinstance(raw_days, list):
        return list(DAY_CODES)
    values: list[str] = []
    for day in raw_days:
        label = str(day).strip().lower()
        if label in DAY_CODES and label not in values:
            values.append(label)
    return values or list(DAY_CODES)


def _normalize_one_off_runs(raw_runs: list[OneOffDeliveryRun]) -> list[OneOffDeliveryRun]:
    normalized: list[OneOffDeliveryRun] = []
    seen: set[str] = set()
    for run in raw_runs:
        key = one_off_identity(run)
        if not run.date or not run.time or key in seen:
            continue
        normalized.append(run)
        seen.add(key)
    return sorted(normalized, key=lambda run: (run.date, run.time))


def _render_schedule(schedule: DeliverySchedule) -> str:
    days = _normalize_days(schedule.days)
    if days == DAY_CODES:
        return "每天 {0}".format(schedule.time)
    if days == WORKDAY_CODES:
        return "工作日 {0}".format(schedule.time)
    if days == WEEKEND_CODES:
        return "周末 {0}".format(schedule.time)
    return "{0} {1}".format(_render_day_labels(days), schedule.time)


def _render_one_off_run(run: OneOffDeliveryRun) -> str:
    return "{0} {1}".format(run.date, run.time)


def _render_day_labels(days: list[str]) -> str:
    labels = {
        "mon": "周一",
        "tue": "周二",
        "wed": "周三",
        "thu": "周四",
        "fri": "周五",
        "sat": "周六",
        "sun": "周日",
    }
    return "、".join(labels[day] for day in days if day in labels)
