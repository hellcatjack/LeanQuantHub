from pathlib import Path
import sys

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app


def test_pipeline_runs_requires_project_id():
    client = TestClient(app)
    resp = client.get("/api/pipeline/runs")
    assert resp.status_code == 422
