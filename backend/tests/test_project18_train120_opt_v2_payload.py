from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.run_project18_train120_opt_v2 import build_payload


def test_v2_payload_risk_off_and_drawdown() -> None:
    baseline_algo = {"max_exposure": 0.3}
    overrides = {
        "max_exposure": 0.32,
        "vol_target": 0.0425,
        "max_weight": 0.026,
        "drawdown_tiers": "0.05,0.09,0.12",
        "drawdown_exposures": "0.45,0.30,0.20",
    }
    payload = build_payload(overrides, baseline_algo, "/tmp/scores.csv")
    algo = payload["params"]["algorithm_parameters"]
    assert algo["risk_off_symbols"] == "VGSH,IEF,GLD,TLT"
    assert algo["score_csv_path"] == "/tmp/scores.csv"
    assert algo["drawdown_tiers"] == "0.05,0.09,0.12"
    assert algo["drawdown_exposures"] == "0.45,0.30,0.20"
