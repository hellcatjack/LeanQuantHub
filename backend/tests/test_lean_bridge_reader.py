from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.lean_bridge_reader import _parse_iso


def test_parse_iso_supports_high_precision_fraction():
    parsed = _parse_iso("2026-01-30T23:01:36.4913968Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.isoformat().startswith("2026-01-30T23:01:36.491396")
