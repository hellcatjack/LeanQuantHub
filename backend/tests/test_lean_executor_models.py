import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import models


def test_lean_executor_models_exist():
    assert hasattr(models, "LeanExecutorPool")
    assert hasattr(models, "LeanExecutorEvent")
