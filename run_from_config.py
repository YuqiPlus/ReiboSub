from __future__ import annotations

import argparse
from pathlib import Path

from video_translate.run_config import run_config


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "configs" / "run.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Video_Translate from a YAML config.")
    parser.add_argument("config", nargs="?", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    run_config(args.config)


if __name__ == "__main__":
    main()
