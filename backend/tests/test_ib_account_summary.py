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
