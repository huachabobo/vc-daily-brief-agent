from __future__ import annotations

import json
import logging
import threading
from dataclasses import replace
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from vc_agent.delivery_preferences import DeliverySchedule, load_delivery_preferences, schedule_identity
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

        tz_name = preferences.timezone or self.settings.timezone
        now_local = utcnow().astimezone(ZoneInfo(tz_name))
        run_date = now_local.strftime("%Y-%m-%d")
        state = self._load_state()
        completed_runs = set(state.get("completed_runs") or [])
        schedules = preferences.schedules or [DeliverySchedule(days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"], time=preferences.daily_time)]

        weekday_code = _weekday_code(now_local.weekday())
        for schedule in schedules:
            if weekday_code not in schedule.days:
                continue
            try:
                hour, minute = _parse_time_string(schedule.time)
            except ValueError:
                LOGGER.warning("忽略无效的推送时间: %s", schedule.time)
                continue
            scheduled_at = datetime.combine(now_local.date(), time(hour=hour, minute=minute), tzinfo=ZoneInfo(tz_name))
            run_key = "{0}:{1}".format(run_date, schedule_identity(schedule))
            if run_key in completed_runs:
                continue
            if now_local < scheduled_at:
                continue
            if not self._runner_lock.acquire(blocking=False):
                return

            try:
                completed_runs.add(run_key)
                state["completed_runs"] = _trim_completed_runs(completed_runs)
                self._save_state(state)
                worker_settings = _settings_for_target(self.settings, preferences.target_type, preferences.target_id)
                result = run(worker_settings)
                LOGGER.info("自动推送完成(%s): %s", schedule_identity(schedule), result)
            except Exception:
                LOGGER.exception("自动推送失败(%s)。", schedule_identity(schedule))
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


def _trim_completed_runs(completed_runs: set[str], limit: int = 50) -> list[str]:
    return sorted(completed_runs)[-limit:]


def _weekday_code(index: int) -> str:
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][index]
