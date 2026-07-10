from __future__ import annotations

from pathlib import Path

import pytest

from video_translate.projects import ProjectPathPolicy


def test_project_path_policy_resolves_relative_paths_inside_root(tmp_path: Path):
    root = tmp_path / "workspace"
    policy = ProjectPathPolicy(root, [root])

    assert policy.resolve("outputs/demo.srt") == (root / "outputs" / "demo.srt").resolve()


def test_project_path_policy_rejects_paths_outside_allowed_roots(tmp_path: Path):
    root = tmp_path / "workspace"
    outside = tmp_path / "outside" / "secret.srt"
    policy = ProjectPathPolicy(root, [root])

    with pytest.raises(ValueError, match="允许的项目目录"):
        policy.ensure_allowed(outside)
