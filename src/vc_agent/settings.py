from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    return float(value)


@dataclass
class Settings:
    repo_root: Path
    db_path: Path
    output_dir: Path
    sources_config: Path
    youtube_api_key: str
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    feishu_webhook_url: str
    feishu_webhook_secret: str
    feishu_app_id: str
    feishu_app_secret: str
    feishu_chat_id: str
    feishu_receive_id_type: str
    feishu_receive_id: str
    feishu_verify_token: str
    feishu_callback_mode: str
    timezone: str
    lookback_hours: int
    fallback_lookback_hours: int
    max_fetch_per_source: int
    max_brief_items: int
    exploration_slots: int
    min_score_threshold: float
    feedback_port: int
    log_level: str

    @classmethod
    def from_env(cls, repo_root: Path = ROOT) -> "Settings":
        _load_dotenv(repo_root / ".env")

        db_path = repo_root / os.getenv("DB_PATH", "data/vc_agent.db")
        output_dir = repo_root / os.getenv("OUTPUT_DIR", "sample_output")
        sources_config = repo_root / os.getenv("SOURCES_CONFIG", "config/sources.yaml")

        return cls(
            repo_root=repo_root,
            db_path=db_path,
            output_dir=output_dir,
            sources_config=sources_config,
            youtube_api_key=os.getenv("YOUTUBE_API_KEY", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            feishu_webhook_url=os.getenv("FEISHU_WEBHOOK_URL", ""),
            feishu_webhook_secret=os.getenv("FEISHU_WEBHOOK_SECRET", ""),
            feishu_app_id=os.getenv("FEISHU_APP_ID", ""),
            feishu_app_secret=os.getenv("FEISHU_APP_SECRET", ""),
            feishu_chat_id=os.getenv("FEISHU_CHAT_ID", ""),
            feishu_receive_id_type=os.getenv("FEISHU_RECEIVE_ID_TYPE", ""),
            feishu_receive_id=os.getenv("FEISHU_RECEIVE_ID", ""),
            feishu_verify_token=os.getenv("FEISHU_VERIFY_TOKEN", ""),
            feishu_callback_mode=(os.getenv("FEISHU_CALLBACK_MODE", "http") or "http").strip().lower(),
            timezone=os.getenv("TIMEZONE", "Asia/Shanghai"),
            lookback_hours=_env_int("LOOKBACK_HOURS", 48),
            fallback_lookback_hours=_env_int("FALLBACK_LOOKBACK_HOURS", 168),
            max_fetch_per_source=_env_int("MAX_FETCH_PER_SOURCE", 10),
            max_brief_items=_env_int("MAX_BRIEF_ITEMS", 6),
            exploration_slots=_env_int("EXPLORATION_SLOTS", 1),
            min_score_threshold=_env_float("MIN_SCORE_THRESHOLD", 0.55),
            feedback_port=_env_int("FEEDBACK_PORT", 8787),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )

    def ensure_runtime_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_feishu_webhook(self) -> bool:
        return bool(self.feishu_webhook_url)

    @property
    def has_feishu_app(self) -> bool:
        has_receiver = bool(self.feishu_chat_id or self.feishu_receive_id)
        return bool(self.feishu_app_id and self.feishu_app_secret and has_receiver)

    def as_runtime_dict(self) -> Dict[str, str]:
        return {
            "db_path": str(self.db_path),
            "output_dir": str(self.output_dir),
            "sources_config": str(self.sources_config),
            "timezone": self.timezone,
        }
