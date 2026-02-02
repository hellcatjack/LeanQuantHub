from pathlib import Path
import json

from app.services import backtest_opt_cagr


def test_score_manifest_filters_and_sorts(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join(
            [
                json.dumps({"id": 1, "params": {"a": 1}}),
                json.dumps({"id": 2, "params": {"a": 2}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = tmp_path / "artifacts"
    (artifacts / "run_1" / "lean_results").mkdir(parents=True)
    (artifacts / "run_2" / "lean_results").mkdir(parents=True)

    (artifacts / "run_1" / "lean_results" / "-summary.json").write_text(
        '{"statistics": {"Compounding Annual Return": "10.0%", "Drawdown": "10.0%"}}',
        encoding="utf-8",
    )
    (artifacts / "run_2" / "lean_results" / "-summary.json").write_text(
        '{"statistics": {"Compounding Annual Return": "20.0%", "Drawdown": "20.0%"}}',
        encoding="utf-8",
    )

    results = backtest_opt_cagr.score_manifest(
        manifest,
        artifacts_root=artifacts,
        max_dd=0.15,
        limit=3,
    )

    assert len(results) == 1
    assert results[0]["run_id"] == 1
    assert results[0]["cagr"] == 0.10
