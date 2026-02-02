import sys
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from scripts import score_train_model_opt  # noqa: E402


def test_score_filters_dd_and_sorts(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join(
            [
                json.dumps({"train_job_id": 1, "run_id": 10, "params": {}}),
                json.dumps({"train_job_id": 2, "run_id": 20, "params": {}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = tmp_path / "artifacts"
    (artifacts / "run_10" / "lean_results").mkdir(parents=True)
    (artifacts / "run_20" / "lean_results").mkdir(parents=True)

    (artifacts / "run_10" / "lean_results" / "-summary.json").write_text(
        '{"statistics": {"Compounding Annual Return": "10.0%", "Drawdown": "10.0%"}}',
        encoding="utf-8",
    )
    (artifacts / "run_20" / "lean_results" / "-summary.json").write_text(
        '{"statistics": {"Compounding Annual Return": "20.0%", "Drawdown": "20.0%"}}',
        encoding="utf-8",
    )

    results = score_train_model_opt.score_manifest(manifest, artifacts, 0.15)
    assert results[0]["train_job_id"] == 1
