from __future__ import annotations

import threading
import json
import logging
from dataclasses import replace
from typing import Any

from vc_agent.delivery.feishu import FeishuNotifier
from vc_agent.feedback.message_preferences import (
    handle_preference_card_action,
    handle_preference_message,
)
from vc_agent.feedback.schedule_commands import (
    handle_schedule_message,
    looks_like_generate_now_request,
    looks_like_preference_followup,
)
from vc_agent.feedback.processing import (
    FeedbackNotFoundError,
    FeedbackValidationError,
    handle_feedback_payload,
)
from vc_agent.pipeline.run_once import run
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
    notifier = FeishuNotifier(settings)

    def do_card_action_trigger(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        body = json.loads(lark.JSON.marshal(data))
        LOGGER.info("收到飞书长连接卡片交互回调。")
        if _has_preference_assistant_action(body):
            try:
                result = handle_preference_card_action(settings, body)
                operator_open_id = _extract_operator_open_id(body)
                if result.reply_text and operator_open_id:
                    notifier.send_text_message("open_id", operator_open_id, result.reply_text)
                return P2CardActionTriggerResponse(
                    {
                        "toast": {
                            "type": "success",
                            "content": result.toast_content,
                        }
                    }
                )
            except Exception:
                LOGGER.exception("飞书长连接处理偏好助手按钮失败。")
                return P2CardActionTriggerResponse(
                    {
                        "toast": {
                            "type": "danger",
                            "content": "偏好修改暂时处理失败，请稍后再试。",
                        }
                    }
                )
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
        body = json.loads(lark.JSON.marshal(data))
        text = _safe_message_preview(data)
        LOGGER.info("收到飞书消息事件。preview=%s", text)
        try:
            chat_id = _extract_chat_id(body)
            if looks_like_generate_now_request(body):
                _handle_generate_now_request(settings, notifier, chat_id)
                return
            text_message = _extract_text_message(body)
            schedule_result = handle_schedule_message(settings, body)
            if schedule_result.handled:
                if not chat_id:
                    LOGGER.warning("飞书消息缺少 chat_id，无法回复调度设置。body=%s", body)
                    return
                notifier.send_text_message("chat_id", chat_id, schedule_result.reply_text)
                if not looks_like_preference_followup(text_message):
                    return
            result = handle_preference_message(settings, body)
            if not result.should_reply:
                return
            if not chat_id:
                LOGGER.warning("飞书消息缺少 chat_id，无法回复。body=%s", body)
                return
            if result.reply_card:
                notifier.send_interactive_message("chat_id", chat_id, result.reply_card)
                return
            notifier.send_text_message("chat_id", chat_id, result.reply_text)
        except Exception:
            LOGGER.exception("飞书长连接处理文本消息失败。")

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


def _extract_chat_id(body: dict[str, Any]) -> str:
    return str(body.get("event", {}).get("message", {}).get("chat_id") or "")


def _extract_operator_open_id(body: dict[str, Any]) -> str:
    return str(body.get("event", {}).get("operator", {}).get("open_id") or "")


def _has_preference_assistant_action(body: dict[str, Any]) -> bool:
    value = body.get("event", {}).get("action", {}).get("value", {})
    if not isinstance(value, dict):
        return False
    return bool(value.get("assistant_action"))


def _extract_text_message(body: dict[str, Any]) -> str:
    raw = body.get("event", {}).get("message", {}).get("content")
    if not raw:
        return ""
    if isinstance(raw, dict):
        return str(raw.get("text") or "").strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return str(parsed.get("text") or "").strip()
    except Exception:
        pass
    return str(raw).strip()


def _handle_generate_now_request(settings: Settings, notifier: FeishuNotifier, chat_id: str) -> None:
    if not chat_id:
        LOGGER.warning("收到生成日报请求，但缺少 chat_id。")
        return
    notifier.send_text_message("chat_id", chat_id, "收到，我现在开始生成一版最新日报，完成后会直接发到这个会话。")
    worker_settings = replace(settings, feishu_chat_id=chat_id, feishu_receive_id_type="", feishu_receive_id="")
    worker = threading.Thread(
        target=_run_generate_now_worker,
        args=(worker_settings, notifier, chat_id),
        name="vc-agent-generate-now",
        daemon=True,
    )
    worker.start()


def _run_generate_now_worker(settings: Settings, notifier: FeishuNotifier, chat_id: str) -> None:
    try:
        result = run(settings)
        notifier.send_text_message(
            "chat_id",
            chat_id,
            "这版日报已经生成并发送完成，共抓到 {0} 条候选内容，最终入选 {1} 条。".format(
                result.get("candidate_count", 0),
                result.get("selected_count", 0),
            ),
        )
    except Exception as exc:
        LOGGER.exception("即时生成日报失败。")
        notifier.send_text_message(
            "chat_id",
            chat_id,
            "这次日报生成失败了：{0}。你可以稍后再试，或者先发“查看当前偏好 / 查看推送时间”。".format(exc),
        )
