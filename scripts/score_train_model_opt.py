from __future__ import annotations

import json
from pathlib import Path

from app.services.backtest_opt_cagr import is_acceptable, parse_summary


def score_manifest(manifest: Path, artifacts_root: Path, max_dd: float):
    results = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        run_id = row["run_id"]
        summary = artifacts_root / f"run_{run_id}" / "lean_results" / "-summary.json"
        if not summary.exists():
            continue
        stats = parse_summary(summary)
        if not is_acceptable(stats, max_dd=max_dd):
            continue
        results.append(
            {
                "train_job_id": row["train_job_id"],
                "run_id": run_id,
                "cagr": stats["cagr"],
                "dd": stats["dd"],
            }
        )
    results.sort(key=lambda x: x["cagr"], reverse=True)
    return results


def main() -> None:
    manifest = Path("/app/stocklean/artifacts/train_model_opt_manifest.jsonl")
    artifacts = Path("/app/stocklean/artifacts")
    results = score_manifest(manifest, artifacts, 0.15)
    print(json.dumps(results[:3], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
