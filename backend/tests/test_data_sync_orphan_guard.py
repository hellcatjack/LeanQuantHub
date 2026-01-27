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


def test_orphan_evaluator_marks_failed(monkeypatch, tmp_path):
    from datetime import datetime, timedelta

    from app.models import BulkSyncJob, DataSyncJob
    from app.routes import datasets as datasets_routes

    (tmp_path / "curated").mkdir(parents=True)
    (tmp_path / "curated" / "125_Alpha_X_Daily.csv").write_text("x")

    bulk_job = BulkSyncJob(
        id=99,
        status="running",
        phase="syncing",
        enqueued_start_at=datetime.utcnow() - timedelta(minutes=5),
        enqueued_end_at=datetime.utcnow(),
    )
    running_job = DataSyncJob(dataset_id=125, source_path="alpha:x", status="running")

    class FakeQuery:
        def __init__(self, items):
            self._items = items

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return list(self._items)

    class FakeSession:
        def __init__(self, items):
            self._items = items

        def query(self, model):
            return FakeQuery(self._items)

        def add(self, obj):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(
        datasets_routes,
        "_bulk_job_range",
        lambda job: (bulk_job.enqueued_start_at, bulk_job.enqueued_end_at),
    )
    monkeypatch.setattr(
        datasets_routes,
        "_bulk_job_counts",
        lambda session, job: (0, 1, 1),
    )
    monkeypatch.setattr(
        datasets_routes,
        "load_data_sync_orphan_guard_config",
        lambda data_root: {"enabled": True, "dry_run": False, "evidence_required": True},
    )
    monkeypatch.setattr(datasets_routes, "_is_sync_queue_idle", lambda data_root: True)
    monkeypatch.setattr(datasets_routes, "record_audit", lambda *args, **kwargs: None)

    session = FakeSession([running_job])
    affected = datasets_routes._evaluate_orphaned_sync_jobs(session, bulk_job, tmp_path)
    assert affected == 1
    assert running_job.status == "failed"
