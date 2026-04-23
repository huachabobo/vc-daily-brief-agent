from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class DeliveryPreferences:
    enabled: bool = False
    daily_time: str = "08:00"
    timezone: str = "Asia/Shanghai"
    target_type: str = ""
    target_id: str = ""


def load_delivery_preferences(path: Path, default_timezone: str) -> DeliveryPreferences:
    if not path.exists():
        return DeliveryPreferences(timezone=default_timezone)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return DeliveryPreferences(
        enabled=bool(payload.get("enabled", False)),
        daily_time=str(payload.get("daily_time") or "08:00"),
        timezone=str(payload.get("timezone") or default_timezone),
        target_type=str(payload.get("target_type") or ""),
        target_id=str(payload.get("target_id") or ""),
    )


def save_delivery_preferences(path: Path, preferences: DeliveryPreferences) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(preferences), ensure_ascii=False, indent=2), encoding="utf-8")


def render_delivery_preferences(preferences: DeliveryPreferences) -> str:
    if not preferences.enabled:
        return "当前还没有启用每日自动推送。你可以直接发：每天早上 8 点推送日报。"
    target = "当前会话" if preferences.target_type and preferences.target_id else "默认接收目标"
    return "当前已设置为每天 {0} 自动推送到{1}。".format(preferences.daily_time, target)
