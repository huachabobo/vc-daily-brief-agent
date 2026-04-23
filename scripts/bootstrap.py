from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vc_agent.bootstrap import run_bootstrap  # noqa: E402


def main() -> None:
    run_bootstrap(ROOT)


if __name__ == "__main__":
    main()
