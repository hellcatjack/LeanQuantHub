from pathlib import Path


def test_force_defensive_defaults_patch_exists_and_targets_config_sources():
    path = Path("deploy/mysql/patches/20260326_update_defensive_basket_to_sgov_vgsh.sql")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "project_versions" in text
    assert "algorithm_versions" in text
    assert "content_hash" in text
    assert "schema_migrations" in text
    assert "SGOV,VGSH" in text
    assert "trade_runs" not in text
    assert "decision_snapshots" not in text
