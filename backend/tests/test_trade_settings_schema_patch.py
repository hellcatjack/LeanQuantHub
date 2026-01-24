from pathlib import Path


def test_trade_settings_execution_data_source_patch_exists():
    root = Path(__file__).resolve().parents[2]
    patch = root / "deploy/mysql/patches/20260124_add_trade_settings_execution_data_source.sql"
    assert patch.exists()


def test_trade_fills_exec_id_patch_exists():
    root = Path(__file__).resolve().parents[2]
    patch = root / "deploy/mysql/patches/20260124_add_trade_fills_exec_id.sql"
    assert patch.exists()


def test_trade_fills_meta_columns_patch_exists():
    root = Path(__file__).resolve().parents[2]
    patch = root / "deploy/mysql/patches/20260124_add_trade_fills_meta_columns.sql"
    assert patch.exists()
