from __future__ import annotations

import argparse

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ReiboSub web UI.")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--install-missing", action="store_true", help="Explicitly install missing web Python dependencies before starting, in the current venv/Conda environment")
    args = parser.parse_args()
    if args.install_missing:
        from reibosub import ReiboSubError
        from video_translate.dependencies import ensure_feature
        try:
            ensure_feature("web", install=True)
        except ReiboSubError as exc:
            parser.exit(2, f"{exc}\n")
    try:
        from video_translate.web_agent import DEFAULT_HOST, DEFAULT_PORT, serve
    except ModuleNotFoundError as exc:
        if exc.name not in {"requests", "yaml", "yt_dlp", "PIL"}:
            raise
        parser.exit(2, 'Missing web dependencies. Run python -m pip install -e ".[web]", or explicitly pass --install-missing in a venv/Conda environment.\n')
    serve(args.host if args.host is not None else DEFAULT_HOST,
          args.port if args.port is not None else DEFAULT_PORT)


if __name__ == "__main__":
    main()
