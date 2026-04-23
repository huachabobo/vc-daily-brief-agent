from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

from vc_agent.domain import DailyBrief
from vc_agent.settings import Settings


LOGGER = logging.getLogger(__name__)


@dataclass
class DeliveryResult:
    channel: Optional[str]
    status: str
    message_id: Optional[str] = None


class FeishuNotifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()

    def send(self, brief: DailyBrief) -> DeliveryResult:
        if self.settings.has_feishu_app:
            try:
                return self._send_via_app(brief)
            except Exception as exc:
                LOGGER.warning("飞书应用发送失败，尝试降级到 webhook: %s", exc)
        if self.settings.has_feishu_webhook:
            return self._send_via_webhook(brief)
        return DeliveryResult(channel=None, status="skipped")

    def _send_via_webhook(self, brief: DailyBrief) -> DeliveryResult:
        payload = {
            "msg_type": "interactive",
            "card": self._build_card(brief),
        }
        if self.settings.feishu_webhook_secret:
            timestamp = str(int(time.time()))
            payload["timestamp"] = timestamp
            payload["sign"] = _sign_webhook(timestamp, self.settings.feishu_webhook_secret)
        response = self.session.post(
            self.settings.feishu_webhook_url,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("code") not in (None, 0):
            raise RuntimeError(body.get("msg", "feishu webhook send failed"))
        return DeliveryResult(channel="webhook", status="sent", message_id=body.get("data"))

    def _send_via_app(self, brief: DailyBrief) -> DeliveryResult:
        token = self._tenant_access_token()
        card = self._build_card(brief)
        receive_id_type, receive_id = self._resolve_receive_target()
        response = self.session.post(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={0}".format(receive_id_type),
            headers={
                "Authorization": "Bearer {0}".format(token),
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "receive_id": receive_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            },
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("code") not in (None, 0):
            raise RuntimeError(body.get("msg", "feishu app send failed"))
        message_id = None
        data = body.get("data") or {}
        if isinstance(data, dict):
            message_id = data.get("message_id")
        return DeliveryResult(channel="app:{0}".format(receive_id_type), status="sent", message_id=message_id)

    def _resolve_receive_target(self) -> tuple[str, str]:
        if self.settings.feishu_chat_id:
            return "chat_id", self.settings.feishu_chat_id

        receive_id_type = (self.settings.feishu_receive_id_type or "open_id").strip()
        receive_id = self.settings.feishu_receive_id.strip()
        if not receive_id:
            raise RuntimeError("飞书应用发送缺少接收者，请配置 FEISHU_CHAT_ID 或 FEISHU_RECEIVE_ID。")
        if receive_id_type not in {"open_id", "union_id", "user_id", "email", "chat_id"}:
            raise RuntimeError("不支持的 FEISHU_RECEIVE_ID_TYPE: {0}".format(receive_id_type))
        return receive_id_type, receive_id

    def _tenant_access_token(self) -> str:
        response = self.session.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": self.settings.feishu_app_id,
                "app_secret": self.settings.feishu_app_secret,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") not in (None, 0):
            raise RuntimeError(payload.get("msg", "failed to get tenant access token"))
        return payload["tenant_access_token"]

    def send_text_message(self, receive_id_type: str, receive_id: str, text: str) -> DeliveryResult:
        if not self.settings.feishu_app_id or not self.settings.feishu_app_secret:
            raise RuntimeError("飞书文本回复需要 FEISHU_APP_ID 和 FEISHU_APP_SECRET。")
        token = self._tenant_access_token()
        return self._send_app_message(
            token=token,
            receive_id_type=receive_id_type,
            receive_id=receive_id,
            msg_type="text",
            content={"text": text},
        )

    def send_interactive_message(self, receive_id_type: str, receive_id: str, card: dict) -> DeliveryResult:
        if not self.settings.feishu_app_id or not self.settings.feishu_app_secret:
            raise RuntimeError("飞书卡片回复需要 FEISHU_APP_ID 和 FEISHU_APP_SECRET。")
        token = self._tenant_access_token()
        return self._send_app_message(
            token=token,
            receive_id_type=receive_id_type,
            receive_id=receive_id,
            msg_type="interactive",
            content=card,
        )

    def _send_app_message(
        self,
        token: str,
        receive_id_type: str,
        receive_id: str,
        msg_type: str,
        content: dict,
    ) -> DeliveryResult:
        response = self.session.post(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={0}".format(receive_id_type),
            headers={
                "Authorization": "Bearer {0}".format(token),
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "receive_id": receive_id,
                "msg_type": msg_type,
                "content": json.dumps(content, ensure_ascii=False),
            },
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("code") not in (None, 0):
            raise RuntimeError(body.get("msg", "feishu app send failed"))
        message_id = None
        data = body.get("data") or {}
        if isinstance(data, dict):
            message_id = data.get("message_id")
        return DeliveryResult(channel="app:{0}".format(receive_id_type), status="sent", message_id=message_id)

    def _build_card(self, brief: DailyBrief) -> dict:
        elements = [
            {
                "tag": "markdown",
                "content": "\n".join(["- {0}".format(item) for item in brief.highlights]),
            },
            {"tag": "markdown", "content": "**今日变化**\n" + "\n".join(["- {0}".format(item) for item in brief.shifts])},
            {"tag": "hr"},
        ]
        for topic, entries in brief.grouped_entries.items():
            elements.append({"tag": "markdown", "content": "### {0}".format(topic)})
            for entry in entries:
                elements.append(
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": (
                                "**{title}**\n{summary}\n"
                                "> {why}\n"
                                "**Why selected**: {selected}\n"
                                "[查看原文]({url})\n"
                                "`{tags}`"
                            ).format(
                                title=entry.title,
                                summary=entry.summary,
                                why=entry.why_it_matters,
                                selected=entry.why_selected,
                                url=entry.source_url,
                                tags=" / ".join(entry.tags),
                            ),
                        },
                    }
                )
                elements.append(
                    {
                        "tag": "action",
                        "actions": [
                            {
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "👍 有用"},
                                "type": "primary",
                                "value": {"item_id": str(entry.item_id), "label": "useful"},
                            },
                            {
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "👎 不想看"},
                                "type": "default",
                                "value": {"item_id": str(entry.item_id), "label": "dislike"},
                            },
                        ],
                    }
                )
            elements.append({"tag": "hr"})

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": "VC Daily Brief | {0}".format(brief.brief_date)},
            },
            "elements": elements,
        }


def _sign_webhook(timestamp: str, secret: str) -> str:
    string_to_sign = "{0}\n{1}".format(timestamp, secret)
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")
