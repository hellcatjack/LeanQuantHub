from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services import defensive_policy


def test_default_defensive_policy_baseline() -> None:
    baseline = defensive_policy.get_default_defensive_policy()
    assert baseline["risk_off_symbol"] == "SGOV"
    assert baseline["risk_off_symbols"] == ["SGOV", "VGSH"]
    assert baseline["benchmark"] == "SPY"


def test_research_matrix_contains_expected_layers() -> None:
    matrix = defensive_policy.load_research_defensive_matrix()
    assert matrix["default"]["risk_off_symbols"] == ["SGOV", "VGSH"]
    assert matrix["conservative"]["risk_off_symbols"] == ["SGOV", "VGSH", "IEF"]
    assert matrix["hedge_opt_in"]["symbols"] == ["GLD"]
    assert matrix["commodity_observation"]["symbols"] == ["USO", "BNO"]
    assert matrix["benchmark_sensitivity"]["benchmarks"] == ["QQQ", "SOXX"]


def test_research_whitelist_tracks_non_default_assets() -> None:
    assert defensive_policy.RESEARCH_ONLY_SYMBOLS == (
        "GLD",
        "USO",
        "BNO",
        "TLT",
        "QQQ",
        "SOXX",
    )
