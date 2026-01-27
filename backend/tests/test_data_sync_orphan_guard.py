import json
from pathlib import Path

from app.services.data_sync_orphan_guard import load_data_sync_orphan_guard_config


def test_orphan_guard_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    cfg = load_data_sync_orphan_guard_config()
    assert cfg["enabled"] is True
    assert cfg["dry_run"] is False
    assert cfg["evidence_required"] is True


def test_orphan_guard_load_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    cfg_path = tmp_path / "config" / "data_sync_orphan_guard.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"enabled": False, "dry_run": True}))
    cfg = load_data_sync_orphan_guard_config()
    assert cfg["enabled"] is False
    assert cfg["dry_run"] is True
