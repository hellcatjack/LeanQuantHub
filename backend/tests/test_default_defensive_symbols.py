from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.routes import algorithms as algorithms_routes
from app.routes import projects as projects_routes


def test_default_project_config_uses_sgov_vgsh_basket():
    config = projects_routes._load_default_config()
    backtest_params = config["backtest_params"]
    assert backtest_params["risk_off_symbols"] == "SGOV,VGSH"
    assert backtest_params.get("risk_off_symbol", "SGOV") == "SGOV"
    assert config["benchmark"] == "SPY"


def test_default_algorithm_config_uses_sgov_vgsh_basket():
    config = projects_routes._load_default_algorithm_config()
    params = config["version"]["params"]
    assert params["risk_off_symbols"] == "SGOV,VGSH"
    assert params["benchmark"] == "SPY"


def test_normalize_project_config_forces_sgov_vgsh_basket():
    normalized = projects_routes._normalize_project_config(
        {
            "data": {"primary_vendor": "stooq", "fallback_vendor": "yahoo"},
            "backtest_params": {
                "risk_off_symbols": "VGSH,IEF,GLD,TLT",
                "risk_off_symbol": "VGSH",
            },
        }
    )
    backtest_params = normalized["backtest_params"]
    assert backtest_params["risk_off_symbols"] == "SGOV,VGSH"
    assert backtest_params["risk_off_symbol"] == "SGOV"


def test_normalize_algorithm_version_params_forces_sgov_vgsh_basket():
    normalized = algorithms_routes._normalize_algorithm_version_params(
        {
            "risk_off_symbols": "SHY,IEF",
            "risk_off_symbol": "BIL",
            "defensive": {"symbols": ["SHY", "IEF"]},
        }
    )
    assert normalized["risk_off_symbols"] == "SGOV,VGSH"
    assert normalized["risk_off_symbol"] == "SGOV"
    assert normalized["defensive"]["symbols"] == ["SGOV", "VGSH"]
