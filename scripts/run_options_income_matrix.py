from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
for path in (ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.options_income_policy import load_options_income_matrix
from scripts.run_cagr_opt import (
    API,
    BASE_PARAMS as DEFAULT_ALGORITHM_PARAMS,
    END,
    OUT as DEFAULT_MANIFEST,
    PROJECT_ID,
    START,
    _request_json,
)

MANIFEST = Path(str(DEFAULT_MANIFEST).replace("cagr_opt_manifest", "options_income_matrix_manifest"))
MAX_INFLIGHT = 4
SLEEP_SECONDS = 5.0


def _weight_label(value: float) -> str:
    return str(int(round(float(value) * 100)))


def _build_algorithm_parameters(
    *,
    baseline: dict[str, Any],
    income_sleeve_symbol: str = "",
    income_sleeve_weight: float = 0.0,
    income_sleeve_mode: str = "none",
) -> dict[str, Any]:
    params = dict(DEFAULT_ALGORITHM_PARAMS)
    params.update(
        {
            "benchmark": baseline["benchmark"],
            "risk_off_symbol": baseline["risk_off_symbol"],
            "risk_off_symbols": ",".join(baseline["risk_off_symbols"]),
            "backtest_start": START,
            "backtest_end": END,
        }
    )
    if income_sleeve_symbol:
        params["income_sleeve_symbol"] = income_sleeve_symbol
        params["income_sleeve_weight"] = str(income_sleeve_weight)
        params["income_sleeve_mode"] = income_sleeve_mode
    return params


def build_matrix_payloads(group: str = "all") -> list[dict[str, Any]]:
    matrix = load_options_income_matrix()
    baseline = matrix["baseline"]
    proxy_assets = list(matrix["proxy_assets"])
    modes = list(matrix["integration_modes"])
    sleeve_weights = list(matrix["sleeve_weights"])

    payloads: list[dict[str, Any]] = [
        {
            "group": "baseline",
            "name": "baseline",
            "payload": {
                "project_id": PROJECT_ID,
                "params": {
                    "benchmark": baseline["benchmark"],
                    "algorithm_parameters": _build_algorithm_parameters(baseline=baseline),
                },
            },
        }
    ]

    for mode in modes:
        for symbol in proxy_assets:
            for weight in sleeve_weights:
                payloads.append(
                    {
                        "group": mode,
                        "name": f"{mode}_{symbol.lower()}_{_weight_label(weight)}",
                        "payload": {
                            "project_id": PROJECT_ID,
                            "params": {
                                "benchmark": baseline["benchmark"],
                                "algorithm_parameters": _build_algorithm_parameters(
                                    baseline=baseline,
                                    income_sleeve_symbol=symbol,
                                    income_sleeve_weight=float(weight),
                                    income_sleeve_mode=mode,
                                ),
                            },
                        },
                    }
                )
    if group == "all":
        return payloads
    return [item for item in payloads if item["group"] == group]


def _append_manifest(row: dict[str, Any]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def filter_existing_payloads(
    payloads: list[dict[str, Any]],
    *,
    manifest_path: Path = MANIFEST,
) -> list[dict[str, Any]]:
    if not manifest_path.exists():
        return payloads
    existing_names: set[str] = set()
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        name = str(row.get("name") or "").strip()
        if name:
            existing_names.add(name)
    return [item for item in payloads if item["name"] not in existing_names]


def load_active_run_ids(
    manifest_path: Path = MANIFEST,
    *,
    is_done_fn: Callable[[int], bool],
) -> list[int]:
    if not manifest_path.exists():
        return []
    active: list[int] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        run_id = int(row.get("id") or 0)
        if run_id <= 0:
            continue
        if not is_done_fn(run_id):
            active.append(run_id)
    return active


def submit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _request_json(
        "POST",
        f"{API}/api/backtests",
        payload,
        timeout=30,
        max_retries=3,
        retry_sleep=1.0,
    )


def is_done(run_id: int) -> bool:
    result = _request_json(
        "GET",
        f"{API}/api/backtests/{run_id}",
        timeout=10,
        max_retries=3,
        retry_sleep=1.0,
    )
    return str(result.get("status") or "").lower() in {"completed", "success", "failed", "canceled"}


def dispatch_payloads(
    payloads: list[dict[str, Any]],
    *,
    max_inflight: int,
    submit_fn: Callable[[dict[str, Any]], dict[str, Any]],
    is_done_fn: Callable[[int], bool],
    sleep_fn: Callable[[float], None],
    persist_fn: Callable[[dict[str, Any]], None],
    initial_inflight: list[int] | None = None,
) -> None:
    inflight: list[int] = list(initial_inflight or [])
    for item in payloads:
        while len(inflight) >= max(1, int(max_inflight)):
            sleep_fn(SLEEP_SECONDS)
            inflight = [run_id for run_id in inflight if not is_done_fn(run_id)]
        result = submit_fn(item["payload"])
        result_id = int(result["id"])
        inflight.append(result_id)
        persist_fn(
            {
                "id": result_id,
                "name": item["name"],
                "group": item["group"],
                "payload": item["payload"],
            }
        )
        print(f"submitted {result_id} -> {item['name']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--group",
        default="all",
        choices=["all", "baseline", "idle_replacement", "defensive_replacement"],
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-inflight", type=int, default=MAX_INFLIGHT)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    payloads = build_matrix_payloads(group=args.group)
    inflight: list[int] = []
    if args.skip_existing:
        payloads = filter_existing_payloads(payloads)
        inflight = load_active_run_ids(MANIFEST, is_done_fn=is_done)
    if args.dry_run:
        for item in payloads:
            print(item["name"])
        return

    dispatch_payloads(
        payloads,
        max_inflight=args.max_inflight,
        submit_fn=submit_payload,
        is_done_fn=is_done,
        sleep_fn=time.sleep,
        persist_fn=_append_manifest,
        initial_inflight=inflight,
    )


if __name__ == "__main__":
    main()
