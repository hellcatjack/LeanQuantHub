from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path
from typing import Dict
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from app.services.backtest_opt_cagr import build_grid

API = "http://127.0.0.1:8021"
PROJECT_ID = 18
TRAIN_JOB_ID = 83
START = "2020-01-01"
END = "2026-01-13"  # 当前数据上限
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
    "score_csv_path": "/app/stocklean/artifacts/ml_job_83/scores.csv",
    "initial_cash": "30000.0",
    "fee_bps": "10.0",
}

OUT = Path("/app/stocklean/artifacts/cagr_opt_manifest.jsonl")


def _request_json(
    method: str,
    url: str,
    payload: dict | None = None,
    *,
    timeout: float = 30,
    max_retries: int = 0,
    retry_sleep: float = 1.0,
) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    attempt = 0
    while True:
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            if exc.code in {429, 500, 502, 503, 504} and attempt < max_retries:
                attempt += 1
                time.sleep(retry_sleep)
                continue
            raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
        except (TimeoutError, URLError, socket.timeout) as exc:
            if attempt >= max_retries:
                raise
            attempt += 1
            time.sleep(retry_sleep)
        except BaseException as exc:  # noqa: BLE001 - retry on timeout-like errors
            if "timed out" not in str(exc):
                raise
            if attempt >= max_retries:
                raise
            attempt += 1
            time.sleep(retry_sleep)


def build_payload(params: Dict[str, float]) -> dict:
    algorithm_parameters = {
        **BASE_PARAMS,
        **params,
        "backtest_start": START,
        "backtest_end": END,
    }
    return {
        "project_id": PROJECT_ID,
        "params": {
            "pipeline_train_job_id": TRAIN_JOB_ID,
            "algorithm_parameters": algorithm_parameters,
        },
    }


def submit(params: Dict[str, float]) -> dict:
    payload = build_payload(params)
    return _request_json("POST", f"{API}/api/backtests", payload)


def is_done(run_id: int) -> bool:
    status = _request_json(
        "GET",
        f"{API}/api/backtests/{run_id}",
        timeout=10,
        max_retries=3,
        retry_sleep=1.0,
    )
    return status.get("status") in {"completed", "failed", "canceled"}


def _load_existing_params() -> set[str]:
    if not OUT.exists():
        return set()
    seen = set()
    for line in OUT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        params = row.get("params") or {}
        seen.add(json.dumps(params, sort_keys=True))
    return seen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="仅提交前N条，0为全量")
    args = parser.parse_args()

    grid = build_grid({"max_exposure": 0.45, "vol_target": 0.055, "max_weight": 0.033})
    if args.limit:
        grid = grid[: args.limit]

    seen = _load_existing_params()
    inflight: list[int] = []
    for item in grid:
        item_key = json.dumps(item, sort_keys=True)
        if item_key in seen:
            continue
        while len(inflight) >= MAX_INFLIGHT:
            time.sleep(5)
            inflight = [rid for rid in inflight if not is_done(rid)]
        res = submit(item)
        inflight.append(int(res["id"]))
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": res["id"], "params": item}, ensure_ascii=False) + "\n")
        print(f"submitted {res['id']} -> {item}")


if __name__ == "__main__":
    main()
