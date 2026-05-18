from pathlib import Path
import sys
from typing import Any
import json

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.run_options_income_matrix import build_matrix_payloads
from scripts.run_options_income_matrix import dispatch_payloads
from scripts.run_options_income_matrix import filter_existing_payloads
from scripts.run_options_income_matrix import load_active_run_ids


def test_build_matrix_payloads_expands_proxy_assets() -> None:
    payloads = build_matrix_payloads()
    names = {item["name"] for item in payloads}

    assert "baseline" in names
    assert "idle_replacement_jepi_20" in names
    assert "defensive_replacement_qyld_30" in names

    sample = next(item for item in payloads if item["name"] == "idle_replacement_jepi_20")
    algo = sample["payload"]["params"]["algorithm_parameters"]
    assert algo["income_sleeve_symbol"] == "JEPI"
    assert algo["income_sleeve_weight"] == "0.2"
    assert algo["income_sleeve_mode"] == "idle_replacement"
    assert algo["risk_off_symbols"] == "SGOV,VGSH"


def test_dispatch_payloads_limits_inflight_submissions() -> None:
    payloads = [
        {"name": "a", "payload": {"slot": "a"}, "group": "baseline"},
        {"name": "b", "payload": {"slot": "b"}, "group": "baseline"},
        {"name": "c", "payload": {"slot": "c"}, "group": "baseline"},
        {"name": "d", "payload": {"slot": "d"}, "group": "baseline"},
    ]
    submitted: list[str] = []
    persisted: list[dict[str, Any]] = []
    sleeps: list[float] = []
    status_calls: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}

    def submit_fn(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(str(payload["slot"]))
        return {"id": len(submitted)}

    def is_done_fn(run_id: int) -> bool:
        status_calls[run_id] += 1
        return status_calls[run_id] >= 2

    def sleep_fn(seconds: float) -> None:
        sleeps.append(seconds)

    def persist_fn(row: dict[str, Any]) -> None:
        persisted.append(row)

    dispatch_payloads(
        payloads,
        max_inflight=2,
        submit_fn=submit_fn,
        is_done_fn=is_done_fn,
        sleep_fn=sleep_fn,
        persist_fn=persist_fn,
    )

    assert submitted == ["a", "b", "c", "d"]
    assert [row["id"] for row in persisted] == [1, 2, 3, 4]
    assert sleeps


def test_filter_existing_payloads_skips_manifest_names(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join(
            [
                json.dumps({"name": "baseline"}),
                json.dumps({"name": "idle_replacement_jepi_20"}),
            ]
        ),
        encoding="utf-8",
    )
    payloads = [
        {"name": "baseline", "payload": {}, "group": "baseline"},
        {"name": "idle_replacement_jepi_20", "payload": {}, "group": "idle_replacement"},
        {"name": "idle_replacement_jepi_30", "payload": {}, "group": "idle_replacement"},
    ]

    filtered = filter_existing_payloads(payloads, manifest_path=manifest)

    assert [item["name"] for item in filtered] == ["idle_replacement_jepi_30"]


def test_load_active_run_ids_restores_running_runs_from_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join(
            [
                json.dumps({"id": 11, "name": "baseline"}),
                json.dumps({"id": 12, "name": "idle_replacement_jepi_20"}),
            ]
        ),
        encoding="utf-8",
    )
    checked: list[int] = []

    def is_done_fn(run_id: int) -> bool:
        checked.append(run_id)
        return run_id == 11

    active = load_active_run_ids(manifest, is_done_fn=is_done_fn)

    assert active == [12]
    assert checked == [11, 12]


def test_dispatch_payloads_respects_existing_inflight_runs() -> None:
    payloads = [{"name": "c", "payload": {"slot": "c"}, "group": "baseline"}]
    submitted: list[str] = []
    persisted: list[dict[str, Any]] = []
    sleeps: list[float] = []
    status_calls = {7: 0}

    def submit_fn(payload: dict[str, Any]) -> dict[str, Any]:
        submitted.append(str(payload["slot"]))
        return {"id": 8}

    def is_done_fn(run_id: int) -> bool:
        status_calls[run_id] = status_calls.get(run_id, 0) + 1
        return status_calls[run_id] >= 2

    def sleep_fn(seconds: float) -> None:
        sleeps.append(seconds)

    def persist_fn(row: dict[str, Any]) -> None:
        persisted.append(row)

    dispatch_payloads(
        payloads,
        max_inflight=1,
        submit_fn=submit_fn,
        is_done_fn=is_done_fn,
        sleep_fn=sleep_fn,
        persist_fn=persist_fn,
        initial_inflight=[7],
    )

    assert submitted == ["c"]
    assert [row["id"] for row in persisted] == [8]
    assert sleeps
