from pathlib import Path
import sys
import datetime as dt

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import decision_snapshot


def test_normalize_snapshot_row_applies_fallback_date():
    row = {"snapshot_date": "", "rebalance_date": ""}
    normalized = decision_snapshot._normalize_snapshot_row(row, "2026-01-23")
    assert normalized["snapshot_date"] == "2026-01-23"
    assert normalized["rebalance_date"] == "2026-01-23"


def test_normalize_snapshot_row_preserves_existing_date():
    row = {"snapshot_date": "2026-01-09", "rebalance_date": "2026-01-10"}
    normalized = decision_snapshot._normalize_snapshot_row(row, "2026-01-23")
    assert normalized["snapshot_date"] == "2026-01-09"
    assert normalized["rebalance_date"] == "2026-01-10"


def test_apply_algorithm_params_maps_drawdown_and_idle_settings():
    weights_cfg = {"backtest_plugins": {"risk_control": {}}}
    algo_params = {
        "max_exposure": 0.42,
        "dynamic_exposure": True,
        "drawdown_tiers": "0.05,0.10,0.15",
        "drawdown_exposures": "0.8,0.6,0.4",
        "drawdown_exposure_floor": 0.1,
        "idle_allocation": "defensive",
    }

    updated = decision_snapshot._apply_algorithm_params(weights_cfg, algo_params)
    risk = updated["backtest_plugins"]["risk_control"]

    assert updated["max_exposure"] == 0.42
    assert updated["dynamic_exposure"] is True
    assert updated["drawdown_tiers"] == "0.05,0.10,0.15"
    assert updated["drawdown_exposures"] == "0.8,0.6,0.4"
    assert updated["drawdown_exposure_floor"] == 0.1
    assert updated["idle_allocation"] == "defensive"
    assert risk["dynamic_exposure"] is True
    assert risk["drawdown_tiers"] == "0.05,0.10,0.15"
    assert risk["drawdown_exposures"] == "0.8,0.6,0.4"
    assert risk["drawdown_exposure_floor"] == 0.1
    assert risk["idle_allocation"] == "defensive"


def test_snapshot_age_days_uses_utc_today(monkeypatch):
    class FixedDateTime(dt.datetime):
        @classmethod
        def utcnow(cls):
            return dt.datetime(2026, 2, 20, 12, 0, 0)

    monkeypatch.setattr(decision_snapshot, "datetime", FixedDateTime)
    assert decision_snapshot._snapshot_age_days("2026-02-13") == 7
    assert decision_snapshot._snapshot_age_days("2026-02-20") == 0


def test_resolve_snapshot_stale_days_defaults_on_invalid_env(monkeypatch):
    monkeypatch.setenv("DECISION_SNAPSHOT_STALE_DAYS", "abc")
    assert decision_snapshot._resolve_snapshot_stale_days() == 7


def test_hydrate_snapshot_runtime_fields_backfills_risk_off_symbol(monkeypatch):
    monkeypatch.setattr(
        decision_snapshot,
        "_select_from_defensive_basket",
        lambda *, summary, algo_params: ("VGSH", ["risk_off_symbol"]),
    )
    row = {
        "snapshot_date": "2026-03-31",
        "rebalance_date": "2026-03-31",
        "risk_off": "1",
        "risk_off_mode": "defensive",
        "risk_off_symbol": "",
        "risk_off_selection": "defensive_missing",
    }

    hydrated = decision_snapshot._hydrate_snapshot_runtime_fields(
        row,
        algo_params={"risk_off_symbols": "SGOV,VGSH"},
    )

    assert hydrated["risk_off_symbol"] == "VGSH"
    assert hydrated["risk_off_selection"] == "compat_defensive_pick"


def test_hydrate_snapshot_runtime_fields_backfills_idle_symbol_and_weight(monkeypatch):
    monkeypatch.setattr(
        decision_snapshot,
        "_resolve_idle_symbol",
        lambda *, summary, algo_params: ("defensive", "VGSH", ["idle_symbol"]),
    )
    row = {
        "snapshot_date": "2026-03-31",
        "rebalance_date": "2026-03-31",
        "risk_off": "0",
        "idle_allocation_mode": "defensive",
        "idle_symbol": "",
        "weights_sum": "0.30000000",
        "idle_weight": "",
    }

    hydrated = decision_snapshot._hydrate_snapshot_runtime_fields(
        row,
        algo_params={"risk_off_symbols": "SGOV,VGSH"},
    )

    assert hydrated["idle_symbol"] == "VGSH"
    assert hydrated["idle_weight"] == "0.70000000"
