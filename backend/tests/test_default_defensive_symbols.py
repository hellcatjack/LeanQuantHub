from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.routes import projects as projects_routes


def test_default_project_config_uses_vgsh():
    config = projects_routes._load_default_config()
    backtest_params = config["backtest_params"]
    symbols = backtest_params["risk_off_symbols"]
    assert "VGSH" in symbols
    assert "SHY" not in symbols


def test_default_algorithm_config_uses_vgsh():
    config = projects_routes._load_default_algorithm_config()
    risk_off_symbols = config["version"]["params"]["risk_off_symbols"]
    assert "VGSH" in risk_off_symbols
    assert "SHY" not in risk_off_symbols
