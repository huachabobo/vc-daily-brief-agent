from __future__ import annotations

import json
import logging
import threading
from dataclasses import replace
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from vc_agent.delivery_preferences import (
    DeliverySchedule,
    OneOffDeliveryRun,
    load_delivery_preferences,
    one_off_identity,
    save_delivery_preferences,
    schedule_identity,
)
from vc_agent.pipeline.run_once import run
from vc_agent.settings import Settings
from vc_agent.user_runtime import iter_runtime_settings, scheduler_state_path
from vc_agent.utils.time import parse_datetime, utcnow


LOGGER = logging.getLogger(__name__)


class BriefScheduler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._stop_event = threading.Event()
        self._runner_lock = threading.Lock()
        self._thread: threading.Thread | None = None

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
        for scoped_settings in iter_runtime_settings(self.settings):
            self._maybe_run_due_brief_for_settings(scoped_settings)

    def _maybe_run_due_brief_for_settings(self, scoped_settings: Settings) -> None:
        preferences = load_delivery_preferences(scoped_settings.delivery_preferences_path, scoped_settings.timezone)
        if not preferences.enabled:
            return

        tz_name = preferences.timezone or scoped_settings.timezone
        now_local = utcnow().astimezone(ZoneInfo(tz_name))
        run_date = now_local.strftime("%Y-%m-%d")
        state_path = scheduler_state_path(scoped_settings)
        state = self._load_state(state_path)
        completed_runs = set(state.get("completed_runs") or [])
        failed_runs = dict(state.get("failed_runs") or {})
        schedules = preferences.schedules
        preferences_changed = False
        state_changed = False

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
                if failed_runs.pop(run_key, None) is not None:
                    state_changed = True
                continue
            if now_local < scheduled_at:
                continue
            if not _can_retry_failed_run(failed_runs.get(run_key), now_local, tz_name):
                continue
            if not self._runner_lock.acquire(blocking=False):
                break

            try:
                worker_settings = _settings_for_target(self.settings, preferences.target_type, preferences.target_id)
                worker_settings = replace(
                    worker_settings,
                    db_path=scoped_settings.db_path,
                    output_dir=scoped_settings.output_dir,
                    user_profile_config=scoped_settings.user_profile_config,
                    delivery_preferences_path=scoped_settings.delivery_preferences_path,
                )
                result = _run_scheduled_brief(worker_settings)
                completed_runs.add(run_key)
                failed_runs.pop(run_key, None)
                state["completed_runs"] = _trim_completed_runs(completed_runs)
                state["failed_runs"] = _trim_failed_runs(failed_runs)
                self._save_state(state_path, state)
                state_changed = False
                LOGGER.info("自动推送完成(%s): %s", schedule_identity(schedule), result)
            except Exception:
                failed_runs[run_key] = _record_failed_run(failed_runs.get(run_key), now_local)
                state["failed_runs"] = _trim_failed_runs(failed_runs)
                self._save_state(state_path, state)
                state_changed = False
                LOGGER.exception("自动推送失败(%s)。", schedule_identity(schedule))
            finally:
                self._runner_lock.release()

        active_one_off_runs: list[OneOffDeliveryRun] = []
        for one_off_run in preferences.one_off_runs:
            try:
                due_date = datetime.fromisoformat(one_off_run.date).date()
                hour, minute = _parse_time_string(one_off_run.time)
            except ValueError:
                LOGGER.warning("忽略无效的单次推送时间: %s %s", one_off_run.date, one_off_run.time)
                preferences_changed = True
                continue

            run_key = "{0}:{1}".format(one_off_run.date, one_off_identity(one_off_run))
            if due_date < now_local.date():
                if failed_runs.pop(run_key, None) is not None:
                    state_changed = True
                preferences_changed = True
                LOGGER.warning("移除已过期的单次推送任务: %s", one_off_identity(one_off_run))
                continue
            if due_date > now_local.date():
                active_one_off_runs.append(one_off_run)
                continue

            scheduled_at = datetime.combine(due_date, time(hour=hour, minute=minute), tzinfo=ZoneInfo(tz_name))
            if run_key in completed_runs:
                if failed_runs.pop(run_key, None) is not None:
                    state_changed = True
                preferences_changed = True
                continue
            if now_local < scheduled_at:
                active_one_off_runs.append(one_off_run)
                continue
            if not _can_retry_failed_run(failed_runs.get(run_key), now_local, tz_name):
                active_one_off_runs.append(one_off_run)
                continue
            if not self._runner_lock.acquire(blocking=False):
                active_one_off_runs.append(one_off_run)
                continue

            try:
                worker_settings = _settings_for_target(self.settings, preferences.target_type, preferences.target_id)
                worker_settings = replace(
                    worker_settings,
                    db_path=scoped_settings.db_path,
                    output_dir=scoped_settings.output_dir,
                    user_profile_config=scoped_settings.user_profile_config,
                    delivery_preferences_path=scoped_settings.delivery_preferences_path,
                )
                result = _run_scheduled_brief(worker_settings)
                completed_runs.add(run_key)
                failed_runs.pop(run_key, None)
                state["completed_runs"] = _trim_completed_runs(completed_runs)
                state["failed_runs"] = _trim_failed_runs(failed_runs)
                self._save_state(state_path, state)
                state_changed = False
                LOGGER.info("单次自动推送完成(%s): %s", one_off_identity(one_off_run), result)
            except Exception:
                failed_runs[run_key] = _record_failed_run(failed_runs.get(run_key), now_local)
                state["failed_runs"] = _trim_failed_runs(failed_runs)
                self._save_state(state_path, state)
                state_changed = False
                active_one_off_runs.append(one_off_run)
                LOGGER.exception("单次自动推送失败(%s)。", one_off_identity(one_off_run))
            finally:
                preferences_changed = True
                self._runner_lock.release()

        if preferences_changed and active_one_off_runs != preferences.one_off_runs:
            preferences.one_off_runs = active_one_off_runs
            save_delivery_preferences(scoped_settings.delivery_preferences_path, preferences)
        if state_changed:
            state["completed_runs"] = _trim_completed_runs(completed_runs)
            state["failed_runs"] = _trim_failed_runs(failed_runs)
            self._save_state(state_path, state)

    def _load_state(self, state_path: Path) -> dict:
        if not state_path.exists():
            return {}
        return json.loads(state_path.read_text(encoding="utf-8"))

    def _save_state(self, state_path: Path, payload: dict) -> None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _run_scheduled_brief(settings: Settings) -> dict:
    result = run(settings)
    delivery_status = str(result.get("delivery_status") or "")
    if delivery_status != "sent":
        raise RuntimeError("scheduled delivery did not send successfully: {0}".format(delivery_status or "unknown"))
    return result


def _can_retry_failed_run(entry: dict | None, now_local: datetime, tz_name: str) -> bool:
    if not entry:
        return True
    next_retry_at = str(entry.get("next_retry_at") or "").strip()
    if not next_retry_at:
        return True
    try:
        retry_at_local = parse_datetime(next_retry_at).astimezone(ZoneInfo(tz_name))
    except Exception:
        return True
    return now_local >= retry_at_local


def _record_failed_run(previous: dict | None, now_local: datetime) -> dict:
    attempts = int((previous or {}).get("attempts") or 0) + 1
    delay_seconds = _retry_delay_seconds(attempts)
    next_retry_at = (now_local + timedelta(seconds=delay_seconds)).astimezone(ZoneInfo("UTC")).isoformat()
    return {
        "attempts": attempts,
        "last_failed_at": now_local.astimezone(ZoneInfo("UTC")).isoformat(),
        "next_retry_at": next_retry_at,
    }


def _retry_delay_seconds(attempts: int) -> int:
    return min(1800, 60 * (2 ** max(attempts - 1, 0)))


def _trim_completed_runs(completed_runs: set[str], limit: int = 50) -> list[str]:
    return sorted(completed_runs)[-limit:]


def _trim_failed_runs(failed_runs: dict[str, dict], limit: int = 50) -> dict[str, dict]:
    items = sorted(
        failed_runs.items(),
        key=lambda item: str(item[1].get("last_failed_at") or ""),
    )[-limit:]
    return {key: value for key, value in items}


def _weekday_code(index: int) -> str:
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][index]
