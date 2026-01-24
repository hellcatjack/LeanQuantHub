from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_filter_summary_whitelist():
    from app.services.ib_account import _filter_summary

    raw = {"NetLiquidation": "100", "Foo": "bar"}
    core = _filter_summary(raw, full=False)
    assert "NetLiquidation" in core
    assert "Foo" not in core
    full = _filter_summary(raw, full=True)
    assert "Foo" in full


def test_build_summary_tags_uses_core_tags():
    from app.services.ib_account import CORE_TAGS, build_account_summary_tags

    tags = build_account_summary_tags(full=False)
    parts = {item.strip() for item in tags.split(",") if item.strip()}
    assert "All" not in parts
    for tag in CORE_TAGS:
        assert tag in parts


def test_resolve_ib_account_settings_skips_probe(monkeypatch):
    from app.services import ib_account as ib_account_module

    sentinel = object()
    monkeypatch.setattr(ib_account_module, "get_or_create_ib_settings", lambda _session: sentinel)
    monkeypatch.setattr(ib_account_module, "ensure_ib_client_id", lambda _session: (_ for _ in ()).throw(RuntimeError("probe-called")))

    assert ib_account_module.resolve_ib_account_settings(object()) is sentinel


def test_iter_account_client_ids_defaults():
    from app.services.ib_account import iter_account_client_ids

    assert list(iter_account_client_ids(100, attempts=3)) == [100, 101, 102]
