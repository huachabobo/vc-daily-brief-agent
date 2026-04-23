from __future__ import annotations

import json
import logging
import threading
from dataclasses import replace
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from vc_agent.delivery_preferences import load_delivery_preferences
from vc_agent.pipeline.run_once import run
from vc_agent.settings import Settings
from vc_agent.utils.time import utcnow


LOGGER = logging.getLogger(__name__)


class BriefScheduler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._stop_event = threading.Event()
        self._runner_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state_path = settings.repo_root / "data" / "delivery_scheduler_state.json"

    def start(self) -> "BriefScheduler":
        if self._thread and self._thread.is_alive():
            return self
        self._thread = threading.Thread(target=self._loop, name="vc-agent-scheduler", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop_event.set()

    def _loop(self) -> None:
        LOGGER.info("启动日报调度器，等待每日自动推送。")
        self._maybe_run_due_brief()
        while not self._stop_event.wait(20):
            self._maybe_run_due_brief()

    def _maybe_run_due_brief(self) -> None:
        preferences = load_delivery_preferences(self.settings.delivery_preferences_path, self.settings.timezone)
        if not preferences.enabled:
            return

        try:
            hour, minute = _parse_time_string(preferences.daily_time)
        except ValueError:
            LOGGER.warning("忽略无效的每日推送时间: %s", preferences.daily_time)
            return

        tz_name = preferences.timezone or self.settings.timezone
        now_local = utcnow().astimezone(ZoneInfo(tz_name))
        scheduled_at = datetime.combine(now_local.date(), time(hour=hour, minute=minute), tzinfo=ZoneInfo(tz_name))
        run_date = now_local.strftime("%Y-%m-%d")
        state = self._load_state()

        if state.get("last_scheduled_run_date") == run_date:
            return
        if now_local < scheduled_at:
            return
        if not self._runner_lock.acquire(blocking=False):
            return

        try:
            state["last_scheduled_run_date"] = run_date
            self._save_state(state)
            worker_settings = _settings_for_target(self.settings, preferences.target_type, preferences.target_id)
            result = run(worker_settings)
            LOGGER.info("每日自动推送完成: %s", result)
        except Exception:
            LOGGER.exception("每日自动推送失败。")
        finally:
            self._runner_lock.release()

    def _load_state(self) -> dict:
        if not self._state_path.exists():
            return {}
        return json.loads(self._state_path.read_text(encoding="utf-8"))

    def _save_state(self, payload: dict) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _settings_for_target(settings: Settings, target_type: str, target_id: str) -> Settings:
    if not target_type or not target_id:
        return settings
    if target_type == "chat_id":
        return replace(settings, feishu_chat_id=target_id, feishu_receive_id_type="", feishu_receive_id="")
    return replace(settings, feishu_chat_id="", feishu_receive_id_type=target_type, feishu_receive_id=target_id)


def _parse_time_string(value: str) -> tuple[int, int]:
    cleaned = value.strip()
    if ":" not in cleaned:
        raise ValueError("invalid time")
    hour_text, minute_text = cleaned.split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("invalid time range")
    return hour, minute
