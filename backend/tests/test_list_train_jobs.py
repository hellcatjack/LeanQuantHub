import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from scripts import list_train_jobs  # noqa: E402


def test_extract_train_job_ids_filters_success():
    items = [
        {"id": 1, "status": "success"},
        {"id": 2, "status": "failed"},
        {"id": 3, "status": "success"},
    ]
    assert list_train_jobs.extract_train_job_ids(items) == [1, 3]
