from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(anchor: Path | str | None = None, *, override: bool = False) -> None:
    candidates: list[Path] = [Path.cwd() / ".env"]
    if anchor is not None:
        anchor_path = Path(anchor).expanduser().resolve()
        candidates.append((anchor_path if anchor_path.is_dir() else anchor_path.parent) / ".env")

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen or not candidate.exists():
            continue
        seen.add(candidate)
        for line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if override:
                os.environ[key] = value
            else:
                os.environ.setdefault(key, value)
