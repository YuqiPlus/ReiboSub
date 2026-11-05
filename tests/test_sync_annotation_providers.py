from pathlib import Path

import pytest
import yaml

from scripts.sync_annotation_providers import SourceModel, read_source, build_plan, apply_plan, discover_dated_aliases
from video_translate.provider_management import create_provider_profile
from video_translate.provider_profiles import list_provider_profiles, get_provider_profile


def config(folder, name, **values):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(yaml.safe_dump(values), encoding="utf-8")


def test_import_excludes_image_models_and_templates_and_never_prints_connections(tmp_path):
    config(tmp_path, "all.yml", model_name="qwen-new", base_url="https://api.example/v1", api_key="private-key")
    config(tmp_path, "image.yml", model_name="image-only", base_url="https://api.example/v1", api_key="private-key", model_purpose="image_generation")
    config(tmp_path, "provider.example.yml", model_name="example", api_key="example")
    records, skipped = read_source(tmp_path)
    assert [r.model for r in records] == ["qwen-new"]
    assert {x["reason"] for x in skipped} == {"example", "not_text_generation"}
    plan = build_plan(records, [], {})
    assert "private-key" not in repr(plan)
    assert "private-key" not in repr([p.public() for p in plan])
    assert "api.example" not in repr([p.public() for p in plan])


def test_models_on_different_connections_are_not_mixed(tmp_path):
    records = [SourceModel("all.yml", "qwen-new", "https://relay.example/v1", "relay-key"),
               SourceModel("deepseek-v4-pro.yml", "deepseek-v4-pro", "https://ark.example/v3", "ark-key"),
               SourceModel("deepseek-new.yml", "deepseek-v4.1-flash", "https://relay.example/v1", "relay-key"),
               SourceModel("openai.yml", "gpt-4o", "https://other.example/v1", "other-key")]
    plan = {p.id: p for p in build_plan(records, [], {})}
    assert plan["deepseek"].models == ["deepseek-v4-pro"]
    assert "deepseek-v4.1-flash" in plan["model-gateway"].models
    assert plan["imported-openai"].source.base_url == "https://other.example/v1"


def test_apply_preserves_task_bindings_and_updates_private_credentials(tmp_path):
    create_provider_profile({"id": "volcano", "base_url": "https://ark.example/v3", "api_key": "old-key",
                             "default_model": "doubao-old", "models": ["doubao-old"]}, tmp_path)
    path = tmp_path / "configs/app_settings.yaml"
    settings = {"version": 1, "defaults": {"provider_profile": "volcano"},
                "tasks": {"subtitle_translation": {"provider_profile": "", "model": "doubao-dated-old"}}}
    path.write_text(yaml.safe_dump(settings), encoding="utf-8")
    before = path.read_bytes()
    records = [SourceModel("all.yml", "qwen-new", "https://relay.example/v1", "relay-key"),
               SourceModel("doubao-new.yml", "doubao-new", "https://ark.example/v3", "new-key")]
    plan = build_plan(records, list_provider_profiles(tmp_path), settings)
    backup = apply_plan(plan, tmp_path)
    assert path.read_bytes() == before
    profile = get_provider_profile("volcano", tmp_path)
    assert profile.api_key == "new-key"
    assert profile.default_model == "doubao-old"
    assert "doubao-dated-old" in profile.models and "doubao-new" in profile.models
    assert (tmp_path / "configs/provider_secrets.yaml").stat().st_mode & 0o777 == 0o600
    assert backup.stat().st_mode & 0o777 == 0o700
    assert "new-key" not in (tmp_path / "configs/provider_profiles.yaml").read_text()


def test_discovery_adds_explicit_release_id_without_changing_default(monkeypatch):
    records = [SourceModel("all.yml", "doubao-seed-2.1-pro", "https://ark.example/v3", "key")]
    plan = build_plan(records, [], {})
    class Response:
        status_code = 200
        def json(self):
            return {"data": [{"id": "doubao-seed-2-1-pro-260628"}, {"id": "doubao-seed-2-1-pro-260915"}]}
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: Response())
    discover_dated_aliases(plan)
    assert all(p.default_model == "doubao-seed-2.1-pro" for p in plan)
    assert all("doubao-seed-2-1-pro-260915" in p.models for p in plan)


def test_failed_sync_rolls_back_all_config_files(tmp_path, monkeypatch):
    records = [SourceModel("all.yml", "qwen-new", "https://relay.example/v1", "key")]
    plan = build_plan(records, [], {})
    original_create = __import__("scripts.sync_annotation_providers", fromlist=["create_provider_profile"]).create_provider_profile
    calls = 0
    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("test failure")
        return original_create(*args, **kwargs)
    monkeypatch.setattr("scripts.sync_annotation_providers.create_provider_profile", fail_second)
    with pytest.raises(RuntimeError):
        apply_plan(plan, tmp_path)
    assert not (tmp_path / "configs/provider_profiles.yaml").exists()
    assert not (tmp_path / "configs/provider_secrets.yaml").exists()
