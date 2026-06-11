from __future__ import annotations

import argparse

from video_translate.web_agent import DEFAULT_HOST, DEFAULT_PORT, serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Video Translate Agent web UI.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
