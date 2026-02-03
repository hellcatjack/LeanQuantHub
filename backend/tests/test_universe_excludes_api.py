from pathlib import Path
import sys

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app


def test_universe_excludes_crud(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data"
    data_root.mkdir()
    monkeypatch.setenv("DATA_ROOT", str(data_root))

    client = TestClient(app)
    res = client.get("/api/universe/excludes")
    assert res.status_code == 200
    items = res.json()["items"]
    assert any(row["symbol"] == "WY" for row in items)

    res = client.post("/api/universe/excludes", json={"symbol": "ZZZ", "reason": "test"})
    assert res.status_code == 200

    res = client.patch("/api/universe/excludes/ZZZ", json={"enabled": False})
    assert res.status_code == 200
