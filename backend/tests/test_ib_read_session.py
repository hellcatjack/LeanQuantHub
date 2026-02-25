from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_resolve_ib_transient_client_id_is_stable():
    from app.services import ib_read_session

    ib_read_session.reset_ib_read_sessions()
    paper_a = ib_read_session.resolve_ib_transient_client_id(mode="paper", purpose="positions")
    paper_b = ib_read_session.resolve_ib_transient_client_id(mode="paper", purpose="positions")
    live = ib_read_session.resolve_ib_transient_client_id(mode="live", purpose="positions")

    assert paper_a == paper_b
    assert paper_a != live


def test_transient_fallback_backoff_respected_and_reset(monkeypatch):
    from app.services import ib_read_session

    now = {"value": 10.0}
    monkeypatch.setattr(ib_read_session, "monotonic", lambda: now["value"], raising=False)
    monkeypatch.setattr(ib_read_session, "_TRANSIENT_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(ib_read_session, "_TRANSIENT_FALLBACK_BASE_BACKOFF_SECONDS", 5.0, raising=False)
    monkeypatch.setattr(ib_read_session, "_TRANSIENT_FALLBACK_MAX_BACKOFF_SECONDS", 20.0, raising=False)
    ib_read_session.reset_ib_read_sessions()

    kwargs = {
        "mode": "paper",
        "host": "127.0.0.1",
        "port": 4002,
        "purpose": "summary",
    }
    assert ib_read_session.can_attempt_ib_transient_fallback(**kwargs) is True

    ib_read_session.record_ib_transient_fallback_result(success=False, **kwargs)
    assert ib_read_session.can_attempt_ib_transient_fallback(**kwargs) is False

    now["value"] = 13.0
    assert ib_read_session.can_attempt_ib_transient_fallback(**kwargs) is False

    now["value"] = 15.0
    assert ib_read_session.can_attempt_ib_transient_fallback(**kwargs) is True

    ib_read_session.record_ib_transient_fallback_result(success=True, **kwargs)
    assert ib_read_session.can_attempt_ib_transient_fallback(**kwargs) is True
