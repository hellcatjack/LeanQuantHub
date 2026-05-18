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
from app.services.trade_option_models import CoveredCallAuditRecentRequest
from app.services.covered_call_audit_recent import list_covered_call_audit_recent
from app.services import covered_call_audit_recent as recent_service


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_recent_requires_paper_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(recent_service, "ARTIFACT_ROOT", tmp_path)
    session = _make_session()
    try:
        with pytest.raises(ValueError, match="paper_only"):
            list_covered_call_audit_recent(session, CoveredCallAuditRecentRequest(mode="live", limit=5))
    finally:
        session.close()


def test_recent_lists_sorted_reviews_with_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(recent_service, "ARTIFACT_ROOT", tmp_path)
    older = tmp_path / "options_review_20260408_010000_000001"
    newer = tmp_path / "options_review_20260408_020000_000001"
    _write_json(older / "review_bundle.json", {"review_id": older.name, "status": "ready", "order_plan": {"underlying_symbol": "AAPL"}})
    _write_json(newer / "review_bundle.json", {"review_id": newer.name, "status": "review_required", "order_plan": {"underlying_symbol": "MSFT"}})
    newer_bundle = newer / "review_bundle.json"
    older_bundle = older / "review_bundle.json"
    older_bundle.touch()
    newer_bundle.touch()

    def _fake_timeline(session_obj, payload):
        assert session_obj is session
        mapping = {
            older.name: {
                "status": "ready",
                "timeline_state": "review_ready",
                "latest_submit": None,
                "artifacts": {"review_bundle": str(older_bundle)},
            },
            newer.name: {
                "status": "submitted",
                "timeline_state": "submit_submitted",
                "latest_submit": {"command_id": "cmd-2"},
                "artifacts": {"review_bundle": str(newer_bundle)},
            },
        }
        base = mapping[payload.review_id]
        return {"mode": "paper", "review_id": payload.review_id, **base}

    session = _make_session()
    try:
        monkeypatch.setattr(recent_service, "build_covered_call_timeline", _fake_timeline)
        result = list_covered_call_audit_recent(session, CoveredCallAuditRecentRequest(mode="paper", limit=1))
    finally:
        session.close()

    assert result["mode"] == "paper"
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["review_id"] == newer.name
    assert item["symbol"] == "MSFT"
    assert item["status"] == "submitted"
    assert item["timeline_state"] == "submit_submitted"
    assert item["latest_command_id"] == "cmd-2"


def test_recent_skips_invalid_review_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(recent_service, "ARTIFACT_ROOT", tmp_path)
    (tmp_path / "options_review_broken").mkdir(parents=True, exist_ok=True)
    good = tmp_path / "options_review_20260408_030000_000001"
    _write_json(good / "review_bundle.json", {"review_id": good.name, "status": "ready"})

    session = _make_session()
    try:
        monkeypatch.setattr(
            recent_service,
            "build_covered_call_timeline",
            lambda _session, payload: {
                "mode": "paper",
                "review_id": payload.review_id,
                "status": "ready",
                "timeline_state": "review_ready",
                "latest_submit": None,
                "artifacts": {"review_bundle": str(good / 'review_bundle.json')},
            },
        )
        result = list_covered_call_audit_recent(session, CoveredCallAuditRecentRequest(mode="paper", limit=5))
    finally:
        session.close()

    assert [item["review_id"] for item in result["items"]] == [good.name]


def test_recent_supports_query_offset_and_total(tmp_path, monkeypatch):
    monkeypatch.setattr(recent_service, "ARTIFACT_ROOT", tmp_path)
    reviews = [
        ("options_review_20260408_010000_000001", "AAPL", "ready", "review_ready", None),
        ("options_review_20260408_020000_000001", "MSFT", "submitted", "submit_submitted", "cmd-2"),
        ("options_review_20260408_030000_000001", "NVDA", "blocked", "submit_blocked", None),
    ]
    for index, (review_id, symbol, _status, _timeline_state, _command_id) in enumerate(reviews):
        bundle = tmp_path / review_id / "review_bundle.json"
        _write_json(bundle, {"review_id": review_id, "order_plan": {"underlying_symbol": symbol}})
        bundle.touch()

    def _fake_timeline(_session_obj, payload):
        mapping = {
            review_id: {
                "mode": "paper",
                "review_id": review_id,
                "status": status,
                "timeline_state": timeline_state,
                "latest_submit": {"command_id": command_id} if command_id else None,
                "artifacts": {"review_bundle": str(tmp_path / review_id / "review_bundle.json")},
            }
            for review_id, _symbol, status, timeline_state, command_id in reviews
        }
        return mapping[payload.review_id]

    session = _make_session()
    try:
        monkeypatch.setattr(recent_service, "build_covered_call_timeline", _fake_timeline)
        result = list_covered_call_audit_recent(
            session,
            CoveredCallAuditRecentRequest(mode="paper", limit=1, offset=1, query="submit"),
        )
    finally:
        session.close()

    assert result["mode"] == "paper"
    assert result["total"] == 2
    assert result["has_more"] is False
    assert len(result["items"]) == 1
    assert result["items"][0]["review_id"] == "options_review_20260408_020000_000001"


def test_recent_query_matches_review_id_and_symbol(tmp_path, monkeypatch):
    monkeypatch.setattr(recent_service, "ARTIFACT_ROOT", tmp_path)
    first = tmp_path / "options_review_alpha"
    second = tmp_path / "options_review_beta"
    _write_json(first / "review_bundle.json", {"review_id": "alpha-review", "order_plan": {"underlying_symbol": "TSLA"}})
    _write_json(second / "review_bundle.json", {"review_id": "beta-review", "order_plan": {"underlying_symbol": "AMD"}})

    def _fake_timeline(_session_obj, payload):
        base = {
            "mode": "paper",
            "latest_submit": None,
            "artifacts": {"review_bundle": str(tmp_path / payload.review_id / "review_bundle.json")},
        }
        if payload.review_id == "alpha-review":
            return {**base, "review_id": "alpha-review", "status": "ready", "timeline_state": "review_ready"}
        return {**base, "review_id": "beta-review", "status": "blocked", "timeline_state": "submit_blocked"}

    session = _make_session()
    try:
        monkeypatch.setattr(recent_service, "build_covered_call_timeline", _fake_timeline)
        by_symbol = list_covered_call_audit_recent(
            session,
            CoveredCallAuditRecentRequest(mode="paper", limit=10, offset=0, query="amd"),
        )
        by_review = list_covered_call_audit_recent(
            session,
            CoveredCallAuditRecentRequest(mode="paper", limit=10, offset=0, query="alpha-review"),
        )
    finally:
        session.close()

    assert [item["review_id"] for item in by_symbol["items"]] == ["beta-review"]
    assert [item["review_id"] for item in by_review["items"]] == ["alpha-review"]
