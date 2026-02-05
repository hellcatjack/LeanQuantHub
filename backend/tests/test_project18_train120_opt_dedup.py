from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.run_project18_train120_opt import (
    _load_existing_params,
    _load_inflight_runs,
    _param_key,
)


def test_load_existing_params_dedupes() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        manifest = Path(tmpdir) / "manifest.jsonl"
        params = {"max_exposure": 0.6, "vol_target": 0.045, "max_weight": 0.03}
        lines = [
            {"run_id": 1, "params": params},
            {"run_id": 2, "params": params},
        ]
        manifest.write_text(
            "\n".join(json.dumps(line, ensure_ascii=False) for line in lines),
            encoding="utf-8",
        )
        seen = _load_existing_params(manifest)
        assert _param_key(params) in seen
        assert len(seen) == 1


def test_load_inflight_runs_filters_done() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        manifest = Path(tmpdir) / "manifest.jsonl"
        lines = [
            {"run_id": 1, "params": {"max_exposure": 0.6}},
            {"run_id": 2, "params": {"max_exposure": 0.7}},
            {"run_id": 3, "params": {"max_exposure": 0.8}},
        ]
        manifest.write_text(
            "\n".join(json.dumps(line, ensure_ascii=False) for line in lines),
            encoding="utf-8",
        )

        def is_done(rid: int) -> bool:
            return rid == 2

        inflight = _load_inflight_runs(manifest, is_done)
        assert set(inflight) == {1, 3}
