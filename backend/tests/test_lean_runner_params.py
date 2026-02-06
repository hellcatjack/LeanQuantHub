from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.lean_runner import _build_execution_params_payload


def test_build_execution_params_payload_defaults():
    payload = _build_execution_params_payload({})
    assert payload["min_qty"] == 1
    assert payload["lot_size"] == 1
