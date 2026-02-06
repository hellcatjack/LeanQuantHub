from __future__ import annotations

import json
from pathlib import Path


def write_execution_params(*, output_dir: Path, run_id: int, params: dict) -> str:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"execution_params_run_{run_id}.json"
    payload = dict(params)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
