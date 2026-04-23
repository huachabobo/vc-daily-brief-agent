from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import replace
from pathlib import Path

from vc_agent.settings import Settings


def settings_for_user(settings: Settings, user_key: str) -> Settings:
    slug = user_slug(user_key)
    return _settings_for_slug(settings, slug, allow_migration=True)


def iter_runtime_settings(settings: Settings) -> list[Settings]:
    user_root = _users_root(settings)
    user_dirs = sorted(path for path in user_root.iterdir() if path.is_dir()) if user_root.exists() else []
    scoped: list[Settings] = []
    if settings.delivery_preferences_path.exists():
        scoped.append(settings)
    for user_dir in user_dirs:
        delivery_path = user_dir / "delivery_preferences.json"
        if delivery_path.exists():
            scoped.append(_settings_for_slug(settings, user_dir.name, allow_migration=False))
    if scoped:
        return scoped
    return [settings]


def user_slug(user_key: str) -> str:
    raw = str(user_key or "").strip()
    if not raw:
        return "default"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-._")
    if slug and len(slug) <= 80:
        return slug
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    prefix = slug[:40] if slug else "user"
    return "{0}-{1}".format(prefix, digest)


def scheduler_state_path(settings: Settings) -> Path:
    return settings.delivery_preferences_path.parent / "delivery_scheduler_state.json"


def _settings_for_slug(
    settings: Settings,
    slug: str,
    allow_migration: bool = False,
) -> Settings:
    user_root = _users_root(settings) / slug
    if allow_migration:
        _ensure_seeded_user_runtime(settings, user_root)
    else:
        user_root.mkdir(parents=True, exist_ok=True)
    scoped_output_dir = settings.repo_root / "sample_output" / "users" / slug
    return replace(
        settings,
        db_path=user_root / "vc_agent.db",
        output_dir=scoped_output_dir,
        user_profile_config=user_root / "user_profile.yaml",
        delivery_preferences_path=user_root / "delivery_preferences.json",
    )


def _ensure_seeded_user_runtime(settings: Settings, user_root: Path) -> None:
    if user_root.exists():
        return
    should_migrate = _should_migrate_global_runtime(settings)
    user_root.mkdir(parents=True, exist_ok=True)
    if should_migrate:
        _copy_if_exists(settings.user_profile_config, user_root / "user_profile.yaml")
        _copy_if_exists(settings.delivery_preferences_path, user_root / "delivery_preferences.json")
        _copy_if_exists(settings.db_path, user_root / "vc_agent.db")
    else:
        _copy_if_exists(settings.user_profile_config, user_root / "user_profile.yaml")


def _should_migrate_global_runtime(settings: Settings) -> bool:
    user_root = _users_root(settings)
    existing_dirs = [path for path in user_root.iterdir() if path.is_dir()] if user_root.exists() else []
    if existing_dirs:
        return False
    return any(
        path.exists()
        for path in (
            settings.user_profile_config,
            settings.delivery_preferences_path,
            settings.db_path,
        )
    )


def _users_root(settings: Settings) -> Path:
    return settings.repo_root / "data" / "users"


def _copy_if_exists(source: Path, destination: Path) -> None:
    if not source.exists() or destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
