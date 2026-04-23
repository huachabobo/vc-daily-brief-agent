from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request

from vc_agent.feedback.processing import (
    FeedbackNotFoundError,
    FeedbackValidationError,
    handle_feedback_payload,
)
from vc_agent.feedback.repository_routing import repository_for_feedback
from vc_agent.settings import Settings


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
            repo = repository_for_feedback(settings, body)
            result = handle_feedback_payload(repo, body, source_hint="feishu_http")
        except FeedbackValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FeedbackNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        return result.as_feishu_response()

    return app


def _deep_get(payload: Dict[str, Any], keys: list[str]) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current
