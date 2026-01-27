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

from app.routes.datasets import _find_sync_job_evidence, _should_orphan_candidates


def test_orphan_evidence_detects_outputs(tmp_path):
    data_root = tmp_path
    (data_root / "curated").mkdir(parents=True)
    (data_root / "curated_adjusted").mkdir(parents=True)
    (data_root / "curated_versions" / "125_Alpha_X_Daily").mkdir(parents=True)

    (data_root / "curated" / "125_Alpha_X_Daily.csv").write_text("x")
    evidence = _find_sync_job_evidence(data_root, dataset_id=125, source_path="alpha:x")
    assert any("curated" in item for item in evidence)


def test_should_orphan_candidates_logic():
    assert _should_orphan_candidates(pending=0, running_total=2, candidate_count=2) is True
    assert _should_orphan_candidates(pending=1, running_total=2, candidate_count=2) is False
    assert _should_orphan_candidates(pending=0, running_total=3, candidate_count=2) is False
