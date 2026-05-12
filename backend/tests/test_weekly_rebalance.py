from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base, DecisionSnapshot, PreTradeRun, Project, TradeRun


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _seed_project(session, name: str = "weekly") -> Project:
    project = Project(name=name, description="")
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _monday(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 5, 11, hour, minute)


def test_prepare_weekly_rebalance_runs_pretrade_and_sends_telegram(monkeypatch):
    from app.services import weekly_rebalance

    Session = _make_session_factory()
    session = Session()
    project = _seed_project(session)
    session.close()

    def _session_local():
        return Session()

    def _fake_run_pretrade_run(run_id: int, *_args, **_kwargs):
        with _session_local() as inner:
            run = inner.get(PreTradeRun, run_id)
            snapshot = DecisionSnapshot(
                project_id=run.project_id,
                status="success",
                snapshot_date="2026-05-08",
                summary={},
                items_path="/tmp/items.csv",
            )
            inner.add(snapshot)
            inner.commit()
            inner.refresh(snapshot)
            trade_run = TradeRun(
                project_id=run.project_id,
                decision_snapshot_id=snapshot.id,
                mode="paper",
                status="queued",
                params={"pretrade_run_id": run.id},
            )
            inner.add(trade_run)
            run.status = "success"
            run.message = "success"
            run.ended_at = datetime.utcnow()
            inner.commit()

    messages: list[str] = []
    monkeypatch.setattr(weekly_rebalance, "SessionLocal", _session_local)
    monkeypatch.setattr(weekly_rebalance, "run_pretrade_run", _fake_run_pretrade_run)
    monkeypatch.setattr(weekly_rebalance, "notify_trade_alert", lambda _session, message: messages.append(message) or True)
    monkeypatch.setattr(weekly_rebalance, "_is_trading_day", lambda _day: True)

    result = weekly_rebalance.prepare_weekly_rebalance(project.id, now=_monday(8))

    assert result.status == "success"
    assert result.pretrade_run_id is not None
    assert result.trade_run_id is not None
    assert result.week_key == "2026-W20"
    assert result.notification_sent is True
    assert messages and "Weekly rebalance prepare success" in messages[-1]


def test_prepare_weekly_rebalance_reuses_same_week_success(monkeypatch):
    from app.services import weekly_rebalance

    Session = _make_session_factory()
    session = Session()
    project = _seed_project(session)
    run = PreTradeRun(
        project_id=project.id,
        status="success",
        created_at=datetime(2026, 5, 11, 12, 0),
        params={"weekly_rebalance": {"phase": "prepare", "week_key": "2026-W20"}},
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    session.close()

    calls = {"run_pretrade": 0}

    def _session_local():
        return Session()

    def _fake_run_pretrade_run(*_args, **_kwargs):
        calls["run_pretrade"] += 1

    monkeypatch.setattr(weekly_rebalance, "SessionLocal", _session_local)
    monkeypatch.setattr(weekly_rebalance, "run_pretrade_run", _fake_run_pretrade_run)
    monkeypatch.setattr(weekly_rebalance, "notify_trade_alert", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(weekly_rebalance, "_is_trading_day", lambda _day: True)

    result = weekly_rebalance.prepare_weekly_rebalance(project.id, now=_monday(8))

    assert result.status == "reused"
    assert result.pretrade_run_id == run.id
    assert calls["run_pretrade"] == 0


def test_prepare_weekly_rebalance_skips_after_market_open(monkeypatch):
    from app.services import weekly_rebalance

    Session = _make_session_factory()
    session = Session()
    project = _seed_project(session)
    session.close()

    called = {"run_pretrade": False}
    monkeypatch.setattr(weekly_rebalance, "SessionLocal", lambda: Session())
    monkeypatch.setattr(weekly_rebalance, "_is_trading_day", lambda _day: True)
    monkeypatch.setattr(
        weekly_rebalance,
        "run_pretrade_run",
        lambda *_args, **_kwargs: called.__setitem__("run_pretrade", True),
    )

    result = weekly_rebalance.prepare_weekly_rebalance(project.id, now=_monday(9, 35))

    assert result.status == "skipped"
    assert result.message == "market_already_open"
    assert called["run_pretrade"] is False


def test_execute_weekly_rebalance_skips_before_market_open(monkeypatch):
    from app.services import weekly_rebalance

    Session = _make_session_factory()
    session = Session()
    project = _seed_project(session)
    session.close()

    called = {"execute": False}
    monkeypatch.setattr(weekly_rebalance, "SessionLocal", lambda: Session())
    monkeypatch.setattr(weekly_rebalance, "_is_trading_day", lambda _day: True)
    monkeypatch.setattr(weekly_rebalance, "execute_trade_run", lambda *_args, **_kwargs: called.__setitem__("execute", True))

    result = weekly_rebalance.execute_weekly_rebalance(project.id, now=_monday(9, 0))

    assert result.status == "skipped"
    assert result.message == "market_not_open"
    assert called["execute"] is False


def test_execute_weekly_rebalance_executes_queued_trade_run_and_notifies(monkeypatch):
    from app.services import weekly_rebalance

    Session = _make_session_factory()
    session = Session()
    project = _seed_project(session)
    pretrade = PreTradeRun(
        project_id=project.id,
        status="success",
        created_at=datetime(2026, 5, 11, 12, 0),
        params={"weekly_rebalance": {"phase": "prepare", "week_key": "2026-W20"}},
    )
    session.add(pretrade)
    session.commit()
    session.refresh(pretrade)
    snapshot = DecisionSnapshot(project_id=project.id, status="success", snapshot_date="2026-05-08", summary={})
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    trade_run = TradeRun(
        project_id=project.id,
        decision_snapshot_id=snapshot.id,
        status="queued",
        mode="paper",
        params={"pretrade_run_id": pretrade.id},
        created_at=datetime(2026, 5, 11, 12, 5),
    )
    session.add(trade_run)
    session.commit()
    session.refresh(trade_run)
    session.close()

    messages: list[str] = []
    executed: list[int] = []

    def _fake_execute_trade_run(run_id: int, *, dry_run: bool = False, force: bool = False, **_kwargs):
        executed.append(run_id)
        with Session() as inner:
            run = inner.get(TradeRun, run_id)
            run.status = "running"
            run.message = "submitted_leader"
            inner.commit()
        return SimpleNamespace(
            run_id=run_id,
            status="running",
            filled=0,
            cancelled=0,
            rejected=0,
            skipped=0,
            message="submitted_leader",
            dry_run=dry_run,
        )

    monkeypatch.setattr(weekly_rebalance, "SessionLocal", lambda: Session())
    monkeypatch.setattr(weekly_rebalance, "_is_trading_day", lambda _day: True)
    monkeypatch.setattr(weekly_rebalance, "execute_trade_run", _fake_execute_trade_run)
    monkeypatch.setattr(weekly_rebalance, "notify_trade_alert", lambda _session, message: messages.append(message) or True)

    result = weekly_rebalance.execute_weekly_rebalance(project.id, now=_monday(9, 35))

    assert result.status == "running"
    assert result.trade_run_id == trade_run.id
    assert executed == [trade_run.id]
    assert result.notification_sent is True
    assert messages and "Weekly rebalance execute running" in messages[-1]

    with Session() as verify:
        refreshed = verify.get(TradeRun, trade_run.id)
        weekly_meta = (refreshed.params or {}).get("weekly_rebalance") or {}
        assert weekly_meta.get("phase") == "execute"
        assert weekly_meta.get("week_key") == "2026-W20"
        assert (refreshed.params or {}).get("execution_session") == "rth"
        assert (refreshed.params or {}).get("allow_outside_rth") is False


def test_weekly_rebalance_status_lists_schedule_and_history(monkeypatch):
    from app.services import weekly_rebalance

    Session = _make_session_factory()
    session = Session()
    project = _seed_project(session)
    pretrade = PreTradeRun(
        project_id=project.id,
        status="success",
        message="pretrade ok",
        created_at=datetime(2026, 5, 11, 12, 0),
        started_at=datetime(2026, 5, 11, 12, 1),
        ended_at=datetime(2026, 5, 11, 12, 8),
        params={
            "weekly_rebalance": {
                "phase": "prepare",
                "week_key": "2026-W20",
                "scheduled_at": "2026-05-11T08:00:00-04:00",
            }
        },
    )
    session.add(pretrade)
    session.commit()
    session.refresh(pretrade)
    trade_run = TradeRun(
        project_id=project.id,
        status="running",
        mode="paper",
        message="submitted",
        created_at=datetime(2026, 5, 11, 13, 35),
        started_at=datetime(2026, 5, 11, 13, 36),
        params={
            "pretrade_run_id": pretrade.id,
            "weekly_rebalance": {
                "phase": "execute",
                "week_key": "2026-W20",
                "pretrade_run_id": pretrade.id,
            },
        },
    )
    session.add(trade_run)
    session.commit()
    session.refresh(trade_run)
    session.close()

    monkeypatch.setattr(weekly_rebalance, "SessionLocal", lambda: Session())
    monkeypatch.setattr(
        weekly_rebalance,
        "_read_systemd_timer_state",
        lambda unit: {
            "active_state": "active",
            "sub_state": "waiting",
            "next_elapse_at": "Mon 2026-05-18 08:00:00 EDT",
            "last_trigger_at": "Mon 2026-05-11 08:00:01 EDT",
            "error": None,
        },
    )

    status = weekly_rebalance.get_weekly_rebalance_status(
        project_id=project.id,
        limit=5,
    )

    assert status["project_id"] == project.id
    assert [item["phase"] for item in status["schedules"]] == ["prepare", "execute"]
    assert status["schedules"][0]["active_state"] == "active"
    assert status["schedules"][0]["next_elapse_at"] == "Mon 2026-05-18 08:00:00 EDT"
    assert len(status["history"]) == 1
    history = status["history"][0]
    assert history["week_key"] == "2026-W20"
    assert history["pretrade_run_id"] == pretrade.id
    assert history["pretrade_status"] == "success"
    assert history["trade_run_id"] == trade_run.id
    assert history["trade_status"] == "running"


def test_weekly_rebalance_status_records_skipped_attempt(monkeypatch):
    from app.services import weekly_rebalance

    Session = _make_session_factory()
    session = Session()
    project = _seed_project(session)
    session.close()

    monkeypatch.setattr(weekly_rebalance, "SessionLocal", lambda: Session())
    monkeypatch.setattr(
        weekly_rebalance,
        "_read_systemd_timer_state",
        lambda unit: {
            "active_state": "active",
            "sub_state": "waiting",
            "next_elapse_at": None,
            "last_trigger_at": None,
            "error": None,
        },
    )

    result = weekly_rebalance.prepare_weekly_rebalance(
        project.id,
        now=datetime(2026, 5, 12, 8, 0),
    )
    status = weekly_rebalance.get_weekly_rebalance_status(
        project_id=project.id,
        limit=5,
    )

    assert result.status == "skipped"
    assert status["history"]
    history = status["history"][0]
    assert history["attempt_phase"] == "prepare"
    assert history["attempt_status"] == "skipped"
    assert history["attempt_message"] == "not_rebalance_day"
    assert history["pretrade_run_id"] is None
    assert history["trade_run_id"] is None


def test_weekly_rebalance_routes_delegate_to_service(monkeypatch):
    from app.routes import automation
    from app.schemas import WeeklyRebalanceRequest

    calls: list[tuple[str, dict]] = []

    def _prepare(**kwargs):
        calls.append(("prepare", kwargs))
        return SimpleNamespace(
            project_id=kwargs["project_id"],
            phase="prepare",
            status="success",
            message="success",
            week_key="2026-W20",
            pretrade_run_id=11,
            trade_run_id=22,
            trade_status="queued",
            notification_sent=True,
        )

    def _execute(**kwargs):
        calls.append(("execute", kwargs))
        return SimpleNamespace(
            project_id=kwargs["project_id"],
            phase="execute",
            status="running",
            message="submitted_leader",
            week_key="2026-W20",
            pretrade_run_id=11,
            trade_run_id=22,
            trade_status="running",
            notification_sent=True,
        )

    monkeypatch.setattr(automation, "prepare_weekly_rebalance", _prepare)
    monkeypatch.setattr(automation, "execute_weekly_rebalance", _execute)

    prepare_out = automation.prepare_weekly_rebalance_route(
        WeeklyRebalanceRequest(project_id=18, force=True, dry_run=True)
    )
    execute_out = automation.execute_weekly_rebalance_route(
        WeeklyRebalanceRequest(project_id=18, force=True, dry_run=True)
    )

    assert prepare_out.status == "success"
    assert execute_out.status == "running"
    assert calls == [
        ("prepare", {"project_id": 18, "force": True}),
        ("execute", {"project_id": 18, "force": True, "dry_run": True}),
    ]
