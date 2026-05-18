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

from app.services.trade_option_models import CoveredCallSubmitRequest
from app.services.covered_call_submit import build_covered_call_submit


def _write_review_bundle(root: Path, *, token: str = "token-1", expires_at: str | None = None) -> Path:
    review_dir = root / "options_review_test"
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
        "runtime_summary": {"state": "healthy"},
        "position_summary": {"shares": 200},
        "open_orders_summary": {"symbol_conflict": False},
    }
    (review_dir / "review_bundle.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return review_dir


def test_build_covered_call_submit_rejects_token_mismatch(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.covered_call_submit.ARTIFACT_ROOT", tmp_path)
    review_dir = _write_review_bundle(tmp_path, token="token-1")

    with pytest.raises(ValueError, match="token_invalid"):
        build_covered_call_submit(
            object(),
            CoveredCallSubmitRequest(
                mode="paper",
                symbol="AAPL",
                review_id=review_dir.name,
                approval_token="wrong-token",
                dry_run=False,
            ),
        )


def test_build_covered_call_submit_rejects_expired_token(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.covered_call_submit.ARTIFACT_ROOT", tmp_path)
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    review_dir = _write_review_bundle(tmp_path, token="token-1", expires_at=expired)

    with pytest.raises(ValueError, match="token_expired"):
        build_covered_call_submit(
            object(),
            CoveredCallSubmitRequest(
                mode="paper",
                symbol="AAPL",
                review_id=review_dir.name,
                approval_token="token-1",
                dry_run=False,
            ),
        )


def test_build_covered_call_submit_blocks_unhealthy_runtime(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.covered_call_submit.ARTIFACT_ROOT", tmp_path)
    review_dir = _write_review_bundle(tmp_path)
    monkeypatch.setattr("app.services.covered_call_submit.resolve_bridge_root", lambda: tmp_path / "bridge")
    monkeypatch.setattr("app.services.covered_call_submit.load_gateway_runtime_health", lambda *_a, **_k: {"state": "degraded"})
    monkeypatch.setattr(
        "app.services.covered_call_submit.get_account_positions_cached",
        lambda *_a, **_k: {"items": [{"symbol": "AAPL", "quantity": 200, "market_price": 225.0}], "stale": False},
    )
    monkeypatch.setattr("app.services.covered_call_submit.read_open_orders", lambda *_a, **_k: {"items": [], "stale": False})

    result = build_covered_call_submit(
        object(),
        CoveredCallSubmitRequest(
            mode="paper",
            symbol="AAPL",
            review_id=review_dir.name,
            approval_token="token-1",
            dry_run=False,
        ),
    )

    assert result["status"] == "blocked"
    assert result["gate_reason"] == "runtime_unhealthy"


def test_build_covered_call_submit_blocks_when_shares_drift_below_requirement(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.covered_call_submit.ARTIFACT_ROOT", tmp_path)
    review_dir = _write_review_bundle(tmp_path)
    monkeypatch.setattr("app.services.covered_call_submit.resolve_bridge_root", lambda: tmp_path / "bridge")
    monkeypatch.setattr("app.services.covered_call_submit.load_gateway_runtime_health", lambda *_a, **_k: {"state": "healthy"})
    monkeypatch.setattr(
        "app.services.covered_call_submit.get_account_positions_cached",
        lambda *_a, **_k: {"items": [{"symbol": "AAPL", "quantity": 100, "market_price": 225.0}], "stale": False},
    )
    monkeypatch.setattr("app.services.covered_call_submit.read_open_orders", lambda *_a, **_k: {"items": [], "stale": False})

    result = build_covered_call_submit(
        object(),
        CoveredCallSubmitRequest(
            mode="paper",
            symbol="AAPL",
            review_id=review_dir.name,
            approval_token="token-1",
            dry_run=False,
        ),
    )

    assert result["status"] == "blocked"
    assert result["gate_reason"] == "shares_insufficient"


def test_build_covered_call_submit_blocks_when_open_order_conflict_exists(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.covered_call_submit.ARTIFACT_ROOT", tmp_path)
    review_dir = _write_review_bundle(tmp_path)
    monkeypatch.setattr("app.services.covered_call_submit.resolve_bridge_root", lambda: tmp_path / "bridge")
    monkeypatch.setattr("app.services.covered_call_submit.load_gateway_runtime_health", lambda *_a, **_k: {"state": "healthy"})
    monkeypatch.setattr(
        "app.services.covered_call_submit.get_account_positions_cached",
        lambda *_a, **_k: {"items": [{"symbol": "AAPL", "quantity": 200, "market_price": 225.0}], "stale": False},
    )
    monkeypatch.setattr(
        "app.services.covered_call_submit.read_open_orders",
        lambda *_a, **_k: {"items": [{"underlying_symbol": "AAPL"}], "stale": False},
    )

    result = build_covered_call_submit(
        object(),
        CoveredCallSubmitRequest(
            mode="paper",
            symbol="AAPL",
            review_id=review_dir.name,
            approval_token="token-1",
            dry_run=False,
        ),
    )

    assert result["status"] == "blocked"
    assert result["gate_reason"] == "open_orders_conflict"


def test_build_covered_call_submit_returns_submitted_when_command_result_arrives(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.covered_call_submit.ARTIFACT_ROOT", tmp_path)
    review_dir = _write_review_bundle(tmp_path)
    bridge_root = tmp_path / "bridge"
    command_results_dir = bridge_root / "command_results"
    command_results_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.services.covered_call_submit.resolve_bridge_root", lambda: bridge_root)
    monkeypatch.setattr("app.services.covered_call_submit.load_gateway_runtime_health", lambda *_a, **_k: {"state": "healthy"})
    monkeypatch.setattr(
        "app.services.covered_call_submit.get_account_positions_cached",
        lambda *_a, **_k: {"items": [{"symbol": "AAPL", "quantity": 200, "market_price": 225.0}], "stale": False},
    )
    monkeypatch.setattr("app.services.covered_call_submit.read_open_orders", lambda *_a, **_k: {"items": [], "stale": False})
    audits = []
    monkeypatch.setattr("app.services.covered_call_submit.record_audit", lambda *args, **kwargs: audits.append(kwargs))

    def _write_command(*_args, **_kwargs):
        payload = {
            "command_id": "submit_order_cc_1",
            "status": "submitted",
            "processed_at": "2026-04-08T03:00:00Z",
            "brokerage_ids": ["12345"],
        }
        (command_results_dir / "submit_order_cc_1.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        class _Ref:
            command_id = "submit_order_cc_1"
            command_path = str(bridge_root / "commands" / "submit_order_cc_1.json")
            requested_at = "2026-04-08T02:59:00Z"
            expires_at = "2026-04-08T03:04:00Z"
        return _Ref()

    monkeypatch.setattr("app.services.covered_call_submit.write_submit_order_command", _write_command)

    result = build_covered_call_submit(
        object(),
        CoveredCallSubmitRequest(
            mode="paper",
            symbol="AAPL",
            review_id=review_dir.name,
            approval_token="token-1",
            dry_run=False,
        ),
    )

    assert result["status"] == "submitted"
    assert result["command_id"] == "submit_order_cc_1"
    assert result["command_result_status"] == "submitted"
    assert Path(result["artifacts"]["summary"]).exists()
    assert Path(result["artifacts"]["submit_request"]).exists()
    assert Path(result["artifacts"]["command_result"]).exists()
    assert [item["action"] for item in audits] == [
        "covered_call_submit_requested",
        "covered_call_submit_result",
    ]


def test_build_covered_call_submit_returns_rejected_result(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.covered_call_submit.ARTIFACT_ROOT", tmp_path)
    review_dir = _write_review_bundle(tmp_path)
    bridge_root = tmp_path / "bridge"
    command_results_dir = bridge_root / "command_results"
    command_results_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.services.covered_call_submit.resolve_bridge_root", lambda: bridge_root)
    monkeypatch.setattr("app.services.covered_call_submit.load_gateway_runtime_health", lambda *_a, **_k: {"state": "healthy"})
    monkeypatch.setattr(
        "app.services.covered_call_submit.get_account_positions_cached",
        lambda *_a, **_k: {"items": [{"symbol": "AAPL", "quantity": 200, "market_price": 225.0}], "stale": False},
    )
    monkeypatch.setattr("app.services.covered_call_submit.read_open_orders", lambda *_a, **_k: {"items": [], "stale": False})
    monkeypatch.setattr("app.services.covered_call_submit.record_audit", lambda *args, **kwargs: None)

    def _write_command(*_args, **_kwargs):
        payload = {
            "command_id": "submit_order_cc_2",
            "status": "place_failed",
            "processed_at": "2026-04-08T03:00:00Z",
            "error": "ib_reject",
        }
        (command_results_dir / "submit_order_cc_2.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        class _Ref:
            command_id = "submit_order_cc_2"
            command_path = str(bridge_root / "commands" / "submit_order_cc_2.json")
            requested_at = "2026-04-08T02:59:00Z"
            expires_at = "2026-04-08T03:04:00Z"
        return _Ref()

    monkeypatch.setattr("app.services.covered_call_submit.write_submit_order_command", _write_command)

    result = build_covered_call_submit(
        object(),
        CoveredCallSubmitRequest(
            mode="paper",
            symbol="AAPL",
            review_id=review_dir.name,
            approval_token="token-1",
            dry_run=False,
        ),
    )

    assert result["status"] == "rejected"
    assert result["command_result_status"] == "place_failed"
    assert result["gate_reason"] == "ib_reject"


def test_build_covered_call_submit_returns_timeout_pending_when_no_result(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.covered_call_submit.ARTIFACT_ROOT", tmp_path)
    review_dir = _write_review_bundle(tmp_path)
    bridge_root = tmp_path / "bridge"
    (bridge_root / "command_results").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.services.covered_call_submit.resolve_bridge_root", lambda: bridge_root)
    monkeypatch.setattr("app.services.covered_call_submit.load_gateway_runtime_health", lambda *_a, **_k: {"state": "healthy"})
    monkeypatch.setattr(
        "app.services.covered_call_submit.get_account_positions_cached",
        lambda *_a, **_k: {"items": [{"symbol": "AAPL", "quantity": 200, "market_price": 225.0}], "stale": False},
    )
    monkeypatch.setattr("app.services.covered_call_submit.read_open_orders", lambda *_a, **_k: {"items": [], "stale": False})
    monkeypatch.setattr("app.services.covered_call_submit.record_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.covered_call_submit._SUBMIT_WAIT_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr("app.services.covered_call_submit._SUBMIT_POLL_INTERVAL_SECONDS", 0.0)

    class _Ref:
        command_id = "submit_order_cc_3"
        command_path = str(bridge_root / "commands" / "submit_order_cc_3.json")
        requested_at = "2026-04-08T02:59:00Z"
        expires_at = "2026-04-08T03:04:00Z"

    monkeypatch.setattr("app.services.covered_call_submit.write_submit_order_command", lambda *_a, **_k: _Ref())

    result = build_covered_call_submit(
        object(),
        CoveredCallSubmitRequest(
            mode="paper",
            symbol="AAPL",
            review_id=review_dir.name,
            approval_token="token-1",
            dry_run=False,
        ),
    )

    assert result["status"] == "timeout_pending"
    assert result["command_id"] == "submit_order_cc_3"
    assert result["command_result_status"] is None
