from pathlib import Path

from vc_agent.settings import Settings
from vc_agent.user_runtime import iter_runtime_settings, settings_for_user


def test_settings_for_user_migrates_global_runtime_for_first_user(tmp_path):
    root = Path(tmp_path)
    (root / "config").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "config" / "user_profile.yaml").write_text("focus_topics:\n- AI\n", encoding="utf-8")
    (root / "data" / "delivery_preferences.json").write_text('{"enabled": true, "daily_time": "09:00", "schedules": []}', encoding="utf-8")
    (root / "data" / "vc_agent.db").write_text("placeholder-db", encoding="utf-8")

    settings = Settings.from_env(root)
    scoped = settings_for_user(settings, "ou_test_user")

    assert scoped.user_profile_config.exists()
    assert scoped.delivery_preferences_path.exists()
    assert scoped.db_path.exists()
    assert scoped.user_profile_config.read_text(encoding="utf-8") == (root / "config" / "user_profile.yaml").read_text(encoding="utf-8")


def test_iter_runtime_settings_keeps_global_and_user_scoped_delivery_targets(tmp_path):
    root = Path(tmp_path)
    (root / "data" / "users" / "ou_user_a").mkdir(parents=True)
    (root / "data" / "users" / "ou_user_b").mkdir(parents=True)
    (root / "data" / "users" / "ou_user_a" / "delivery_preferences.json").write_text('{"enabled": true, "daily_time": "09:00", "schedules": []}', encoding="utf-8")
    (root / "data" / "users" / "ou_user_b" / "delivery_preferences.json").write_text('{"enabled": true, "daily_time": "10:00", "schedules": []}', encoding="utf-8")
    (root / "data" / "delivery_preferences.json").write_text('{"enabled": true, "daily_time": "08:00", "schedules": []}', encoding="utf-8")

    settings = Settings.from_env(root)
    scoped_settings = iter_runtime_settings(settings)

    assert len(scoped_settings) == 3
    assert scoped_settings[0].delivery_preferences_path == root / "data" / "delivery_preferences.json"
    assert sum("/data/users/" in str(item.delivery_preferences_path) for item in scoped_settings) == 2
