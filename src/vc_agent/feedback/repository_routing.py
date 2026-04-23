from __future__ import annotations

from typing import Any, Dict

from vc_agent.feedback.processing import extract_feedback_target, item_matches_feedback_target
from vc_agent.settings import Settings
from vc_agent.storage import Repository
from vc_agent.user_runtime import settings_for_user


def repository_for_feedback(settings: Settings, body: Dict[str, Any]) -> Repository:
    user_key = _extract_feedback_user_key(body)
    if not user_key:
        return _build_repo(settings.db_path)

    scoped_settings = settings_for_user(settings, user_key)
    scoped_repo = _build_repo(scoped_settings.db_path)
    target = extract_feedback_target(body)
    if target.item_id is None:
        return scoped_repo

    scoped_item = scoped_repo.get_item(target.item_id)
    if item_matches_feedback_target(scoped_item, target):
        return scoped_repo

    if scoped_settings.db_path == settings.db_path:
        return scoped_repo

    global_repo = _build_repo(settings.db_path)
    global_item = global_repo.get_item(target.item_id)
    if item_matches_feedback_target(global_item, target):
        return global_repo

    return scoped_repo


def _build_repo(db_path) -> Repository:
    repo = Repository(db_path)
    repo.init_db()
    return repo


def _extract_feedback_user_key(body: Dict[str, Any]) -> str:
    for path in (
        ["operator", "open_id"],
        ["event", "operator", "open_id"],
        ["operator", "user_id"],
        ["event", "operator", "user_id"],
        ["event", "message", "chat_id"],
        ["action", "open_chat_id"],
    ):
        value = _deep_get(body, path)
        if value:
            return str(value)
    return ""


def _deep_get(payload: Dict[str, Any], keys: list[str]) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current
