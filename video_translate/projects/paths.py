from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


class ProjectPathPolicy:
    """Resolves user-provided paths only within configured project roots."""

    def __init__(self, root: Path, allowed_roots: Iterable[Path]) -> None:
        self._root = Path(root).resolve()
        self._allowed_roots = [Path(path).resolve() for path in allowed_roots]

    def resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self._root / path
        return path.resolve()

    def ensure_allowed(self, path: Path) -> None:
        resolved = Path(path).resolve()
        if not any(self.is_relative_to(resolved, root) for root in self._allowed_roots):
            raise ValueError("路径不在允许的项目目录内")

    @staticmethod
    def is_relative_to(path: Path, parent: Path) -> bool:
        try:
            Path(path).resolve().relative_to(Path(parent).resolve())
            return True
        except ValueError:
            return False
