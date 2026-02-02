from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List
import sys

import requests

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.backtest_opt_random import generate_candidates
from app.services.backtest_opt_runner import (
    merge_algo_params,
    parse_pct,
    select_core_params,
)

BASE_URL = "http://192.168.1.31:8021"
PROJECT_ID = 18
BASE_RUN_ID = 514
TRAIN_JOB_ID = 97
TOTAL_RUNS = 80
MAX_CONCURRENCY = 8
BACKTEST_START = "2020-01-01"

ARTIFACT_ROOT = Path("/app/stocklean/artifacts/backtest_opt/project_18/train_97")
MANIFEST = ARTIFACT_ROOT / "manifest.jsonl"
SUMMARY_CSV = ARTIFACT_ROOT / "summary.csv"
TOP10_JSON = ARTIFACT_ROOT / "top10.json"


def _get(url: str, **kwargs):
    resp = requests.get(url, timeout=10, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _post(url: str, payload: Dict[str, Any]):
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_base_params() -> Dict[str, Any]:
    run = _get(f"{BASE_URL}/api/backtests/{BASE_RUN_ID}")
    params = run.get("params") or {}
    algo = params.get("algorithm_parameters") or {}
    config = _get(f"{BASE_URL}/api/projects/{PROJECT_ID}/config").get("config") or {}
    backtest_params = config.get("backtest_params") or {}
    algo = merge_algo_params(algo, backtest_params)
    algo["backtest_start"] = BACKTEST_START
    algo["backtest_end"] = ""
    params["algorithm_parameters"] = algo
    params["pipeline_train_job_id"] = TRAIN_JOB_ID
    return params


def build_candidates(base_algo: Dict[str, Any]) -> List[Dict[str, Any]]:
    core = select_core_params(base_algo)
    return generate_candidates(core, total=TOTAL_RUNS, seed=97)


def submit_backtest(params: Dict[str, Any]) -> int:
    payload = {"project_id": PROJECT_ID, "params": params}
    run = _post(f"{BASE_URL}/api/backtests", payload)
    return int(run["id"])


def fetch_run(run_id: int) -> Dict[str, Any]:
    return _get(f"{BASE_URL}/api/backtests/{run_id}")


def is_terminal(status: str | None) -> bool:
    return status in {"success", "failed"}


def main() -> None:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    base_params = fetch_base_params()
    base_algo = base_params.get("algorithm_parameters") or {}
    candidates = build_candidates(base_algo)

    active: Dict[int, Dict[str, Any]] = {}
    pending = list(candidates)
    results: List[Dict[str, Any]] = []

    with MANIFEST.open("w", encoding="utf-8") as handle:
        while pending or active:
            while pending and len(active) < MAX_CONCURRENCY:
                item = pending.pop(0)
                params = json.loads(json.dumps(base_params))
                params["algorithm_parameters"].update(item)
                run_id = submit_backtest(params)
                active[run_id] = {
                    "params": params["algorithm_parameters"],
                    "status": "queued",
                }
                handle.write(
                    json.dumps(
                        {"id": run_id, "params": item, "status": "queued"},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                handle.flush()

            time.sleep(20)
            done_ids = []
            for run_id in list(active.keys()):
                run = fetch_run(run_id)
                status = run.get("status") or ""
                active[run_id]["status"] = status
                if is_terminal(status):
                    metrics = run.get("metrics") or {}
                    cagr = parse_pct(metrics.get("Compounding Annual Return"))
                    dd = parse_pct(metrics.get("Drawdown"))
                    results.append(
                        {
                            "run_id": run_id,
                            "status": status,
                            "cagr": cagr,
                            "dd": dd,
                            "metrics": metrics,
                            "params": active[run_id]["params"],
                        }
                    )
                    done_ids.append(run_id)
                    handle.write(
                        json.dumps(
                            {"id": run_id, "status": status, "cagr": cagr, "dd": dd},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    handle.flush()
            for run_id in done_ids:
                active.pop(run_id, None)

    with SUMMARY_CSV.open("w", encoding="utf-8") as handle:
        handle.write("run_id,status,cagr,dd\n")
        for row in results:
            handle.write(
                f"{row['run_id']},{row['status']},{row['cagr']:.6f},{row['dd']:.6f}\n"
            )

    candidates_ok = [
        r for r in results if r["status"] == "success" and r["dd"] <= 0.15
    ]
    candidates_ok.sort(key=lambda x: x["cagr"], reverse=True)
    with TOP10_JSON.open("w", encoding="utf-8") as handle:
        json.dump(candidates_ok[:10], handle, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
