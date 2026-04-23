import logging
from pathlib import Path
import sys

import uvicorn


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vc_agent.feedback.server import create_app  # noqa: E402
from vc_agent.feedback.long_connection import serve_long_connection  # noqa: E402
from vc_agent.scheduler import BriefScheduler  # noqa: E402
from vc_agent.settings import Settings  # noqa: E402


def main() -> None:
    settings = Settings.from_env(ROOT)
    settings.ensure_runtime_dirs()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    scheduler = BriefScheduler(settings).start()

    if settings.feishu_callback_mode == "long_connection":
        serve_long_connection(settings)
        scheduler.stop()
        return
    if settings.feishu_callback_mode != "http":
        scheduler.stop()
        raise RuntimeError(
            "不支持的 FEISHU_CALLBACK_MODE: {0}，请使用 `http` 或 `long_connection`。".format(
                settings.feishu_callback_mode
            )
        )

    app = create_app(settings)
    uvicorn.run(app, host="0.0.0.0", port=settings.feedback_port)
    scheduler.stop()


if __name__ == "__main__":
    main()
