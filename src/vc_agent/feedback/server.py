from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request

from vc_agent.feedback.processing import (
    FeedbackNotFoundError,
    FeedbackValidationError,
    handle_feedback_payload,
)
from vc_agent.settings import Settings
from vc_agent.storage import Repository
from vc_agent.user_runtime import settings_for_user


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="vc-agent-feedback")

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.post("/feishu/callback")
    async def feishu_callback(request: Request) -> Dict[str, Any]:
        body = await request.json()
        incoming_token = body.get("token") or _deep_get(body, ["header", "token"])

        if body.get("type") == "url_verification":
            if settings.feishu_verify_token and incoming_token and incoming_token != settings.feishu_verify_token:
                raise HTTPException(status_code=403, detail="invalid token")
            return {"challenge": body.get("challenge", "")}

        if settings.feishu_verify_token and incoming_token and incoming_token != settings.feishu_verify_token:
            raise HTTPException(status_code=403, detail="invalid token")

        try:
            scoped_settings = _runtime_settings_for_callback(settings, body)
            repo = Repository(scoped_settings.db_path)
            repo.init_db()
            result = handle_feedback_payload(repo, body, source_hint="feishu_http")
        except FeedbackValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FeedbackNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        return result.as_feishu_response()

    return app


def _runtime_settings_for_callback(settings: Settings, body: Dict[str, Any]) -> Settings:
    user_key = _extract_callback_user_key(body)
    if not user_key:
        return settings
    return settings_for_user(settings, user_key)


def _extract_callback_user_key(body: Dict[str, Any]) -> str:
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
