"""Standalone subtitle commands. Video/application commands belong to the web product."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from dataclasses import asdict
from pathlib import Path

from .dependencies import FEATURES, check_feature, ensure_feature
from .errors import ReiboSubError
from .models import Subtitle



def _show(status, *, json_output=False):
    value = asdict(status) | {"ready": status.ready, "python_ready": status.python_ready, "install_command": list(status.install_command) if status.missing_requirements else []}
    if json_output:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(f"{status.feature}: {'ready' if status.ready else 'needs setup'}")
        for key in ("missing_requirements", "missing_modules", "missing_external", "manual_steps", "conflicts", "notes"):
            if value[key]:
                print(f"{key}: " + "; ".join(value[key]))
        if status.missing_requirements:
            print("install: " + shlex.join(status.install_command))


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="reibosub", description="Standalone subtitle tools and explicit lightweight dependency setup.")
    sub = parser.add_subparsers(dest="command", required=True)
    convert = sub.add_parser("convert", help="Convert subtitle format without OCR/ASR")
    convert.add_argument("source", type=Path); convert.add_argument("out", type=Path)
    convert.add_argument("--format", default=None); convert.add_argument("--overwrite", action="store_true")
    script = sub.add_parser("script", help="Convert Simplified/Traditional text locally")
    script.add_argument("source", type=Path); script.add_argument("out", type=Path)
    script.add_argument("--to", choices=("simplified", "traditional"), required=True)
    script.add_argument("--install-missing", action="store_true"); script.add_argument("--overwrite", action="store_true")
    text = sub.add_parser("text", help="Print dialogue as plain text")
    text.add_argument("source", type=Path); text.add_argument("--timestamps", action="store_true")
    translate = sub.add_parser("translate", help="Translate with an explicitly configured compatible service")
    translate.add_argument("source", type=Path); translate.add_argument("out", type=Path)
    translate.add_argument("--base-url", required=True); translate.add_argument("--model", required=True)
    translate.add_argument("--target", default="en"); translate.add_argument("--source-language", default=None)
    translate.add_argument("--api-key-env", default="REIBOSUB_API_KEY")
    translate.add_argument("--batch-size", type=int, default=40); translate.add_argument("--timeout", type=float, default=60)
    translate.add_argument("--overwrite", action="store_true")
    doctor = sub.add_parser("doctor", help="Read-only optional dependency diagnostics")
    doctor.add_argument("feature", nargs="?", default="core", choices=FEATURES); doctor.add_argument("--json", action="store_true")
    setup = sub.add_parser("setup", help="Inspect or explicitly install a feature in the current venv/Conda environment")
    setup.add_argument("feature", choices=FEATURES); setup.add_argument("--yes", action="store_true"); setup.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            _show(check_feature(args.feature), json_output=args.json)
        elif args.command == "setup":
            status = check_feature(args.feature)
            _show(status)
            if args.dry_run or status.ready:
                return
            if not args.yes:
                parser.error("No installation performed. Add --yes to explicitly install missing Python dependencies")
            _show(ensure_feature(args.feature, install=True))
        elif args.command == "text":
            print(Subtitle.load(args.source).to_text(timestamps=args.timestamps))
        else:
            if (args.out.exists() or args.out.is_symlink()) and not args.overwrite:
                raise FileExistsError("Output exists; choose a new path or explicitly pass --overwrite")
            subtitle = Subtitle.load(args.source)
            if args.command == "convert":
                subtitle.save(args.out, format=args.format, overwrite=args.overwrite)
            elif args.command == "script":
                result = subtitle.to_simplified(install_missing=args.install_missing) if args.to == "simplified" else subtitle.to_traditional(install_missing=args.install_missing)
                result.save(args.out, overwrite=args.overwrite)
            elif args.command == "translate":
                from .translation import Translator
                key = os.environ.get(args.api_key_env)
                if not key:
                    parser.error(f"Set the explicitly selected API-key variable {args.api_key_env}; website keys are never loaded")
                client = Translator(base_url=args.base_url, api_key=key, model=args.model, timeout=args.timeout)
                client.translate(subtitle, target_language=args.target, source_language=args.source_language, batch_size=args.batch_size).save(args.out, overwrite=args.overwrite)
    except (ReiboSubError, OSError, UnicodeError) as exc:
        parser.exit(2, f"reibosub: {exc}\n")


if __name__ == "__main__":
    main()
