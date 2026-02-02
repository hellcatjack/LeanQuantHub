import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from scripts import run_train_model_opt  # noqa: E402


def test_build_payload_includes_train_job_and_params():
    base_params = {"max_exposure": 0.4, "vol_target": 0.045, "max_weight": 0.028}
    payload = run_train_model_opt.build_payload(83, base_params)
    params = payload["params"]
    assert params["pipeline_train_job_id"] == 83
    algo = params["algorithm_parameters"]
    assert algo["max_exposure"] == 0.4
    assert algo["vol_target"] == 0.045
    assert algo["max_weight"] == 0.028


def test_prune_inflight_filters_done_ids():
    inflight = [1, 2, 3]
    done = {2}
    remaining = run_train_model_opt.prune_inflight(inflight, lambda rid: rid in done)
    assert remaining == [1, 3]


def test_is_retryable_exception_for_timeout():
    assert run_train_model_opt.is_retryable_exception(TimeoutError("timeout")) is True
    assert run_train_model_opt.is_retryable_exception(ValueError("no")) is False
