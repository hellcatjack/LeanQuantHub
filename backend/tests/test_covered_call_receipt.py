from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.trade_option_models import CoveredCallReceiptRequest
from app.services.covered_call_receipt import build_covered_call_receipt


def _write_review_bundle(root: Path, *, token: str = "token-1", expires_at: str | None = None) -> Path:
    review_dir = root / "options_review_receipt_test"
    review_dir.mkdir(parents=True, exist_ok=True)
    if expires_at is None:
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    payload = {
        "mode": "paper",
        "status": "ready",
        "review_id": review_dir.name,
        "approval_token": token,
        "approval_expires_at": expires_at,
        "eligible": {"symbol": "AAPL", "shares": 200, "coverable_contracts": 2},
        "order_plan": {
            "underlying_symbol": "AAPL",
            "sec_type": "OPT",
            "side": "SELL",
            "expiry": "2026-05-15",
            "strike": 210.0,
            "right": "C",
            "contracts": 2,
            "quantity": 2,
            "multiplier": 100,
            "order_type": "LMT",
            "limit_price": 1.25,
            "dry_run": True,
            "risk_tags": [],
        },
    }
    (review_dir / "review_bundle.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return review_dir


def test_build_covered_call_receipt_requires_review_and_command_id(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.covered_call_receipt.ARTIFACT_ROOT", tmp_path)

    with pytest.raises(ValueError, match="review_id_required"):
        build_covered_call_receipt(
            object(),
            CoveredCallReceiptRequest(mode="paper", review_id="", command_id="cmd-1"),
        )

    with pytest.raises(ValueError, match="command_id_required"):
        build_covered_call_receipt(
            object(),
            CoveredCallReceiptRequest(mode="paper", review_id="review-1", command_id=""),
        )


def test_build_covered_call_receipt_rejects_live_mode(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.covered_call_receipt.ARTIFACT_ROOT", tmp_path)

    with pytest.raises(ValueError, match="paper_only"):
        build_covered_call_receipt(
            object(),
            CoveredCallReceiptRequest(mode="live", review_id="review-1", command_id="cmd-1"),
        )


def test_build_covered_call_receipt_reports_rejected_command(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.covered_call_receipt.ARTIFACT_ROOT", tmp_path)
    review_dir = _write_review_bundle(tmp_path)
    bridge_root = tmp_path / "bridge"
    command_results_dir = bridge_root / "command_results"
    command_results_dir.mkdir(parents=True, exist_ok=True)
    (command_results_dir / "submit_order_cc_1.json").write_text(
        json.dumps(
            {
                "command_id": "submit_order_cc_1",
                "status": "place_failed",
                "processed_at": "2026-04-08T04:00:00Z",
                "error": "ib_reject",
                "tag": "covered_call:options_review_receipt_test",
                "brokerage_ids": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.services.covered_call_receipt.resolve_bridge_root", lambda: bridge_root)
    monkeypatch.setattr("app.services.covered_call_receipt.load_gateway_runtime_health", lambda *_a, **_k: {"state": "healthy"})
    monkeypatch.setattr("app.services.covered_call_receipt.read_open_orders", lambda *_a, **_k: {"items": [], "stale": False})

    result = build_covered_call_receipt(
        object(),
        CoveredCallReceiptRequest(mode="paper", review_id=review_dir.name, command_id="submit_order_cc_1"),
    )

    assert result["status"] == "rejected"
    assert result["receipt_state"] == "rejected"
    assert result["command_result_status"] == "place_failed"
    assert result["open_orders_summary"]["matched_count"] == 0


def test_build_covered_call_receipt_confirms_open_order_match(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.covered_call_receipt.ARTIFACT_ROOT", tmp_path)
    review_dir = _write_review_bundle(tmp_path)
    bridge_root = tmp_path / "bridge"
    command_results_dir = bridge_root / "command_results"
    command_results_dir.mkdir(parents=True, exist_ok=True)
    (command_results_dir / "submit_order_cc_2.json").write_text(
        json.dumps(
            {
                "command_id": "submit_order_cc_2",
                "status": "submitted",
                "processed_at": "2026-04-08T04:00:00Z",
                "tag": "covered_call:options_review_receipt_test",
                "brokerage_ids": ["2001"],
                "underlying_symbol": "AAPL",
                "symbol": "AAPL",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.services.covered_call_receipt.resolve_bridge_root", lambda: bridge_root)
    monkeypatch.setattr("app.services.covered_call_receipt.load_gateway_runtime_health", lambda *_a, **_k: {"state": "healthy"})
    monkeypatch.setattr(
        "app.services.covered_call_receipt.read_open_orders",
        lambda *_a, **_k: {
            "items": [
                {
                    "symbol": "AAPL  250515C00210000",
                    "underlying_symbol": "AAPL",
                    "tag": "covered_call:options_review_receipt_test",
                    "brokerage_ids": ["2001"],
                }
            ],
            "stale": False,
        },
    )

    result = build_covered_call_receipt(
        object(),
        CoveredCallReceiptRequest(mode="paper", review_id=review_dir.name, command_id="submit_order_cc_2"),
    )

    assert result["status"] == "submitted"
    assert result["receipt_state"] == "open_confirmed"
    assert result["command_result_status"] == "submitted"
    assert result["open_orders_summary"]["matched_count"] == 1


def test_build_covered_call_receipt_marks_unconfirmed_when_no_open_order_match(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.covered_call_receipt.ARTIFACT_ROOT", tmp_path)
    review_dir = _write_review_bundle(tmp_path)
    bridge_root = tmp_path / "bridge"
    command_results_dir = bridge_root / "command_results"
    command_results_dir.mkdir(parents=True, exist_ok=True)
    (command_results_dir / "submit_order_cc_3.json").write_text(
        json.dumps(
            {
                "command_id": "submit_order_cc_3",
                "status": "submitted",
                "processed_at": "2026-04-08T04:00:00Z",
                "tag": "covered_call:options_review_receipt_test",
                "brokerage_ids": ["2002"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.services.covered_call_receipt.resolve_bridge_root", lambda: bridge_root)
    monkeypatch.setattr("app.services.covered_call_receipt.load_gateway_runtime_health", lambda *_a, **_k: {"state": "healthy"})
    monkeypatch.setattr("app.services.covered_call_receipt.read_open_orders", lambda *_a, **_k: {"items": [], "stale": False})

    result = build_covered_call_receipt(
        object(),
        CoveredCallReceiptRequest(mode="paper", review_id=review_dir.name, command_id="submit_order_cc_3"),
    )

    assert result["status"] == "submitted"
    assert result["receipt_state"] == "submitted_unconfirmed"
    assert result["command_result_status"] == "submitted"
    assert result["open_orders_summary"]["matched_count"] == 0
