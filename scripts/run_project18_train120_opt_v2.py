from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.services.backtest_opt_train120_v2 import build_grid, build_contrast

API = "http://127.0.0.1:8021"
PROJECT_ID = 18
TRAIN_JOB_ID = 120
BASELINE_RUN_ID = 622
START = "2020-01-01"
END = "2026-01-13"
MAX_INFLIGHT = 8
OUT = Path("/app/stocklean/artifacts/train120_opt_v2_manifest.jsonl")
RISK_OFF = "VGSH,IEF,GLD,TLT"


def _request_json(method: str, url: str, payload: dict | None = None, *, timeout: float = 30) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (TimeoutError, URLError, socket.timeout))


def _request_with_retry(method: str, url: str, payload: dict | None = None) -> dict:
    attempt = 0
    while True:
        try:
            return _request_json(method, url, payload, timeout=30)
        except HTTPError as exc:
            if exc.code in {429, 500, 502, 503, 504} and attempt < 3:
                attempt += 1
                time.sleep(1.0)
                continue
            raise
        except BaseException as exc:  # noqa: BLE001
            if not _is_retryable(exc) or attempt >= 3:
                raise
            attempt += 1
            time.sleep(1.0)


def _param_key(params: dict) -> str:
    return json.dumps(params, sort_keys=True)


def _load_existing_params(path: Path) -> set[str]:
    if not path.exists():
        return set()
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        params = row.get("params") or {}
        seen.add(_param_key(params))
    return seen


def _load_inflight_runs(path: Path, is_done_fn) -> list[int]:
    if not path.exists():
        return []
    inflight: list[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        run_id = row.get("run_id")
        if run_id is None:
            continue
        run_id = int(run_id)
        if is_done_fn(run_id):
            continue
        inflight.append(run_id)
    return inflight


def fetch_baseline_params(run_id: int) -> dict:
    data = _request_with_retry("GET", f"{API}/api/backtests/{run_id}")
    params = data.get("params") or {}
    return params.get("algorithm_parameters") or {}


def fetch_train_job(job_id: int) -> dict:
    return _request_with_retry("GET", f"{API}/api/ml/train-jobs/{job_id}")


def build_payload(overrides: dict, baseline_algo: dict, scores_path: str) -> dict:
    algo = dict(baseline_algo)
    algo.update(overrides)
    algo.update(
        {
            "backtest_start": START,
            "backtest_end": END,
            "risk_off_symbols": RISK_OFF,
            "score_csv_path": scores_path,
        }
    )
    return {
        "project_id": PROJECT_ID,
        "params": {
            "pipeline_train_job_id": TRAIN_JOB_ID,
            "algorithm_parameters": algo,
        },
    }


def is_done(run_id: int) -> bool:
    try:
        status = _request_with_retry("GET", f"{API}/api/backtests/{run_id}")
    except Exception:
        return False
    return status.get("status") in {"completed", "failed", "canceled", "success"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, default=1, choices=[1, 2])
    args = parser.parse_args()

    baseline = fetch_baseline_params(BASELINE_RUN_ID)
    train = fetch_train_job(TRAIN_JOB_ID)
    scores_path = train.get("scores_path") or train.get("metrics", {}).get("scores_path")
    if not scores_path:
        raise SystemExit("scores_path missing for train job 120")

    batch = build_grid()
    if args.stage == 2:
        contrast = build_contrast()
        for idx, item in enumerate(contrast):
            base = dict(batch[idx])
            base.update(item)
            batch.append(base)

    seen = _load_existing_params(OUT)
    inflight = _load_inflight_runs(OUT, is_done)
    for item in batch:
        if _param_key(item) in seen:
            continue
        while len(inflight) >= MAX_INFLIGHT:
            time.sleep(5)
            inflight = [rid for rid in inflight if not is_done(rid)]
        payload = build_payload(item, baseline, scores_path)
        res = _request_with_retry("POST", f"{API}/api/backtests", payload)
        inflight.append(int(res["id"]))
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"run_id": res["id"], "params": item}, ensure_ascii=False) + "\n")
        print(f"submitted {res['id']} -> {item}")


if __name__ == "__main__":
    main()
