from pathlib import Path

from video_translate.run_config import run_config


CONFIG_PATH = Path(__file__).resolve().parent / "configs" / "run.yaml"


if __name__ == "__main__":
    run_config(CONFIG_PATH)
