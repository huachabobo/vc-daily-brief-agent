import logging

from vc_agent.delivery.feishu import DeliveryResult, FeishuNotifier
from vc_agent.settings import Settings


def test_send_text_message_logs_success(monkeypatch, tmp_path, caplog):
    settings = Settings.from_env(tmp_path)
    settings.feishu_app_id = "cli_test"
    settings.feishu_app_secret = "secret"
    notifier = FeishuNotifier(settings)

    monkeypatch.setattr(notifier, "_tenant_access_token", lambda: "token")
    monkeypatch.setattr(
        notifier,
        "_send_app_message",
        lambda **kwargs: DeliveryResult(channel="app:chat_id", status="sent", message_id="om_test_message"),
    )

    with caplog.at_level(logging.INFO):
        result = notifier.send_text_message("chat_id", "oc_test_chat", "你好")

    assert result.message_id == "om_test_message"
    assert "飞书文本消息发送成功" in caplog.text
