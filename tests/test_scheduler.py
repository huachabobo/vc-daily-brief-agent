import json
from datetime import datetime, timezone
from pathlib import Path

import vc_agent.scheduler as scheduler_module
from vc_agent.delivery_preferences import DeliveryPreferences, DeliverySchedule, OneOffDeliveryRun, load_delivery_preferences, save_delivery_preferences
from vc_agent.scheduler import BriefScheduler
from vc_agent.settings import Settings


def test_scheduler_runs_one_off_only_when_due(monkeypatch, tmp_path):
    root = Path(tmp_path)
    settings = Settings.from_env(root)
    settings.delivery_preferences_path = root / "data" / "delivery_preferences.json"
    settings.repo_root = root

    save_delivery_preferences(
        settings.delivery_preferences_path,
        DeliveryPreferences(
            enabled=True,
            schedules=[],
            one_off_runs=[OneOffDeliveryRun(date="2026-04-24", time="10:00")],
            timezone="Asia/Shanghai",
            target_type="chat_id",
            target_id="oc_test_chat",
        ),
    )

    calls: list[Settings] = []
    monkeypatch.setattr(
        scheduler_module,
        "run",
        lambda worker_settings: calls.append(worker_settings) or {"delivery_status": "sent"},
    )
    scheduler = BriefScheduler(settings)

    monkeypatch.setattr(
        scheduler_module,
        "utcnow",
        lambda: datetime(2026, 4, 23, 11, 0, tzinfo=timezone.utc),
    )
    scheduler._maybe_run_due_brief()
    assert calls == []
    assert load_delivery_preferences(settings.delivery_preferences_path, settings.timezone).one_off_runs

    monkeypatch.setattr(
        scheduler_module,
        "utcnow",
        lambda: datetime(2026, 4, 24, 2, 30, tzinfo=timezone.utc),
    )
    scheduler._maybe_run_due_brief()
    assert len(calls) == 1
    assert load_delivery_preferences(settings.delivery_preferences_path, settings.timezone).one_off_runs == []


def test_scheduler_retries_failed_recurring_runs_with_backoff(monkeypatch, tmp_path):
    root = Path(tmp_path)
    settings = Settings.from_env(root)
    settings.delivery_preferences_path = root / "data" / "delivery_preferences.json"
    settings.repo_root = root

    save_delivery_preferences(
        settings.delivery_preferences_path,
        DeliveryPreferences(
            enabled=True,
            schedules=[DeliverySchedule(days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"], time="10:00")],
            timezone="Asia/Shanghai",
            target_type="chat_id",
            target_id="oc_test_chat",
        ),
    )

    outcomes = [RuntimeError("temporary failure"), {"delivery_status": "sent"}]

    def fake_run(worker_settings):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(scheduler_module, "run", fake_run)
    scheduler = BriefScheduler(settings)

    monkeypatch.setattr(
        scheduler_module,
        "utcnow",
        lambda: datetime(2026, 4, 24, 2, 30, tzinfo=timezone.utc),
    )
    scheduler._maybe_run_due_brief()

    state = json.loads((root / "data" / "delivery_scheduler_state.json").read_text(encoding="utf-8"))
    run_key = "2026-04-24:mon,tue,wed,thu,fri,sat,sun@10:00"
    assert run_key not in state.get("completed_runs", [])
    assert state["failed_runs"][run_key]["attempts"] == 1

    scheduler._maybe_run_due_brief()
    state = json.loads((root / "data" / "delivery_scheduler_state.json").read_text(encoding="utf-8"))
    assert run_key not in state.get("completed_runs", [])
    assert outcomes == [{"delivery_status": "sent"}]

    monkeypatch.setattr(
        scheduler_module,
        "utcnow",
        lambda: datetime(2026, 4, 24, 2, 31, 1, tzinfo=timezone.utc),
    )
    scheduler._maybe_run_due_brief()
    state = json.loads((root / "data" / "delivery_scheduler_state.json").read_text(encoding="utf-8"))
    assert run_key in state.get("completed_runs", [])
    assert run_key not in state.get("failed_runs", {})


def test_scheduler_keeps_failed_one_off_runs_until_retry_succeeds(monkeypatch, tmp_path):
    root = Path(tmp_path)
    settings = Settings.from_env(root)
    settings.delivery_preferences_path = root / "data" / "delivery_preferences.json"
    settings.repo_root = root

    save_delivery_preferences(
        settings.delivery_preferences_path,
        DeliveryPreferences(
            enabled=True,
            schedules=[],
            one_off_runs=[OneOffDeliveryRun(date="2026-04-24", time="10:00")],
            timezone="Asia/Shanghai",
            target_type="chat_id",
            target_id="oc_test_chat",
        ),
    )

    outcomes = [RuntimeError("temporary failure"), {"delivery_status": "sent"}]

    def fake_run(worker_settings):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(scheduler_module, "run", fake_run)
    scheduler = BriefScheduler(settings)

    monkeypatch.setattr(
        scheduler_module,
        "utcnow",
        lambda: datetime(2026, 4, 24, 2, 30, tzinfo=timezone.utc),
    )
    scheduler._maybe_run_due_brief()
    preferences = load_delivery_preferences(settings.delivery_preferences_path, settings.timezone)
    assert len(preferences.one_off_runs) == 1
    state = json.loads((root / "data" / "delivery_scheduler_state.json").read_text(encoding="utf-8"))
    run_key = "2026-04-24:2026-04-24@10:00"
    assert state["failed_runs"][run_key]["attempts"] == 1

    monkeypatch.setattr(
        scheduler_module,
        "utcnow",
        lambda: datetime(2026, 4, 24, 2, 31, 1, tzinfo=timezone.utc),
    )
    scheduler._maybe_run_due_brief()
    preferences = load_delivery_preferences(settings.delivery_preferences_path, settings.timezone)
    assert preferences.one_off_runs == []
    state = json.loads((root / "data" / "delivery_scheduler_state.json").read_text(encoding="utf-8"))
    assert run_key in state.get("completed_runs", [])
    assert run_key not in state.get("failed_runs", {})


def test_scheduler_clears_expired_failed_one_off_runs(monkeypatch, tmp_path):
    root = Path(tmp_path)
    settings = Settings.from_env(root)
    settings.delivery_preferences_path = root / "data" / "delivery_preferences.json"
    settings.repo_root = root

    save_delivery_preferences(
        settings.delivery_preferences_path,
        DeliveryPreferences(
            enabled=True,
            schedules=[],
            one_off_runs=[OneOffDeliveryRun(date="2026-04-24", time="10:00")],
            timezone="Asia/Shanghai",
            target_type="chat_id",
            target_id="oc_test_chat",
        ),
    )
    (root / "data" / "delivery_scheduler_state.json").write_text(
        json.dumps(
            {
                "completed_runs": [],
                "failed_runs": {
                    "2026-04-24:2026-04-24@10:00": {
                        "attempts": 2,
                        "last_failed_at": "2026-04-24T02:31:01+00:00",
                        "next_retry_at": "2026-04-24T02:33:01+00:00",
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    scheduler = BriefScheduler(settings)
    monkeypatch.setattr(
        scheduler_module,
        "utcnow",
        lambda: datetime(2026, 4, 25, 2, 30, tzinfo=timezone.utc),
    )

    scheduler._maybe_run_due_brief()

    preferences = load_delivery_preferences(settings.delivery_preferences_path, settings.timezone)
    assert preferences.one_off_runs == []
    state = json.loads((root / "data" / "delivery_scheduler_state.json").read_text(encoding="utf-8"))
    assert state.get("failed_runs", {}) == {}
