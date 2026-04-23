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
    label = _deep_get(body, ["action", "value", "label"])
    if label is None:
        label = _deep_get(body, ["event", "action", "value", "label"])
    if label is None:
        label = body.get("label")
    return label


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
