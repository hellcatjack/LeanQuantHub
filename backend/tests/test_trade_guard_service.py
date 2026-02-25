from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, TradeGuardState, TradeOrder, TradeRun, TradeFill, TradeSettings
import app.services.trade_guard as trade_guard
from app.services.trade_guard import evaluate_intraday_guard


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session()


def _seed_position(session):
    run = TradeRun(project_id=1, mode="paper", status="done", params={"portfolio_value": 1000})
    session.add(run)
    session.flush()
    order = TradeOrder(
        run_id=run.id,
        client_order_id="run-1-SPY",
        symbol="SPY",
        side="BUY",
        quantity=10,
        status="FILLED",
    )
    session.add(order)
    session.flush()
    fill = TradeFill(order_id=order.id, exec_id="E1", fill_quantity=10, fill_price=100)
    session.add(fill)
    session.commit()
    return run


def test_guard_triggers_daily_loss(monkeypatch):
    session = _make_session()
    try:
        monkeypatch.setattr(trade_guard, "_load_ib_equity_snapshot", lambda _session, *, mode: {})
        _seed_position(session)
        state = TradeGuardState(
            project_id=1,
            trade_date=date(2026, 1, 17),
            mode="paper",
            day_start_equity=1000,
            equity_peak=1000,
            last_equity=1000,
        )
        session.add(state)
        session.commit()
        settings = TradeSettings(risk_defaults={"max_daily_loss": -0.05})
        session.add(settings)
        session.commit()

        result = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"max_daily_loss": -0.05},
            price_map={"SPY": 90.0},
            trade_date=date(2026, 1, 17),
        )
        assert result["status"] == "halted"
        assert isinstance(result.get("thresholds"), dict)
        assert result["thresholds"]["max_daily_loss"] == -0.05
        reason = result.get("reason") or {}
        assert "max_daily_loss" in (reason.get("reasons") or [])
        details = reason.get("details") or []
        assert any(item.get("reason") == "max_daily_loss" for item in details)
    finally:
        session.close()


def test_guard_degrades_when_valuation_unreliable(monkeypatch):
    session = _make_session()
    try:
        _seed_position(session)
        monkeypatch.setattr(
            trade_guard,
            "read_quotes",
            lambda _root: {"items": [], "stale": True, "updated_at": datetime.now(timezone.utc).isoformat()},
            raising=False,
        )
        monkeypatch.setattr(
            trade_guard,
            "_load_ib_equity_snapshot",
            lambda _session, *, mode: {"stale": True, "source": "ib"},
        )

        run_date = date(2026, 1, 17)
        result = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"cash_available": 0.0},
            trade_date=run_date,
        )

        assert result["status"] == "degraded"
        reason = result.get("reason") or {}
        assert "valuation_unreliable" in (reason.get("reasons") or [])

        state = (
            session.query(TradeGuardState)
            .filter(
                TradeGuardState.project_id == 1,
                TradeGuardState.mode == "paper",
                TradeGuardState.trade_date == run_date,
            )
            .one()
        )
        assert state.status == "active"
    finally:
        session.close()


def test_guard_skips_market_fetch_without_positions(monkeypatch):
    session = _make_session()

    def _boom(*args, **kwargs):
        raise AssertionError("quote fetch called")

    monkeypatch.setattr(trade_guard, "read_quotes", _boom)
    monkeypatch.setattr(trade_guard, "_load_ib_equity_snapshot", lambda _session, *, mode: {})
    try:
        result = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"cash_available": 1000},
        )
        assert result["status"] == "active"
    finally:
        session.close()


def test_guard_accepts_timezone_aware_quote_timestamp(monkeypatch):
    session = _make_session()

    def _quotes(_root):
        ts = datetime.now(timezone.utc).isoformat()
        return {
            "items": [{"symbol": "SPY", "timestamp": ts, "data": {"last": 100.0}}],
            "stale": False,
            "updated_at": ts,
        }

    monkeypatch.setattr(trade_guard, "read_quotes", _quotes)
    monkeypatch.setattr(trade_guard, "_load_ib_equity_snapshot", lambda _session, *, mode: {})
    try:
        _seed_position(session)
        result = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"cash_available": 0},
        )
        assert result["status"] == "active"
        assert float(result["equity"]) > 0
        assert result["thresholds"]["max_daily_loss"] == -0.05
        assert result["thresholds"]["max_intraday_drawdown"] == 0.08
    finally:
        session.close()


def test_guard_applies_cashflow_adjustment_for_ib_equity(monkeypatch, tmp_path):
    session = _make_session()
    try:
        monkeypatch.setattr(trade_guard.settings, "data_root", str(tmp_path), raising=False)
        trade_guard._IB_GUARD_BASELINE_PNL.clear()
        trade_guard._IB_GUARD_BASELINE_PNL_BY_CURRENCY.clear()
        _seed_position(session)
        snapshots = [
            {
                "net_liquidation": 1000.0,
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
                "pnl_total_by_currency": {"USD": 0.0},
                "stale": False,
                "source": "ib",
            },
            {
                "net_liquidation": 1500.0,
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
                "pnl_total_by_currency": {"USD": 0.0},
                "stale": False,
                "source": "ib",
            },
        ]

        monkeypatch.setattr(
            trade_guard,
            "_load_ib_equity_snapshot",
            lambda _session, *, mode: snapshots.pop(0),
        )

        first = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"cash_available": 0.0},
            price_map={"SPY": 100.0},
            trade_date=date(2026, 1, 17),
        )
        second = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"cash_available": 0.0},
            price_map={"SPY": 100.0},
            trade_date=date(2026, 1, 17),
        )

        assert first["equity_source"] == "ib_net_liquidation"
        assert abs(float(first["cashflow_adjustment"] or 0.0)) < 1e-9
        assert second["equity_source"] == "ib_net_liquidation"
        assert abs(float(second["cashflow_adjustment"] or 0.0) - 500.0) < 1e-9
        metrics = second.get("metrics") or {}
        assert abs(float(metrics.get("equity_adjusted") or 0.0) - 1000.0) < 1e-9
    finally:
        trade_guard._IB_GUARD_BASELINE_PNL.clear()
        trade_guard._IB_GUARD_BASELINE_PNL_BY_CURRENCY.clear()
        session.close()


def test_resolve_trade_date_uses_market_timezone(monkeypatch):
    monkeypatch.setattr(trade_guard.settings, "market_timezone", "America/New_York", raising=False)
    utc_now = datetime(2026, 1, 17, 2, 30, tzinfo=timezone.utc)
    assert trade_guard._resolve_trade_date(utc_now) == date(2026, 1, 16)


def test_guard_computes_dd_52w_from_history(monkeypatch):
    session = _make_session()
    try:
        monkeypatch.setattr(trade_guard, "_load_ib_equity_snapshot", lambda _session, *, mode: {})
        base_day = date(2026, 1, 14)
        prior_values = [100.0, 120.0, 110.0]
        for idx, value in enumerate(prior_values):
            state = TradeGuardState(
                project_id=1,
                trade_date=base_day + timedelta(days=idx),
                mode="paper",
                status="active",
                day_start_equity=value,
                equity_peak=value,
                last_equity=value,
            )
            session.add(state)
        session.commit()

        result = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={
                "cash_available": 80.0,
                "max_daily_loss": -1.0,
                "max_intraday_drawdown": 1.0,
                "max_drawdown": 1.0,
                "max_drawdown_52w": 1.0,
            },
            trade_date=date(2026, 1, 17),
        )
        metrics = result.get("metrics") or {}
        assert abs(float(metrics.get("dd_52w") or 0.0) - (1.0 - 80.0 / 120.0)) < 1e-9
    finally:
        session.close()


def test_guard_ignores_stale_peak_all_outlier(monkeypatch):
    session = _make_session()
    try:
        monkeypatch.setattr(trade_guard, "_load_ib_equity_snapshot", lambda _session, *, mode: {})
        session.add(
            TradeGuardState(
                project_id=1,
                trade_date=date(2026, 1, 15),
                mode="paper",
                status="active",
                day_start_equity=100.0,
                equity_peak=100.0,
                last_equity=100.0,
            )
        )
        # Simulate one corrupted historical peak that should not keep the guard locked forever.
        session.add(
            TradeGuardState(
                project_id=1,
                trade_date=date(2026, 1, 16),
                mode="paper",
                status="active",
                day_start_equity=100.0,
                equity_peak=1000.0,
                last_equity=100.0,
            )
        )
        session.commit()

        result = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={
                "cash_available": 95.0,
                "max_daily_loss": -1.0,
                "max_intraday_drawdown": 1.0,
                "max_drawdown": 0.08,
                "max_drawdown_52w": 1.0,
                "peak_all_outlier_ratio": 3.0,
            },
            trade_date=date(2026, 1, 17),
        )
        assert result["status"] == "active"
        metrics = result.get("metrics") or {}
        assert abs(float(metrics.get("dd_all") or 0.0) - 0.05) < 1e-9
        assert abs(float(metrics.get("peak_all_raw") or 0.0) - 1000.0) < 1e-9
        assert abs(float(metrics.get("peak_all") or 0.0) - 100.0) < 1e-9
        assert metrics.get("peak_all_outlier_filtered") is True
    finally:
        session.close()


def test_guard_drawdown_lock_unlock_by_recovery_ratio(monkeypatch):
    session = _make_session()
    try:
        monkeypatch.setattr(trade_guard, "_load_ib_equity_snapshot", lambda _session, *, mode: {})
        session.add(
            TradeGuardState(
                project_id=1,
                trade_date=date(2026, 1, 16),
                mode="paper",
                status="active",
                day_start_equity=100.0,
                equity_peak=100.0,
                last_equity=100.0,
            )
        )
        session.commit()

        risk = {
            "max_daily_loss": -1.0,
            "max_intraday_drawdown": 1.0,
            "max_drawdown": 0.10,
            "max_drawdown_52w": 0.10,
            "drawdown_recovery_ratio": 0.9,
            "cash_available": 85.0,
        }
        first = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params=risk,
            trade_date=date(2026, 1, 17),
        )
        assert first["status"] == "halted"
        assert first["dd_lock_state"] is True
        assert "max_drawdown" in ((first.get("reason") or {}).get("reasons") or [])

        risk_recovered = dict(risk)
        risk_recovered["cash_available"] = 95.0
        second = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params=risk_recovered,
            trade_date=date(2026, 1, 17),
        )
        assert second["status"] == "active"
        assert second["dd_lock_state"] is False
        reason = second.get("reason") or {}
        assert reason.get("unlock_reason") == "drawdown_recovered"
    finally:
        session.close()


def test_guard_unlocks_non_drawdown_halt_after_cooldown(monkeypatch):
    session = _make_session()
    try:
        monkeypatch.setattr(trade_guard, "_load_ib_equity_snapshot", lambda _session, *, mode: {})
        run_date = date(2026, 1, 17)
        session.add(
            TradeGuardState(
                project_id=1,
                trade_date=run_date,
                mode="paper",
                status="halted",
                halt_reason={"reasons": ["max_intraday_drawdown"]},
                day_start_equity=1000.0,
                equity_peak=1000.0,
                last_equity=920.0,
                cooldown_until=datetime.utcnow() - timedelta(minutes=5),
            )
        )
        session.commit()

        result = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"cash_available": 1000.0},
            trade_date=run_date,
        )
        assert result["status"] == "active"
        reason = result.get("reason") or {}
        assert reason.get("unlock_reason") == "cooldown_elapsed"

        refreshed = (
            session.query(TradeGuardState)
            .filter(
                TradeGuardState.project_id == 1,
                TradeGuardState.mode == "paper",
                TradeGuardState.trade_date == run_date,
            )
            .one()
        )
        assert refreshed.status == "active"
        assert refreshed.cooldown_until is None
    finally:
        session.close()


def test_guard_persists_ib_baseline_pnl_across_memory_reset(monkeypatch, tmp_path):
    session = _make_session()
    try:
        monkeypatch.setattr(trade_guard.settings, "data_root", str(tmp_path), raising=False)
        trade_guard._IB_GUARD_BASELINE_PNL.clear()
        trade_guard._IB_GUARD_BASELINE_PNL_BY_CURRENCY.clear()
        snapshots = [
            {
                "net_liquidation": 1000.0,
                "unrealized_pnl": 10.0,
                "realized_pnl": 0.0,
                "stale": False,
                "source": "ib",
            },
            {
                "net_liquidation": 1200.0,
                "unrealized_pnl": 20.0,
                "realized_pnl": 0.0,
                "stale": False,
                "source": "ib",
            },
        ]
        monkeypatch.setattr(
            trade_guard,
            "_load_ib_equity_snapshot",
            lambda _session, *, mode: snapshots.pop(0),
        )
        run_date = date(2026, 1, 17)

        first = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"cash_available": 0.0},
            trade_date=run_date,
        )
        assert first["equity_source"] == "ib_net_liquidation"
        assert abs(float(first["cashflow_adjustment"] or 0.0)) < 1e-9

        baseline_file = tmp_path / "state" / "trade_guard_ib_baseline_pnl.json"
        assert baseline_file.exists()

        # Simulate process restart: in-memory baseline cache is empty.
        trade_guard._IB_GUARD_BASELINE_PNL.clear()
        trade_guard._IB_GUARD_BASELINE_PNL_BY_CURRENCY.clear()

        second = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"cash_available": 0.0},
            trade_date=run_date,
        )
        assert second["equity_source"] == "ib_net_liquidation"
        # With persisted baseline(10), cashflow adjustment should be 1200 - (1000 + (20-10)) = 190.
        assert abs(float(second["cashflow_adjustment"] or 0.0) - 190.0) < 1e-9
    finally:
        trade_guard._IB_GUARD_BASELINE_PNL.clear()
        trade_guard._IB_GUARD_BASELINE_PNL_BY_CURRENCY.clear()
        session.close()


def test_load_ib_equity_snapshot_extracts_currency_maps(monkeypatch):
    session = _make_session()
    try:
        import app.services.ib_account as ib_account_module

        monkeypatch.setattr(
            ib_account_module,
            "get_account_summary",
            lambda _session, *, mode, full=True, force_refresh=False: {
                "items": {
                    "NetLiquidation": "1500",
                    "UnrealizedPnL": "150",
                    "RealizedPnL": "20",
                    "__by_currency__": {
                        "NetLiquidation": {"USD": "1000", "EUR": "500"},
                        "UnrealizedPnL": {"USD": "20", "EUR": "130"},
                        "RealizedPnL": {"USD": "5", "EUR": "15"},
                    },
                },
                "stale": False,
                "source": "ib",
            },
        )
        snapshot = trade_guard._load_ib_equity_snapshot(session, mode="paper")
        assert snapshot["net_liquidation"] == 1500.0
        assert snapshot["unrealized_pnl"] == 150.0
        assert snapshot["realized_pnl"] == 20.0
        assert snapshot["net_liquidation_by_currency"] == {"USD": 1000.0, "EUR": 500.0}
        assert snapshot["pnl_total_by_currency"] == {"USD": 25.0, "EUR": 145.0}
    finally:
        session.close()


def test_load_ib_equity_snapshot_uses_currency_sums_when_scalars_missing(monkeypatch):
    session = _make_session()
    try:
        import app.services.ib_account as ib_account_module

        monkeypatch.setattr(
            ib_account_module,
            "get_account_summary",
            lambda _session, *, mode, full=True, force_refresh=False: {
                "items": {
                    "__by_currency__": {
                        "NetLiquidation": {"USD": "1000", "EUR": "200"},
                        "UnrealizedPnL": {"USD": "20", "EUR": "30"},
                        "RealizedPnL": {"USD": "5", "EUR": "7"},
                    },
                },
                "stale": False,
                "source": "ib",
            },
        )
        snapshot = trade_guard._load_ib_equity_snapshot(session, mode="paper")
        assert snapshot["net_liquidation"] == 1200.0
        assert snapshot["unrealized_pnl"] == 50.0
        assert snapshot["realized_pnl"] == 12.0
        assert snapshot["pnl_total_by_currency"] == {"USD": 25.0, "EUR": 37.0}
    finally:
        session.close()


def test_guard_uses_currency_pnl_for_cashflow_adjustment(monkeypatch, tmp_path):
    session = _make_session()
    try:
        monkeypatch.setattr(trade_guard.settings, "data_root", str(tmp_path), raising=False)
        trade_guard._IB_GUARD_BASELINE_PNL.clear()
        trade_guard._IB_GUARD_BASELINE_PNL_BY_CURRENCY.clear()

        snapshots = [
            {
                "net_liquidation": 1000.0,
                "unrealized_pnl": 110.0,
                "realized_pnl": 0.0,
                "pnl_total_by_currency": {"USD": 10.0, "EUR": 100.0},
                "stale": False,
                "source": "ib",
            },
            {
                "net_liquidation": 1300.0,
                "unrealized_pnl": 150.0,
                "realized_pnl": 0.0,
                "pnl_total_by_currency": {"USD": 20.0, "EUR": 130.0},
                "stale": False,
                "source": "ib",
            },
        ]
        monkeypatch.setattr(
            trade_guard,
            "_load_ib_equity_snapshot",
            lambda _session, *, mode: snapshots.pop(0),
        )
        run_date = date(2026, 1, 17)
        first = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"cash_available": 0.0},
            trade_date=run_date,
        )
        assert abs(float(first["cashflow_adjustment"] or 0.0)) < 1e-9

        # Simulate service restart.
        trade_guard._IB_GUARD_BASELINE_PNL.clear()
        trade_guard._IB_GUARD_BASELINE_PNL_BY_CURRENCY.clear()

        second = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"cash_available": 0.0},
            trade_date=run_date,
        )
        # market_pnl=(20-10)+(130-100)=40 -> cashflow=1300-(1000+40)=260
        assert abs(float(second["cashflow_adjustment"] or 0.0) - 260.0) < 1e-9
        metrics = second.get("metrics") or {}
        assert (metrics.get("pnl_total_by_currency") or {}).get("EUR") == 130.0
    finally:
        trade_guard._IB_GUARD_BASELINE_PNL.clear()
        trade_guard._IB_GUARD_BASELINE_PNL_BY_CURRENCY.clear()
        session.close()


def test_guard_disables_cashflow_adjustment_when_mode_off(monkeypatch, tmp_path):
    session = _make_session()
    try:
        monkeypatch.setattr(trade_guard.settings, "data_root", str(tmp_path), raising=False)
        trade_guard._IB_GUARD_BASELINE_PNL.clear()
        trade_guard._IB_GUARD_BASELINE_PNL_BY_CURRENCY.clear()

        snapshots = [
            {
                "net_liquidation": 1000.0,
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
                "pnl_total_by_currency": {"USD": 0.0},
                "stale": False,
                "source": "ib",
            },
            {
                "net_liquidation": 1500.0,
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
                "pnl_total_by_currency": {"USD": 0.0},
                "stale": False,
                "source": "ib",
            },
        ]

        monkeypatch.setattr(
            trade_guard,
            "_load_ib_equity_snapshot",
            lambda _session, *, mode: snapshots.pop(0),
        )
        run_date = date(2026, 1, 17)
        first = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"cash_available": 0.0, "cashflow_adjustment_mode": "off"},
            trade_date=run_date,
        )
        second = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={"cash_available": 0.0, "cashflow_adjustment_mode": "off"},
            trade_date=run_date,
        )

        assert first["equity_source"] == "ib_net_liquidation"
        assert second["equity_source"] == "ib_net_liquidation"
        assert abs(float(second["cashflow_adjustment"] or 0.0)) < 1e-9
        metrics = second.get("metrics") or {}
        assert abs(float(metrics.get("equity_adjusted") or 0.0) - 1500.0) < 1e-9
        assert metrics.get("cashflow_adjustment_mode") == "off"
    finally:
        trade_guard._IB_GUARD_BASELINE_PNL.clear()
        trade_guard._IB_GUARD_BASELINE_PNL_BY_CURRENCY.clear()
        session.close()


def test_guard_can_rebase_equity_baseline(monkeypatch):
    session = _make_session()
    try:
        monkeypatch.setattr(
            trade_guard,
            "_load_ib_equity_snapshot",
            lambda _session, *, mode: {
                "net_liquidation": 200.0,
                "unrealized_pnl": None,
                "realized_pnl": None,
                "stale": False,
                "source": "ib",
            },
        )
        session.add(
            TradeGuardState(
                project_id=1,
                trade_date=date(2026, 1, 17),
                mode="paper",
                status="active",
                day_start_equity=1000.0,
                equity_peak=1000.0,
                last_equity=1000.0,
            )
        )
        session.commit()

        result = evaluate_intraday_guard(
            session,
            project_id=1,
            mode="paper",
            risk_params={
                "cashflow_adjustment_mode": "off",
                "rebase_equity_baseline": True,
                "max_daily_loss": -0.05,
                "max_intraday_drawdown": 0.08,
                "max_drawdown": 0.08,
                "max_drawdown_52w": 0.12,
            },
            trade_date=date(2026, 1, 17),
        )

        metrics = result.get("metrics") or {}
        assert result["status"] == "active"
        assert abs(float(metrics.get("day_start_equity") or 0.0) - 200.0) < 1e-9
        assert abs(float(metrics.get("equity_peak") or 0.0) - 200.0) < 1e-9
        assert abs(float(metrics.get("equity_adjusted") or 0.0) - 200.0) < 1e-9
        assert abs(float(metrics.get("daily_loss") or 0.0)) < 1e-9
        assert bool(metrics.get("baseline_rebased")) is True
    finally:
        session.close()
