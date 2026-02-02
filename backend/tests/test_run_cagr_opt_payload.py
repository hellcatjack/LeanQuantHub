import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from scripts import run_cagr_opt  # noqa: E402


def test_build_payload_uses_params_and_algorithm_parameters() -> None:
    algo_params = {"max_exposure": 0.4, "vol_target": 0.05, "max_weight": 0.03}
    payload = run_cagr_opt.build_payload(algo_params)

    assert "project_id" in payload
    assert "params" in payload
    params = payload["params"]
    assert "pipeline_train_job_id" in params
    assert "algorithm_parameters" in params
    ap = params["algorithm_parameters"]
    assert ap["max_exposure"] == 0.4
    assert ap["vol_target"] == 0.05
    assert ap["max_weight"] == 0.03
    assert ap["backtest_start"] == run_cagr_opt.START
    assert ap["backtest_end"] == run_cagr_opt.END
    assert ap["score_csv_path"] == run_cagr_opt.BASE_PARAMS["score_csv_path"]
