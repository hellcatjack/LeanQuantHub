from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.run_project18_train120_opt import build_payload


def test_build_payload_applies_overrides_and_risk_off() -> None:
    baseline_algo = {"max_exposure": 0.9, "vol_target": 0.055, "max_weight": 0.05}
    overrides = {"max_exposure": 0.70, "vol_target": 0.050, "max_weight": 0.035}
    payload = build_payload(overrides, baseline_algo, "/tmp/scores.csv")
    algo = payload["params"]["algorithm_parameters"]
    assert payload["params"]["pipeline_train_job_id"] == 120
    assert algo["risk_off_symbols"] == "VGSH,IEF,GLD,TLT"
    assert algo["score_csv_path"] == "/tmp/scores.csv"
    assert algo["max_exposure"] == 0.70
    assert algo["vol_target"] == 0.050
    assert algo["max_weight"] == 0.035
    assert algo["backtest_start"] == "2020-01-01"
    assert algo["backtest_end"] == "2026-01-13"
