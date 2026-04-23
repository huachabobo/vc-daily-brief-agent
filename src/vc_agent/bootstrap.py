from __future__ import annotations

from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
import sys
from typing import Dict, Iterable, List


SECRET_KEYS = {
    "YOUTUBE_API_KEY",
    "OPENAI_API_KEY",
    "FEISHU_WEBHOOK_SECRET",
    "FEISHU_APP_SECRET",
}


@dataclass(frozen=True)
class PromptOption:
    key: str
    label: str


def parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def env_key_order(path: Path) -> List[str]:
    keys: List[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _ = line.split("=", 1)
        keys.append(key.strip())
    return keys


def render_env(keys: Iterable[str], values: Dict[str, str]) -> str:
    lines: List[str] = []
    previous_blank = False
    for key in keys:
        if key in {"OPENAI_API_KEY", "FEISHU_WEBHOOK_URL", "FEISHU_APP_ID", "DB_PATH"} and lines and not previous_blank:
            lines.append("")
        lines.append("{0}={1}".format(key, values.get(key, "")))
        previous_blank = False
    return "\n".join(lines) + "\n"


def run_bootstrap(repo_root: Path) -> None:
    template_path = repo_root / ".env.example"
    env_path = repo_root / ".env"
    template = parse_env_file(template_path)
    values = template.copy()
    values.update(parse_env_file(env_path))
    keys = env_key_order(template_path)

    if env_path.exists() and not _confirm("检测到已有 .env，是否覆盖", default=True):
        print("已取消，不修改现有 .env。")
        return

    print("VC Agent 配置向导")
    print("直接回车会保留当前值或默认值。")
    print("")

    values["YOUTUBE_API_KEY"] = _prompt_value(
        "YOUTUBE_API_KEY",
        current=values.get("YOUTUBE_API_KEY", ""),
        required=True,
        secret=True,
    )

    if _confirm("是否配置 OpenAI 兼容摘要接口", default=bool(values.get("OPENAI_API_KEY"))):
        values["OPENAI_API_KEY"] = _prompt_value(
            "OPENAI_API_KEY",
            current=values.get("OPENAI_API_KEY", ""),
            required=True,
            secret=True,
        )
        values["OPENAI_BASE_URL"] = _prompt_value(
            "OPENAI_BASE_URL",
            current=values.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        values["OPENAI_MODEL"] = _prompt_value(
            "OPENAI_MODEL",
            current=values.get("OPENAI_MODEL", "gpt-4.1-mini"),
        )
    else:
        values["OPENAI_API_KEY"] = ""

    feishu_mode = _prompt_choice(
        "飞书发送方式",
        [
            PromptOption("none", "不配置"),
            PromptOption("webhook", "Webhook"),
            PromptOption("app", "App Bot"),
        ],
        default=_default_feishu_mode(values),
    )
    _clear_feishu_values(values)
    if feishu_mode == "webhook":
        values["FEISHU_WEBHOOK_URL"] = _prompt_value(
            "FEISHU_WEBHOOK_URL",
            current=values.get("FEISHU_WEBHOOK_URL", ""),
            required=True,
        )
        values["FEISHU_WEBHOOK_SECRET"] = _prompt_value(
            "FEISHU_WEBHOOK_SECRET",
            current=values.get("FEISHU_WEBHOOK_SECRET", ""),
            secret=True,
        )
    elif feishu_mode == "app":
        values["FEISHU_APP_ID"] = _prompt_value(
            "FEISHU_APP_ID",
            current=values.get("FEISHU_APP_ID", ""),
            required=True,
        )
        values["FEISHU_APP_SECRET"] = _prompt_value(
            "FEISHU_APP_SECRET",
            current=values.get("FEISHU_APP_SECRET", ""),
            required=True,
            secret=True,
        )
        receiver_mode = _prompt_choice(
            "飞书接收对象",
            [
                PromptOption("private", "私聊"),
                PromptOption("group", "群聊"),
            ],
            default="private",
        )
        if receiver_mode == "group":
            values["FEISHU_CHAT_ID"] = _prompt_value(
                "FEISHU_CHAT_ID",
                current=values.get("FEISHU_CHAT_ID", ""),
                required=True,
            )
        else:
            values["FEISHU_RECEIVE_ID_TYPE"] = _prompt_choice(
                "私聊接收 ID 类型",
                [
                    PromptOption("open_id", "open_id"),
                    PromptOption("user_id", "user_id"),
                    PromptOption("email", "email"),
                ],
                default=values.get("FEISHU_RECEIVE_ID_TYPE", "open_id") or "open_id",
            )
            values["FEISHU_RECEIVE_ID"] = _prompt_value(
                "FEISHU_RECEIVE_ID",
                current=values.get("FEISHU_RECEIVE_ID", ""),
                required=True,
            )
        values["FEISHU_CALLBACK_MODE"] = _prompt_choice(
            "反馈接收方式",
            [
                PromptOption("long_connection", "长连接"),
                PromptOption("http", "HTTP 回调"),
            ],
            default=values.get("FEISHU_CALLBACK_MODE", "long_connection") or "long_connection",
        )
        if values["FEISHU_CALLBACK_MODE"] == "http":
            values["FEISHU_VERIFY_TOKEN"] = _prompt_value(
                "FEISHU_VERIFY_TOKEN",
                current=values.get("FEISHU_VERIFY_TOKEN", ""),
            )

    env_text = render_env(keys, values)
    env_path.write_text(env_text, encoding="utf-8")

    print("")
    print("已写入 {0}".format(env_path))
    print("下一步建议：")
    print("1. 检查 config/sources.yaml 中的频道列表")
    print("2. 运行 python scripts/run_once.py")
    if feishu_mode == "app":
        print("3. 如需接收反馈，运行 python scripts/serve_feedback.py")


def _default_feishu_mode(values: Dict[str, str]) -> str:
    if values.get("FEISHU_APP_ID") or values.get("FEISHU_APP_SECRET"):
        return "app"
    if values.get("FEISHU_WEBHOOK_URL"):
        return "webhook"
    return "none"


def _clear_feishu_values(values: Dict[str, str]) -> None:
    for key in (
        "FEISHU_WEBHOOK_URL",
        "FEISHU_WEBHOOK_SECRET",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_CHAT_ID",
        "FEISHU_RECEIVE_ID_TYPE",
        "FEISHU_RECEIVE_ID",
        "FEISHU_VERIFY_TOKEN",
        "FEISHU_CALLBACK_MODE",
    ):
        values[key] = ""
    values["FEISHU_CALLBACK_MODE"] = "http"


def _prompt_value(key: str, current: str, required: bool = False, secret: bool = False) -> str:
    while True:
        if secret:
            prompt = "{0} {1}: ".format(key, _secret_hint(current, required))
            if sys.stdin.isatty():
                try:
                    raw = getpass(prompt)
                except Exception:
                    raw = input(prompt)
            else:
                raw = input(prompt)
        else:
            suffix = " [{0}]".format(current) if current else ""
            raw = input("{0}{1}: ".format(key, suffix))
        value = raw.strip() or current.strip()
        if value or not required:
            return value
        print("{0} 为必填项。".format(key))


def _prompt_choice(title: str, options: List[PromptOption], default: str) -> str:
    mapping = {str(index): option.key for index, option in enumerate(options, start=1)}
    print(title + ":")
    default_index = "1"
    for index, option in enumerate(options, start=1):
        if option.key == default:
            default_index = str(index)
        print("  {0}. {1}".format(index, option.label))
    while True:
        raw = input("请选择 [{0}]: ".format(default_index)).strip() or default_index
        selected = mapping.get(raw)
        if selected:
            return selected
        print("请输入有效编号。")


def _confirm(title: str, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    raw = input("{0} {1}: ".format(title, suffix)).strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes"}


def _secret_hint(current: str, required: bool) -> str:
    if current:
        return "[已存在，回车保留]"
    if required:
        return "[必填]"
    return "[可留空]"
