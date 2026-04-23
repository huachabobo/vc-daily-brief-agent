from __future__ import annotations

import json
import logging
from typing import Any

from vc_agent.feedback.processing import (
    FeedbackNotFoundError,
    FeedbackValidationError,
    handle_feedback_payload,
)
from vc_agent.settings import Settings
from vc_agent.storage import Repository


LOGGER = logging.getLogger(__name__)


def serve_long_connection(settings: Settings) -> None:
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise RuntimeError("长连接模式需要 FEISHU_APP_ID 和 FEISHU_APP_SECRET。")

    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1.model.p2_im_message_receive_v1 import P2ImMessageReceiveV1
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTrigger,
            P2CardActionTriggerResponse,
        )
    except ImportError as exc:
        raise RuntimeError(
            "长连接模式需要安装 `lark-oapi`。请执行 `uv pip install -r requirements.txt`。"
        ) from exc

    repo = Repository(settings.db_path)
    repo.init_db()

    def do_card_action_trigger(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        body = json.loads(lark.JSON.marshal(data))
        LOGGER.info("收到飞书长连接卡片交互回调。")
        try:
            result = handle_feedback_payload(repo, body, source_hint="feishu_long_connection")
            return P2CardActionTriggerResponse(result.as_feishu_response())
        except FeedbackValidationError:
            LOGGER.warning("飞书长连接回调缺少 item_id 或 label: %s", body)
            return P2CardActionTriggerResponse(
                {
                    "toast": {
                        "type": "warning",
                        "content": "反馈参数不完整，这次没有记录。",
                    }
                }
            )
        except FeedbackNotFoundError:
            LOGGER.warning("飞书长连接回调引用了不存在的 item: %s", body)
            return P2CardActionTriggerResponse(
                {
                    "toast": {
                        "type": "warning",
                        "content": "这条内容已过期，请刷新后再试。",
                    }
                }
            )
        except Exception:
            LOGGER.exception("飞书长连接处理反馈失败。")
            return P2CardActionTriggerResponse(
                {
                    "toast": {
                        "type": "danger",
                        "content": "反馈暂时写入失败，请稍后重试。",
                    }
                }
            )

    def do_message_receive(data: P2ImMessageReceiveV1) -> None:
        text = _safe_message_preview(data)
        LOGGER.info("收到飞书消息事件，已忽略。preview=%s", text)

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(do_message_receive)
        .register_p2_card_action_trigger(do_card_action_trigger)
        .build()
    )

    client = lark.ws.Client(
        settings.feishu_app_id,
        settings.feishu_app_secret,
        event_handler=event_handler,
        log_level=_resolve_log_level(lark, settings.log_level),
    )
    LOGGER.info("启动飞书长连接模式，等待卡片交互事件。")
    client.start()


def _resolve_log_level(lark_module: Any, raw_level: str) -> Any:
    level = raw_level.upper()
    if level == "DEBUG":
        return lark_module.LogLevel.DEBUG
    if level in {"WARN", "WARNING"}:
        return lark_module.LogLevel.WARN
    if level == "ERROR":
        return lark_module.LogLevel.ERROR
    return lark_module.LogLevel.INFO


def _safe_message_preview(data: Any) -> str:
    try:
        event = getattr(data, "event", None)
        message = getattr(event, "message", None)
        content = getattr(message, "content", "") or ""
        if isinstance(content, str):
            return content[:120]
    except Exception:
        pass
    return ""
