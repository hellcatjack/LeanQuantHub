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
from app.services.trade_option_models import CoveredCallTimelineRequest
from app.services.covered_call_timeline import build_covered_call_timeline
from app.services import covered_call_timeline as timeline_service


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_timeline_requires_paper_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(timeline_service, "ARTIFACT_ROOT", tmp_path)
    session = _make_session()
    try:
        with pytest.raises(ValueError, match="paper_only"):
            build_covered_call_timeline(
                session,
                CoveredCallTimelineRequest(mode="live", review_id="review-1"),
            )
    finally:
        session.close()


def test_timeline_returns_review_ready_when_submit_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(timeline_service, "ARTIFACT_ROOT", tmp_path)
    review_dir = tmp_path / "review-1"
    _write_json(
        review_dir / "review_bundle.json",
        {
            "review_id": "review-1",
            "mode": "paper",
            "status": "ready",
            "approval_token": "token-1",
            "order_plan": {"underlying_symbol": "AAPL"},
        },
    )
    session = _make_session()
    try:
        result = build_covered_call_timeline(
            session,
            CoveredCallTimelineRequest(mode="paper", review_id="review-1"),
        )
    finally:
        session.close()

    assert result["status"] == "ready"
    assert result["timeline_state"] == "review_ready"
    assert result["latest_submit"] is None
    assert result["latest_receipt"] is None
    assert result["stages"][0]["stage"] == "review"
    assert result["stages"][0]["status"] == "ready"




def test_timeline_ignores_receipt_for_different_command(tmp_path, monkeypatch):
    monkeypatch.setattr(timeline_service, "ARTIFACT_ROOT", tmp_path)
    review_dir = tmp_path / "review-3"
    _write_json(
        review_dir / "review_bundle.json",
        {
            "review_id": "review-3",
            "mode": "paper",
            "status": "ready",
            "approval_token": "token-3",
            "order_plan": {"underlying_symbol": "NXT"},
        },
    )
    _write_json(
        tmp_path / "options_submit_20260408_030000_000001" / "summary.json",
        {
            "review_id": "review-3",
            "status": "blocked",
            "gate_reason": "shares_insufficient",
            "command_id": None,
        },
    )
    _write_json(
        tmp_path / "options_receipt_20260408_031000_000001" / "summary.json",
        {
            "review_id": "review-3",
            "command_id": "cmd-other",
            "status": "submitted",
            "receipt_state": "submitted_unconfirmed",
            "command_result_status": "submitted",
        },
    )
    session = _make_session()
    try:
        result = build_covered_call_timeline(
            session,
            CoveredCallTimelineRequest(mode="paper", review_id="review-3"),
        )
    finally:
        session.close()

    assert result["status"] == "blocked"
    assert result["timeline_state"] == "submit_blocked"
    assert result["latest_submit"]["status"] == "blocked"
    assert result["latest_receipt"] is None
    assert [item["stage"] for item in result["stages"]] == ["review", "submit"]

def test_timeline_prefers_latest_submit_and_receipt_state(tmp_path, monkeypatch):
    monkeypatch.setattr(timeline_service, "ARTIFACT_ROOT", tmp_path)
    review_dir = tmp_path / "review-2"
    _write_json(
        review_dir / "review_bundle.json",
        {
            "review_id": "review-2",
            "mode": "paper",
            "status": "review_required",
            "approval_token": "token-2",
            "order_plan": {"underlying_symbol": "MSFT"},
        },
    )
    _write_json(
        tmp_path / "options_submit_20260408_010000_000001" / "summary.json",
        {
            "review_id": "review-2",
            "status": "blocked",
            "gate_reason": "runtime_unhealthy",
            "command_id": None,
        },
    )
    _write_json(
        tmp_path / "options_submit_20260408_020000_000001" / "summary.json",
        {
            "review_id": "review-2",
            "status": "submitted",
            "gate_reason": None,
            "command_id": "cmd-2",
            "command_result_status": "submitted",
        },
    )
    _write_json(
        tmp_path / "options_receipt_20260408_021000_000001" / "summary.json",
        {
            "review_id": "review-2",
            "command_id": "cmd-2",
            "status": "submitted",
            "receipt_state": "open_confirmed",
            "command_result_status": "submitted",
        },
    )
    session = _make_session()
    try:
        result = build_covered_call_timeline(
            session,
            CoveredCallTimelineRequest(mode="paper", review_id="review-2"),
        )
    finally:
        session.close()

    assert result["status"] == "submitted"
    assert result["timeline_state"] == "open_confirmed"
    assert result["latest_submit"]["command_id"] == "cmd-2"
    assert result["latest_submit"]["status"] == "submitted"
    assert result["latest_receipt"]["receipt_state"] == "open_confirmed"
    assert [item["stage"] for item in result["stages"]] == ["review", "submit", "receipt"]
