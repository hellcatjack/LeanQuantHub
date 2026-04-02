from pathlib import Path
import sys
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import BacktestRun, Base, PreTradeRun, PreTradeStep, Project, TradeRun
import app.services.pretrade_runner as pretrade_runner


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Session


def test_pretrade_can_trigger_trade_run(monkeypatch):
    Session = _make_session_factory()
    session = Session()

    def _fake_generate_decision_snapshot(*_args, **_kwargs):
        return {
            "summary": {"snapshot_date": "2026-01-16"},
            "summary_path": "/tmp/decision_summary.json",
            "items_path": "/tmp/decision_items.csv",
            "filters_path": "/tmp/decision_filters.csv",
            "artifact_dir": "/tmp/decision_artifacts",
            "log_path": "/tmp/decision.log",
        }

    monkeypatch.setattr(pretrade_runner, "generate_decision_snapshot", _fake_generate_decision_snapshot)

    try:
        project = Project(name="pretrade-test", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = PreTradeRun(project_id=project.id, status="running")
        session.add(run)
        session.commit()
        session.refresh(run)

        step = PreTradeStep(run_id=run.id, step_key="decision_snapshot", step_order=0, status="running")
        session.add(step)
        session.commit()
        session.refresh(step)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        result = pretrade_runner.step_decision_snapshot(ctx, {})

        trade_run_id = result.artifacts.get("trade_run_id") if result.artifacts else None
        decision_snapshot_id = result.artifacts.get("decision_snapshot_id") if result.artifacts else None

        assert trade_run_id is not None
        assert decision_snapshot_id is not None

        trade_run = session.get(TradeRun, trade_run_id)
        assert trade_run is not None
        assert trade_run.decision_snapshot_id == decision_snapshot_id
        assert isinstance(trade_run.params, dict)
        strategy_snapshot = trade_run.params.get("strategy_snapshot")
        assert isinstance(strategy_snapshot, dict)
        assert isinstance(strategy_snapshot.get("backtest_params"), dict)
        assert result.artifacts.get("decision_snapshot_stage") == "trade_run_ready"
        assert result.artifacts.get("decision_snapshot_db_lock_wait_seconds") == 30
        stages = result.artifacts.get("decision_snapshot_stages")
        assert isinstance(stages, list)
        assert stages
        assert stages[-1].get("stage") == "trade_run_ready"
    finally:
        session.close()


def test_create_pretrade_run_for_project_creates_steps():
    Session = _make_session_factory()
    session = Session()
    try:
        project = Project(name="pretrade-create", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = pretrade_runner.create_pretrade_run_for_project(session, project_id=project.id)
        steps = (
            session.query(PreTradeStep)
            .filter(PreTradeStep.run_id == run.id)
            .all()
        )
        assert run.id is not None
        assert len(steps) > 0
    finally:
        session.close()


def test_apply_decision_snapshot_db_timeouts_for_mysql_session():
    executed: list[tuple[str, dict[str, int] | None]] = []

    class DummySession:
        def __init__(self):
            self._bind = SimpleNamespace(dialect=SimpleNamespace(name="mysql"))

        def get_bind(self):
            return self._bind

        def execute(self, statement, params=None):
            executed.append((str(statement), params))

    applied = pretrade_runner._apply_decision_snapshot_db_timeouts(DummySession(), 17)

    assert applied == 17
    assert len(executed) == 2
    assert all(item[1] == {"seconds": 17} for item in executed)


def test_pretrade_decision_snapshot_sanitizes_non_finite_summary(monkeypatch):
    Session = _make_session_factory()
    session = Session()

    def _fake_generate_decision_snapshot(*_args, **_kwargs):
        return {
            "summary": {
                "snapshot_date": "2026-01-16",
                "source_summary": {
                    "turnover_avg": float("nan"),
                    "weights_sum": float("inf"),
                },
            },
            "summary_path": "/tmp/decision_summary.json",
            "items_path": "/tmp/decision_items.csv",
            "filters_path": "/tmp/decision_filters.csv",
            "artifact_dir": "/tmp/decision_artifacts",
            "log_path": "/tmp/decision.log",
        }

    monkeypatch.setattr(pretrade_runner, "generate_decision_snapshot", _fake_generate_decision_snapshot)

    try:
        project = Project(name="pretrade-sanitize", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = PreTradeRun(project_id=project.id, status="running")
        session.add(run)
        session.commit()
        session.refresh(run)

        step = PreTradeStep(run_id=run.id, step_key="decision_snapshot", step_order=0, status="running")
        session.add(step)
        session.commit()
        session.refresh(step)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        result = pretrade_runner.step_decision_snapshot(ctx, {})
        snapshot_id = result.artifacts.get("decision_snapshot_id") if result.artifacts else None
        assert snapshot_id is not None
        snapshot = session.get(pretrade_runner.DecisionSnapshot, snapshot_id)
        assert snapshot is not None
        source_summary = (snapshot.summary or {}).get("source_summary") or {}
        assert source_summary.get("turnover_avg") is None
        assert source_summary.get("weights_sum") is None
        decision_snapshot = (result.artifacts or {}).get("decision_snapshot") or {}
        decision_source_summary = decision_snapshot.get("source_summary") or {}
        assert decision_source_summary.get("turnover_avg") is None
        assert decision_source_summary.get("weights_sum") is None
    finally:
        session.close()


def test_pretrade_decision_snapshot_persists_effective_algo_params(monkeypatch):
    Session = _make_session_factory()
    session = Session()

    effective_algo = {"risk_off_mode": "defensive", "max_drawdown": 0.12}

    def _fake_generate_decision_snapshot(*_args, **_kwargs):
        return {
            "summary": {
                "snapshot_date": "2026-01-16",
                "algorithm_parameters": effective_algo,
                "algorithm_parameters_source": "backtest_run",
            },
            "summary_path": "/tmp/decision_summary.json",
            "items_path": "/tmp/decision_items.csv",
            "filters_path": "/tmp/decision_filters.csv",
            "artifact_dir": "/tmp/decision_artifacts",
            "log_path": "/tmp/decision.log",
            "params": {
                "algorithm_parameters": effective_algo,
                "algorithm_parameters_source": "backtest_run",
            },
        }

    monkeypatch.setattr(pretrade_runner, "generate_decision_snapshot", _fake_generate_decision_snapshot)

    try:
        project = Project(name="pretrade-effective-algo", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        run = PreTradeRun(project_id=project.id, status="running")
        session.add(run)
        session.commit()
        session.refresh(run)

        step = PreTradeStep(run_id=run.id, step_key="decision_snapshot", step_order=0, status="running")
        session.add(step)
        session.commit()
        session.refresh(step)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        result = pretrade_runner.step_decision_snapshot(ctx, {})
        snapshot_id = result.artifacts.get("decision_snapshot_id") if result.artifacts else None
        assert snapshot_id is not None
        snapshot = session.get(pretrade_runner.DecisionSnapshot, snapshot_id)
        assert snapshot is not None
        snapshot_params = snapshot.params or {}
        assert snapshot_params.get("algorithm_parameters") == effective_algo
        assert snapshot_params.get("algorithm_parameters_source") == "backtest_run"
    finally:
        session.close()


def test_pretrade_decision_snapshot_defaults_to_current_project_without_explicit_backtest(monkeypatch):
    Session = _make_session_factory()
    session = Session()

    def _fake_generate_decision_snapshot(*_args, **_kwargs):
        return {
            "summary": {
                "snapshot_date": "2026-01-16",
                "algorithm_parameters": {},
                "algorithm_parameters_source": "empty",
            },
            "summary_path": "/tmp/decision_summary.json",
            "items_path": "/tmp/decision_items.csv",
            "filters_path": "/tmp/decision_filters.csv",
            "artifact_dir": "/tmp/decision_artifacts",
            "log_path": "/tmp/decision.log",
            "params": {
                "algorithm_parameters": {},
                "algorithm_parameters_source": "empty",
            },
        }

    monkeypatch.setattr(pretrade_runner, "generate_decision_snapshot", _fake_generate_decision_snapshot)

    try:
        project = Project(name="pretrade-current-project", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        old_run = BacktestRun(project_id=project.id, status="success")
        session.add(old_run)
        session.commit()

        run = PreTradeRun(project_id=project.id, status="running")
        session.add(run)
        session.commit()
        session.refresh(run)

        step = PreTradeStep(run_id=run.id, step_key="decision_snapshot", step_order=0, status="running")
        session.add(step)
        session.commit()
        session.refresh(step)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        result = pretrade_runner.step_decision_snapshot(ctx, {})
        snapshot_id = result.artifacts.get("decision_snapshot_id") if result.artifacts else None
        assert snapshot_id is not None
        snapshot = session.get(pretrade_runner.DecisionSnapshot, snapshot_id)
        assert snapshot is not None
        assert snapshot.backtest_run_id is None
        snapshot_params = snapshot.params or {}
        assert snapshot_params.get("backtest_run_id") is None
        assert snapshot_params.get("backtest_link_status") == "current_project"
    finally:
        session.close()


def test_pretrade_trade_run_strategy_snapshot_prefers_snapshot_backtest_run(monkeypatch):
    Session = _make_session_factory()
    session = Session()

    def _fake_generate_decision_snapshot(*_args, **_kwargs):
        return {
            "summary": {
                "snapshot_date": "2026-01-16",
                "algorithm_parameters": {},
                "algorithm_parameters_source": "backtest_run",
            },
            "summary_path": "/tmp/decision_summary.json",
            "items_path": "/tmp/decision_items.csv",
            "filters_path": "/tmp/decision_filters.csv",
            "artifact_dir": "/tmp/decision_artifacts",
            "log_path": "/tmp/decision.log",
            "params": {
                "algorithm_parameters": {},
                "algorithm_parameters_source": "backtest_run",
            },
        }

    monkeypatch.setattr(pretrade_runner, "generate_decision_snapshot", _fake_generate_decision_snapshot)

    try:
        project = Project(name="pretrade-snapshot-backtest", description="")
        session.add(project)
        session.commit()
        session.refresh(project)

        backtest_run = BacktestRun(
            project_id=project.id,
            status="success",
            params={
                "benchmark": "QQQ",
                "algorithm_parameters": {
                    "risk_off_symbols": "SGOV,VGSH,IEF,GLD",
                    "risk_off_symbol": "SGOV",
                    "max_exposure": 0.3,
                    "backtest_start": "2020-01-01",
                    "backtest_end": "2026-03-26",
                },
            },
        )
        session.add(backtest_run)
        session.commit()
        session.refresh(backtest_run)

        run = PreTradeRun(project_id=project.id, status="running")
        session.add(run)
        session.commit()
        session.refresh(run)

        step = PreTradeStep(run_id=run.id, step_key="decision_snapshot", step_order=0, status="running")
        session.add(step)
        session.commit()
        session.refresh(step)

        ctx = pretrade_runner.StepContext(session=session, run=run, step=step)
        result = pretrade_runner.step_decision_snapshot(ctx, {"backtest_run_id": backtest_run.id})

        trade_run_id = result.artifacts.get("trade_run_id") if result.artifacts else None
        assert trade_run_id is not None
        trade_run = session.get(TradeRun, trade_run_id)
        assert trade_run is not None
        params = trade_run.params or {}
        strategy_snapshot = params.get("strategy_snapshot") or {}
        assert strategy_snapshot.get("backtest_run_id") == backtest_run.id
        assert strategy_snapshot.get("backtest_params", {}).get("risk_off_symbols") == "SGOV,VGSH,IEF,GLD"
        assert strategy_snapshot.get("benchmark") == "QQQ"
    finally:
        session.close()
