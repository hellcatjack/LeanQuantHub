from pathlib import Path
import json
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import decision_snapshot as decision_snapshot_service


def test_sanitize_json_replaces_non_finite_values():
    payload = {
        "alpha": float("nan"),
        "beta": [1.0, float("inf"), {"gamma": float("-inf")}],
        "delta": {"nested": float("nan")},
    }
    sanitized = decision_snapshot_service._sanitize_json(payload)

    assert sanitized["alpha"] is None
    assert sanitized["beta"][1] is None
    assert sanitized["beta"][2]["gamma"] is None
    assert sanitized["delta"]["nested"] is None

    # ensure JSON is valid for strict parsers (MySQL JSON)
    json.dumps(sanitized, allow_nan=False)
