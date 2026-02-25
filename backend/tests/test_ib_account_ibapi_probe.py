from pathlib import Path
import socket
import sys
import types

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _install_fake_ibapi(monkeypatch):
    connect_calls = {"count": 0}

    class _FakeEWrapper:
        pass

    class _FakeEClient:
        def __init__(self, _wrapper):
            pass

        def connect(self, *_args, **_kwargs):
            connect_calls["count"] += 1
            raise AssertionError("connect should not be called")

        def run(self):
            return None

        def reqPositions(self):
            return None

        def reqAccountSummary(self, *_args, **_kwargs):
            return None

        def reqPnL(self, *_args, **_kwargs):
            return None

        def cancelAccountSummary(self, *_args, **_kwargs):
            return None

        def cancelPnL(self, *_args, **_kwargs):
            return None

        def disconnect(self):
            return None

    ibapi_pkg = types.ModuleType("ibapi")
    client_mod = types.ModuleType("ibapi.client")
    wrapper_mod = types.ModuleType("ibapi.wrapper")
    client_mod.EClient = _FakeEClient
    wrapper_mod.EWrapper = _FakeEWrapper

    monkeypatch.setitem(sys.modules, "ibapi", ibapi_pkg)
    monkeypatch.setitem(sys.modules, "ibapi.client", client_mod)
    monkeypatch.setitem(sys.modules, "ibapi.wrapper", wrapper_mod)
    return connect_calls


def _raise_probe_timeout(*_args, **_kwargs):
    raise TimeoutError("probe_timeout")


def test_fetch_positions_via_ibapi_skips_connect_when_socket_probe_fails(monkeypatch):
    from app.services import ib_account as ib_account_module

    connect_calls = _install_fake_ibapi(monkeypatch)
    monkeypatch.setattr(socket, "create_connection", _raise_probe_timeout)

    payload = ib_account_module._fetch_positions_via_ibapi(
        host="127.0.0.1",
        port=4001,
        client_id=1,
        timeout_seconds=1.0,
    )

    assert payload is None
    assert connect_calls["count"] == 0


def test_fetch_account_summary_via_ibapi_skips_connect_when_socket_probe_fails(monkeypatch):
    from app.services import ib_account as ib_account_module

    connect_calls = _install_fake_ibapi(monkeypatch)
    monkeypatch.setattr(socket, "create_connection", _raise_probe_timeout)

    payload = ib_account_module._fetch_account_summary_via_ibapi(
        host="127.0.0.1",
        port=4001,
        client_id=1,
        timeout_seconds=1.0,
        account_id="DU123456",
    )

    assert payload is None
    assert connect_calls["count"] == 0


def test_fetch_account_pnl_via_ibapi_skips_connect_when_socket_probe_fails(monkeypatch):
    from app.services import ib_account as ib_account_module

    connect_calls = _install_fake_ibapi(monkeypatch)
    monkeypatch.setattr(socket, "create_connection", _raise_probe_timeout)

    payload = ib_account_module._fetch_account_pnl_via_ibapi(
        host="127.0.0.1",
        port=4001,
        client_id=1,
        account_id="DU123456",
        timeout_seconds=1.0,
    )

    assert payload is None
    assert connect_calls["count"] == 0
