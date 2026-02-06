from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.lean_execution_params import write_execution_params


def test_write_execution_params_writes_json(tmp_path: Path):
    path = write_execution_params(
        output_dir=tmp_path,
        run_id=123,
        params={"min_qty": 1, "lot_size": 5, "cash_buffer_ratio": 0.1},
    )
    data = Path(path).read_text(encoding="utf-8")
    assert "min_qty" in data
    assert "lot_size" in data
    assert "cash_buffer_ratio" in data
