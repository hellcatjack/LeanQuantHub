from pathlib import Path
import json
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base
from app.services.trade_option_models import CoveredCallAuditRequest
from app.services.covered_call_audit import build_covered_call_audit
from app.services import covered_call_audit as audit_service


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_audit_requires_paper_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_service, "ARTIFACT_ROOT", tmp_path)
    session = _make_session()
    try:
        with pytest.raises(ValueError, match="paper_only"):
            build_covered_call_audit(session, CoveredCallAuditRequest(mode="live", review_id="review-1"))
    finally:
        session.close()


def test_audit_returns_unified_view(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_service, "ARTIFACT_ROOT", tmp_path)
    review_id = "review-1"
    review_dir = tmp_path / review_id
    _write_json(
        review_dir / "review_bundle.json",
        {
            "review_id": review_id,
            "mode": "paper",
            "status": "ready",
            "approval_token": "token-1",
            "order_plan": {"underlying_symbol": "AAPL"},
        },
    )
    submit_path = tmp_path / "options_submit_20260408_050000_000001" / "summary.json"
    _write_json(
        submit_path,
        {
            "review_id": review_id,
            "status": "submitted",
            "command_id": "cmd-1",
            "command_result_status": "submitted",
        },
    )
    receipt_path = tmp_path / "options_receipt_20260408_050100_000001" / "summary.json"
    _write_json(
        receipt_path,
        {
            "review_id": review_id,
            "command_id": "cmd-1",
            "status": "submitted",
            "receipt_state": "open_confirmed",
            "command_result_status": "submitted",
        },
    )

    def _fake_timeline(session_obj, payload):
        assert session_obj is session
        assert payload.review_id == review_id
        return {
            "mode": "paper",
            "status": "submitted",
            "timeline_state": "open_confirmed",
            "review_id": review_id,
            "latest_submit": {"command_id": "cmd-1", "status": "submitted"},
            "latest_receipt": {"command_id": "cmd-1", "receipt_state": "open_confirmed"},
            "stages": [
                {"stage": "review", "status": "ready"},
                {"stage": "submit", "status": "submitted"},
                {"stage": "receipt", "status": "submitted", "receipt_state": "open_confirmed"},
            ],
            "artifacts": {
                "summary": "/tmp/timeline-summary.json",
                "review_bundle": str(review_dir / "review_bundle.json"),
                "latest_submit_summary": str(submit_path),
                "latest_receipt_summary": str(receipt_path),
            },
        }

    monkeypatch.setattr(audit_service, "build_covered_call_timeline", _fake_timeline)
    session = _make_session()
    try:
        result = build_covered_call_audit(session, CoveredCallAuditRequest(mode="paper", review_id=review_id))
    finally:
        session.close()

    assert result["status"] == "submitted"
    assert result["timeline_state"] == "open_confirmed"
    assert result["review"]["review_id"] == review_id
    assert result["submit"]["command_id"] == "cmd-1"
    assert result["receipt"]["receipt_state"] == "open_confirmed"
    assert result["timeline"]["stages"][2]["stage"] == "receipt"


def test_audit_handles_missing_submit_and_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_service, "ARTIFACT_ROOT", tmp_path)
    review_id = "review-2"
    review_dir = tmp_path / review_id
    _write_json(
        review_dir / "review_bundle.json",
        {
            "review_id": review_id,
            "mode": "paper",
            "status": "ready",
            "approval_token": "token-2",
        },
    )

    monkeypatch.setattr(
        audit_service,
        "build_covered_call_timeline",
        lambda _session, _payload: {
            "mode": "paper",
            "status": "ready",
            "timeline_state": "review_ready",
            "review_id": review_id,
            "latest_submit": None,
            "latest_receipt": None,
            "stages": [{"stage": "review", "status": "ready"}],
            "artifacts": {
                "summary": "/tmp/timeline-summary.json",
                "review_bundle": str(review_dir / "review_bundle.json"),
                "latest_submit_summary": None,
                "latest_receipt_summary": None,
            },
        },
    )
    session = _make_session()
    try:
        result = build_covered_call_audit(session, CoveredCallAuditRequest(mode="paper", review_id=review_id))
    finally:
        session.close()

    assert result["status"] == "ready"
    assert result["timeline_state"] == "review_ready"
    assert result["submit"] is None
    assert result["receipt"] is None
