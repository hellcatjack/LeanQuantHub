from __future__ import annotations

from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core import config
from app.services import lean_bridge_paths


def test_resolve_bridge_root_prefers_data_root(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data_root"
    data_root.mkdir()
    monkeypatch.setattr(config.settings, "data_root", str(data_root))
    monkeypatch.setattr(config.settings, "artifact_root", str(tmp_path / "artifacts"))
    result = lean_bridge_paths.resolve_bridge_root()
    assert result == data_root / "lean_bridge"


def test_resolve_bridge_root_accepts_root_with_data_subdir(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "root"
    (data_root / "data" / "lean_bridge").mkdir(parents=True)
    monkeypatch.setattr(config.settings, "data_root", str(data_root))
    monkeypatch.setattr(config.settings, "artifact_root", str(tmp_path / "artifacts"))
    result = lean_bridge_paths.resolve_bridge_root()
    assert result == data_root / "data" / "lean_bridge"


def test_resolve_bridge_root_uses_fallback_when_artifacts_missing(
    tmp_path: Path, monkeypatch
) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    fallback_root = tmp_path / "fallback"
    (fallback_root / "lean_bridge").mkdir(parents=True)
    monkeypatch.setattr(config.settings, "data_root", "")
    monkeypatch.setattr(config.settings, "artifact_root", str(artifact_root))
    monkeypatch.setattr(lean_bridge_paths, "DEFAULT_LEAN_BRIDGE_FALLBACK", fallback_root)
    result = lean_bridge_paths.resolve_bridge_root()
    assert result == fallback_root / "lean_bridge"


def test_resolve_bridge_root_prefers_artifacts_when_present(
    tmp_path: Path, monkeypatch
) -> None:
    artifact_root = tmp_path / "artifacts"
    (artifact_root / "lean_bridge").mkdir(parents=True)
    fallback_root = tmp_path / "fallback"
    (fallback_root / "lean_bridge").mkdir(parents=True)
    monkeypatch.setattr(config.settings, "data_root", "")
    monkeypatch.setattr(config.settings, "artifact_root", str(artifact_root))
    monkeypatch.setattr(lean_bridge_paths, "DEFAULT_LEAN_BRIDGE_FALLBACK", fallback_root)
    result = lean_bridge_paths.resolve_bridge_root()
    assert result == artifact_root / "lean_bridge"
