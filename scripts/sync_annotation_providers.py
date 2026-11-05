"""Import text-model choices from local annotation provider YAML files.

Preview: python scripts/sync_annotation_providers.py --source-dir PATH
Apply: add --apply. Connection values stay in the local credential store;
printed plans and summaries contain no credentials or endpoint URLs.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml

from video_translate.local_config_lock import LOCAL_CONFIG_WRITE_LOCK
from video_translate.provider_management import (
    create_provider_profile, update_provider_profile, _snapshot_file, _restore_file,
)
from video_translate.provider_profiles import (
    list_provider_profiles, clear_provider_model_cache, get_provider_profile,
    ProviderProfile, _model_discovery_url, _parse_model_ids, _url_origin,
)
from video_translate.provider_secrets import update_provider_connection_settings


@dataclass
class SourceModel:
    filename: str
    model: str
    base_url: str = field(repr=False)
    api_key: str = field(repr=False)

    @property
    def connection(self):
        return self.base_url.rstrip("/"), self.api_key


@dataclass
class ImportItem:
    id: str
    label: str
    default_model: str
    models: list[str]
    source: SourceModel = field(repr=False)

    def public(self):
        return {"id": self.id, "label": self.label, "default_model": self.default_model,
                "models": self.models}


def read_source(source_dir):
    records, skipped = [], []
    for path in sorted([*source_dir.glob("*.yml"), *source_dir.glob("*.yaml")]):
        if "example" in path.stem.lower():
            skipped.append({"file": path.name, "reason": "example"})
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, UnicodeError):
            raise ValueError(f"Invalid provider YAML: {path.name}") from None
        if not isinstance(data, dict):
            raise ValueError(f"Provider must be a mapping: {path.name}")
        if data.get("model_purpose", "chat") not in {"chat", "text", "translation"}:
            skipped.append({"file": path.name, "reason": "not_text_generation"})
            continue
        interface = str(data.get("interface") or "openai_compatible").replace("_", "-")
        protocol = str(data.get("usage_protocol") or interface).replace("_", "-")
        if interface != "openai-compatible" or protocol != "openai-compatible":
            skipped.append({"file": path.name, "reason": "unsupported_protocol"})
            continue
        values = [str(data.get(k) or "").strip() for k in ["model_name", "base_url", "api_key"]]
        if not all(values):
            raise ValueError(f"Incomplete local connection: {path.name}")
        if re.fullmatch(r"[A-Z_][A-Z0-9_]*", values[2]):
            skipped.append({"file": path.name, "reason": "unresolved_environment_key"})
            continue
        records.append(SourceModel(path.name, *values))
    if not records:
        raise ValueError("Source directory contains no configured text models")
    return records, skipped


def build_plan(records, existing, settings):
    by_id = {p.id: p for p in existing}
    primary = next((r for r in records if Path(r.filename).stem == "all"), records[0])
    plan = []

    def add(profile_id, label, source, selected, preserve_catalog=False):
        models = {r.model for r in selected}
        current = by_id.get(profile_id)
        if preserve_catalog and current:
            models.update(current.models)
        if current and current.default_model:
            # Catalog maintenance never silently changes the user's default.
            models.add(current.default_model)
        defaults = settings.get("defaults", {})
        for binding in settings.get("tasks", {}).values():
            effective = binding.get("provider_profile") or defaults.get("provider_profile")
            if effective == profile_id and binding.get("model"):
                models.add(binding["model"])
        plan.append(ImportItem(profile_id, current.label if current else label,
                               current.default_model if current and current.default_model else source.model,
                               sorted(models), source))

    for profile_id, label, prefix in [
        ("claude", "Anthropic", "claude-"), ("gemini", "Google", "gemini-"),
        ("openai", "OpenAI", "gpt-"), ("qianwen", "阿里云", "qwen"),
    ]:
        selected = [r for r in records if r.connection == primary.connection and r.model.startswith(prefix)]
        if selected:
            add(profile_id, label, selected[0], selected)

    deepseek = next((r for r in records if Path(r.filename).stem == "deepseek-v4-pro"), None)
    if deepseek:
        add("deepseek", "DeepSeek", deepseek,
            [r for r in records if r.connection == deepseek.connection and r.model.startswith("deepseek-")])
    doubao = [r for r in records if r.model.startswith("doubao-")]
    if doubao:
        source = doubao[0]
        current = by_id.get("volcano")
        if current:
            source = next((r for r in doubao if r.base_url.rstrip("/") == str(current.base_url or "").rstrip("/")), source)
        add("volcano", "火山引擎", source, [r for r in records if r.connection == source.connection], True)

    if "model-gateway" in by_id and str(by_id["model-gateway"].base_url or "").rstrip("/") != primary.base_url.rstrip("/"):
        raise ValueError("Import ID conflicts with another saved connection: model-gateway")
    add("model-gateway", "统一模型网关", primary, [r for r in records if r.connection == primary.connection])
    covered = {item.source.connection for item in plan}
    for record in records:
        if record.connection in covered:
            continue
        profile_id = "imported-" + Path(record.filename).stem.lower()
        if profile_id in by_id:
            current = by_id[profile_id]
            if str(current.base_url or "").rstrip("/") != record.base_url.rstrip("/"):
                raise ValueError(f"Import ID conflicts with another saved connection: {profile_id}")
        add(profile_id, f"备用接口 · {record.model}", record,
            [r for r in records if r.connection == record.connection])
        covered.add(record.connection)
    return plan


def discover_dated_aliases(plan):
    """Add actual date-versioned IDs without changing saved task selections."""
    import requests
    catalogs, checks = {}, []
    for item in plan:
        connection = item.source.connection
        if connection not in catalogs:
            profile = ProviderProfile(item.id, item.label, item.source.base_url, item.source.api_key,
                                      None, "openai-compatible", (), item.id)
            url = _model_discovery_url(profile)
            try:
                response = requests.get(url, headers={"Authorization": f"Bearer {item.source.api_key}",
                                                     "Accept": "application/json"},
                                        timeout=15, allow_redirects=False)
                catalog = _parse_model_ids(response.json()) if 200 <= response.status_code < 300 else []
                catalogs[connection] = catalog
                checks.append({"provider": item.id, "http": response.status_code, "models": len(catalog)})
            except (requests.RequestException, ValueError, TypeError):
                catalogs[connection] = []
                checks.append({"provider": item.id, "status": "catalog_unavailable"})
        for configured in list(item.models):
            # Ark advertises explicit release IDs for Doubao rather than the
            # short aliases used by some annotation configurations.
            if not configured.startswith("doubao-seed-"):
                continue
            normalized = configured.replace(".", "-")
            candidates = [m for m in catalogs[connection]
                          if re.fullmatch(re.escape(normalized) + r"-\d{6}", m)]
            if candidates:
                item.models = sorted(set([*item.models, max(candidates)]))
    return checks


def apply_plan(plan, root):
    paths = [root / "configs" / name for name in ["provider_profiles.yaml", "provider_secrets.yaml", "app_settings.yaml"]]
    with LOCAL_CONFIG_WRITE_LOCK:
        snapshots = {path: _snapshot_file(path) for path in paths}
        backup = root / "outputs/config_backups" / datetime.now(timezone.utc).strftime("provider-sync-%Y%m%dT%H%M%S%fZ")
        backup.mkdir(parents=True, mode=0o700)
        for path, snapshot in snapshots.items():
            if snapshot.existed:
                target = backup / path.name
                shutil.copy2(path, target)
                target.chmod(0o600)
        existing = {p.id for p in list_provider_profiles(root)}
        try:
            for item in plan:
                connection = {"base_url": item.source.base_url, "api_key": item.source.api_key}
                if item.id in existing:
                    update_provider_profile(item.id, {"label": item.label, "default_model": item.default_model,
                                                      "models": item.models}, root)
                    # A discovery override on the old origin must not carry
                    # the new endpoint's credentials to a different service.
                    current = get_provider_profile(item.id, root)
                    if current.models_url and _url_origin(current.models_url) != _url_origin(item.source.base_url):
                        connection["clear_models_url"] = True
                    update_provider_connection_settings(item.id, connection, root)
                else:
                    create_provider_profile({**item.public(), **connection}, root)
            settings = paths[-1]
            if snapshots[settings] != _snapshot_file(settings):
                raise RuntimeError("Provider sync unexpectedly changed task bindings")
        except Exception:
            for path, snapshot in snapshots.items():
                _restore_file(path, snapshot)
            clear_provider_model_cache()
            raise
    clear_provider_model_cache()
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--root", default=ROOT, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--discover", action="store_true", help="Check remote catalogs and add date-versioned Doubao IDs")
    args = parser.parse_args()
    root = args.root.resolve()
    records, skipped = read_source(args.source_dir.resolve())
    settings_path = root / "configs/app_settings.yaml"
    settings = yaml.safe_load(settings_path.read_text()) if settings_path.exists() else {}
    plan = build_plan(records, list_provider_profiles(root), settings or {})
    checks = discover_dated_aliases(plan) if args.discover else []
    import json
    print(json.dumps({"providers": [item.public() for item in plan], "skipped": skipped, "catalog_checks": checks}, ensure_ascii=False, indent=2))
    if args.apply:
        backup = apply_plan(plan, root)
        print("Applied. Private backup:", backup.relative_to(root))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Upstream parsing/validation errors can contain raw credential lines.
        print(f"Provider sync failed ({type(exc).__name__}); no secret values printed.", file=sys.stderr)
        raise SystemExit(1) from None
