from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.run_cagr_opt import build_payload as build_cagr_payload
from scripts.run_train_model_opt import build_payload as build_train_payload


def test_cagr_payload_uses_default_policy_baseline() -> None:
    payload = build_cagr_payload({"max_exposure": 0.35})
    algo = payload["params"]["algorithm_parameters"]
    assert payload["params"]["benchmark"] == "SPY"
    assert algo["risk_off_symbols"] == "SGOV,VGSH"
    assert algo["benchmark"] == "SPY"


def test_train_model_payload_uses_default_policy_baseline() -> None:
    payload = build_train_payload(120, {"max_exposure": 0.4})
    algo = payload["params"]["algorithm_parameters"]
    assert payload["params"]["benchmark"] == "SPY"
    assert algo["risk_off_symbols"] == "SGOV,VGSH"
    assert algo["benchmark"] == "SPY"
