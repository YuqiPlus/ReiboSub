import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video_translate.youtube.download_video import *  # noqa: F401,F403
from video_translate.youtube.download_video import main


if __name__ == "__main__":
    main()
