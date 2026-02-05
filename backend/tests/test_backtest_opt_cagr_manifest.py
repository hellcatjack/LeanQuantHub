from __future__ import annotations

import json
from pathlib import Path
import tempfile
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.backtest_opt_cagr import score_manifest


def test_score_manifest_accepts_run_id_key() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        manifest = root / "manifest.jsonl"
        artifacts = root
        summary = artifacts / "run_1" / "lean_results"
        summary.mkdir(parents=True, exist_ok=True)
        (summary / "-summary.json").write_text(
            json.dumps(
                {
                    "statistics": {
                        "Compounding Annual Return": "12.34%",
                        "Drawdown": "10.00%",
                        "Sharpe Ratio": "1.23",
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        manifest.write_text(json.dumps({"run_id": 1, "params": {}}, ensure_ascii=False), encoding="utf-8")
        results = score_manifest(manifest, artifacts_root=artifacts, max_dd=0.15, limit=3)
        assert len(results) == 1
        assert results[0]["run_id"] == 1
