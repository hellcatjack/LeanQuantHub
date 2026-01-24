from __future__ import annotations

import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.lean_bridge_reader import (
    read_account_summary,
    read_bridge_status,
    read_positions,
    read_quotes,
)


def test_read_bridge_status_missing(tmp_path: Path) -> None:
    result = read_bridge_status(tmp_path)
    assert result["stale"] is True
    assert result["status"] == "missing"


def test_read_account_summary_ok(tmp_path: Path) -> None:
    payload = {
        "updated_at": "2026-01-24T00:00:00Z",
        "items": [{"name": "NetLiquidation", "value": 1000.0}],
    }
    (tmp_path / "account_summary.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    result = read_account_summary(tmp_path)
    assert result["items"][0]["name"] == "NetLiquidation"
    assert result["stale"] is False


def test_read_positions_ok(tmp_path: Path) -> None:
    payload = {
        "updated_at": "2026-01-24T00:00:00Z",
        "items": [{"symbol": "SPY", "position": 1}],
    }
    (tmp_path / "positions.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    result = read_positions(tmp_path)
    assert result["items"][0]["symbol"] == "SPY"
    assert result["stale"] is False


def test_read_quotes_ok(tmp_path: Path) -> None:
    payload = {
        "updated_at": "2026-01-24T00:00:00Z",
        "items": [{"symbol": "SPY", "last": 100}],
    }
    (tmp_path / "quotes.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    result = read_quotes(tmp_path)
    assert result["items"][0]["symbol"] == "SPY"
    assert result["stale"] is False
