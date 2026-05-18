from __future__ import annotations

from pathlib import Path
import csv
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import DecisionSnapshot
from app.services import trade_execution_targets


def _write_adjusted_series(
    root: Path,
    *,
    symbol: str,
    closes: list[float],
    start_date: str = "2026-03-24",
) -> None:
    path = root / f"999_Alpha_{symbol}_Daily.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    dates = [
        "2026-03-24",
        "2026-03-25",
        "2026-03-26",
        "2026-03-27",
        "2026-03-30",
        "2026-03-31",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["date", "open", "high", "low", "close", "volume", "symbol"],
        )
        writer.writeheader()
        for idx, close in enumerate(closes):
            writer.writerow(
                {
                    "date": dates[idx],
                    "open": f"{close:.6f}",
                    "high": f"{close:.6f}",
                    "low": f"{close:.6f}",
                    "close": f"{close:.6f}",
                    "volume": "1000",
                    "symbol": symbol,
                }
            )


def test_resolve_snapshot_execution_targets_risk_off_uses_basket_selection_before_default_symbol(
    tmp_path, monkeypatch
):
    adjusted_root = tmp_path / "curated_adjusted"
    _write_adjusted_series(adjusted_root, symbol="SGOV", closes=[100, 100, 100, 100, 100, 100])
    _write_adjusted_series(adjusted_root, symbol="VGSH", closes=[100, 101, 102, 103, 104, 105])
    monkeypatch.setattr(
        trade_execution_targets,
        "_resolve_adjusted_data_root",
        lambda: adjusted_root,
        raising=False,
    )

    snapshot = DecisionSnapshot(
        id=1,
        summary={
            "snapshot_date": "2026-03-31",
            "rebalance_date": "2026-03-31",
            "risk_off": True,
            "risk_off_mode": "defensive",
            "risk_off_symbol": "",
            "effective_exposure_cap": 0.3,
            "algorithm_parameters": {
                "risk_off_symbol": "SGOV",
                "risk_off_symbols": "SGOV,VGSH",
                "risk_off_pick": "best_momentum",
                "risk_off_lookback_days": 5,
            },
        },
    )

    target_weights, meta = trade_execution_targets.resolve_snapshot_execution_targets(
        snapshot,
        [],
    )

    assert target_weights == {"VGSH": 0.3}
    assert meta.get("risk_off_symbol") == "VGSH"
    assert meta.get("compat_fallback_used") is True


def test_resolve_snapshot_execution_targets_risk_on_adds_defensive_idle_weight(
    tmp_path, monkeypatch
):
    adjusted_root = tmp_path / "curated_adjusted"
    _write_adjusted_series(adjusted_root, symbol="SGOV", closes=[100, 100, 100, 100, 100, 100])
    _write_adjusted_series(adjusted_root, symbol="VGSH", closes=[100, 101, 102, 103, 104, 105])
    monkeypatch.setattr(
        trade_execution_targets,
        "_resolve_adjusted_data_root",
        lambda: adjusted_root,
        raising=False,
    )

    snapshot = DecisionSnapshot(
        id=2,
        summary={
            "snapshot_date": "2026-03-31",
            "rebalance_date": "2026-03-31",
            "risk_off": False,
            "idle_allocation_mode": "defensive",
            "idle_symbol": "",
            "algorithm_parameters": {
                "risk_off_symbol": "SGOV",
                "risk_off_symbols": "SGOV,VGSH",
                "risk_off_pick": "best_momentum",
                "risk_off_lookback_days": 5,
            },
        },
    )
    items = [{"symbol": "AAA", "weight": 0.3}]

    target_weights, meta = trade_execution_targets.resolve_snapshot_execution_targets(
        snapshot,
        items,
    )

    assert target_weights == {"AAA": 0.3, "VGSH": 0.7}
    assert meta.get("idle_symbol") == "VGSH"
    assert meta.get("compat_fallback_used") is True


def test_resolve_snapshot_execution_targets_risk_on_adds_benchmark_idle_weight():
    snapshot = DecisionSnapshot(
        id=3,
        summary={
            "snapshot_date": "2026-03-31",
            "rebalance_date": "2026-03-31",
            "risk_off": False,
            "idle_allocation_mode": "benchmark",
            "idle_symbol": "",
            "algorithm_parameters": {
                "benchmark": "QQQ",
            },
        },
    )
    items = [{"symbol": "AAA", "weight": 0.25}]

    target_weights, meta = trade_execution_targets.resolve_snapshot_execution_targets(
        snapshot,
        items,
    )

    assert target_weights == {"AAA": 0.25, "QQQ": 0.75}
    assert meta.get("idle_symbol") == "QQQ"
    assert meta.get("compat_fallback_used") is True
