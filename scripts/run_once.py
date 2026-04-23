from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vc_agent.pipeline.run_once import run  # noqa: E402
from vc_agent.settings import Settings  # noqa: E402


def main() -> None:
    settings = Settings.from_env(ROOT)
    result = run(settings)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
