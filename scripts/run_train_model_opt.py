from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Dict
from urllib.request import Request, urlopen
from urllib.error import HTTPError

API = "http://127.0.0.1:8021"
PROJECT_ID = 18
START = "2020-01-01"
END = "2026-01-13"
MAX_INFLIGHT = 8

BASE_PARAMS: Dict[str, str] = {
    "top_n": "30",
    "retain_top_n": "10",
    "weighting": "score",
    "min_score": "0",
    "market_filter": "True",
    "market_ma_window": "200",
    "rebalance_frequency": "Weekly",
    "rebalance_day": "Monday",
    "rebalance_time_minutes": "30",
    "dynamic_exposure": "True",
    "drawdown_tiers": "0.08,0.12,0.15",
    "drawdown_exposures": "0.80,0.60,0.40",
    "max_drawdown": "0.15",
    "max_drawdown_52w": "0.15",
    "risk_off_mode": "defensive",
    "risk_off_pick": "lowest_vol",
    "risk_off_symbols": "SHY,IEF,GLD,TLT",
    "initial_cash": "30000.0",
    "fee_bps": "10.0",
}

OUT = Path("/app/stocklean/artifacts/train_model_opt_manifest.jsonl")


def _request_json(url: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def build_payload(train_job_id: int, params: Dict[str, float]) -> dict:
    algorithm_parameters = {
        **BASE_PARAMS,
        **params,
        "backtest_start": START,
        "backtest_end": END,
    }
    return {
        "project_id": PROJECT_ID,
        "params": {
            "pipeline_train_job_id": train_job_id,
            "algorithm_parameters": algorithm_parameters,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-jobs", required=True, help="train_job_id 列表文件")
    args = parser.parse_args()

    base = {"max_exposure": 0.4, "vol_target": 0.045, "max_weight": 0.028}
    with open(args.train_jobs, "r", encoding="utf-8") as f:
        ids = [int(x.strip()) for x in f.read().splitlines() if x.strip()]

    inflight: list[int] = []
    for train_job_id in ids:
        while len(inflight) >= MAX_INFLIGHT:
            time.sleep(5)
        payload = build_payload(train_job_id, base)
        res = _request_json(f"{API}/api/backtests", payload)
        inflight.append(int(res["id"]))
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {"train_job_id": train_job_id, "run_id": res["id"], "params": base},
                    ensure_ascii=False,
                )
                + "\n"
            )


if __name__ == "__main__":
    main()
