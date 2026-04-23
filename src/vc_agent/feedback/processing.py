from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from vc_agent.ranking.learner import apply_feedback
from vc_agent.storage import Repository


class FeedbackError(Exception):
    """Base error for feedback processing."""


class FeedbackValidationError(FeedbackError):
    """Raised when callback payload misses required fields."""


class FeedbackNotFoundError(FeedbackError):
    """Raised when the referenced item cannot be found."""


@dataclass
class FeedbackHandleResult:
    item_id: int
    label: str
    toast_type: str = "success"
    toast_content: str = "反馈已记录，下次排序会调整。"

    def as_feishu_response(self) -> Dict[str, Any]:
        return {
            "toast": {
                "type": self.toast_type,
                "content": self.toast_content,
            }
        }


@dataclass(frozen=True)
class FeedbackTarget:
    item_id: Optional[int]
    source_key: str = ""
    platform_item_id: str = ""


def handle_feedback_payload(
    repo: Repository,
    body: Dict[str, Any],
    source_hint: Optional[str] = None,
) -> FeedbackHandleResult:
    item_id = _extract_item_id(body)
    label = _extract_label(body)
    if not item_id or label not in ("useful", "dislike"):
        raise FeedbackValidationError("missing item_id or label")

    item = repo.get_item(item_id)
    if item is None:
        raise FeedbackNotFoundError("item not found")

    repo.record_feedback(
        item_id=item_id,
        label=label,
        source=source_hint or _extract_source(body),
        user_id=_extract_user_id(body),
        metadata=body,
    )

    state = repo.load_preference_state()
    state = apply_feedback(state, item, label)
    repo.save_preference_state(state)

    return FeedbackHandleResult(item_id=item_id, label=label)


def extract_feedback_target(body: Dict[str, Any]) -> FeedbackTarget:
    return FeedbackTarget(
        item_id=_extract_item_id(body),
        source_key=_extract_action_value(body, "source_key") or "",
        platform_item_id=_extract_action_value(body, "platform_item_id") or "",
    )


def item_matches_feedback_target(item: Any, target: FeedbackTarget) -> bool:
    if item is None:
        return False
    if target.item_id is not None and getattr(item, "item_id", None) != target.item_id:
        return False
    if target.source_key and getattr(item, "source_key", "") != target.source_key:
        return False
    if target.platform_item_id and getattr(item, "platform_item_id", "") != target.platform_item_id:
        return False
    return True


def _extract_item_id(body: Dict[str, Any]) -> Optional[int]:
    raw = _deep_get(body, ["action", "value", "item_id"])
    if raw is None:
        raw = _deep_get(body, ["event", "action", "value", "item_id"])
    if raw is None:
        raw = body.get("item_id")
    if raw in (None, ""):
        return None
    return int(raw)


def _extract_label(body: Dict[str, Any]) -> Optional[str]:
    return _extract_action_value(body, "label") or body.get("label")


def _extract_action_value(body: Dict[str, Any], field: str) -> Optional[Any]:
    value = _deep_get(body, ["action", "value", field])
    if value is None:
        value = _deep_get(body, ["event", "action", "value", field])
    return value


def _extract_user_id(body: Dict[str, Any]) -> Optional[str]:
    for path in (
        ["operator", "open_id"],
        ["event", "operator", "open_id"],
        ["operator", "user_id"],
        ["event", "operator", "user_id"],
    ):
        value = _deep_get(body, path)
        if value:
            return str(value)
    return None


def _extract_source(body: Dict[str, Any]) -> str:
    if "event" in body or "action" in body:
        return "feishu"
    return "local"


def _deep_get(payload: Dict[str, Any], keys: list[str]) -> Optional[Any]:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current
